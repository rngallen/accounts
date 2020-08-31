"""
Django settings for proj project.

Generated by 'django-admin startproject' using Django 3.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/3.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.0/ref/settings/
"""

import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = '=d#m@3-878v0(s)pq6+ar52amg8+d(j&t_xl4y57eb@racaqqa'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

INTERNAL_IPS = [
    '127.0.0.1',
]

# Application definition

INSTALLED_APPS = [
    # native
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.forms',
    'django.contrib.postgres',

    # third party
    'crispy_forms',
    # 'debug_toolbar',
    # custom widgets will slow down page loads massively
    'django_extensions',
    'mptt',
    'tempus_dominus',

    # ours
    'accountancy',
    'cashbook',
    'items',
    'nominals',
    'purchases',
    'sales',
    'vat'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # 'debug_toolbar.middleware.DebugToolbarMiddleware',
    # debug toolbar causes custom widgets to load really slowly !!!
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'proj.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, "templates")],
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

# Allowed layout pack
CRISPY_ALLOWED_TEMPLATE_PACKS = (
    'bootstrap',
    'uni_form',
    'bootstrap3',
    'bootstrap4',
    'accounts'
)

# Default layout pack
CRISPY_TEMPLATE_PACK = 'accounts'

WSGI_APPLICATION = 'proj.wsgi.application'


# Database
# https://docs.djangoproject.com/en/3.0/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
#     }
# }


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'dspace',  # maps to the POSTGRES POSTGRES_DB ENV
        'USER': 'dspace',  # maps to the POSTGRES POSTGRES_USER ENV
        'PASSWORD': 'dspace',  # maps to the POSTGRES POSTGRES_PASSWORD ENV
        'HOST': '127.0.0.1',  # maps to the POSTGRES DB SERVICE NAME IN DOCKER
        'PORT': 5432
    }
}


# Password validation
# https://docs.djangoproject.com/en/3.0/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/3.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.0/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [ os.path.join(BASE_DIR, 'static'), ]

DEFAULT_VAT_NOMINAL = "Vat"
DEFAULT_SYSTEM_SUSPENSE = "System Suspense Account"

ACCOUNTANCY_MODULES = {
    "PL": "purchases",
    "NL": "nominals",
    "SL": "sales"
}