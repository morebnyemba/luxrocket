"""Django settings. All environment-specific values come from environment variables.

No secret has a production-safe default: missing secrets fail fast unless DJANGO_DEBUG=1.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


DEBUG = env("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key" if DEBUG else None)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.admin",
    "django.contrib.messages",
    "rest_framework",
    "luxrocket.core",
    "luxrocket.operators",
    "luxrocket.gaming",
    "luxrocket.wallet",
    "luxrocket.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "luxrocket.core.middleware.GameApiCorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "luxrocket.core.db.backend",
        "NAME": env("POSTGRES_DB", "luxrocket"),
        "USER": env("POSTGRES_USER", "luxrocket"),
        "PASSWORD": env("POSTGRES_PASSWORD", "luxrocket-dev-only" if DEBUG else None),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"options": "-c search_path=platform,public"},
    }
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
}

# Security headers (non-embeddable surfaces; the game launch document sets its own CSP).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Strict"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# --- LUX ROCKET platform settings ------------------------------------------------------------

# Shared bearer token for Phoenix <-> Django internal calls (mTLS added in production).
INTERNAL_SERVICE_TOKEN = env("INTERNAL_SERVICE_TOKEN", "dev-internal-token" if DEBUG else None)

# Ed25519 key (base64 of the 32-byte raw private key) signing game-session tokens (ADR-022).
GAME_TOKEN_PRIVATE_KEY_B64 = env(
    "GAME_TOKEN_PRIVATE_KEY_B64",
    # Deterministic dev-only key; production must provide its own.
    "ZGV2LW9ubHktbm90LWEtc2VjcmV0LWdhbWUta2V5ISE=" if DEBUG else None,
)
GAME_TOKEN_TTL_SECONDS = int(env("GAME_TOKEN_TTL_SECONDS", "900"))
LAUNCH_TOKEN_TTL_SECONDS = int(env("LAUNCH_TOKEN_TTL_SECONDS", "60"))
WS_TICKET_TTL_SECONDS = int(env("WS_TICKET_TTL_SECONDS", "30"))
SESSION_MAX_HOURS = int(env("SESSION_MAX_HOURS", "24"))

# Origins and URLs.
GAME_ORIGIN = env("GAME_ORIGIN", "http://localhost:3000")
PLAY_BASE_URL = env("PLAY_BASE_URL", GAME_ORIGIN)
REALTIME_INTERNAL_URL = env("REALTIME_INTERNAL_URL", "http://localhost:4000")

# Sandbox wallet opening balance for new players (minor units).
SANDBOX_OPENING_BALANCE_MINOR = int(env("SANDBOX_OPENING_BALANCE_MINOR", "100000"))

# Game rules (must match the stream's ruleset in Phoenix; doc 07 §1).
RULESET = {
    "house_edge_bp": 300,
    "max_multiplier_x10000": 100_000_000,
    "panels": 2,
}
SANDBOX_DEBIT_UNKNOWN_RATE = float(env("SANDBOX_DEBIT_UNKNOWN_RATE", "0"))
CONTRACTS_DIR = env("CONTRACTS_DIR", str(BASE_DIR.parent / "contracts"))
