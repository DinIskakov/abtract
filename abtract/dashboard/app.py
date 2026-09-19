"""Dashboard + product front door: static pages and a JSON API over the store.

Pages (all static HTML from static/ or the embedded bundle; the JS talks to /api/*):
    GET /                                               landing: paste a URL -> starts an intake job
    GET /jobs/{job_id}                                  progress + report page for one job (polls /api/jobs/{id})
    GET /dashboard[?site=<site_id>]                     the full dashboard (timeline, A/B, heatmap, traces, diffs)

API (every handler reloads the Volume first; dashboard traffic is low enough for that):
    GET  /api/overview                                  sites -> versions (SiteVersion) -> runs (RunSummary, no tasks)
    GET  /api/meta                                      model display names / prices, agent kinds
    GET  /api/models                                    swarm models from the registry; `default` flags DEFAULT_SWARM
    GET  /api/demo-url                                  {"url": <hosted demo site>} (abtract.hosting.urls, with fallback)
    POST /api/jobs                                      start a job -> {"job_id": ...}. Body:
                                                            {"type":"intake","url":...,"model_ids":[...],"agent_kinds":[...],"budget_usd":...}
                                                            {"type":"loop","site_id":...,"site_version":...,"run_id":...,"iterations":N,...}
    GET  /api/jobs[?limit=20]                           recent jobs, newest first, without log/findings
    GET  /api/jobs/{job_id}                             full Job (+ baseline_run_id for loop jobs)
    GET  /api/runs                                      all RunSummaries (no tasks)
    GET  /api/runs/{run_id}                             full RunSummary
    GET  /api/runs/{run_id}/episodes                    episodes without steps (+ n_steps, duration_s)
    GET  /api/runs/{run_id}/episodes/{ep_id}            full episode, steps carry screenshot_url when a PNG exists
    GET  /api/compare?a=&b=                             side-by-side MetricBlocks + per_task/per_model/... deltas
    GET  /api/sites/{site_id}/versions/{v}/files        file list of one site version
    GET  /api/sites/{site_id}/versions/{v}/file?path=   one file as text
    GET  /api/sites/{site_id}/versions/{v}/events       SiteEvents (?episode_id= to filter)
    GET  /screenshots/{run_id}/{ep_id}/{name}           PNG from store.screenshot_dir

`abtract.jobs` (job runner) and `abtract.hosting.urls` are imported lazily inside the handlers so the dashboard
still serves everything else if they are missing or broken.

Local dev:  uv run python -m abtract.dashboard.app --port 8001
Modal:      registered on the shared app as `dashboard` (label "dashboard").
"""
from __future__ import annotations

import base64
import asyncio
import hmac
import math
import mimetypes
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel

from abtract import store
from abtract.config import settings
from abtract.dashboard import bundle
from abtract.schemas import AgentKind, Episode, Job, MetricBlock, RunSummary, SiteVersion

STATIC_DIR = bundle.STATIC_DIR
AGENT_KINDS = [k.value for k in AgentKind]
PAGES = {"index": "index.html", "dashboard": "dashboard.html", "job": "job.html"}

# Keep the embedded copy of the static assets in sync whenever this module is imported where static/ exists
# (local dev, and the local side of `modal deploy`). Inside a Modal container static/ is absent -> no-op.
try:
    bundle.refresh_if_stale()
except Exception:  # noqa: BLE001  read-only checkout etc.; the existing bundle is still used
    pass


# --------------------------------------------------------------------------- static assets

def _static(name: str) -> tuple[bytes, str] | None:
    p = STATIC_DIR / name
    if STATIC_DIR.is_dir() and ".." not in name and p.is_file():
        data = p.read_bytes()
    else:
        try:
            from abtract.dashboard import static_bundle
        except ImportError:
            return None
        data = static_bundle.FILES.get(name)
        if data is None:
            return None
    ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}.get(
        Path(name).suffix, mimetypes.guess_type(name)[0] or "application/octet-stream"
    )
    return data, ctype


