# abtract — A/B testing platform for AI agents (hackathon)

Loop: host a site version on Modal -> swarm of LLM agents (Modal hosted inference) attempts tasks -> score
success / steps / time / cost -> Gemini rewrites the site to remove what tripped agents -> host new version -> repeat.

## Layout
- `abtract/schemas.py`     shared pydantic contracts (Task, Action, Step, Episode, RunSummary, SiteEvent, SiteVersion). Read first.
- `abtract/config.py`      env settings (`settings`). `settings.site_url(site_id, version)` -> hosted URL.
- `abtract/store.py`       filesystem store under `settings.data_dir` (= Modal Volume `/data` in the cloud). Call `store.commit()` after writes on Modal.
- `abtract/models/`        `registry.py` (ModelSpec list; add a model = add an entry), `llm.py` (`chat()` for every provider + `extract_json`).
- `abtract/modal_app.py`   the one `modal.App`, `base_image`, `browser_image`, `sandbox_image`, `data_volume`, `secrets`.
- `abtract/agents/`        `base.py` loop + `prompts.py`; `text_agent.py` (httpx, no JS), `browser.py` shared Playwright session, `dom_agent.py`, `vision_agent.py` (set-of-marks screenshots). `run_local.py` CLI. All return an `Episode`.
- `abtract/swarm/`         `runner.py` (Modal fn `run_episode`, `run_swarm` fan-out local/cloud), `cli.py` (shared arg parsing for scripts), `report.py` (rich tables).
- `abtract/metrics/`       `score.py`: `judge()` (answer/url/action), `aggregate()`, `compare()`.
- `abtract/optimizer/`     `rewrite.py` (Gemini context -> proposal -> new version, validated by `check_site.py` in a modal.Sandbox or subprocess; Modal fn `optimize_site_remote`), `task_gen.py` (Gemini writes tasks), `findings.py` (plain-language report for the job page). `ABTRACT_OPTIMIZER_MODEL=mock` for offline.
- `abtract/intake/`        `mirror.py` (crawl a URL into the store as `<site_id>/v0`, links rewritten relative), `tasks.py` (`pick_tasks`: validated site-provided `abtract-tasks.json` -> Gemini -> tasks derived from captured content/links).
- `abtract/jobs.py`        `start_job(Job)` / `run_job_sync`: the product flow (intake: mirror -> tasks -> swarm -> findings; loop: optimize -> swarm x N). Modal fn `run_job`.
- `abtract/hosting/`       `urls.py` (`resolve_site_base_url()` via env or the deployed `site_server` web URL), `serve.py`: serves versions at `/s/{site_id}/{version}/`, records SiteEvents from `POST .../api/event` and `.../api/{name}`. Modal fn `site_server` (label `site`).
- `abtract/dashboard/`     `app.py` FastAPI + `static/` (bundled into `static_bundle.py` for Modal, regenerated on import). Modal fn `dashboard` (label `dashboard`).
- `demo_site/v0/`          fake "Zephyr Compute" site with 10 deliberate agent traps; `demo_site/tasks.json` (14 tasks), `demo_site/TRAPS.md`.
- `scripts/`               `import_demo_site.py` (`--modal` uploads to the Volume), `run_swarm.py`, `run_loop.py` (both: `--local` or `modal run`), `seed_fake_data.py` (dashboard dev data), `list_models.py`, `check_site.py`.
- `deploy.py`              Modal entrypoint (imports everything that registers functions). `.claude/launch.json` has `dashboard` (8001) and `site` (8000) dev servers.

## Conventions
- Python 3.12, `uv` for deps (`uv sync`, `uv run ...`). Pydantic v2. No new top-level deps without adding to both `pyproject.toml` and `abtract/modal_app.py::_PY_DEPS`.
- Agents observe -> ask model for `{"thought": ..., "action": {...}}` JSON (see `Action` in schemas) -> act. Terminal actions: `answer`, `give_up`.
- Agents send header `X-Abtract-Episode: <episode_id>` on every request so the site server can attribute SiteEvents.
- Site files use *relative* links only (they are served under a path prefix).
- Everything must run offline with `model_id="mock"` (no API keys) for smoke tests.
