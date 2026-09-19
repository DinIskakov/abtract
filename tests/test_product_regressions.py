"""Cross-module checks for the hosted product flow; no paid model calls."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from abtract import jobs, store
from abtract.config import settings
from abtract.dashboard.app import JobRequest, _build_job, create_app
from abtract.hosting.serve import create_app as site_app
from abtract.schemas import Episode, Job, RunSummary, SiteVersion, Task
from abtract.swarm import runner


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "dashboard_password", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    site = store.site_dir("demo", "v0")
    site.mkdir(parents=True)
    (site / "index.html").write_text("<html><body><h1>Fixture</h1></body></html>")
    store.register_version(SiteVersion(site_id="demo", version="v0"))
    return tmp_path


def test_site_identifiers_cannot_expose_data_root(data):
    (data / "private.txt").write_text("PRIVATE REVIEW MARKER")
    for app, url in [
        (site_app(), "/s/%2e%2e/%2e/private.txt"),
        (create_app(), "/api/sites/%2e%2e/versions/%2e/file?path=private.txt"),
    ]:
        response = TestClient(app).get(url)
        assert response.status_code == 404
        assert "PRIVATE REVIEW MARKER" not in response.text


def test_product_password_protects_job_api_and_pages(data, monkeypatch):
    monkeypatch.setattr(settings, "dashboard_password", "test-password")
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 401
        assert client.post("/api/jobs", json={"url": "https://example.com"}).status_code == 401
        assert client.get("/", auth=("abtract", "wrong")).status_code == 401
        assert client.get("/", auth=("abtract", "test-password")).status_code == 200
        assert client.get("/healthz").status_code == 200


def test_modal_product_requires_password(data, monkeypatch):
    import modal

    monkeypatch.setattr(modal, "is_local", lambda: False)
    with pytest.raises(RuntimeError, match="ABTRACT_DASHBOARD_PASSWORD"):
        create_app()


def test_loop_persists_exact_baseline(data):
    run = RunSummary(site_id="demo", site_version="v0", site_url="http://example/s/demo/v0/",
                     model_ids=["mock"], agent_kinds=["text"])
    store.save_run(run)
    job = _build_job(JobRequest(type="loop", site_id="demo", site_version="v0", run_id=run.run_id,
                               url="https://original.example/"))
    store.save_job(job)
    assert TestClient(create_app()).get(f"/api/jobs/{job.id}").json()["baseline_run_id"] == run.run_id
    assert job.url == "https://original.example/"


def test_cloud_budget_stops_new_batches(data, monkeypatch):
    tasks = [Task(id=f"t{i}", kind="answer", prompt="heading?", expected_answer="Fixture") for i in range(5)]
    run = RunSummary(site_id="demo", site_version="v0", site_url="http://example/")
    calls = []

    def fake_map(payloads, **kwargs):
        calls.extend(payloads)
        for p in payloads:
            ep = runner.error_episode(p, "test model result")
            ep.cost_usd = 0.6
            yield ep.model_dump(mode="json")

    monkeypatch.setattr(runner, "run_episode", SimpleNamespace(map=fake_map))
    eps = runner._fan_out_modal(runner.build_payloads(run, tasks, ["mock"], ["text"]), None,
                                 budget_usd=1, concurrency=2)
    assert len(calls) == 2  # in-flight calls finish; the other three never start
    assert len(eps) == 5
    assert all("budget exhausted" in ep.error for ep in eps[2:])


def test_job_allowance_is_shared_between_swarm_phases(data, monkeypatch):
    allowances = []

    def fake_swarm(site, version, tasks, models, agents, *, on_episode, budget_usd, **kwargs):
        allowances.append(budget_usd)
        run = RunSummary(site_id=site, site_version=version, site_url="http://example/")
        on_episode(Episode(run_id=run.run_id, site_id=site, site_version=version, task_id=tasks[0].id,
                           agent_kind="text", model_id="mock", cost_usd=0.4, success=True))
        return run

    monkeypatch.setattr(jobs, "run_swarm", fake_swarm)
    monkeypatch.setattr(jobs, "serve_site_locally", lambda: ("http://example", lambda: None))
    job = Job(type="loop", model_ids=["mock"], agent_kinds=["text"], budget_usd=1)
    task = Task(kind="answer", prompt="heading?", expected_answer="Fixture")
    for version in ("v0", "v1"):
        jobs._run_swarm_phase(job, "demo", version, [task], phase="Testing", local=True)
    assert allowances == pytest.approx([1, 0.6])
    assert store.load_job(job.id).swarm_spent_usd == pytest.approx(0.8)


def test_vision_swarm_screenshots_reach_dashboard(data, monkeypatch):
    from tests.test_agents_mock import chromium_available

    if not chromium_available():
        pytest.skip("Playwright Chromium is not installed")
    monkeypatch.setenv("ABTRACT_MOCK_REPLY", '{"action":{"type":"answer","text":"Fixture"}}')
    base, stop = runner.serve_site_locally()
    try:
        run = RunSummary(site_id="demo", site_version="v0", site_url=f"{base}/s/demo/v0/")
        task = Task(kind="answer", prompt="heading?", expected_answer="Fixture", max_steps=1)
        ep = Episode(**runner.run_episode_sync(runner.build_payloads(run, [task], ["mock"], ["vision"], use_llm_judge=False)[0]))
        assert ep.success
        with TestClient(create_app()) as client:
            detail = client.get(f"/api/runs/{ep.run_id}/episodes/{ep.id}").json()
            url = detail["steps"][0]["screenshot_url"]
            assert url
            response = client.get(url)
            assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
    finally:
        stop()
