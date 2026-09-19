"""Frozen, exact response patches. Drift leaves the original response intact."""

import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class VariantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    patch_id: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    old_text: str = Field(min_length=1, max_length=100_000)
    new_text: str = Field(max_length=100_000)


PatchStatus = Literal[
    "applied",
    "hash_mismatch",
    "text_not_unique",
    "unsupported_encoding",
    "response_ineligible",
]


class PatchOutcome(BaseModel):
    patch_id: str
    status: PatchStatus


def origin(url: str) -> tuple[str, str | None, int | None]:
    parts = urlsplit(url)
    return (
        parts.scheme,
        parts.hostname,
        parts.port or (443 if parts.scheme == "https" else 80),
    )


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def variant_hash(patches: list[VariantPatch]) -> str:
    payload = [patch.model_dump(mode="json") for patch in patches]
    return sha256(json.dumps(payload, sort_keys=True).encode())


def apply_patch(body: bytes, patch: VariantPatch) -> tuple[bytes, PatchOutcome]:
    status: PatchStatus = "applied"
    if sha256(body) != patch.expected_sha256:
        status = "hash_mismatch"
    else:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            status = "unsupported_encoding"
        else:
            if text.count(patch.old_text) != 1:
                status = "text_not_unique"
            else:
                body = text.replace(patch.old_text, patch.new_text, 1).encode()
    return body, PatchOutcome(patch_id=patch.patch_id, status=status)
