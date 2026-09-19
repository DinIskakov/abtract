"""Small local JSON store for the MVP. No database or job queue."""

import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.config import settings

ArtifactKind = Literal["runs", "evaluations", "proposals", "evaluation_inputs"]


def artifact_path(kind: ArtifactKind, identifier: str) -> Path:
    # Only generated UUIDs are filenames; never accept paths from API clients.
    return settings.artifact_dir / kind / f"{UUID(identifier)}.json"


def save_artifact(kind: ArtifactKind, identifier: str, value: BaseModel) -> None:
    path = artifact_path(kind, identifier)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(f".{uuid4()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(value.model_dump_json(indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_artifact(kind: ArtifactKind, identifier: str) -> dict[str, object]:
    value: dict[str, object] = json.loads(artifact_path(kind, identifier).read_text())
    return value
