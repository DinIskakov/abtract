"""Site server: serves every site version out of the store and records what agents do on the site.

Routes (all under /s/{site_id}/{version}/):
    GET  <path>              static file; "" or a directory -> index.html; missing "x" -> "x.html"
    POST api/event           JSON {"name": str, "payload": {...}} -> SiteEvent
    POST api/{name}          form-encoded or JSON body -> SiteEvent(name=name, payload=fields);
                             browsers (Accept: text/html) get a 303 to thanks.html, others JSON
    GET  api/events          ?episode_id=... -> JSON list of SiteEvents (debug)

Episode attribution order: header X-Abtract-Episode, query ?abtract_ep=, cookie abtract_ep. When the header or
query is present the cookie is set on the response so later plain navigations by a browser keep the attribution.

Local dev:  uv run python -m abtract.hosting.serve --port 8000
Modal:      registered on the shared app as `site_server` (label "site").
"""
from __future__ import annotations

import html
import json
import mimetypes
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from abtract import store
from abtract.schemas import SiteEvent

EPISODE_HEADER = "x-abtract-episode"
EPISODE_PARAM = "abtract_ep"
EPISODE_COOKIE = "abtract_ep"
COOKIE_MAX_AGE_S = 6 * 3600

# How long to wait before we are willing to `store.reload()` again for the same missing version dir.
RELOAD_THROTTLE_S = 5.0

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".xml": "application/xml",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def content_type_for(path: Path) -> str:
    ct = _CONTENT_TYPES.get(path.suffix.lower())
    if ct:
        return ct
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


# --------------------------------------------------------------------------- helpers

class _VersionCache:
    """Remembers which version dirs exist so we only hit `store.reload()` when a version is genuinely unknown,
    and at most once per RELOAD_THROTTLE_S per version (Volume reloads are expensive)."""

    def __init__(self) -> None:
        self.known: set[tuple[str, str]] = set()
        self.last_reload: dict[tuple[str, str], float] = {}
        self.lock = threading.Lock()

    def resolve(self, site_id: str, version: str) -> Path | None:
        key = (site_id, version)
        d = store.site_dir(site_id, version)
        if d.is_dir():
            with self.lock:
                self.known.add(key)
            return d
        with self.lock:
            self.known.discard(key)
            now = time.monotonic()
            if now - self.last_reload.get(key, -1e9) < RELOAD_THROTTLE_S:
                return None
            self.last_reload[key] = now
        store.reload()
        if d.is_dir():
            with self.lock:
                self.known.add(key)
            return d
        return None


def _safe_join(base: Path, rel: str) -> Path | None:
    """Join `rel` onto `base`, refusing anything that escapes it. Returns None when unsafe."""
    rel = rel.replace("\\", "/")
    if "\x00" in rel:
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    candidate = base.joinpath(*parts) if parts else base
    try:
        base_r = base.resolve()
        cand_r = candidate.resolve()
    except OSError:
        return None
    if cand_r != base_r and base_r not in cand_r.parents:
        return None
    return candidate


def _pick_file(base: Path, rel: str) -> Path | None:
    """Apply the index.html / .html fallbacks. Returns an existing file or None."""
    p = _safe_join(base, rel)
    if p is None:
        return None
    if p.is_dir():
        idx = _safe_join(base, str((p / "index.html").relative_to(base)))
        return idx if idx is not None and idx.is_file() else None
    if p.is_file():
        return p
    if not rel.endswith("/"):
        alt = p.with_name(p.name + ".html")
        if alt.is_file() and _safe_join(base, rel + ".html") is not None:
            return alt
    return None


def episode_from_request(request: Request, extra: dict[str, Any] | None = None) -> tuple[str | None, bool]:
    """Return (episode_id, explicit). `explicit` is True when it came from the header/query/body (-> set cookie)."""
    ep = request.headers.get(EPISODE_HEADER)
    if ep:
        return ep.strip(), True
    ep = request.query_params.get(EPISODE_PARAM)
    if ep:
        return ep.strip(), True
    if extra:
        ep = extra.get(EPISODE_PARAM)
        if isinstance(ep, str) and ep.strip():
            return ep.strip(), True
    ep = request.cookies.get(EPISODE_COOKIE)
    return (ep.strip() if ep else None), False


def _set_episode_cookie(resp: Response, episode_id: str) -> None:
    resp.set_cookie(EPISODE_COOKIE, episode_id, max_age=COOKIE_MAX_AGE_S, path="/", samesite="lax", httponly=False)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "application/xhtml+xml" in accept


