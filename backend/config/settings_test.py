"""Test settings: safe local defaults, then the real settings module."""

import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-key")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")

from config.settings import *  # noqa: F403
