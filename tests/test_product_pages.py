"""Tests for the product front door in abtract/dashboard/app.py: landing + job pages, POST/GET /api/jobs,
/api/models, /api/demo-url. The job runner (abtract.jobs) and abtract.hosting.urls are faked via sys.modules."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abtract import store
from abtract.config import settings
from abtract.schemas import Job

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory):
    data_dir = tmp_path_factory.mktemp("data")
    old = settings.data_dir
    settings.data_dir = data_dir
    try:
        run_ids = _load_script("seed_fake_data").seed("demo", None, seed=7, verbose=False)
        yield {"data_dir": data_dir, "run_ids": run_ids}
    finally:
        settings.data_dir = old


@pytest.fixture()
def client(seeded, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "data_dir", seeded["data_dir"])
    from abtract.dashboard.app import create_app

    return TestClient(create_app())


@pytest.fixture()
def fake_runner(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake `abtract.jobs` whose start_job records the job and marks it running (like the real one would)."""
    calls: list[Job] = []

    def start_job(job: Job) -> Job:
        calls.append(job)
        job.status = "running"
        job.phase = "Mirroring site"
        job.log.append("fake runner picked up the job")
        store.save_job(job)
        return job

    mod = types.ModuleType("abtract.jobs")
    mod.start_job = start_job  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "abtract.jobs", mod)
    return calls


def _job_file(job_id: str) -> Path:
    return store.jobs_dir() / f"{job_id}.json"


# --------------------------------------------------------------------------- pages

