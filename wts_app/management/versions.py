"""Selecting a results version by slug, for commands that take one.

A version slug is unique only within an election (`unique_together` on
`('election', 'slug')`), so "final" may name several. Rather than silently
pick one, every command that takes a slug reports the ambiguity and asks for
`--election-slug`. Shared so that the commands cannot disagree about what a
slug means.
"""

from django.core.management.base import CommandError

from wts_app.models.elections import ElectionResultVersion


def select_version(slug, election_slug=None, flag='--version-slug'):
    """The one results version with this slug, or a CommandError saying why not.

    ``flag`` names the option the slug came from, so the message points at the
    argument the caller actually typed.
    """
    versions = ElectionResultVersion.objects.select_related('election').filter(slug=slug)
    if election_slug:
        versions = versions.filter(election__slug=election_slug)

    found = list(versions)
    if not found:
        raise CommandError(f'{flag}: no results version has the slug {slug!r}.')
    if len(found) > 1:
        listed = '\n'.join(f'    {v.election.slug} / {v.slug}' for v in found)
        raise CommandError(
            f'{flag}: {len(found)} results versions have the slug {slug!r}. '
            f'Narrow with --election-slug:\n{listed}')
    return found[0]
