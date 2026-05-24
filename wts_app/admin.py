from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered

app = apps.get_app_config('wts_app')

for model in app.get_models():
    if model._meta.label_lower == 'wts_app.user':
        continue
    try:
        admin.site.register(model)
    except AlreadyRegistered:
        pass
