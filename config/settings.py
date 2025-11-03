# config/settings.py
from pathlib import Path
import os
from dotenv import load_dotenv

# --- BASE DIR + .env ---
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Django base ---
SECRET_KEY = 'django-insecure-_*s16=px$!crf0ysw6&6z5*=zv(u49(g6^!8cpe$$@za4uq=(r'
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]   # 👈 unificado aquí

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "sirepsi",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],   # 👈 usamos /templates del proyecto
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Bases de datos ---
DATABASES = {
    # SQLite solo para la parte interna de Django (migraciones, auth, etc.)
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },

    # SQL Server existente (solo lectura para nuestros reportes)
    "BDFarmacia": {
        "ENGINE": "mssql",  # mssql-django
        "NAME": os.getenv("DB_NAME", "BDFarmacia"),
        "USER": os.getenv("DB_USER", "sa"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "1433"),
        "OPTIONS": {
            "driver": os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server"),
            # calidad de textos unicode y evitar quejas por certificados locales
            "unicode_results": True,
            "trustServerCertificate": "yes",
        },
    },
}

# --- Password validators ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n / zona horaria ---
LANGUAGE_CODE = "es"
TIME_ZONE = "America/La_Paz"
USE_I18N = True
USE_TZ = False  # trabajaremos en hora local

# --- Static files ---
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]      # 👈 para desarrollo (tu carpeta /static)
STATIC_ROOT = BASE_DIR / "staticfiles"        # 👈 para 'collectstatic' en despliegue

# --- Django defaults ---
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# (Opcional) logging básico para depurar conexiones SQL Server
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django.db.backends": {"handlers": ["console"], "level": "ERROR"},  # cambia a DEBUG si necesitas ver SQL
    },
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "django_cache",
        "TIMEOUT": 300,  # 5 minutos
    }
}