def test_landing_page(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'id="url"' in r.text and "Try with the demo site" in r.text and "let it fix itself" in r.text
    assert "/static/landing.js" in r.text
    assert 'id="budget"' not in r.text
    assert client.get("/static/landing.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/static/product.css").headers["content-type"].startswith("text/css")


def test_dashboard_page(client: TestClient):
    r = client.get("/dashboard")
    assert r.status_code == 200 and "Version timeline" in r.text and "/static/app.js" in r.text
    assert 'id="site-select"' in r.text
    assert client.get("/dashboard?site=demo").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_job_page(client: TestClient):
    job = Job(type="intake", url="https://example.com", model_ids=["mock"], agent_kinds=["text"])
    store.save_job(job)
    r = client.get(f"/jobs/{job.id}")
    assert r.status_code == 200 and 'id="stepper"' in r.text and "/static/job.js" in r.text
    missing = client.get("/jobs/job_doesnotexist")
    assert missing.status_code == 404 and 'id="stepper"' in missing.text  # page still renders; JS shows "not found"
    assert client.get("/jobs", follow_redirects=False).status_code in (307, 308)


# --------------------------------------------------------------------------- POST /api/jobs

def test_create_intake_job(client: TestClient, fake_runner):
    body = {"type": "intake", "url": "https://zephyr.example.com/", "model_ids": ["mock", "kimi-k3"], "agent_kinds": ["text", "dom"], "budget_usd": 2.5}
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert job_id.startswith("job_") and r.json()["job"]["status"] == "running"
    assert len(fake_runner) == 1 and fake_runner[0].id == job_id
    assert _job_file(job_id).is_file()
    saved = store.load_job(job_id)
    assert saved.type == "intake" and saved.url == "https://zephyr.example.com/"
    assert saved.model_ids == ["mock", "kimi-k3"] and [k.value for k in saved.agent_kinds] == ["text", "dom"]
    assert saved.budget_usd == 2.5 and saved.status == "running" and saved.log


def test_create_job_defaults(client: TestClient, fake_runner):
    from abtract.models.registry import DEFAULT_SWARM

    r = client.post("/api/jobs", json={"url": "zephyr.example.com"})
    assert r.status_code == 200, r.text
    saved = store.load_job(r.json()["job_id"])
    assert saved.url == "https://zephyr.example.com"
    assert saved.model_ids == list(DEFAULT_SWARM)
    assert [k.value for k in saved.agent_kinds] == ["text", "dom", "vision"]
    assert saved.budget_usd == settings.job_swarm_budget_usd and saved.iterations == 1


def test_create_loop_job(client: TestClient, fake_runner, seeded):
    run_id = seeded["run_ids"]["v2"]
    r = client.post("/api/jobs", json={"type": "loop", "site_id": "demo", "site_version": "v2", "run_id": run_id, "iterations": 2})
    assert r.status_code == 200, r.text
    saved = store.load_job(r.json()["job_id"])
    run = store.load_run(run_id)
    assert saved.type == "loop" and saved.site_id == "demo" and saved.site_version == "v2" and saved.iterations == 2
    assert saved.url == run.site_url
    assert saved.model_ids == run.model_ids and saved.agent_kinds == run.agent_kinds  # copied from the source run
    r2 = client.post("/api/jobs", json={"type": "loop", "site_id": "demo", "site_version": "v2", "run_id": run_id, "model_ids": ["mock"], "agent_kinds": ["vision"]})
    saved2 = store.load_job(r2.json()["job_id"])
    assert saved2.model_ids == ["mock"] and [k.value for k in saved2.agent_kinds] == ["vision"]


def test_quick_scan_defaults_to_a_small_grid(client: TestClient, fake_runner):
    r = client.post("/api/jobs", json={"url": "https://example.com", "scan_mode": "quick"})
    assert r.status_code == 200
    job = store.load_job(r.json()["job_id"])
    assert job.scan_mode == "quick" and len(job.model_ids) == 1
    assert [k.value for k in job.agent_kinds] == ["text", "dom"]


@pytest.mark.parametrize("body,needle", [
    ({"type": "intake"}, "url is required"),
    ({"type": "intake", "url": "   "}, "url is required"),
    ({"type": "intake", "url": "ftp://x.example"}, "http(s)"),
    ({"type": "intake", "url": "https://x.example", "model_ids": []}, "at least one model"),
    ({"type": "intake", "url": "https://x.example", "model_ids": ["nope-9000"]}, "unknown model"),
    ({"type": "intake", "url": "https://x.example", "agent_kinds": ["telepathy"]}, "unknown agent kind"),
    ({"type": "intake", "url": "https://x.example", "agent_kinds": []}, "at least one agent"),
    ({"type": "intake", "url": "https://x.example", "budget_usd": -1}, "budget_usd"),
    ({"type": "loop"}, "site_id, site_version, run_id"),
    ({"type": "loop", "site_id": "demo", "site_version": "v2"}, "run_id"),
    ({"type": "loop", "site_id": "demo", "site_version": "v2", "run_id": "run_nope"}, "unknown run"),
    ({"type": "loop", "site_id": "other", "site_version": "v2", "run_id": "run_fake_v2"}, "belongs to site demo"),
    ({"type": "loop", "site_id": "demo", "site_version": "v2", "run_id": "run_fake_v2", "iterations": 0}, "iterations"),
    ({"type": "teleport", "url": "https://x.example"}, "type"),
    ({"type": "intake", "url": "https://x.example", "iterations": "many"}, "iterations"),
])
def test_create_job_validation(client: TestClient, fake_runner, body, needle):
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 422, r.text
    assert needle in r.json()["error"]
    assert not fake_runner, "invalid requests must not reach the runner"


def test_create_job_malformed_body(client: TestClient, fake_runner):
    r = client.post("/api/jobs", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "error" in r.json()
    assert not fake_runner


def test_create_job_runner_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "abtract.jobs", None)  # import raises ImportError
    r = client.post("/api/jobs", json={"url": "https://x.example"})
    assert r.status_code == 503 and "job runner unavailable" in r.json()["error"]
    failed = [j for j in store.list_jobs() if j.url == "https://x.example" and j.status == "failed"]
    assert failed and "job runner unavailable" in (failed[-1].error or "")


def test_create_job_runner_raises(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    mod = types.ModuleType("abtract.jobs")

    def start_job(job: Job) -> Job:
        raise RuntimeError("modal is down")

    mod.start_job = start_job  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "abtract.jobs", mod)
    r = client.post("/api/jobs", json={"url": "https://down.example"})
    assert r.status_code == 500 and "modal is down" in r.json()["error"]
    job = next(j for j in store.list_jobs() if j.url == "https://down.example")
    assert job.status == "failed" and "modal is down" in job.error


# --------------------------------------------------------------------------- GET /api/jobs

def test_list_and_get_jobs(client: TestClient, seeded):
    older = Job(type="intake", url="https://old.example", model_ids=["mock"], agent_kinds=["text"], created_at=1_000, log=["a", "b"], findings="# hi")
    newer = Job(type="loop", site_id="demo", site_version="v1", run_ids=[seeded["run_ids"]["v1"]], model_ids=["mock"], agent_kinds=["dom"], created_at=2_000_000_000)
    store.save_job(older)
    store.save_job(newer)
    jobs = client.get("/api/jobs").json()
    ids = [j["id"] for j in jobs]
    assert ids[0] == newer.id and ids.index(older.id) == len(ids) - 1  # newest first
    brief = next(j for j in jobs if j["id"] == older.id)
    assert "log" not in brief and "findings" not in brief and brief["has_findings"] is True and brief["last_log"] == "b" and brief["n_runs"] == 0
    assert len(client.get("/api/jobs?limit=1").json()) == 1
    full = client.get(f"/api/jobs/{older.id}").json()
    assert full["log"] == ["a", "b"] and full["findings"] == "# hi" and full["baseline_run_id"] is None
    assert client.get("/api/jobs/job_nope").status_code == 404


def test_baseline_run_id_for_loop_jobs(client: TestClient, seeded):
    rid = seeded["run_ids"]
    # first produced run is on v1 (parent v0) -> baseline is the run on v0
    produced = Job(type="loop", site_id="demo", site_version="v1", run_ids=[rid["v1"]], model_ids=["mock"], agent_kinds=["text"])
    store.save_job(produced)
    assert client.get(f"/api/jobs/{produced.id}").json()["baseline_run_id"] == rid["v0"]
    # nothing produced yet -> the latest run on the version the loop starts from
    fresh = Job(type="loop", site_id="demo", site_version="v2", model_ids=["mock"], agent_kinds=["text"])
    store.save_job(fresh)
    assert client.get(f"/api/jobs/{fresh.id}").json()["baseline_run_id"] == rid["v2"]


# --------------------------------------------------------------------------- models / demo url

def test_models(client: TestClient):
    from abtract.models.registry import DEFAULT_SWARM, MODELS

    m = client.get("/api/models").json()
    by_id = {x["id"]: x for x in m["models"]}
    assert set(by_id) == set(MODELS)
    for mid in DEFAULT_SWARM:
        assert by_id[mid]["default"] is True
    assert "mock" in by_id and by_id["mock"]["default"] is False and by_id["mock"]["provider"] == "mock"
    k = by_id["kimi-k3"]
    assert {"display_name", "provider", "supports_vision", "input_price_per_m", "output_price_per_m"} <= set(k)
    assert m["defaults"] == list(DEFAULT_SWARM) and m["agent_kinds"] == ["text", "dom", "vision"]


def test_demo_url(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    mod = types.ModuleType("abtract.hosting.urls")
    mod.demo_site_url = lambda: "https://ws--abtract-site.modal.run/s/demo/v0/"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "abtract.hosting.urls", mod)
    r = client.get("/api/demo-url").json()
    assert r == {"url": "https://ws--abtract-site.modal.run/s/demo/v0/", "source": "hosting.urls"}


def test_demo_url_fallback(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "abtract.hosting.urls", None)
    r = client.get("/api/demo-url").json()
    assert r["url"].endswith("/s/demo/v0/") and r["source"] == "fallback"
    mod = types.ModuleType("abtract.hosting.urls")

    def boom():
        raise RuntimeError("no base url")

    mod.demo_site_url = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "abtract.hosting.urls", mod)
    assert client.get("/api/demo-url").json()["source"] == "fallback"


