from django.db import models
import uuid
import hashlib
from functools import partial
from django.conf import settings
from django.utils import timezone
from django.core.files.storage import storages
from .base import BaseModel
from django.utils.text import slugify

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
            # For existing files, read from the file
            instance.file.open()
            file_hash = hash_file(instance.file)[-5:]
            instance.file.close()
        else:
            # Fallback: use a simple hash based on timestamp and filename
            file_hash = hashlib.md5(f"{timezone.now().timestamp()}{filename}".encode()).hexdigest()[-5:]
    except (ValueError, AttributeError, IOError):
        # Fallback if file can't be opened
        file_hash = hashlib.md5(f"{timezone.now().timestamp()}{filename}".encode()).hexdigest()[-5:]
    
    return "{0}-{1}/{2}".format(int(timezone.now().timestamp()), file_hash, filename)


def select_storage():
    return storages["documents"]


class Category(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField()
    parent_category = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    slug = models.SlugField(unique=True,blank=True,null=True)

    class Meta:
        verbose_name_plural = "Categories"

    def save(self, *args, **kwargs):
        if not self.id or not self.slug:
            self.slug = slugify(self.name)
        super(Category, self).save(*args, **kwargs)

    def __str__(self):
        return self.name

class CopyrightParty(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Copyright parties"

    def __str__(self):
        return self.name

class Licence(BaseModel):
    name = models.CharField(max_length=255)
    parent_licence = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True,null=True)
    licence_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.name

class Document(BaseModel):
    categories = models.ManyToManyField(Category)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class File(BaseModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="files", null=True, blank=True)
    file_name = models.TextField()
    file_description = models.TextField(blank=True, null=True)
    source_url = models.URLField(blank=True, null=True)
    file_type = models.CharField(max_length=255)
    original_link_alive = models.BooleanField(default=True)
    original_link_last_checked = models.DateTimeField(blank=True, null=True)
    original_md5 = models.CharField(max_length=32, blank=True, default="")
    stored_md5 = models.CharField(max_length=32, blank=True, default="")
    file = models.FileField(upload_to=upload_to, storage=select_storage)
    published_date = models.DateField(blank=True, null=True)

    copyright_owner = models.ForeignKey(CopyrightParty, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_files')
    licence_grantor = models.ForeignKey(CopyrightParty, on_delete=models.SET_NULL, null=True, blank=True, related_name='licensed_files')
    licence = models.ForeignKey(Licence, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.file_name
    
    def save(self, *args, **kwargs):
        self.stored_md5 = hash_file(self.file)
        if self.original_md5 == "":
            self.original_md5 = self.stored_md5
        super(File, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.file.delete(save=False)
        super(File, self).delete(*args, **kwargs)
    

class DocumentCollection(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    documents = models.ManyToManyField(Document)
    categories = models.ManyToManyField(Category)

    def __str__(self):
        return self.name