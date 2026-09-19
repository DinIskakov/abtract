# abtract — A/B testing for AI agents

abtract measures how well AI agents can use a website, then uses Gemini to propose a revised snapshot and tests it again. The working product is the Python app in `abtract/`. The original Next.js/FastAPI scaffold remains in `apps/` and `packages/`; its setup is preserved in [docs/monorepo.md](docs/monorepo.md).

## Product flow

1. Enter a URL on the landing page, or choose **Try with the demo site**.
2. abtract mirrors the site, chooses tasks, and runs a swarm while the job page shows progress.
3. The report shows task results, agent/model breakdowns, costs, and findings. The dashboard provides traces, screenshots, and version diffs.
4. Choose **Optimize in a loop** for one to three iterations. Gemini proposes changes, the validator checks the candidate, and another swarm measures the new version against the original baseline. Failed validation rejects the candidate.

The demo is a fake GPU-cloud website with 10 deliberate agent traps and 14 tasks. See [demo_site/TRAPS.md](demo_site/TRAPS.md). A site can supply an `abtract-tasks.json` manifest; otherwise Gemini generates tasks, with a generic navigation fallback when no key is configured.

| Agent | What it sees |
| --- | --- |
| Text | HTTP responses converted to text, without JavaScript |
| DOM | Chromium, visible text, and numbered interactive elements |
| Vision | Chromium screenshots with numbered interactive elements |

## Local hosting and offline testing

Run these setup commands from the repository root:

```bash
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env
uv run python scripts/import_demo_site.py
```

On Linux, `uv run playwright install --with-deps chromium` also installs missing browser system libraries. Keep API keys empty and set `ABTRACT_OPTIMIZER_MODEL=mock` in `.env` for an offline test.

Start the demo host in one terminal:

```bash
uv run python -m abtract.hosting.serve --port 8000
```

Start the product in a second terminal:

```bash
uv run python -m abtract.dashboard.app --port 8001
```

Open the product at **http://localhost:8001**. The demo is **http://localhost:8000/s/demo/v0/**. Click **Try with the demo site**, deselect the two default models, select **Mock**, then **Run the swarm**. When the report appears, choose **Optimize in a loop**.

Mock validates the workflow without API spending: its agents give up by default and its optimizer proposes no changes. Those results are not evidence of actual site quality or improvement. To test real behavior, configure the provider keys below and remove `ABTRACT_OPTIMIZER_MODEL=mock`.

## Host the product and demo on Modal

The product and demo use the same Modal deployment, with two separate HTTPS endpoints and a shared `abtract-data` Volume.

1. Authenticate with Modal. Create an inference proxy token only if you will use Modal for model inference:

   ```bash
   uv run modal setup
   uv run modal workspace proxy-tokens create
   ```

