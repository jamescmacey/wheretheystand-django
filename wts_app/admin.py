from django.apps import apps
from django.contrib import admin, messages
from django.contrib.admin.sites import AlreadyRegistered
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.db.models import Q

from wts_app.models import User
from wts_app.models.elections import (
    ElectionCandidate,
    ElectionElectorate,
    ElectionResultVersion,
    ElectionVotingPlace,
    ElectorateIncumbent,
    PartyIncumbent,
    PersistentCandidate,
    PersistentParty,
)


class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Profile", {"fields": ("avatar", "github_username", "bio")}),
    )


admin.site.register(User, CustomUserAdmin)


# Election results. Registered explicitly, above the catch-all loop below, so
# that pushing to Firestore is available from the admin. Pushes are queued
# rather than run inline: a save must not wait on a network round trip.

def _queue(request, task, *args, description=""):
    from wts_app.firebase.client import is_firebase_push_enabled

    if not is_firebase_push_enabled():
        messages.error(
            request,
            "Firestore writes are disabled in this environment. "
            "Set FIREBASE_PUSH_ENABLED=true in production only.")
        return False
    try:
        task.delay(*args)
    except Exception as exc:
        messages.error(request, f"Could not queue the push: {exc}")
        return False
    messages.info(request, description)
    return True


class PartyIncumbentInline(admin.TabularInline):
    """Seats each party is defending, edited with the version they belong to.

    About twenty rows for a general election, and meaningless apart from the
    version, so they belong on its form. The electorate incumbents do not: at
    seventy-two rows they get a changelist of their own.
    """

    model = PartyIncumbent
    extra = 0
    raw_id_fields = ("persistent_party",)


@admin.register(ElectionResultVersion)
class ElectionResultVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "election", "is_primary", "publish_status", "access_mode",
                    "is_live", "is_final", "firebase_id", "last_snapshot_published_at")
    list_filter = ("publish_status", "is_live", "is_final", "access_mode", "is_primary")
    search_fields = ("name", "slug", "firebase_id", "election__name")
    readonly_fields = ("refdata_built", "snapshot_paths",
                       "last_firebase_push_at", "last_snapshot_published_at")
    actions = ("push_to_firestore", "publish_snapshots", "publish_manifest")
    inlines = (PartyIncumbentInline,)

    # Grouped because the curated fields are the ones a person actually fills
    # in, and the two bloc lists are raw JSON textareas that need the ordering
    # rule stated next to them.
    fieldsets = (
        (None, {
            "fields": ("election", "name", "slug", "description", "is_primary",
                       "publish_status"),
        }),
        ("Transport", {
            "fields": ("access_mode", "firebase_id", "is_live", "is_final",
                       "refdata_built", "archived", "archived_url"),
        }),
        ("Timing", {
            "fields": ("embargo_start", "embargo_end", "result_targets"),
        }),
        ("Blocs", {
            "description": (
                "Ordered lists of persistent party UUIDs. The left bloc, then "
                "every party in neither list, then the right bloc, is the "
                "seating order from the far left of the chamber to the far "
                "right &mdash; so write the left bloc far-left first and the "
                "right bloc centre first. A party in neither list is "
                "cross-bench and sits in the middle."),
            "fields": ("bloc_order_left", "bloc_order_right"),
        }),
        ("Comparison", {
            "description": (
                "<code>comparison_version</code> is the version in another "
                "election that the dashboard compares this one against. Its "
                "results are published with this version's snapshots, so "
                "republish the snapshots after changing it."),
            "fields": ("comparison_version", "comparison_version_ids"),
        }),
        ("Presentation", {
            "fields": ("card_image", "card_url", "vp_finder_url"),
        }),
        ("Published", {
            "fields": ("snapshot_paths", "vp_numbering_scheme",
                       "last_firebase_push_at", "last_snapshot_published_at"),
        }),
    )

    @admin.action(description="Push events document to Firestore")
    def push_to_firestore(self, request, queryset):
        from wts_app.tasks.firebase import push_event

        for version in queryset:
            _queue(request, push_event, str(version.pk),
                   description=f"Queued Firestore push for {version}.")

    @admin.action(description="Publish snapshots to R2")
    def publish_snapshots(self, request, queryset):
        from wts_app.snapshots import publisher

        try:
            published = publisher.publish_all(
                publisher.StorageWriter(), versions=list(queryset))
        except publisher.PublishDisabled as exc:
            messages.error(request, str(exc))
            return
        except Exception as exc:
            messages.error(request, f"Publishing failed: {exc}")
            return
        messages.info(
            request,
            f"Published {len(queryset)} version(s). Manifest: {published['manifest']}")


    @admin.action(description="Publish manifest only (fast)")
    def publish_manifest(self, request, queryset):
        """Rewrite the pointer clients read, regenerating nothing.

        Saving a version does this automatically. This is for forcing it when
        the queue is not running, or after changing something by other means.
        """
        from wts_app.snapshots import publisher

        try:
            path = publisher.publish_manifest_only(publisher.StorageWriter())
        except publisher.PublishDisabled as exc:
            messages.error(request, str(exc))
            return
        except Exception as exc:
            messages.error(request, f"Could not publish the manifest: {exc}")
            return
        messages.info(request, f"Published {path}. Clients follow within 30 seconds.")


