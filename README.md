# abtract — A/B Testing & Optimization Platform for AI Agents

> **Public Source Code Repository:** [https://github.com/DinIskakov/abtract](https://github.com/DinIskakov/abtract)  
> *Agent-to-App (A2A) UX Evaluation, Benchmarking Swarms, and Autonomous Regeneration Loop.*

---

## 1. Executive Summary & Jury Evaluation Guide

Just as WCAG standards and Google Lighthouse evaluate human accessibility, **abtract evaluates and optimizes Agent Accessibility & Usability (A2A UX)**.

Modern web applications are built for human eyes and manual clicks. When autonomous AI agents attempt to navigate them, they encounter massive token bloat, ambiguous selectors, hidden interactive states, unlabeled icon buttons, and non-deterministic UI updates. This wastes billions of LLM tokens, causes cascading hallucinated actions, and tanks autonomous task completion rates.

**abtract solves this through a closed-loop evolutionary system:**
1. **Intake & Mirroring:** Ingests any target web application URL, creates a hermetic snapshot, and discovers or synthesizes benchmark tasks.
2. **Multi-Model Agent Swarms:** Deploys parallel swarms across multiple agent modalities (DOM, Vision, Text) and LLM providers (Gemini, Claude, GPT, DeepSeek, GLM) to run benchmark tasks in disposable sandboxes.
3. **Telemetry & ARS Scoring:** Evaluates step-by-step trajectories and calculates a composite **Agent Readiness Score (ARS: 0–100)**, measuring affordance clarity, token efficiency, latency, and cost.
4. **Autonomous Design Regeneration:** Uses Gemini to synthesize optimized DOM markup (injecting `data-agent-*` identifiers, pruning noisy nodes, surfacing deterministic `aria-live` state transitions).
5. **A/B Benchmark Validation:** Runs an identical swarm against the regenerated candidate in an isolated sandbox, proving statistical deltas ($\Delta\text{Success}$, $\Delta\text{Cost}$, $\Delta\text{Tokens}$, $\Delta\text{Latency}$).

```text
Target URL ──► Mirror (v0) ──► Swarm Evaluation ──► ARS Score & Friction Map 
                                                            │
    ┌───────────────────────────────────────────────────────┘
    ▼
Gemini Rewrite ──► Candidate (v1) ──► Swarm Evaluation ──► A/B Comparison Report
```

---

## 2. Architecture & Monorepo Design

The repository is organized as a clean, unified monorepo with two decoupled application stacks:

```text
.
├── apps/
│   ├── web/                     # Next.js 16 (App Router) product interface (Port 3000)
│   │   ├── src/app/             # Pages: / (Landing), /jobs/[jobId] (Live Runner), /dashboard (A/B Metrics)
│   │   ├── src/components/      # UI components & layouts
│   │   ├── public/scripts/      # Client-side agent event hooks and charts
│   │   └── next.config.ts       # Reverse proxy: /api/*, /docs, /screenshots/*, /s/* -> Port 8000
│   │
│   └── api/                     # FastAPI backend, agent swarm runtime, and Modal SDK (Port 8000)
│       ├── app/
│       │   ├── main.py          # Unified FastAPI server (combines product API + site host router)
│       │   ├── schemas.py       # Pydantic v2 contracts (Task, Action, Step, Episode, RunSummary)
│       │   ├── store.py         # Local filesystem / Modal Volume persistence
│       │   ├── modal_app.py     # Modal serverless app, images, sandboxes, and volumes
│       │   ├── agents/          # Agent perception loops (DOM, Vision, Text agents)
│       │   ├── swarm/           # Parallel worker runner and live progress streaming
│       │   ├── intake/          # Crawler, site mirror, and task generator
│       │   ├── optimizer/       # Gemini AST/DOM rewriter, validator, and findings generator
│       │   ├── hosting/         # Versioned site server (/s/{site}/{version}/) & telemetry beacons
│       │   └── routers/         # Modular REST routers (/api/jobs, /api/runs, /api/compare)
│       ├── tests/               # Pytest suite (208+ unit, integration, and regression tests)
│       ├── scripts/             # CLI runners: import_demo_site.py, run_swarm.py, run_loop.py
│       └── demo_site/           # Reference benchmark website ("Zephyr Compute") with 10 agent traps
│
├── packages/
│   └── typescript-config/       # Centralized TypeScript configuration (@abtract/typescript-config)
├── mise.toml                    # Toolchain pinning (Node 24, Bun 1.3, Python 3.12, uv) & tasks
├── turbo.json                   # Turborepo task pipeline and caching rules
└── pyproject.toml / uv.lock     # Single Python lockfile located in apps/api/
```

---

## 3. Technology Stack, Frameworks & APIs

### Frontend (`apps/web`)
* **Next.js 16 (App Router):** Server-rendered layouts, dynamic routing, and reverse-proxy rewrite rules.
* **React 19:** Modern functional components and state hooks.
* **Tailwind CSS v4:** Modern utility-first styling system.
* **Bun:** High-performance JavaScript package manager and unit test runner (`bun test`).
* **Turborepo v2:** Monorepo orchestration, task pipelining, and output caching.

### Backend (`apps/api`)
* **Python 3.12:** Clean modern Python runtime.
* **FastAPI:** High-performance async ASGI web framework for REST endpoints and live telemetry streaming.
* **uv:** Ultra-fast, deterministic Python package resolver, virtual environment manager, and lockfile generator.
* **Pydantic v2 & Pydantic Settings:** Strict schema contracts for all episode telemetry, actions, observations, and environment variables.
* **Playwright (Chromium):** Headless browser automation driving the DOM and Vision agent loops.
* **Uvicorn:** Production ASGI server hosting both the product APIs and static site clones on port 8000.
* **BeautifulSoup4 & lxml:** HTML parsing, semantic cleaning, link rewriting, and DOM validation.
* **Rich:** Formatted CLI reports, terminal tables, and live audit progress bars.

### Cloud Infrastructure & Sandboxing
* **Modal:** Serverless microVM execution layer used for:
  * Distributed swarm workers (`run_episode`, `run_swarm`).
  * Cloud file persistence via Modal Volumes (`abtract-data`).
  * Untrusted site code validation inside isolated sandboxes (`modal.Sandbox`).
  * Persistent API & dashboard cloud deployments.

### Multi-Model Inference Matrix
* **Google Gemini (`google-genai`):** Primary optimizer and multimodal agent model (`gemini-3.8-flash` / `gemini-2.5-flash`).
* **OpenAI API (`openai`):** Integration for GPT-4o and reasoning models.
* **Modal Shared Endpoints:** High-throughput, token-metered models including DeepSeek V4.1 Flash and GLM 5.3 Flash.
* **Mock Provider:** Deterministic, offline testing model enabling full \$0 pipeline validation without external API keys.

### Quality & Verification
* **Ruff:** Lightning-fast Python linting and code formatting.
* **Mypy:** Strict static type analysis across all 43 backend modules.
* **Pytest & pytest-asyncio:** Extensive test suite covering agents, scoring, site intake, optimizer, and live preview.
* **ESLint:** Frontend code quality rules for React and Next.js.

---

## 4. REST API Specification

FastAPI serves the product API on port `8000` (proxied to `http://localhost:3000/api/*` by Next.js). Interactive Swagger documentation is available at **[http://localhost:3000/docs](http://localhost:3000/docs)** (or `http://localhost:8000/api/docs`).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/overview` | Lists all mirrored sites, available versions, and summarized benchmark runs. |
| `GET` | `/api/models` | Returns available swarm models, supported modalities (text/vision), and token pricing. |
| `GET` | `/api/demo-url` | Resolves the hosted URL for the reference demo benchmark site. |
| `POST` | `/api/jobs` | Dispatches an `intake` job (crawl + swarm) or a `loop` job (optimize + retest). |
| `GET` | `/api/jobs/{job_id}` | Polls live job status, step progress, streaming agent logs, and plain-language findings. |
| `GET` | `/api/runs` | Returns all completed benchmark runs. |
| `GET` | `/api/runs/{run_id}` | Full run summary including task completion scores, cost, step counts, and duration. |
| `GET` | `/api/runs/{run_id}/episodes` | List of individual agent episodes for a run. |
| `GET` | `/api/runs/{run_id}/episodes/{ep_id}` | Full step-by-step agent trajectory (observation, thought, action, target coordinates, screenshot). |
| `GET` | `/api/compare?a={runA}&b={runB}` | Computes A/B statistical deltas: win-rates, $\Delta\text{Cost}$, $\Delta\text{Tokens}$, and per-task breakdowns. |
| `GET` | `/api/sites/{site_id}/versions/{v}/files` | Returns the file tree of an ingested site snapshot. |
| `GET` | `/api/sites/{site_id}/versions/{v}/file?path=` | Returns raw text content of a specific snapshot file for diffing. |
| `GET` | `/screenshots/{run_id}/{ep_id}/{name}` | Serves visual agent screenshot artifacts captured during execution. |
| `GET` | `/s/{site_id}/{version}/*` | Serves the mirrored or regenerated static website under test. |
| `POST` | `/s/{site_id}/{version}/api/event` | Telemetry beacon receiver recording agent interactions on the test site. |

---

## 5. Comprehensive Setup & Installation

### Step 1: Prerequisites
Ensure [mise](https://mise.jdx.dev/) is installed to manage toolchains deterministically:

```bash
# macOS / Linux
curl https://mise.run | sh
```

### Step 2: One-Command Workspace Setup
Run the unified setup task from the repository root. This installs Bun packages, creates the Python virtual environment with `uv`, downloads Playwright Chromium binaries, and imports the reference demo site:

```bash
mise run setup
```

### Step 3: Configure Environment
Copy the example environment configuration:

```bash
cp .env.example .env
```

* **Offline / Free Testing Mode:** Leave API keys blank in `.env` and set `ABTRACT_OPTIMIZER_MODEL=mock`. This allows testing the full swarm and optimization workflow locally with mock agents at **\$0 cost**.
* **Live Inference Mode:** Fill in `GEMINI_API_KEY` for real agent perception and code generation. Optionally add OpenAI or Modal proxy credentials.

### Step 4: Start Local Development Servers
Start both the Next.js frontend and FastAPI backend concurrently with hot reloading:

```bash
mise run dev
```

* **Web Application UI:** [http://localhost:3000](http://localhost:3000)
* **FastAPI Direct & API Docs:** [http://localhost:8000](http://localhost:8000) | [http://localhost:3000/docs](http://localhost:3000/docs)
* **Hosted Demo Site:** [http://localhost:8000/s/demo/v0/](http://localhost:8000/s/demo/v0/)

---

## 6. Technical Evaluation Details for Jury Review

### A. Three Distinct Agent Modalities
Abtract benchmarks sites using three distinct agent paradigms to uncover different classes of friction:
1. **DOM Agent (`app/agents/dom_agent.py`):** Uses headless Chromium to extract the browser's accessibility tree and interactive DOM nodes. Injects numbered visual markers into actionable elements (`[1] Submit`, `[2] Pricing`) so the LLM outputs deterministic element IDs rather than brittle CSS selectors.
2. **Vision Agent (`app/agents/vision_agent.py`):** Captures full-page screenshots with Set-of-Marks visual bounding boxes. Relies on Multimodal Vision Models (VLM) to verify visual discoverability, spatial hierarchy, and layout clarity.
3. **Text Agent (`app/agents/text_agent.py`):** A lightweight agent operating over pure HTML responses without JavaScript execution. Tests if the site remains accessible to fast, low-cost text-only scrapers and search indexing agents.

### B. Core Evaluation Metrics & Formulas

| Metric | Measurement / Formula | Target Goal |
|---|---|---|
| **Task Completion Rate ($\text{TCR}$)** | $\frac{\text{Successful Benchmark Episodes}}{\text{Total Episodes Tested}}$ | $\ge 90\%$ |
| **Cost per Successful Task ($\text{CPT}$)** | $\frac{\sum \text{Model Inference Cost (USD)}}{\text{Number of Successful Episodes}}$ | Minimization |
| **Step Efficiency Ratio ($\text{SER}$)** | $\frac{\text{Mean Steps}_{\text{Variant B}}}{\text{Mean Steps}_{\text{Variant A}}}$ | $< 1.0$ (Fewer steps) |
| **Semantic Affordance Index ($\text{SAI}$)** | $\frac{\text{Interactive Elements with Accessible Name \& Role}}{\text{Total Interactive Elements}}$ | $\ge 95\%$ |
| **DOM Token Efficiency ($\text{DTE}$)** | $\frac{\text{Tokens in Accessibility Tree / Action Graph}}{\text{Total Raw HTML Tokens}}$ | High signal-to-noise ratio |
| **Agent Readiness Score ($\text{ARS}$)** | $0.35 \cdot \text{TCR} + 0.20 \cdot \text{SAI} + 0.15 \cdot \text{DTE} + 0.15 \cdot (1 - \text{Friction}) + 0.15 \cdot \text{Robustness}$ | $0 - 100$ Index |

### C. Reference Evaluation Benchmark: The 10 Agent Traps
The bundled demo site (`apps/api/demo_site/v0/`) models a cloud infrastructure provider ("Zephyr Compute") with **10 deliberate agent traps** documented in `apps/api/demo_site/TRAPS.md`:
1. **Dynamic Tab Switching:** Pricing data concealed behind unannounced tabs with identical class names.
2. **Icon-Only Buttons:** Action buttons lacking `aria-label` or accessible names.
3. **Hover-Activated Menus:** Critical documentation links rendered only on CSS `:hover`.
4. **Nested Iframe Obstructions:** Embedded widgets that trap mouse gaze coordinates.
5. **DOM Token Flooding:** Excessive decorative SVGs and inline data blobs inflating prompt tokens.
6. **Non-Standard Form Controls:** Clickable `<div>` wrappers mimicking checkboxes without ARIA roles.
7. **Delayed Asynchronous Updates:** Forms submitting without `aria-busy` or visual progress indicators.
8. **Ambiguous Duplicate Selectors:** Multiple identical "Sign Up" links pointing to different target URLs.
9. **Invisible Validation Alerts:** Form error messages styled offscreen or not linked via `aria-describedby`.
10. **Dead-End Pagination:** Pagination controls lacking canonical URL state links.

### D. Sandboxed Validation Safety
Untrusted code generated by LLM optimizers is never executed directly on the host machine. Candidate website revisions are verified inside an isolated `modal.Sandbox` or disposable process container (`apps/api/app/optimizer/check_site.py`) to validate HTML structure, assert link integrity, and prevent script injection before registering the candidate as a testable variant.

---

## 7. Cloud Deployment with Modal

The backend and distributed swarm can be deployed to Modal with persistent cloud storage:

```bash
# 1. Create your cloud secrets file
cp .env.modal.example .env.modal
# Fill in GEMINI_API_KEY and ABTRACT_DASHBOARD_PASSWORD

# 2. Upload cloud secrets to Modal
cd apps/api
uv run modal secret create abtract-secrets --from-dotenv ../../.env.modal
cd ../..

# 3. Deploy the application to Modal
mise run modal:deploy

# 4. Import the reference demo site to the cloud volume
cd apps/api
uv run python scripts/import_demo_site.py --modal
```

To run with live hot reloading in the cloud:
```bash
mise run modal:serve
```

---

## 8. CLI & Developer Command Reference

All tasks are defined in `mise.toml` and orchestrated via Turborepo:

| Command | Action |
|---|---|
| `mise run setup` | Complete workspace bootstrap (Bun install, uv sync, Playwright Chromium, demo import). |
| `mise run dev` | Runs both Next.js (port 3000) and FastAPI (port 8000) concurrently with hot reload. |
| `mise run dev:web` | Runs the Next.js frontend only. |
| `mise run dev:api` | Runs the FastAPI backend only. |
| `mise run demo:import` | Imports the demo benchmark site into the local store. |
| `mise run test` | Runs all unit and integration tests (`bun test` + `pytest`). |
| `mise run lint` | Runs code linters across the repository (`eslint` + `ruff check`). |
| `mise run lint:fix` | Automatically formats and fixes lint issues (`eslint --fix` + `ruff check --fix`). |
| `mise run typecheck` | Validates static types across the monorepo (`tsc --noEmit` + `mypy`). |
| `mise run build` | Produces production builds for all applications (`next build` + `uv sync --locked`). |
| `mise run modal:deploy` | Deploys the backend API, swarm runners, and site host to Modal. |
| `mise run modal:serve` | Starts a hot-reloading development server on Modal. |

---

## 9. Running Autonomous Swarms via CLI

In addition to the Web UI, you can run headless evaluations and optimization loops directly from the terminal:

```bash
# Run a single 1-iteration optimization loop (Benchmark v0 -> Rewrite -> Benchmark v1 -> Compare)
cd apps/api
uv run python scripts/run_loop.py \
  --local \
  --site demo \
  --version v0 \
  --iterations 1 \
  --models mock \
  --agents dom,vision \
  --tasks demo_site/tasks.json
```