def _page(name: str, status_code: int = 200) -> Response:
    got = _static(name)
    if got is None:
        return PlainTextResponse(f"dashboard asset {name} missing: run scripts/bundle_dashboard.py", status_code=500)
    return Response(got[0], media_type=got[1], headers={"Cache-Control": "no-cache"}, status_code=status_code)


# --------------------------------------------------------------------------- shaping helpers

def _run_brief(r: RunSummary) -> dict[str, Any]:
    d = r.model_dump(exclude={"tasks"})
    d["n_tasks"] = len(r.tasks)
    return d


def _episode_brief(e: Episode) -> dict[str, Any]:
    d = e.model_dump(exclude={"steps"})
    d["n_steps"] = e.n_steps
    d["duration_s"] = e.duration_s
    d["has_screenshots"] = any(s.screenshot_path for s in e.steps)
    return d


def _episode_full(e: Episode) -> dict[str, Any]:
    d = e.model_dump()
    d["n_steps"] = e.n_steps
    d["duration_s"] = e.duration_s
    shots = store.run_dir(e.run_id) / "screenshots" / store._safe(e.id)
    for s, sd in zip(e.steps, d["steps"]):
        sd["screenshot_url"] = None
        if s.screenshot_path:
            name = Path(s.screenshot_path).name
            if (shots / name).is_file():
                sd["screenshot_url"] = f"/screenshots/{e.run_id}/{e.id}/{name}"
    return d


_DELTA_FIELDS = ("episodes", "success_rate", "avg_steps", "avg_duration_s", "avg_cost_usd", "total_cost_usd")


def _delta(a: MetricBlock | None, b: MetricBlock | None) -> dict[str, float | None]:
    if a is None or b is None:
        return {k: None for k in _DELTA_FIELDS}
    return {k: getattr(b, k) - getattr(a, k) for k in _DELTA_FIELDS}


def _compare_group(ga: dict[str, MetricBlock], gb: dict[str, MetricBlock]) -> list[dict[str, Any]]:
    keys = list(dict.fromkeys([*ga.keys(), *gb.keys()]))
    return [
        {"key": k, "a": ga[k].model_dump() if k in ga else None, "b": gb[k].model_dump() if k in gb else None, "delta": _delta(ga.get(k), gb.get(k))}
        for k in keys
    ]


def _site_file(site_id: str, version: str, rel: str) -> Path:
    base = store.site_dir(site_id, version)
    if not base.is_dir():
        raise HTTPException(404, f"unknown site version {site_id}/{version}")
    rel = rel.replace("\\", "/").lstrip("/")
    if "\x00" in rel or any(p == ".." for p in rel.split("/")):
        raise HTTPException(400, "bad path")
    p = (base / rel)
    try:
        if base.resolve() not in p.resolve().parents and p.resolve() != base.resolve():
            raise HTTPException(400, "bad path")
    except OSError:
        raise HTTPException(400, "bad path") from None
    if not p.is_file():
        raise HTTPException(404, f"no such file {rel}")
    return p


def _version_key(v: SiteVersion) -> tuple[int, float]:
    """v0 < v1 < v10 regardless of created_at (re-imports bump created_at); non-numeric names sort by time after."""
    m = re.fullmatch(r"v(\d+)", v.version)
    return (int(m.group(1)), 0.0) if m else (1 << 30, v.created_at)


def _load_run(run_id: str) -> RunSummary:
    try:
        return store.load_run(run_id)
    except FileNotFoundError:
        raise HTTPException(404, f"unknown run {run_id}") from None


# --------------------------------------------------------------------------- jobs (product flow)

class JobRequest(BaseModel):
    """Body of POST /api/jobs. `model_ids`/`agent_kinds` omitted -> defaults; given but empty -> 422."""

    type: Literal["intake", "loop"] = "intake"
    scan_mode: Literal["quick", "full"] = "full"
    url: str | None = None
    site_id: str | None = None
    site_version: str | None = None
    run_id: str | None = None
    iterations: int = 1
    model_ids: list[str] | None = None
    agent_kinds: list[str] | None = None
    budget_usd: float | None = None