@admin.register(PersistentParty)
class PersistentPartyAdmin(admin.ModelAdmin):
    list_display = ("display_name", "abbreviation", "colour", "alternate_colour",
                    "party", "firebase_id")
    search_fields = ("display_name", "abbreviation", "short_name")
    actions = ("push_to_firestore",)

    @admin.action(description="Push selected parties to Firestore")
    def push_to_firestore(self, request, queryset):
        from wts_app.tasks.firebase import push_persistent

        ids = [str(pk) for pk in queryset.values_list("id", flat=True)]
        _queue(request, push_persistent, ["persistent_parties"], ids,
               description=f"Queued a Firestore push of {len(ids)} part"
                           f"{'y' if len(ids) == 1 else 'ies'}.")


@admin.register(PersistentCandidate)
class PersistentCandidateAdmin(admin.ModelAdmin):
    list_display = ("display_name", "person", "firebase_id")
    search_fields = ("display_name",)
    raw_id_fields = ("person",)
    actions = ("push_to_firestore",)

    @admin.action(description="Push selected candidates to Firestore")
    def push_to_firestore(self, request, queryset):
        from wts_app.tasks.firebase import push_persistent

        ids = [str(pk) for pk in queryset.values_list("id", flat=True)]
        _queue(request, push_persistent, ["persistent_candidates"], ids,
               description=f"Queued a Firestore push of {len(ids)} candidate"
                           f"{'' if len(ids) == 1 else 's'}.")


@admin.register(ElectionCandidate)
class ElectionCandidateAdmin(admin.ModelAdmin):
    """Candidates as they stood in one results version.

    Filtered by election first and version second, because an election usually
    has several versions and each carries its own copy of every candidate.

    The party and electorate columns show the plain name rather than the
    object, whose __str__ walks up to the version and election and would cost
    two extra queries per row.
    """

    list_display = ("name", "number", "party_name", "list_pos",
                    "electorate_name", "is_dead", "election",
                    "results_version", "persistent_candidate")
    list_filter = ("results_version__election", "results_version", "is_dead")
    search_fields = ("name", "persistent_candidate__display_name",
                     "party__name", "party__abbreviation", "electorate__name",
                     "firebase_id")
    ordering = ("-results_version__election__polling_date", "results_version",
                "number")
    raw_id_fields = ("results_version", "persistent_candidate", "electorate",
                     "party")
    list_select_related = ("results_version__election", "persistent_candidate",
                           "party", "electorate")

    @admin.display(description="Party", ordering="party__name")
    def party_name(self, obj):
        return obj.party.name if obj.party else None

    @admin.display(description="Electorate", ordering="electorate__name")
    def electorate_name(self, obj):
        return obj.electorate.name if obj.electorate else None

    @admin.display(description="Election",
                   ordering="results_version__election__polling_date")
    def election(self, obj):
        return obj.results_version.election


class VotingPlaceElectorateFilter(admin.SimpleListFilter):
    """Filter by electorate name, narrowed to whatever is already selected.

    By name rather than by row, because each version has its own copy of every
    electorate: a plain foreign key filter would list each one once per version,
    and a choice would stop matching as soon as the version filter changed.
    """

    title = "electorate"
    parameter_name = "electorate"

    def lookups(self, request, model_admin):
        electorates = ElectionElectorate.objects.all()
        version = request.GET.get("results_version__id__exact")
        election = request.GET.get("results_version__election__id__exact")
        try:
            if version:
                electorates = electorates.filter(results_version_id=version)
            elif election:
                electorates = electorates.filter(
                    results_version__election_id=election)
            names = list(electorates.order_by("name")
                         .values_list("name", flat=True).distinct())
        except ValidationError:
            # A hand-edited URL with a malformed id. The changelist reports
            # that itself; it should not be a server error here first.
            names = []
        return [(name, name) for name in names]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(physical_electorate__name=self.value())
        return queryset


