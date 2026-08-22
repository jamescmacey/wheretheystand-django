"""Publish election snapshots to R2, or to a directory for development.

Ordering matters. Payloads are written first and the manifest last, because the
manifest is the only mutable pointer: until it names a path, nothing is visible,
so a publish that fails part way through leaves the previous state intact rather
than a half-updated event.

Payload filenames carry a content hash, which means they can be cached forever
and that republishing unchanged data is a no-op.
"""

import hashlib
import json
import pathlib

from django.core.files.base import ContentFile
from django.core.files.storage import storages

from . import builders
from ..models.elections import ElectionElectorate

# Cache classes, mapped to the storage aliases configured in settings.
MANIFEST = 'elections_manifest'
IMMUTABLE = 'elections_snapshots'
# Fixed filenames whose contents change, so they cannot be cached indefinitely.
# Only the per-electorate voting place files are published this way now.
SHORT_CACHE = 'elections_latest'


def _serialise(payload):
    """Deterministic JSON, so that an unchanged payload hashes the same."""
    return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      default=str).encode('utf-8')


def _revision(body):
    return hashlib.sha256(body).hexdigest()[:12]


class PublishDisabled(RuntimeError):
    """Raised when an environment that may not publish tries to."""


class StorageWriter:
    """Writes to R2 through the configured django-storages aliases.

    Gated at construction rather than at each call site, so that nothing --
    a signal, an admin action, a management command, a test -- can reach the
    live bucket without the environment saying it may. Every environment holds
    the same R2 credentials, so the credentials themselves are no protection.
    """

    def __init__(self):
        from django.conf import settings

        if not getattr(settings, 'ELECTIONS_PUBLISH_ENABLED', False):
            raise PublishDisabled(
                "Publishing election snapshots is disabled here. Set "
                "ELECTIONS_PUBLISH_ENABLED=true in production only; use "
                "--local or --dry-run elsewhere.")
        self.written = []

    def write(self, path, body, cache_class):
        storage = storages[cache_class]
        # S3Storage.save() with file_overwrite replaces in place. Deleting
        # first would leave a window where the object 404s.
        storage.save(path, ContentFile(body))
        self.written.append(path)
        return path


class LocalWriter:
    """Writes the same tree to a directory.

    Lets the client be pointed at a local snapshot base without R2 credentials,
    and makes payloads easy to inspect and diff.
    """

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.written = []

    def write(self, path, body, cache_class):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        self.written.append(path)
        return path


class DryRunWriter:
    """Records what would be written, and writes nothing."""

    def __init__(self):
        self.written = []
        self.sizes = {}

    def write(self, path, body, cache_class):
        self.written.append(path)
        self.sizes[path] = len(body)
        return path


def _event_prefix(version):
    """Where one results version's payloads live.

    Keyed on slugs rather than the Firestore event id, so that a version which
    has never been near Firestore still publishes.
    """
    return f"events/{version.election.slug}/{version.slug}"


def _write_hashed(writer, directory, name, payload):
    """Write a payload under a content-addressed filename."""
    body = _serialise(payload)
    path = f"{directory}/{name}-{_revision(body)}.json" if directory else \
        f"{name}-{_revision(body)}.json"
    writer.write(path, body, IMMUTABLE)
    return path


def publish_persistent(writer):
    """Publish the cross-election entities.

    Published once at the root rather than per event: the content hash means
    identical data lands on the same path, so every event shares one object.
    """
    return _write_hashed(writer, '', 'persistent', builders.build_persistent())


def publish_reference(writer, version):
    return _write_hashed(writer, _event_prefix(version), 'reference',
                         builders.build_reference(version))


def publish_results(writer, version):
    """Publish the results payload.

    Always content addressed and cached indefinitely. There is no rolling
    variant any more: during a live count clients read tallies from Firestore
    directly, and this file is what they fall back to once the count ends.
    """
    return _write_hashed(writer, _event_prefix(version), 'results',
                         builders.build_results(version))


