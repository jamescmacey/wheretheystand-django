from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.contrib.auth.admin import UserAdmin

from wts_app.models import User


class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Profile", {"fields": ("avatar", "github_username", "bio")}),
    )


admin.site.register(User, CustomUserAdmin)

app = apps.get_app_config('wts_app')

for model in app.get_models():
    if model._meta.label_lower == 'wts_app.user':
        continue
    try:
        admin.site.register(model)
    except AlreadyRegistered:
        pass
