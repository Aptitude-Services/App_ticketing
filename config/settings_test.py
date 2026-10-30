"""Paramètres de test : base SQLite en mémoire, mots de passe hachés rapidement."""
import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")

from .settings import *  # noqa: E402,F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
AXES_ENABLED = False
import tempfile  # noqa: E402

MEDIA_ROOT = tempfile.mkdtemp(prefix="aptitude-test-media-")
