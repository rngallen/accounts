"""
Django settings for proj project.

Generated by 'django-admin startproject' using Django 3.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/3.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.0/ref/settings/
"""


"""

HELP !!!


1. With whitenoise installed and DEBUG=False and <!doctype html> instead of <!DOCTYPE html> I had a weird issue where commenting out JS lines
   in input_dropdown_widget.js was stripping off the trailing characters of the JS file.

2. I uninstalled whitenoises but then got the problem where the css files were rejected because MIME-TYPE = text/html and this is obviously not right.
   The answer is Debug=True.  Although i think the HTML declaration is wrong so this needs changing anyway.

   Then the JS file problem went away.

"""


import dj_database_url
import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = '=d#m@3-878v0(s)pq6+ar52amg8+d(j&t_xl4y57eb@racaqqa'

ENVIRONMENT = os.environ.get('ENVIRONMENT', default='local')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = int(os.environ.get('DEBUG', default=1))

ALLOWED_HOSTS = ['.herokuapp.com', 'localhost', '127.0.0.1']

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
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'django.forms',
    'django.contrib.postgres',

    # third party
    'crispy_forms',
    # 'debug_toolbar',
    # custom widgets will slow down page loads massively
    'django_extensions',
    'drf_yasg',
    'mptt',
    'simple_history',
    'tempus_dominus',

    # ours
    'accountancy',
    'cashbook',
    'contacts',
    'nominals',
    'purchases',
    'sales',
    'users',
    'vat'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    # 'debug_toolbar.middleware.DebugToolbarMiddleware',
    # debug toolbar causes custom widgets to load really slowly !!!
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
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

db_from_env = dj_database_url.config(conn_max_age=500)
# db_from_env is empty without heroku config vars
# so database default setting does not update
DATABASES['default'].update(db_from_env)

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


LOGIN_URL = '/users/sigin'
LOGIN_REDIRECT_URL = '/users/profile'
LOGOUT_REDIRECT_URL = '/users/signin'

ANYMAIL = {
    "MAILGUN_API_KEY": os.environ.get('MAILGUN_API_KEY', ''),
    "MAILGUN_SENDER_DOMAIN": os.environ.get('MAILGUN_DOMAIN', ''),
}

# EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
EMAIL_BACKEND = "users.backends.CustomEmailBackend"

DEFAULT_FROM_EMAIL = "you@example.com"
# the email address that error messages come from, such as those sent to ADMINS and MANAGERS
SERVER_EMAIL = "your-server@example.com"

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.0/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static'), ]


DEFAULT_VAT_NOMINAL = "Vat"
DEFAULT_SYSTEM_SUSPENSE = "System Suspense Account"

# This dictionary is used for NL and CB tran enquiries
# so the user can click on a transaction and view it
ACCOUNTANCY_MODULES = {
    "PL": "purchases",
    "NL": "nominals",
    "SL": "sales",
    'CB': 'cashbook'
}


# DEFAULT_RENDERER_CLASSES = (
#     'rest_framework.renderers.JSONRenderer',
# )

# # Browsable API is great for development but i don't really want it to be
# # viewable for end users.  The consumers of the API, like a third party software
# # company, are expected to use the API via a Python client.

# if DEBUG:
#     # Based on this SO answer - https://stackoverflow.com/a/49395080
#     DEFAULT_RENDERER_CLASSES = DEFAULT_RENDERER_CLASSES + (
#         'rest_framework.renderers.BrowsableAPIRenderer',
#     )

# REST_FRAMEWORK = {
#     'DEFAULT_PERMISSION_CLASSES': (
#         'rest_framework.permissions.IsAuthenticatedOrReadOnly',
#     ),
#     'DEFAULT_RENDERER_CLASSES': DEFAULT_RENDERER_CLASSES,
#     'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
#     'PAGE_SIZE': 10
# }


# production
if ENVIRONMENT == 'production' and DEBUG == 0:
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True # include a header which bans the browsing from guessing the file type i.e. rely on the content type in the server response for file type
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')