def _registry() -> tuple[dict[str, Any], list[str]]:
    """(ModelSpec by id, DEFAULT_SWARM ids that exist). Tolerates a registry that is mid-edit or broken."""
    try:
        from abtract.models import registry
    except Exception:  # noqa: BLE001
        return {}, []
    raw = getattr(registry, "MODELS", {})
    specs = list(raw.values()) if isinstance(raw, dict) else list(raw)
    models = {m.id: m for m in specs if getattr(m, "id", None)}
    defaults = [m for m in getattr(registry, "DEFAULT_SWARM", []) if m in models]
    return models, defaults


def _normalize_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(422, "url must be an http(s) URL, e.g. https://example.com")
    return url


def _build_job(req: JobRequest) -> Job:
    models, defaults = _registry()
    run: RunSummary | None = None
    if req.type == "loop":
        missing = [f for f in ("site_id", "site_version", "run_id") if not (getattr(req, f) or "").strip()]
        if missing:
            raise HTTPException(422, f"loop jobs need {', '.join(missing)}")
        try:
            run = store.load_run(req.run_id or "")
        except FileNotFoundError:
            raise HTTPException(422, f"unknown run {req.run_id}") from None
        if run.site_id != req.site_id:
            raise HTTPException(422, f"run {req.run_id} belongs to site {run.site_id}, not {req.site_id}")
        if run.site_version != req.site_version:
            raise HTTPException(422, "the baseline run must match the selected site version")
        if not store.site_dir(req.site_id or "", req.site_version or "").is_dir():
            raise HTTPException(422, f"site version {req.site_id}/{req.site_version} is not in the store")
        if not 1 <= req.iterations <= 10:
            raise HTTPException(422, "iterations must be between 1 and 10")
    elif not (req.url or "").strip():
        raise HTTPException(422, "url is required for an intake job")

    if req.model_ids is None:
        model_ids = list(run.model_ids) if run and run.model_ids else list(defaults) or (["mock"] if "mock" in models else [])
        if req.type == "intake" and req.scan_mode == "quick":
            model_ids = model_ids[:1]
    else:
        model_ids = list(dict.fromkeys(m.strip() for m in req.model_ids if m and m.strip()))
    if not model_ids:
        raise HTTPException(422, "pick at least one model")
    unknown = [m for m in model_ids if models and m not in models]
    if unknown:
        raise HTTPException(422, f"unknown model(s): {', '.join(unknown)}. Known: {', '.join(models)}")

    if req.agent_kinds is None:
        kinds = [k.value for k in run.agent_kinds] if run and run.agent_kinds else list(AGENT_KINDS)
        if req.type == "intake" and req.scan_mode == "quick":
            kinds = ["text", "dom"]
    else:
        kinds = list(dict.fromkeys(k.strip() for k in req.agent_kinds if k and k.strip()))
    bad = [k for k in kinds if k not in AGENT_KINDS]
    if bad:
        raise HTTPException(422, f"unknown agent kind(s): {', '.join(bad)}. Use {', '.join(AGENT_KINDS)}")
    if not kinds:
        raise HTTPException(422, "pick at least one agent kind")
    if req.budget_usd is not None and (not math.isfinite(req.budget_usd) or req.budget_usd <= 0):
        raise HTTPException(422, "budget_usd must be a positive number of dollars")

    allowance = req.budget_usd if req.budget_usd is not None else settings.job_swarm_budget_usd
    common: dict[str, Any] = {"model_ids": model_ids, "agent_kinds": [AgentKind(k) for k in kinds],
                              "budget_usd": allowance, "scan_mode": run.scan_mode if run else req.scan_mode}
    if req.type == "intake":
        return Job(type="intake", url=_normalize_url(req.url or ""), **common)
    assert run is not None
    # The runner takes run_ids[-1] as the baseline it optimizes from and appends every run it produces after it.
    return Job(type="loop", url=_normalize_url(req.url) if req.url else run.site_url or None, site_id=req.site_id, site_version=req.site_version,
               run_ids=[run.run_id], baseline_run_id=run.run_id, iterations=req.iterations, **common)


