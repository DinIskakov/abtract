import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def temporary_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_dir", tmp_path / "artifacts")