# --------------------------------------------------------------------------- bundle fallback (Modal has no static/)

def test_bundle_fallback_serves_product_pages(seeded, monkeypatch: pytest.MonkeyPatch):
    from abtract.dashboard import app as dash, bundle

    bundle.refresh_if_stale()
    monkeypatch.setattr(settings, "data_dir", seeded["data_dir"])
    monkeypatch.setattr(dash, "STATIC_DIR", Path("/nonexistent/static"))
    c = TestClient(dash.create_app())
    assert c.get("/healthz").json()["static"] == "bundle"
    assert 'id="url"' in c.get("/").text
    assert "Version timeline" in c.get("/dashboard").text
    assert 'id="stepper"' in c.get("/jobs/job_x").text
    for name in ("landing.js", "job.js", "app.js", "product.css", "style.css"):
        assert c.get(f"/static/{name}").status_code == 200, name


def test_bundle_is_current():
    from abtract.dashboard import bundle

    assert bundle.current_bundle() == bundle.collect(), "run scripts/bundle_dashboard.py"
    assert {"index.html", "dashboard.html", "job.html", "landing.js", "job.js", "product.css"} <= set(bundle.collect())


def test_job_roundtrip_json(seeded):
    job = Job(type="intake", url="https://x.example", model_ids=["mock"], agent_kinds=["text"], findings="**bold**")
    store.save_job(job)
    raw = json.loads(_job_file(job.id).read_text())
    assert raw["agent_kinds"] == ["text"] and raw["findings"] == "**bold**"
