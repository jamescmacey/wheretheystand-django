from django.apps import apps
from django.contrib import admin, messages
from django.contrib.admin.sites import AlreadyRegistered
from django.contrib.auth.admin import UserAdmin

from wts_app.models import User
from wts_app.models.elections import (
    ElectionResultVersion,
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
    list_display = ("name", "election", "is_primary", "access_mode", "is_live",
                    "is_final", "firebase_id", "last_snapshot_published_at")
    list_filter = ("is_live", "is_final", "access_mode", "is_primary")
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
            "fields": ("election", "name", "slug", "description", "is_primary"),
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
            "fields": ("comparison_version_ids",),
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
    list_display = ("display_name", "abbreviation", "colour", "party", "firebase_id")
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
