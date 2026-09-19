"""Where are site versions served? One answer for local dev, `modal run`, and code running inside Modal.

    resolve_site_base_url() -> "https://<ws>--abtract-site.modal.run" | settings.site_base_url | "http://localhost:8000"
    site_url(site_id, version)   -> "<base>/s/<site_id>/<version>/"
    demo_site_url()              -> site_url("demo", "v0")

Resolution order: ABTRACT_SITE_BASE_URL (settings.site_base_url) -> the deployed Modal `site_server` web URL
(modal.Function.from_name("abtract", "site_server").get_web_url(), cached; needs a Modal token or a container)
-> http://localhost:8000. Lookups that fail are not retried for NEGATIVE_TTL_S so callers can poll cheaply.
"""
from __future__ import annotations

import threading
import time

from abtract.config import settings
from abtract.modal_app import APP_NAME

LOCAL_DEFAULT = "http://localhost:8000"
NEGATIVE_TTL_S = 60.0

_lock = threading.Lock()
_cached: str | None = None
_failed_at: float | None = None


def _modal_web_url() -> str | None:
    import modal

    fn = modal.Function.from_name(APP_NAME, "site_server")
    url = fn.get_web_url()  # hydrates the handle: raises when there is no token / no deployed app
    return url.rstrip("/") if url else None


def resolve_site_base_url(*, refresh: bool = False) -> str:
    """Base URL of the site server (no trailing slash)."""
    global _cached, _failed_at
    if settings.site_base_url:
        return settings.site_base_url.rstrip("/")
    with _lock:
        if _cached and not refresh:
            return _cached
        if not refresh and _failed_at is not None and time.monotonic() - _failed_at < NEGATIVE_TTL_S:
            return LOCAL_DEFAULT
        try:
            url = _modal_web_url()
        except Exception:  # noqa: BLE001  no token, not deployed, offline, ...
            url = None
        if url:
            _cached, _failed_at = url.rstrip("/"), None
            return _cached
        _failed_at = time.monotonic()
        return LOCAL_DEFAULT


def site_url(site_id: str, version: str) -> str:
    return f"{resolve_site_base_url()}/s/{site_id}/{version}/"


def demo_site_url() -> str:
    return site_url("demo", "v0")
