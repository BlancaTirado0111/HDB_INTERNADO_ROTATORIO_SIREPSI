# config/settings.py
from __future__ import annotations

from pathlib import Path
import os
from dotenv import load_dotenv

# =============================================================================
# BASE DIR + .env
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # Lee variables si existen; no falla si falta

# =============================================================================
# Django base
# =============================================================================
# Nota de auditoría: en producción, definir SECRET_KEY en .env
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-_*s16=px$!crf0ysw6&6z5*=zv(u49(g6^!8cpe$$@za4uq=(r",  # fallback dev
)

# DEBUG por defecto True (dev). En prod, setear DEBUG=false en .env
DEBUG = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes", "y")

# ALLOWED_HOSTS puede venir de .env (coma-separado). Por defecto, localhost.
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()
]

# (Opcional) Si usas dominio/puerto HTTPS en prod, añade en .env, ej.:
# CSRF_TRUSTED_ORIGINS=https://sirepsi.midominio.bo,https://www.midominio.bo
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

INSTALLED_APPS = [
    # Core Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # App
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
        # Usamos /templates del proyecto (además de las carpetas de cada app)
        "DIRS": [BASE_DIR / "templates"],
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

# =============================================================================
# Bases de datos
# =============================================================================
# SQLite para internals de Django; SQL Server para reportes (solo lectura)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
    "BDFarmacia": {
        "ENGINE": "mssql",  # requiere paquete 'mssql-django'
        "NAME": os.getenv("DB_NAME", "BDFarmacia"),
        "USER": os.getenv("DB_USER", "sa"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "1433"),
        "OPTIONS": {
            # Driver ODBC; en Windows suele ser 'ODBC Driver 17 for SQL Server'
            "driver": os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server"),
            # Resultados unicode y tolerancia de certs locales (dev)
            "unicode_results": True,
            "trustServerCertificate": os.getenv("DB_TRUST_CERT", "yes"),
            # "autocommit": True,  # (opcional) por si tu driver lo requiere
        },
    },
}

# =============================================================================
# Password validators
# =============================================================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =============================================================================
# i18n / zona horaria
# =============================================================================
LANGUAGE_CODE = "es"
TIME_ZONE = "America/La_Paz"
USE_I18N = True
USE_TZ = False  # Trabajamos en hora local por requerimiento

# =============================================================================
# Static files
# =============================================================================
STATIC_URL = "static/"
# Para desarrollo: carpeta /static del proyecto
STATICFILES_DIRS = [BASE_DIR / "static"]
# Para despliegue: destino de collectstatic
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =============================================================================
# Logging (nivel configurable por .env)
# =============================================================================
DJANGO_SQL_LOG_LEVEL = os.getenv("DJANGO_SQL_LOG_LEVEL", "ERROR").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        # Cambia a DEBUG en .env si necesitas ver SQL emitido por Django ORM
        "django.db.backends": {"handlers": ["console"], "level": DJANGO_SQL_LOG_LEVEL},
    },
}

# =============================================================================
# Cache (file-based; 5 minutos)
# =============================================================================
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "django_cache",
        "TIMEOUT": 300,  # 5 minutos
    }
}

# =============================================================================
# Seguridad para producción (se aplican solo si DEBUG=False)
# =============================================================================
if not DEBUG:
    # Cookies solo por HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Cabeceras de seguridad comunes
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))  # 1 año
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "true").lower() in ("1", "true", "yes", "y")

    # Política de contenido (ajusta según tus assets/CDNs)
    # CSP es opcional; descomenta y ajusta si usas.
    # CSP_DEFAULT_SRC = ("'self'",)
    # CSP_STYLE_SRC = ("'self'", "https://cdn.jsdelivr.net", "'unsafe-inline'")
    # CSP_SCRIPT_SRC = ("'self'", "https://cdn.jsdelivr.net")
    X_FRAME_OPTIONS = "DENY"
    SECURE_BROWSER_XSS_FILTER = True  # Antiguo; algunos navegadores lo ignoran
    SECURE_CONTENT_TYPE_NOSNIFF = True
