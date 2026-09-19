# Developer quickstart

Run the complete local setup from the repository root:

```bash
mise run setup
mise run dev
```

This starts Next.js at [localhost:3000](http://localhost:3000) and FastAPI at [localhost:8000](http://localhost:8000). The web app proxies its API requests to FastAPI. The API process also hosts the bundled demo at [localhost:8000/s/demo/v0/](http://localhost:8000/s/demo/v0/).

For an offline workflow check, leave provider keys empty, set `ABTRACT_OPTIMIZER_MODEL=mock`, select the mock model in the UI, and use **Try with the demo site**.

| Change | Location |
| --- | --- |
| Product UI | `apps/web/src/app`, `apps/web/src/components` |
| Product API and job orchestration | `apps/api/app/routers/product.py`, `apps/api/app/jobs.py` |
| Agent execution | `apps/api/app/agents`, `apps/api/app/swarm` |
| Findings and website rewrites | `apps/api/app/optimizer` |
| Demo pages | `apps/api/demo_site` |

Run checks from the root with `mise run lint`, `mise run typecheck`, `mise run test`, and `mise run build`.

A Git push does not update Modal. An authorized team member can use `mise run modal:deploy`; the command deploys `apps/api/deploy.py` with the existing `abtract-secrets` secret.
