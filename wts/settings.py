"""
Django settings for wts project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from kombu import Queue

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
  # Custom user model must load before contrib apps that reference AUTH_USER_MODEL.
    'wts_app.apps.WtsAppConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'storages',
    'colorfield',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'django_celery_beat',
    'django_celery_results',
    'algoliasearch_django'
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

# Axiom

from opentelemetry.instrumentation.django import DjangoInstrumentor
DjangoInstrumentor().instrument()


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
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer'
    ],
}

if DEBUG:
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'].append('rest_framework.renderers.BrowsableAPIRenderer')

# CORS settings
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", default="").split(",")
if not CORS_ALLOWED_ORIGINS:
    raise ValueError("CORS_ALLOWED_ORIGINS is not set")
CORS_ALLOW_CREDENTIALS = True

# CSRF settings
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", default="").split(",")
if not CSRF_TRUSTED_ORIGINS:
    raise ValueError("CSRF_TRUSTED_ORIGINS is not set")

# Session / cookie settings (cross-site Nuxt frontend → API)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "1209600"))  # 2 weeks

if DEBUG:
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") == "True"
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "False") == "True"
    CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "Lax")
else:
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "None")
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "None")
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Turnstile settings
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY")
if not TURNSTILE_SECRET_KEY:
    raise ValueError("TURNSTILE_SECRET_KEY is not set")

TURNSTILE_BYPASS_CODE = os.getenv("TURNSTILE_BYPASS_CODE")

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

from google.oauth2 import service_account
import base64
import json


def _load_json_env(name: str) -> dict:
    """Load JSON from a single-line env var, or from {name}_B64 (for docker-compose .env)."""
    raw = os.getenv(name)
    if not raw:
        b64 = os.getenv(f"{name}_B64")
        if b64:
            raw = base64.b64decode(b64).decode()
    if not raw:
        raise ValueError(f"{name} (or {name}_B64) is not set")
    return json.loads(raw)


GCP_PRIVATE_FILES_CREDENTIALS = _load_json_env("GCP_PRIVATE_FILES_CREDENTIALS")
GCP_PRIVATE_FILES_BUCKET_NAME = os.getenv("GCP_PRIVATE_FILES_BUCKET_NAME")

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
    "private_files": {
        "BACKEND": "storages.backends.gcloud.GoogleCloudStorage",
        "OPTIONS": {
          "bucket_name": GCP_PRIVATE_FILES_BUCKET_NAME,
          "credentials": service_account.Credentials.from_service_account_info(GCP_PRIVATE_FILES_CREDENTIALS),
          "gzip": True,
        },
      },
}

# Firebase settings
FIREBASE_CONFIG = _load_json_env("FIREBASE_CONFIG")

BOT_USER_AGENT = os.getenv("BOT_USER_AGENT", default="Mozilla/5.0 (compatible; WhereTheyStand/2.0)") 

# Gemini settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")

# Celery settings
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = os.getenv("REDIS_PORT")
REDIS_USER = os.getenv("REDIS_USER")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REDIS_DB = os.getenv("REDIS_DB")
if not REDIS_HOST or not REDIS_PORT or not REDIS_USER or not REDIS_PASSWORD or not REDIS_DB:
    raise ValueError("REDIS_HOST, REDIS_PORT, REDIS_USER, REDIS_PASSWORD, and REDIS_DB are not set")

CELERY_BROKER_URL = f"redis://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "1800"))
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_QUEUES = (
    Queue("celery"),
    Queue("hansard"),
)
CELERY_TASK_ROUTES = {
    "wts_app.hansard.get_results": {"queue": "hansard"},
    "wts_app.hansard.get_daily": {"queue": "hansard"},
}

# Static URL
STATIC_URL = f'https://{os.getenv("API_STATIC_CUSTOM_DOMAIN")}/'

# Algolia
ALGOLIA = {
    "APPLICATION_ID": os.getenv("ALGOLIA_APPLICATION_ID"),
    "API_KEY": os.getenv("ALGOLIA_SEARCH_API_KEY"),
    "INDEX_PREFIX": os.getenv("ALGOLIA_INDEX_PREFIX"),
    "INDEX_SUFFIX": os.getenv("ALGOLIA_INDEX_SUFFIX"),
}

# Email settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", default="587"))
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", default="WhereTheyStand <no-reply@mail.wheretheystand.nz>")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", default="WhereTheyStand <no-reply@mail.wheretheystand.nz>")
EMAIL_SUBJECT_PREFIX = ""


AUTH_USER_MODEL = 'wts_app.User'

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
