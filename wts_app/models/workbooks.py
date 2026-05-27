"""
A workbook is the object used to group files which are ready to be ingested.
"""
from .base import BaseModel
from django.db import models
from django.core.files.storage import storages
from django.conf import settings
import hashlib
from functools import partial
from django.utils import timezone

def hash_file(file, block_size=65536):
    hasher = hashlib.md5()
    for buf in iter(partial(file.read, block_size), b''):
        hasher.update(buf)

    return hasher.hexdigest()


def hash_content(content, block_size=65536):
    """Hash file content directly from bytes."""
    hasher = hashlib.md5()
    if isinstance(content, bytes):
        # For bytes, process in chunks
        for i in range(0, len(content), block_size):
            hasher.update(content[i:i + block_size])
    else:
        # For file-like objects
        for buf in iter(partial(content.read, block_size), b''):
            hasher.update(buf)
    return hasher.hexdigest()


def upload_to(instance, filename):
    # Try to get hash from file content if available
    # This handles the case where we're saving a new file
    try:
        # Check if instance has a _file_content attribute (set before save)
        if hasattr(instance, '_file_content_for_hash'):
            content = instance._file_content_for_hash
            file_hash = hash_content(content)[-5:]
            # Clean up the temporary attribute
            delattr(instance, '_file_content_for_hash')
        elif instance.file and hasattr(instance.file, 'file') and instance.file.file:
            if instance.file.closed:
                instance.file.open()
            file_hash = hash_file(instance.file)[-5:]
            instance.file.seek(0)
        else:
            # Fallback: use a simple hash based on timestamp and filename
            file_hash = hashlib.md5(f"{timezone.now().timestamp()}{filename}".encode()).hexdigest()[-5:]
    except (ValueError, AttributeError, IOError):
        # Fallback if file can't be opened
        file_hash = hashlib.md5(f"{timezone.now().timestamp()}{filename}".encode()).hexdigest()[-5:]
    
    return "workbook-files/{0}-{1}/{2}".format(int(timezone.now().timestamp()), file_hash, filename)

def select_storage():
    return storages["private_files"]

class Workbook(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workbooks", null=True, blank=True)
    name = models.CharField(max_length=255)

class WorkbookFile(BaseModel):
    workbook = models.ForeignKey(Workbook, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to=upload_to, storage=select_storage)

    def __str__(self):
        return f"{self.workbook.name} - {self.file.name}"

    def delete(self, *args, **kwargs):
        if self.file:
            self.file.delete(save=False)
        super().delete(*args, **kwargs)