def publish_voting_places(writer, version):
    """Publish voting place reference data and per-electorate results."""
    prefix = _event_prefix(version)
    paths = {'reference': _write_hashed(
        writer, prefix, 'voting-places',
        builders.build_voting_places_reference(version))}

    by_electorate = {}
    for electorate in ElectionElectorate.objects.filter(
            results_version=version).order_by('number'):
        body = _serialise(
            builders.build_voting_places_for_electorate(version, electorate))
        path = f"{prefix}/voting-places/by-electorate/{electorate.number}.json"
        writer.write(path, body, SHORT_CACHE)
        by_electorate[electorate.number] = path

    paths['by_electorate_base'] = f"{prefix}/voting-places/by-electorate/"
    paths['by_electorate_count'] = len(by_electorate)
    return paths


def publish_version(writer, version, persistent_path, include_voting_places=False):
    """Publish every payload for one results version and return its paths."""
    paths = {
        'persistent': persistent_path,
        'reference': publish_reference(writer, version),
        'results': publish_results(writer, version),
    }
    if include_voting_places:
        paths['voting_places'] = publish_voting_places(writer, version)
    return paths


def publish_manifest(writer, entries_by_election):
    body = _serialise(builders.build_manifest(entries_by_election))
    return writer.write('manifest.json', body, MANIFEST)


def build_manifest_entries(paths_by_version=None):
    """Describe every publishable version, newest election first.

    Versions are described by the paths recorded when they were last published,
    so the manifest can be rebuilt without regenerating any payload.
    ``paths_by_version`` overrides those recorded paths for versions published on
    this run.

    A version that has never been published has nothing to point at and is left
    out until it does.
    """
    paths_by_version = paths_by_version or {}
    entries_by_election = {}

    for version in builders.publishable_versions():
        paths = paths_by_version.get(version.id) or version.snapshot_paths
        if not paths:
            continue
        entries_by_election.setdefault(version.election, []).append(
            builders.build_version_entry(version, paths))

    return entries_by_election


def publish_manifest_only(writer):
    """Rewrite just the manifest, leaving every payload untouched.

    The manifest is the control plane: it carries `is_live`, `is_final` and the
    event's own description, and it is the only election document the client
    hard-codes a URL for. Changing any of those in Django has no effect on
    anyone until this runs.

    It is a few kilobytes and needs no serialising of results, so it is cheap
    enough to run on every save -- unlike the payloads, which change for
    entirely different reasons and are three orders of magnitude larger.
    """
    return publish_manifest(writer, build_manifest_entries())


def publish_all(writer, versions=None, include_voting_places=False, record=True):
    """Publish the given versions, then rewrite the manifest in full.

    The manifest always describes *every* publishable version, not only the ones
    written on this run. Versions that were not republished are described by the
    paths recorded when they last were, so publishing a single event cannot drop
    the others.

    Returns a mapping of ``election-slug/version-slug`` to published paths, plus
    the manifest path under the key ``manifest``.
    """
    from django.utils import timezone

    from ..models.elections import ElectionResultVersion

    versions = (list(builders.publishable_versions()) if versions is None
                else list(versions))

    persistent_path = publish_persistent(writer)

    published = {}
    paths_by_version = {}
    for version in versions:
        paths = publish_version(
            writer, version, persistent_path,
            include_voting_places=include_voting_places)
        published[f"{version.election.slug}/{version.slug}"] = paths
        paths_by_version[version.id] = paths

    # Shared with publish_manifest_only, so the two cannot describe the same
    # versions differently.
    published['manifest'] = publish_manifest(
        writer, build_manifest_entries(paths_by_version))

    if record and not isinstance(writer, DryRunWriter):
        now = timezone.now()
        for version in versions:
            ElectionResultVersion.objects.filter(id=version.id).update(
                snapshot_paths=paths_by_version[version.id],
                last_snapshot_published_at=now)

    return published
