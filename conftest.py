import os

import pytest

os.environ.setdefault("DEBUG", "true")
os.environ["DATABASE_URL"] = "sqlite://:memory:"


@pytest.fixture(autouse=True)
def plain_static_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