def _job_brief(job: Job) -> dict[str, Any]:
    d = job.model_dump(exclude={"log", "findings", "live_preview"})
    d["n_runs"] = len(job.run_ids)
    d["has_findings"] = bool(job.findings)
    d["last_log"] = job.log[-1] if job.log else None
    return d


def _prev_version(site_id: str, version: str) -> str | None:
    parent = next((v.parent for v in store.list_versions(site_id) if v.version == version), None)
    if parent:
        return parent
    m = re.fullmatch(r"v(\d+)", version)
    return f"v{int(m.group(1)) - 1}" if m and int(m.group(1)) > 0 else None


def _baseline_run_id(job: Job) -> str | None:
    """For a loop job: the run it started from, i.e. the "before" of the before/after report.

    POST /api/jobs seeds run_ids with the source run and the runner appends what it produces, so normally this is
    run_ids[0]. A run is the baseline (not produced by this job) when its site version predates the job. If the
    runner looked the baseline up itself, it is the latest finished run on the version the first produced run was
    derived from.
    """
    if job.type != "loop" or not job.site_id:
        return None
    if job.baseline_run_id:
        return job.baseline_run_id
    runs = {r.run_id: r for r in store.list_runs() if r.site_id == job.site_id}
    known = [runs[i] for i in job.run_ids if i in runs]
    if known:
        first = known[0]
        target = _prev_version(job.site_id, first.site_version)
        if target is None:
            return first.run_id
    else:
        target = job.site_version
    if not target:
        return None
    cands = [r for r in runs.values() if r.site_version == target and r.run_id not in job.run_ids]
    finished = [r for r in cands if r.finished_at]
    pick = finished or cands
    return max(pick, key=lambda r: r.created_at).run_id if pick else None


def _job_full(job: Job) -> dict[str, Any]:
    d = job.model_dump()
    d["baseline_run_id"] = _baseline_run_id(job)
    return d


def _load_job(job_id: str) -> Job:
    try:
        return store.load_job(job_id)
    except FileNotFoundError:
        raise HTTPException(404, f"unknown job {job_id}") from None


# --------------------------------------------------------------------------- app

def _fresh() -> None:
    store.reload()


