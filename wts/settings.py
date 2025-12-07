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
SECRET_KEY = 'django-insecure-9$^-xo)71^&2p*lvups$57h2gh-@yuw4yy6=r(tg1h$6yn%62a'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

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
    'wts_app',
    'storages',
    'colorfield',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
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


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'wts',
        'USER': 'wts',
        'PASSWORD': '2hwbDpMCzPtWiXqP8uofadBIRM1cwr8w20pM4is00YcbgDsvCTOmxHAointzOAsJ',
        'HOST': 'mysql.h1.jamescmacey.com',
        'PORT': '55432',
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
            "custom_domain": "api-static.wheretheystand.nz",
        },
    },
}

BOT_USER_AGENT = os.getenv("BOT_USER_AGENT", default="Mozilla/5.0 (compatible; WhereTheyStand/2.0)") 

STATIC_URL = 'https://api-static.wheretheystand.nz/'


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-nz'

TIME_ZONE = 'Pacific/Auckland'

USE_I18N = True

USE_TZ = True


# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
