"""Test settings: safe local defaults, then the real settings module."""

import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-key")

from config.settings import *  # noqa: F403