async def _read_body_fields(request: Request) -> dict[str, Any]:
    """Body of a form post or a JSON post as a flat dict."""
    ctype = request.headers.get("content-type", "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return {}
        return dict(data) if isinstance(data, dict) else {"value": data}
    if "form" in ctype:  # application/x-www-form-urlencoded or multipart/form-data
        form = await request.form()
        out: dict[str, Any] = {}
        for k in form.keys():
            vals = form.getlist(k)
            vals = [v if isinstance(v, str) else getattr(v, "filename", str(v)) for v in vals]
            out[k] = vals[0] if len(vals) == 1 else vals
        return out
    raw = (await request.body()).decode("utf-8", "replace").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return dict(data) if isinstance(data, dict) else {"value": data}
    except ValueError:
        return {"raw": raw}


_events_lock = threading.Lock()


def record_event(site_id: str, version: str, name: str, payload: dict[str, Any], episode_id: str | None) -> SiteEvent:
    ev = SiteEvent(name=name, payload=payload, site_id=site_id, version=version, episode_id=episode_id)
    with _events_lock:
        store.append_event(ev)
        store.commit()
    return ev


def _site_root_path(request: Request, site_id: str, version: str) -> str:
    return f"{request.scope.get('root_path', '')}/s/{site_id}/{version}/"


# --------------------------------------------------------------------------- app

def create_app() -> FastAPI:
    app = FastAPI(title="abtract site server", docs_url=None, redoc_url=None)
    versions = _VersionCache()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/")
    def index(request: Request):
        sites = [{"site_id": s, "versions": [v.model_dump() for v in store.list_versions(s)]} for s in store.list_sites()]
        if not _wants_html(request):
            return JSONResponse({"sites": sites})
        rows = []
        for s in sites:
            vers = s["versions"] or [{"version": p.name} for p in (store.root() / "sites" / s["site_id"]).iterdir() if p.is_dir()]
            links = " ".join(
                f'<a href="{html.escape(_site_root_path(request, s["site_id"], v["version"]))}">{html.escape(v["version"])}</a>'
                for v in vers
            )
            rows.append(f"<li><b>{html.escape(s['site_id'])}</b>: {links or '<i>no versions</i>'}</li>")
        body = (
            "<!doctype html><meta charset=utf-8><title>abtract sites</title>"
            "<style>body{font-family:system-ui,sans-serif;background:#0d0d0d;color:#eee;padding:2rem}"
            "a{color:#3987e5;margin-right:.5rem}</style>"
            "<h1>abtract site server</h1>"
            f"<ul>{''.join(rows) or '<li><i>no sites imported yet</i></li>'}</ul>"
        )
        return HTMLResponse(body)

    # ---- events (declared before the catch-all so /api/events wins over the file route)

    @app.get("/s/{site_id}/{version}/api/events")
    def list_events(site_id: str, version: str, episode_id: str | None = None):
        evs = store.read_events(site_id, version, episode_id)
        return JSONResponse([e.model_dump() for e in evs])

    @app.post("/s/{site_id}/{version}/api/event")
    async def post_event(site_id: str, version: str, request: Request):
        fields = await _read_body_fields(request)
        name = fields.get("name")
        if not isinstance(name, str) or not name.strip():
            return JSONResponse({"ok": False, "error": "missing 'name'"}, status_code=400)
        payload = fields.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        ep, explicit = episode_from_request(request, fields)
        ev = record_event(site_id, version, name.strip(), payload, ep)
        resp = JSONResponse({"ok": True, "episode_id": ev.episode_id, "name": ev.name, "ts": ev.ts})
        if explicit and ep:
            _set_episode_cookie(resp, ep)
        return resp

    @app.post("/s/{site_id}/{version}/api/{name}")
    async def post_named_event(site_id: str, version: str, name: str, request: Request):
        fields = await _read_body_fields(request)
        ep, explicit = episode_from_request(request, fields)
        payload = {k: v for k, v in fields.items() if k != EPISODE_PARAM}
        ev = record_event(site_id, version, name, payload, ep)
        if _wants_html(request):
            base = versions.resolve(site_id, version)
            root = _site_root_path(request, site_id, version)
            if base is not None and (base / "thanks.html").is_file():
                resp: Response = RedirectResponse(root + "thanks.html", status_code=303)
            else:
                resp = HTMLResponse(
                    "<!doctype html><meta charset=utf-8><title>Thanks</title>"
                    "<style>body{font-family:system-ui,sans-serif;padding:2rem}</style>"
                    f"<h1>Thanks!</h1><p>Your <code>{html.escape(name)}</code> submission was received.</p>"
                    f'<p><a href="{html.escape(root)}">Back to the site</a></p>'
                )
        else:
            resp = JSONResponse({"ok": True, "episode_id": ev.episode_id, "name": ev.name, "ts": ev.ts})
        if explicit and ep:
            _set_episode_cookie(resp, ep)
        return resp

    # ---- static site files

    @app.get("/s/{site_id}/{version}")
    def site_root_redirect(site_id: str, version: str, request: Request):
        url = _site_root_path(request, site_id, version)
        if request.url.query:
            url += "?" + request.url.query
        return RedirectResponse(url, status_code=307)

    @app.get("/s/{site_id}/{version}/{path:path}")
    def serve_file(site_id: str, version: str, path: str, request: Request):
        ep, explicit = episode_from_request(request)
        base = versions.resolve(site_id, version)
        if base is None:
            resp: Response = PlainTextResponse(f"unknown site version {site_id}/{version}", status_code=404)
        else:
            f = _pick_file(base, path)
            if f is None:
                resp = PlainTextResponse("not found", status_code=404)
            else:
                resp = FileResponse(f, media_type=content_type_for(f), headers={"Cache-Control": "no-cache"})
        if explicit and ep:
            _set_episode_cookie(resp, ep)
        return resp

    return app


# --------------------------------------------------------------------------- Modal registration

try:
    import modal

    from abtract.modal_app import app as _modal_app, base_image, secrets, volumes

    @_modal_app.function(image=base_image, volumes=volumes, secrets=secrets, max_containers=1)
    @modal.concurrent(max_inputs=100)
    @modal.asgi_app(label="site")
    def site_server():
        return create_app()

except Exception:  # noqa: BLE001  modal not configured (e.g. no token in CI); local dev still works
    site_server = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- local dev

def main(argv: list[str] | None = None) -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="Serve site versions from the local store.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    print(f"abtract site server on http://{args.host}:{args.port}/  (data dir: {store.root().resolve()})")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