2. For Modal inference, open the [Endpoints page](https://modal.com/endpoints) while signed in. Modal's [Shared Endpoints documentation](https://modal.com/docs/guide/shared-endpoints) describes creating them from that page; this has not been verified in every workspace's dashboard. If a Shared option is available, start with DeepSeek V4.1 Flash and GLM 5.3 Flash, the two default models. Copy the supplied API base URL/model name if it differs from our defaults. Shared Endpoints are billed per token; `modal endpoint create` examples on library pages create dedicated endpoints with a different cost model.

   **If Shared Endpoints are absent:** continue hosting the app on Modal and use Gemini for inference. No Shared Endpoint or Modal inference proxy token is needed for this path. Fill in `GEMINI_API_KEY`, keep `ABTRACT_OPTIMIZER_MODEL` unset, and after deployment deselect DeepSeek and GLM on the landing page and select only **Gemini**. Text, DOM, and vision agents can all use it, as can the optimizer. CLI runs use `--models gemini-flash`. This tests multiple agent kinds with one model; it does not provide the planned comparison across model providers. The real Gemini integration still needs a live API test.

3. Prepare a cloud-only secret file:

   ```bash
   cp .env.modal.example .env.modal
   ```

   Fill in `GEMINI_API_KEY` and a strong `ABTRACT_DASHBOARD_PASSWORD`; also fill in `MODAL_PROXY_TOKEN` if using Modal inference. The product requires that password when running on Modal. Sign in with username **abtract**. Keep `.env.modal` private; Git ignores it. Do not upload your local `.env`, whose local storage path would override the cloud Volume path.

4. Create the secret, deploy the app, and upload the demo:

   ```bash
   uv run modal secret create abtract-secrets --from-dotenv .env.modal
   uv run modal deploy deploy.py
   uv run python scripts/import_demo_site.py --modal
   ```

   To replace an existing `abtract-secrets` secret, add `--force` to the secret command and redeploy. Modal's [secret CLI reference](https://modal.com/docs/cli/latest/secret) describes this behavior.

5. Open the **dashboard** URL printed by deployment. The demo lives at **<site URL>/s/demo/v0/**. The **Try with the demo site** button discovers this URL automatically. `ABTRACT_SITE_BASE_URL` is an optional override if discovery is unavailable.

The product is protected for a shared team trial; the demo and mirrored snapshots are publicly accessible on the separate site endpoint. This is not a multi-tenant customer service yet. Use public test content, and run one optimization loop per site at a time: version metadata uses a filesystem store without distributed locking.

### Execution and cost controls

Snapshots are static folders on the Volume, served by one small container that can scale to zero. Each agent episode runs in a Modal function container. Gemini output is checked in a sandbox before its version is registered. A separate always-running sandbox per clone is unnecessary for this static-site prototype. Authenticated apps and sites that need a live backend require a different deployment strategy; mirrored form submissions record simulated events rather than running the original backend.

The landing page has no budget field. `ABTRACT_JOB_SWARM_BUDGET_USD` is an internal allowance, defaulting to **$5 per product job**, shared across that job's swarm iterations. This can later sit behind package pricing. CLI `--budget-usd` is per swarm run, including each run in a CLI loop. Estimates can reject a run before it starts, and local/cloud workers stop scheduling more episodes when recorded spend reaches the allowance. Calls already running can overshoot it. These controls cover agent model tokens; Gemini task generation, judging, findings, rewrites, Modal compute, and storage are additional charges. They are not a provider billing cap.

Start with two models and a small task set, then expand after observing actual usage. Configure provider-side spend controls as well. Modal says Shared Endpoint usage cannot be paid with included compute credits; see the [Shared Endpoint billing notes](https://modal.com/docs/guide/shared-endpoints). Hosting can incur cold starts and is not a fixed-price package.

## Models and CLI

The configured Modal Shared Endpoint catalog contains **six models**, verified against the [Modal library](https://modal.com/library) on 2026-09-19. `cheapest:10` currently selects those six; it does not invent four more or launch dedicated GPU endpoints. `default` selects the two cheapest. Rankings use `0.8 × input price + 0.2 × output price` for input-heavy agent traffic. Per-model prices and source URLs live in `abtract/models/pricing.py`.

Other selectors are `vision`, `all`, individual model IDs, `gemini-flash`, and `mock`. Vision combinations are skipped for models without vision support. To inspect endpoint availability, put the token in your local `.env` and run:

```bash
uv run python scripts/list_models.py
```

Use `ABTRACT_MODEL_<ID>` overrides if the model names returned by your gateway do not match the registry. Gemini defaults to `gemini-3.8-flash`; `GEMINI_MODEL` can select another available model.

Local command-line smoke test:

```bash
ABTRACT_OPTIMIZER_MODEL=mock uv run python scripts/run_loop.py \
  --local --site demo --version v0 --iterations 1 \
  --models mock --agents text,dom,vision --tasks demo_site/tasks.json
```

For cloud CLI runs, supply the deployed site endpoint explicitly (or set `ABTRACT_SITE_BASE_URL` in your local `.env`). The driver runs on your laptop, and episodes execute on Modal:

```bash
uv run modal run scripts/run_swarm.py \
  --site demo --version v0 --tasks demo_site/tasks.json \
  --site-base-url https://YOUR-SITE-ENDPOINT.modal.run \
  --models default --agents text,dom,vision --budget-usd 5
```

## Validation and next steps

```bash
uv run pytest -q
```

Tests cover intake/mirroring, task selection, scoring, rewrite rejection, job APIs, baseline comparisons, spending controls, and screenshot retrieval. Browser tests need Chromium; mock tests do not need paid API calls. [CLAUDE.md](CLAUDE.md) describes the module layout.

Before opening this to customers, add accounts and per-customer data isolation, durable job scheduling and cancellation, distributed version locking, stricter limits on fetched URLs/content, and package entitlements/billing. Review semantic correctness of rewrites as well as measured agent success: the current validator checks site structure and links, not every factual claim. Run the hosted demo with real models before publishing improvement numbers on the landing page.
