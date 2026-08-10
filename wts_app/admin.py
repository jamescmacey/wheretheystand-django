from django.apps import apps
from django.contrib import admin, messages
from django.contrib.admin.sites import AlreadyRegistered
from django.contrib.auth.admin import UserAdmin

from wts_app.models import User
from wts_app.models.elections import (
    ElectionResultVersion,
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


@admin.register(ElectionResultVersion)
class ElectionResultVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "election", "is_primary", "access_mode", "is_live",
                    "is_final", "firebase_id", "last_snapshot_published_at")
    list_filter = ("is_live", "is_final", "access_mode", "is_primary")
    search_fields = ("name", "slug", "firebase_id", "election__name")
    readonly_fields = ("refdata_built", "snapshot_paths",
                       "last_firebase_push_at", "last_snapshot_published_at")
    actions = ("push_to_firestore", "publish_snapshots", "publish_manifest")

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


app = apps.get_app_config('wts_app')

for model in app.get_models():
    if model._meta.label_lower == 'wts_app.user':
        continue
    try:
        admin.site.register(model)
    except AlreadyRegistered:
        pass
