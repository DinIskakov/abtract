# abtract — A/B testing for AI agents

abtract measures how well AI agents can use a website, uses Gemini to propose a revised snapshot, and tests it again.

The repository has two application stacks:

- `apps/web`: Next.js product UI on port 3000.
- `apps/api`: FastAPI product API, hosted-site routes, agent runtime, and Modal definitions on port 8000.

Shared TypeScript configuration remains in `packages/`. Python code, tests, scripts, fixtures, dependency metadata, and the Modal entrypoint all belong to `apps/api`.

## Local development

Install mise, then prepare the full workspace once:

```bash
mise run setup
```

Start both applications with hot reload:

```bash
mise run dev
```

Open [http://localhost:3000](http://localhost:3000). Next.js proxies `/api/*` and `/screenshots/*` to FastAPI. FastAPI also serves imported test sites at `/s/{site}/{version}/`, so no second Python server is required. The demo is available at [http://localhost:8000/s/demo/v0/](http://localhost:8000/s/demo/v0/).

Useful focused commands:

```bash
mise run dev:web
mise run dev:api
mise run demo:import
mise run lint
mise run typecheck
mise run test
mise run build
```

Copy `.env.example` to `.env` or `apps/api/.env` when local credentials are needed. Keep `ABTRACT_OPTIMIZER_MODEL=mock` and select the mock model for an offline workflow check.

## Repository map

| Responsibility | Location |
| --- | --- |
| Landing, job progress, and dashboard UI | `apps/web/src/app`, `apps/web/src/components` |
| Browser behavior and product styles | `apps/web/public/scripts`, `apps/web/src/styles` |
| FastAPI entrypoint and product routes | `apps/api/app/main.py`, `apps/api/app/routers/product.py` |
| Agent execution and scheduling | `apps/api/app/agents`, `apps/api/app/swarm` |
| Intake, findings, and rewrites | `apps/api/app/intake`, `apps/api/app/optimizer` |
| Storage contracts and job orchestration | `apps/api/app/schemas.py`, `apps/api/app/store.py`, `apps/api/app/jobs.py` |
| Hosted test sites | `apps/api/app/hosting` |
| Modal app and deployment entrypoint | `apps/api/app/modal_app.py`, `apps/api/deploy.py` |
| Demo fixture and Python utilities | `apps/api/demo_site`, `apps/api/scripts` |
| Backend tests | `apps/api/tests` |

## Modal

Create or update the `abtract-secrets` secret from `.env.modal`, then use the workspace tasks:

```bash
cd apps/api
uv run modal secret create abtract-secrets --from-dotenv ../../.env.modal
cd ../..
mise run modal:deploy
```

`mise run modal:serve` provides hot reload. `mise run modal:deploy` deploys the API, site host, swarm workers, and optimizer from the single app-owned entrypoint.

See [endpoint setup](docs/endpoint-setup.md) for inference endpoint details.