class VolumeAccessMiddleware:
    """A reload temporarily unmounts the Volume in this web container.

    Keep it exclusive with all dashboard reads/writes, through the end of file
    responses. Other containers can still run swarm attempts in parallel.
    """
    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith(("/api/", "/jobs/", "/screenshots/")):
            async with self.lock:
                await self.app(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def create_app() -> FastAPI:
    import modal

    password = settings.dashboard_password
    if not modal.is_local() and not password:
        raise RuntimeError("Set ABTRACT_DASHBOARD_PASSWORD in abtract-secrets before hosting the product")
    app = FastAPI(title="abtract dashboard", docs_url="/api/docs", redoc_url=None)
    app.add_middleware(VolumeAccessMiddleware)
    if password:
        @app.middleware("http")
        async def authenticate(request: Request, call_next):
            if request.url.path == "/healthz":
                return await call_next(request)
            try:
                scheme, encoded = request.headers.get("authorization", "").split(" ", 1)
                user, supplied = base64.b64decode(encoded, validate=True).decode().split(":", 1)
                valid = scheme.lower() == "basic" and hmac.compare_digest(user.encode(), b"abtract") and hmac.compare_digest(supplied.encode(), password.encode())
            except (ValueError, UnicodeError):
                valid = False
            if not valid:
                return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="abtract", charset="UTF-8"'})
            return await call_next(request)
    api = APIRouter(prefix="/api", dependencies=[Depends(_fresh)])

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "data_dir": str(store.root()), "static": "dir" if (STATIC_DIR / "index.html").is_file() else "bundle"}

    # ---- pages

    @app.get("/")
    def index():
        return _page(PAGES["index"])

    @app.get("/dashboard")
    def dashboard_page():
        return _page(PAGES["dashboard"])

    @app.get("/jobs")
    def jobs_index():
        return RedirectResponse("/#recent", status_code=307)

    @app.get("/jobs/{job_id}")
    def job_page(job_id: str):
        store.reload()
        exists = (store.jobs_dir() / f"{store._safe(job_id)}.json").is_file()
        return _page(PAGES["job"], status_code=200 if exists else 404)

    @app.get("/static/{name:path}")
    def static(name: str):
        got = _static(name)
        if got is None:
            raise HTTPException(404)
        return Response(got[0], media_type=got[1], headers={"Cache-Control": "no-cache"})

    # ---- overview / meta

    @api.get("/overview")
    def overview() -> dict[str, Any]:
        runs = store.list_runs()
        sites = []
        for site_id in store.list_sites():
            versions = store.list_versions(site_id)
            known = {v.version for v in versions}
            # versions on disk without a versions.json entry (e.g. raw uploads) still show up
            for p in sorted((store.root() / "sites" / site_id).iterdir()):
                if p.is_dir() and p.name not in known:
                    versions.append(SiteVersion(site_id=site_id, version=p.name, created_at=p.stat().st_mtime))
            versions.sort(key=_version_key)
            sites.append({
                "site_id": site_id,
                "versions": [
                    {**v.model_dump(), "runs": [_run_brief(r) for r in runs if r.site_id == site_id and r.site_version == v.version]}
                    for v in versions
                ],
            })
        return {"sites": sites, "runs": [_run_brief(r) for r in runs]}

    @api.get("/meta")
    def meta() -> dict[str, Any]:
        models_by_id, _ = _registry()
        models = {m.id: m.model_dump(exclude={"model"}) for m in models_by_id.values()}
        return {"models": models, "agent_kinds": list(AGENT_KINDS)}

    @api.get("/models")
    def models() -> dict[str, Any]:
        models_by_id, defaults = _registry()
        out = []
        for m in models_by_id.values():
            out.append({
                "id": m.id, "display_name": m.display_name, "provider": m.provider, "supports_vision": m.supports_vision,
                "input_price_per_m": m.input_price_per_m, "output_price_per_m": m.output_price_per_m,
                "default": m.id in defaults,
            })
        return {"models": out, "defaults": defaults, "agent_kinds": list(AGENT_KINDS)}

    @api.get("/demo-url")
    def demo_url() -> dict[str, Any]:
        url, source = None, "hosting.urls"
        try:
            from abtract.hosting.urls import demo_site_url as _demo_site_url  # resolved by module path, so tests can patch it

            url = _demo_site_url()
        except Exception:  # noqa: BLE001  module missing / misconfigured -> fall back to the local site server
            url = None
        if not url:
            url, source = settings.site_url("demo", "v0"), "fallback"
        return {"url": url, "source": source}

    # ---- jobs

    @api.post("/jobs")
    def create_job(req: JobRequest) -> dict[str, Any]:
        job = _build_job(req)
        store.save_job(job)  # visible to the progress page even before the runner picks it up
        try:
            from abtract.jobs import start_job
        except ImportError as e:
            job.status, job.error = "failed", f"job runner unavailable: {e}"
            store.save_job(job)
            store.commit()
            raise HTTPException(503, job.error) from None
        try:
            started = start_job(job)
        except Exception as e:  # noqa: BLE001
            job.status, job.error = "failed", f"could not start job: {e}"
            store.save_job(job)
            store.commit()
            raise HTTPException(500, job.error) from None
        if isinstance(started, Job):
            job = started
        store.commit()
        return {"job_id": job.id, "job": _job_brief(job)}

    @api.get("/jobs")
    def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
        jobs = sorted(store.list_jobs(), key=lambda j: j.created_at, reverse=True)
        return [_job_brief(j) for j in jobs[: max(1, min(limit, 200))]]

    @api.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _job_full(_load_job(job_id))

    @api.get("/jobs/{job_id}/first-look")
    def first_look(job_id: str):
        job = _load_job(job_id)
        if job.type != "intake" or not job.url or job.status not in {"queued", "running"}:
            return None
        if job.live_preview and job.live_preview.page:
            return job.live_preview
        from abtract.optimizer.preview import fetch_first_look
        try:
            return fetch_first_look(job.url)
        except (httpx.HTTPError, ValueError):
            # The worker can continue with its normal crawl; a slow preview must
            # neither fail the job nor replace its saved state.
            return None

    # ---- runs & episodes

    @api.get("/runs")
    def runs() -> list[dict[str, Any]]:
        return [_run_brief(r) for r in store.list_runs()]

    @api.get("/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        return _load_run(run_id).model_dump()

    @api.get("/runs/{run_id}/episodes")
    def episodes(run_id: str) -> list[dict[str, Any]]:
        _load_run(run_id)
        return [_episode_brief(e) for e in store.load_episodes(run_id)]

    @api.get("/runs/{run_id}/episodes/{ep_id}")
    def episode(run_id: str, ep_id: str) -> dict[str, Any]:
        p = store.run_dir(run_id) / "episodes" / f"{store._safe(ep_id)}.json"
        if not p.is_file():
            raise HTTPException(404, f"unknown episode {ep_id}")
        return _episode_full(Episode.model_validate_json(p.read_text()))

    @api.get("/compare")
    def compare(a: str, b: str) -> dict[str, Any]:
        ra, rb = _load_run(a), _load_run(b)
        tasks = {t.id: t for t in [*ra.tasks, *rb.tasks]}
        per_task = _compare_group(ra.per_task, rb.per_task)
        for row in per_task:
            t = tasks.get(row["key"])
            row["prompt"] = t.prompt if t else row["key"]
            row["trap"] = t.trap if t else None
            row["kind"] = t.kind.value if t else None
        return {
            "a": _run_brief(ra),
            "b": _run_brief(rb),
            "delta": _delta(ra.overall, rb.overall),
            "per_task": per_task,
            "per_model": _compare_group(ra.per_model, rb.per_model),
            "per_agent": _compare_group(ra.per_agent, rb.per_agent),
            "per_trap": _compare_group(ra.per_trap, rb.per_trap),
        }

    # ---- site files & events

    @api.get("/sites/{site_id}/versions/{version}/files")
    def site_files(site_id: str, version: str) -> dict[str, Any]:
        base = store.site_dir(site_id, version)
        if not base.is_dir():
            raise HTTPException(404, f"unknown site version {site_id}/{version}")
        files = sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_file())
        return {"site_id": site_id, "version": version, "files": files}

    @api.get("/sites/{site_id}/versions/{version}/file")
    def site_file(site_id: str, version: str, path: str):
        p = _site_file(site_id, version, path)
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, f"{path} is not a text file ({len(data)} bytes)") from None
        return PlainTextResponse(text)

    @api.get("/sites/{site_id}/versions/{version}/events")
    def site_events(site_id: str, version: str, episode_id: str | None = None) -> list[dict[str, Any]]:
        return [e.model_dump() for e in store.read_events(site_id, version, episode_id)]

    @app.get("/screenshots/{run_id}/{ep_id}/{name}")
    def screenshot(run_id: str, ep_id: str, name: str):
        if "/" in name or name.startswith(".") or ".." in name:
            raise HTTPException(400, "bad name")
        p = store.run_dir(run_id) / "screenshots" / store._safe(ep_id) / name
        if not p.is_file():
            store.reload()
            if not p.is_file():
                raise HTTPException(404)
        return FileResponse(p, media_type=mimetypes.guess_type(name)[0] or "image/png")

    app.include_router(api)

    @app.exception_handler(HTTPException)
    async def _http_exc(_: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", ()) if x != "body")
            parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        return JSONResponse({"error": "; ".join(parts) or "invalid request"}, status_code=422)

    return app


# --------------------------------------------------------------------------- Modal registration

try:
    import modal

    from abtract.modal_app import app as _modal_app, base_image, secrets, volumes

    @_modal_app.function(image=base_image, volumes=volumes, secrets=secrets)
    @modal.concurrent(max_inputs=50)
    @modal.asgi_app(label="dashboard")
    def dashboard():
        return create_app()

except Exception:  # noqa: BLE001
    dashboard = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- local dev

def main(argv: list[str] | None = None) -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="Serve the abtract dashboard from the local store.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args(argv)
    print(f"abtract on http://{args.host}:{args.port}/  (dashboard at /dashboard, data dir: {store.root().resolve()})")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
