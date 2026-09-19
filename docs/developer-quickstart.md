# abtract: developer quickstart

abtract tests how well AI agents can use a website. You enter a URL, it mirrors the site, runs agents against tasks in parallel, and shows live findings. Gemini can then revise the snapshot and rerun the same tasks to measure the change.

The working product is the Python app in `abtract/`, with plain HTML/CSS/JavaScript in `abtract/dashboard/static/`. Start from the **`product-flow`** branch. The older scaffold in `apps/` and `packages/` is separate; you don't need to start it.

## Try the hosted product

1. Open [the product](https://harris-labs--dashboard.modal.run).
2. Sign in as **`abtract`**. Get the dashboard password from Harris privately.
3. Click **Try with the demo site**, then **Run full audit**. The [demo website](https://harris-labs--site.modal.run/s/demo/v0/) is already hosted.
4. Watch the homepage preview, tasks in progress, and completed results. Full audits can take several minutes; **Quick scan** is an optional smaller sample.
5. Open the report and inspect failed tasks, traces, and screenshots. **Optimize in a loop** tests a revised snapshot against the baseline when Gemini authentication is working.

This is a shared team environment: jobs and results are shared, and real runs use the team's paid model endpoints. Test with public content and coordinate optimization runs on the same site.

## Do I need keys?

| What you want to do | What you need |
| --- | --- |
| Use the hosted product | Dashboard login only. API keys are already stored on Modal. |
| Develop locally with mock agents | No API keys or Modal account. Follow the setup below. |
| Run real models locally | Approved credentials in your private `.env`; see [endpoint setup](endpoint-setup.md). Cloud secrets are not automatically available on your laptop. |
| Redeploy to the existing team workspace | Modal access to `harris-labs`. The deployment reuses its existing `abtract-secrets` secret. |

**You do not need to create or replace keys to try the hosted demo or develop with mocks.** Do not recreate the team's endpoints or overwrite its cloud secret as part of onboarding. Keep `.env` and `.env.modal` out of Git.

Known issue from testing on September 19, 2026: Google rejected the configured Gemini credential with `401 UNAUTHENTICATED` / `ACCESS_TOKEN_TYPE_UNSUPPORTED` when clicking Optimize. The deployment owner needs to fix that shared credential/project configuration once; each developer does not need a separate replacement key. See [Gemini troubleshooting](endpoint-setup.md).

## Run locally without API spending

Prerequisites: Git, Python 3.12+, and `uv`. From a fresh clone:

```bash
git clone --branch product-flow https://github.com/DinIskakov/abtract.git
cd abtract
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env
```

On Linux, use `uv run playwright install --with-deps chromium` if browser system libraries are missing.

Leave `GEMINI_API_KEY` and `MODAL_PROXY_TOKEN` empty in `.env`. Set these two entries:

```dotenv
ABTRACT_OPTIMIZER_MODEL=mock
ABTRACT_SITE_BASE_URL=http://localhost:8000
```

Import the demo, then start its server:

```bash
uv run python scripts/import_demo_site.py
uv run python -m abtract.hosting.serve --port 8000
```

In a second terminal, from the repository root:

```bash
uv run python -m abtract.dashboard.app --port 8001
```

Open [the local product](http://localhost:8001). Click **Try with the demo site**, expand the model options, deselect the default models, and select **Mock** only. Then click **Run full audit**. If you change the scan mode, select Mock again because changing modes resets the model selection.

The local demo is [localhost:8000/s/demo/v0/](http://localhost:8000/s/demo/v0/). Local results go into `data/`. Mock agents deliberately give up, and the mock optimizer makes no changes: this checks the workflow, not actual site quality.

## Make a change

Create a feature branch from `product-flow`, for example `git switch -c codex/my-change`. Open pull requests against **`product-flow`**; keep `main` unchanged for now.

| Area | Where to look |
| --- | --- |
| Landing page, progress page, dashboard UI | `abtract/dashboard/static/` |
| Product API and job orchestration | `abtract/dashboard/app.py`, `abtract/jobs.py` |
| Agent execution and parallel scheduling | `abtract/agents/`, `abtract/swarm/` |
| Findings and website rewrites | `abtract/optimizer/` |
| Demo pages and deliberate traps | `demo_site/` |
| Tests | `tests/` |

Run the tests with your local mock configuration:

```bash
uv run pytest -q
```

After changing dashboard assets, regenerate the checked-in bundle with `uv run python scripts/bundle_dashboard.py` and include it in your commit.

**A Git push does not update the hosted product.** Once a change is ready to deploy, an authorized team member can run `uv run modal setup` to authenticate to `harris-labs`, then `uv run modal deploy deploy.py`. This updates the shared app using the existing cloud secret; no key edits are needed for an ordinary code deployment.

When reporting a problem, include the job URL, expected behavior, actual behavior, and a screenshot or error message without credentials. See the [main README](../README.md) for architecture, hosting details, and current limitations.
