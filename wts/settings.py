"""
Django settings for wts project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is not set")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", default="False") == "True"

if not DEBUG:
    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", default="").split(",")
    if not ALLOWED_HOSTS:
        raise ValueError("ALLOWED_HOSTS is not set")
else:
    ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'wts_app',
    'storages',
    'colorfield',
    'drf_spectacular',
    'drf_spectacular_sidecar',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'wts.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'wts.wsgi.application'

# Spectacular settings

SPECTACULAR_SETTINGS = {
    'TITLE': 'WhereTheyStand API',
    'DESCRIPTION': 'This is the API for WhereTheyStand.  Although the endpoints here are public, the main purpose of this API is to provide data for the WhereTheyStand website.  Things may therefore break without notice.',
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_DIST': 'SIDECAR',  # shorthand to use the sidecar instead
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    'CONTACT': {
        'name': 'WhereTheyStand',
        'url': 'https://wheretheystand.nz',
    }
}

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticatedOrReadOnly'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# CORS settings
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", default="").split(",")
if not CORS_ALLOWED_ORIGINS:
    raise ValueError("CORS_ALLOWED_ORIGINS is not set")

# CSRF settings
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", default="").split(",")
if not CSRF_TRUSTED_ORIGINS:
    raise ValueError("CSRF_TRUSTED_ORIGINS is not set")

# Database

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'wts',
        'USER': os.getenv("MYSQL_USER"),
        'PASSWORD': os.getenv("MYSQL_PASSWORD"),
        'HOST': os.getenv("MYSQL_HOST"),
        'PORT': os.getenv("MYSQL_PORT"),
    }
}

# Storage
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
          "bucket_name": "wheretheystand-public",
          "region_name": "auto",
          "endpoint_url": os.getenv("R2_ENDPOINT_URL"),
          "access_key": os.getenv("R2_ACCESS_KEY_ID"),
          "secret_key": os.getenv("R2_SECRET_ACCESS_KEY"),
          "custom_domain": "media.wheretheystand.nz",
        },
    },
    "documents": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
          "bucket_name": "wheretheystand-public",
          "region_name": "auto",
          "endpoint_url": os.getenv("R2_ENDPOINT_URL"),
          "access_key": os.getenv("R2_ACCESS_KEY_ID"),
          "secret_key": os.getenv("R2_SECRET_ACCESS_KEY"),
          "querystring_auth": False,
          "custom_domain": "media.wheretheystand.nz",
        },
    },
    "staticfiles": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": "wheretheystand-api-static",
            "region_name": "auto",
            "endpoint_url": os.getenv("R2_ENDPOINT_URL"),
            "access_key": os.getenv("R2_ACCESS_KEY_ID"),
            "secret_key": os.getenv("R2_SECRET_ACCESS_KEY"),
            "querystring_auth": False,
            "custom_domain": os.getenv("API_STATIC_CUSTOM_DOMAIN"),
        },
    },
}

# Firebase settings
import json
FIREBASE_CONFIG = os.getenv("FIREBASE_CONFIG")
if FIREBASE_CONFIG:
    FIREBASE_CONFIG = json.loads(FIREBASE_CONFIG)
if not FIREBASE_CONFIG:
    raise ValueError("FIREBASE_CONFIG is not set")

BOT_USER_AGENT = os.getenv("BOT_USER_AGENT", default="Mozilla/5.0 (compatible; WhereTheyStand/2.0)") 

STATIC_URL = f'https://{os.getenv("API_STATIC_CUSTOM_DOMAIN")}/'

# Email settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_PORT = os.getenv("EMAIL_PORT")
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", default="WhereTheyStand <no-reply@mail.wheretheystand.nz>")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", default="WhereTheyStand <no-reply@mail.wheretheystand.nz>")
EMAIL_SUBJECT_PREFIX = ""


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization

LANGUAGE_CODE = 'en-nz'

TIME_ZONE = 'Pacific/Auckland'

USE_I18N = True

USE_TZ = True


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
