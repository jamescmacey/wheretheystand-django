from django.apps import AppConfig


class WtsAppConfig(AppConfig):
    name = 'wts_app'
    verbose_name = 'WhereTheyStand'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from django.contrib import admin
        from django.contrib.auth.admin import UserAdmin

        from wts_app.models import User

        admin.site.register(User, UserAdmin)
