# abtract repository guide

The repository has two application owners. Keep UI code in `apps/web` and all Python, FastAPI, Modal, storage, and agent code in `apps/api`. Do not add another root application package or root dependency manifest.

## Backend

- `apps/api/app/main.py`: local FastAPI entrypoint. It combines the product API and hosted test-site routes.
- `apps/api/app/routers/product.py`: jobs, runs, comparisons, files, events, and screenshots.
- `apps/api/app/schemas.py`, `store.py`, `jobs.py`: contracts, filesystem/Modal Volume persistence, and orchestration.
- `apps/api/app/agents`, `swarm`, `metrics`: agent execution, scheduling, and scoring.
- `apps/api/app/intake`, `optimizer`: mirroring, task selection, first-look evidence, findings, and rewrites.
- `apps/api/app/hosting`: serves site versions under `/s/{site}/{version}/`.
- `apps/api/app/modal_app.py`, `apps/api/deploy.py`: the shared Modal app and deployment registration.
- `apps/api/tests`, `apps/api/scripts`, `apps/api/demo_site`: backend tests, utilities, and fixtures.

Python 3.12 dependencies and tooling belong in `apps/api/pyproject.toml`; update `app/modal_app.py::_PY_DEPS` when a runtime dependency must also exist in Modal images.

## Frontend

- `apps/web/src/app`: Next.js routes for `/`, `/dashboard`, and `/jobs/[jobId]`.
- `apps/web/src/components`: UI integration components.
- `apps/web/src/styles` and `apps/web/public/scripts`: product styles and migrated browser behavior.
- `apps/web/next.config.ts`: local API and screenshot proxying.

New UI work belongs in React components. The migrated browser scripts preserve the current product while components are incrementally converted.

## Commands

Use mise from the repository root: `mise run setup`, `mise run dev`, `mise run lint`, `mise run typecheck`, `mise run test`, and `mise run build`. Use `mise run modal:serve` or `mise run modal:deploy` for Modal.
