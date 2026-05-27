"""Custom user model with UUID primary key."""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from django.core.files.storage import storages

def upload_to(instance, filename):
    return f"users/{instance.id}/avatars/{filename}"

def select_storage():
    return storages["private_files"]

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    avatar = models.ImageField(upload_to=upload_to, storage=select_storage, null=True, blank=True)
    github_username = models.CharField(max_length=255, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.get_username()