class VotingPlaceCoordinatesFilter(admin.SimpleListFilter):
    """Places without a location cannot be drawn on the map."""

    title = "coordinates"
    parameter_name = "has_coordinates"

    def lookups(self, request, model_admin):
        return [("yes", "Has coordinates"), ("no", "Missing coordinates")]

    def queryset(self, request, queryset):
        located = Q(latitude__isnull=False, longitude__isnull=False)
        if self.value() == "yes":
            return queryset.filter(located)
        if self.value() == "no":
            return queryset.exclude(located)
        return queryset


class VotingPlacePersistentFilter(admin.SimpleListFilter):
    """Places not yet matched to a persistent voting place."""

    title = "persistent voting place"
    parameter_name = "has_persistent"

    def lookups(self, request, model_admin):
        return [("yes", "Matched"), ("no", "Not matched")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(persistent_voting_place__isnull=False)
        if self.value() == "no":
            return queryset.filter(persistent_voting_place__isnull=True)
        return queryset


@admin.register(ElectionVotingPlace)
class ElectionVotingPlaceAdmin(admin.ModelAdmin):
    """Voting places as they stood in one results version.

    Filtered by election first and version second, as candidates are, because
    each version carries its own copy of every voting place. raw_id_fields
    because a general election has thousands of them, and a select on the
    persistent voting place would load every one into the change form.
    """

    list_display = ("address", "number", "electorate_name", "latitude",
                    "longitude", "election", "results_version", "is_matched")
    list_filter = ("results_version__election", "results_version",
                   VotingPlaceElectorateFilter, VotingPlaceCoordinatesFilter,
                   VotingPlacePersistentFilter)
    search_fields = ("address", "=number", "physical_electorate__name",
                     "persistent_voting_place__address", "firebase_id")
    ordering = ("-results_version__election__polling_date", "results_version",
                "number")
    raw_id_fields = ("results_version", "physical_electorate",
                     "persistent_voting_place")
    list_select_related = ("results_version__election", "physical_electorate")

    @admin.display(description="Electorate",
                   ordering="physical_electorate__name")
    def electorate_name(self, obj):
        return obj.physical_electorate.name

    @admin.display(description="Election",
                   ordering="results_version__election__polling_date")
    def election(self, obj):
        return obj.results_version.election

    @admin.display(description="Matched", boolean=True,
                   ordering="persistent_voting_place")
    def is_matched(self, obj):
        return obj.persistent_voting_place_id is not None


@admin.register(ElectorateIncumbent)
class ElectorateIncumbentAdmin(admin.ModelAdmin):
    """Who held each electorate going into a results version.

    Filtered by version, because that is the only way to work through them:
    seventy-two rows per general election, curated once and then copied forward
    with `copy_incumbents`.

    raw_id_fields rather than autocomplete_fields throughout: Electorate is
    registered by the catch-all loop below with no search_fields, so an
    autocomplete on it would fail at runtime rather than at import.
    """

    list_display = ("electorate", "persistent_candidate", "persistent_party",
                    "has_left_party", "current_persistent_party",
                    "results_version")
    list_filter = ("results_version", "has_left_party")
    search_fields = ("electorate__name", "persistent_candidate__display_name",
                     "persistent_party__display_name")
    raw_id_fields = ("electorate", "persistent_candidate", "persistent_party",
                     "current_persistent_party")
    list_select_related = ("electorate", "persistent_candidate",
                           "persistent_party", "current_persistent_party",
                           "results_version")


@admin.register(PartyIncumbent)
class PartyIncumbentAdmin(admin.ModelAdmin):
    """Also editable inline on the results version; this is for bulk edits."""

    list_display = ("persistent_party", "electorate_seats", "list_seats",
                    "total_seats", "results_version")
    list_filter = ("results_version",)
    search_fields = ("persistent_party__display_name",
                     "persistent_party__abbreviation")
    raw_id_fields = ("persistent_party",)
    list_select_related = ("persistent_party", "results_version")

    @admin.display(description="Total")
    def total_seats(self, obj):
        return obj.total_seats


app = apps.get_app_config('wts_app')

for model in app.get_models():
    if model._meta.label_lower == 'wts_app.user':
        continue
    try:
        admin.site.register(model)
    except AlreadyRegistered:
        pass
