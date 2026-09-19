"""Tests for the product API: seed fake data into a temporary store, then hit the routes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import settings

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
        seed_mod = _load_script("seed_fake_data")
        run_ids = seed_mod.seed("demo", None, seed=7, verbose=False)
        yield {"data_dir": data_dir, "run_ids": run_ids, "seed_mod": seed_mod}
    finally:
        settings.data_dir = old


@pytest.fixture()
def client(seeded, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "data_dir", seeded["data_dir"])
    from app.routers.product import create_app

    return TestClient(create_app())


# --------------------------------------------------------------------------- seed script itself


def test_seed_writes_consistent_metrics(seeded):
    run_ids = seeded["run_ids"]
    assert list(run_ids) == ["v0", "v1", "v2"]
    assert [v.version for v in store.list_versions("demo")] == ["v0", "v1", "v2"]
    rates = []
    for _version, run_id in run_ids.items():
        run = store.load_run(run_id)
        eps = store.load_episodes(run_id)
        assert run.overall.episodes == len(eps) == 3 * 3 * 8
        assert run.overall.success_rate == pytest.approx(sum(1 for e in eps if e.success) / len(eps))
        assert run.overall.total_cost_usd == pytest.approx(sum(e.cost_usd for e in eps))
        assert sum(run.overall.failure_modes.values()) == sum(1 for e in eps if not e.success)
        assert set(run.per_model) == set(run.model_ids) and set(run.per_agent) == {"text", "dom", "vision"}
        assert set(run.per_task) == {t.id for t in run.tasks}
        assert sum(b.episodes for b in run.per_trap.values()) == len(eps)
        assert all(e.steps and e.finished_at for e in eps)
        rates.append(run.overall.success_rate)
    assert rates[0] < rates[1] < rates[2], "success should improve across versions"
    assert store.list_versions("demo")[1].notes and store.list_versions("demo")[1].changed_files
    assert (store.site_dir("demo", "v2") / "index.html").exists()
    assert store.read_events("demo", "v2"), "action tasks should have recorded SiteEvents"


# --------------------------------------------------------------------------- API


def test_health(client: TestClient):
    assert client.get("/healthz").json()["ok"] is True


def test_overview(client: TestClient, seeded):
    ov = client.get("/api/overview").json()
    site = next(s for s in ov["sites"] if s["site_id"] == "demo")
    assert [v["version"] for v in site["versions"]] == ["v0", "v1", "v2"]
    for v in site["versions"]:
        assert len(v["runs"]) == 1 and v["runs"][0]["run_id"] == seeded["run_ids"][v["version"]]
        assert "tasks" not in v["runs"][0] and v["runs"][0]["n_tasks"] == 8
        assert "overall" in v["runs"][0]
    assert site["versions"][1]["notes"]
    assert len(ov["runs"]) >= 3


def test_meta(client: TestClient):
    m = client.get("/api/meta").json()
    assert "kimi-k3" in m["models"] and m["agent_kinds"] == ["text", "dom", "vision"]


def test_runs_and_episodes(client: TestClient, seeded):
    run_id = seeded["run_ids"]["v1"]
    runs = client.get("/api/runs").json()
    assert any(r["run_id"] == run_id for r in runs)
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["run_id"] == run_id and len(run["tasks"]) == 8 and run["per_model"]
    eps = client.get(f"/api/runs/{run_id}/episodes").json()
    assert len(eps) == 72
    assert "steps" not in eps[0] and eps[0]["n_steps"] > 0 and eps[0]["duration_s"] > 0
    vision = next(e for e in eps if e["agent_kind"] == "vision")
    assert vision["has_screenshots"] is True
    full = client.get(f"/api/runs/{run_id}/episodes/{vision['id']}").json()
    assert full["steps"] and full["steps"][0]["screenshot_url"].startswith(f"/screenshots/{run_id}/{vision['id']}/")
    png = client.get(full["steps"][0]["screenshot_url"])
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    text = next(e for e in eps if e["agent_kind"] == "text")
    full_t = client.get(f"/api/runs/{run_id}/episodes/{text['id']}").json()
    assert all(s["screenshot_url"] is None for s in full_t["steps"])
    assert client.get(f"/api/runs/{run_id}/episodes/ep_missing").status_code == 404
    assert client.get("/api/runs/run_missing").status_code == 404
    assert client.get("/api/runs/run_missing/episodes").status_code == 404
    assert client.get(f"/screenshots/{run_id}/{vision['id']}/nope.png").status_code == 404


def test_compare(client: TestClient, seeded):
    a, b = seeded["run_ids"]["v0"], seeded["run_ids"]["v2"]
    cmp = client.get(f"/api/compare?a={a}&b={b}").json()
    assert cmp["a"]["run_id"] == a and cmp["b"]["run_id"] == b
    assert cmp["delta"]["success_rate"] == pytest.approx(
        cmp["b"]["overall"]["success_rate"] - cmp["a"]["overall"]["success_rate"]
    )
    assert cmp["delta"]["success_rate"] > 0
    assert len(cmp["per_task"]) == 8
    row = cmp["per_task"][0]
    assert row["prompt"] and row["a"] and row["b"] and "success_rate" in row["delta"]
    assert cmp["per_model"] and cmp["per_agent"] and cmp["per_trap"]
    assert client.get(f"/api/compare?a={a}&b=nope").status_code == 404


def test_site_files_and_events(client: TestClient):
    files = client.get("/api/sites/demo/versions/v1/files").json()["files"]
    assert "index.html" in files and "docs/index.html" in files
    r = client.get("/api/sites/demo/versions/v1/file", params={"path": "pricing.html"})
    assert r.status_code == 200 and "$3.95/hr" in r.text
    r0 = client.get("/api/sites/demo/versions/v0/file", params={"path": "pricing.html"})
    assert "$3.95/hr" not in r0.text  # v0 hides the price in an image; v1 fixed it
    assert client.get("/api/sites/demo/versions/v1/file", params={"path": "../versions.json"}).status_code == 400
    assert client.get("/api/sites/demo/versions/v1/file", params={"path": "nope.html"}).status_code == 404
    assert client.get("/api/sites/demo/versions/v9/files").status_code == 404
    evs = client.get("/api/sites/demo/versions/v2/events").json()
    assert evs and evs[0]["name"] in ("waitlist_submit", "contact_submit")
    one = client.get("/api/sites/demo/versions/v2/events", params={"episode_id": evs[0]["episode_id"]}).json()
    assert len(one) >= 1 and all(e["episode_id"] == evs[0]["episode_id"] for e in one)


def test_api_reloads_store(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(store, "reload", lambda: calls.append(1))
    client.get("/api/runs")
    client.get("/api/overview")
    assert len(calls) == 2
