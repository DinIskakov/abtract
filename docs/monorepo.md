# Monorepo structure

The workspace uses Bun and Turborepo to coordinate two applications:

```text
apps/
  web/  Next.js frontend
  api/  FastAPI backend, Modal runtime, scripts, tests, and fixtures
packages/
  typescript-config/
```

`mise run dev` starts both applications. The browser connects to Next.js on port 3000; rewrites send API and screenshot requests to FastAPI on port 8000. FastAPI mounts hosted site versions in the same process at `/s/...`.

Each app owns its dependencies and commands. There is no root Python package or root Python lockfile. Workspace-wide commands delegate through package scripts and Turbo, while mise exposes stable commands for developers and CI.
