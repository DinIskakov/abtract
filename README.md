# UpTrack / Abtract Monorepo

An agent usability experiment workbench with a **Next.js** frontend and **FastAPI** backend. Paste a public page URL, select native agent harnesses, and Gemini creates simple tasks, evaluates parallel Modal runs, and proposes patches for a second evaluation.

See [workbench setup](apps/web/README.md) and [backend workflow](apps/api/README.md#automatic-workbench-workflow). This is a local, single-worker MVP.

---

## 🏛 Architecture & Stack

- **Tooling & Environment Management:** [mise](https://mise.jdx.dev/) pins tools (`node`, `bun`, `uv`, `python 3.12`) and provides unified CLI tasks.
- **Monorepo Orchestration:** [Turborepo](https://turbo.build/repo) coordinates parallel execution, dependency graph ordering, and caching across JavaScript and Python workspaces.
- **Frontend App (`apps/web`):** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, and Bun Test.
- **Backend App (`apps/api`):** FastAPI, Pydantic v2, Uvicorn, Ruff (linting & formatting), Mypy (type checking), and Pytest, fully managed with [uv](https://docs.astral.sh/uv/).
- **Shared Packages (`packages/*`):** `@abtract/typescript-config` for centralized compiler options across apps.

---

## 📁 Repository Structure

```text
.
├── apps/
│   ├── web/                     # Next.js frontend application
│   │   ├── src/app/             # App Router pages and layouts
│   │   ├── next.config.ts       # Configured with API proxy rewrites to FastAPI
│   │   └── package.json
│   └── api/                     # FastAPI backend application
│       ├── app/
│       │   ├── main.py          # App entrypoint and CORS configuration
│       │   ├── config.py        # Pydantic Settings
│       │   └── routers/         # Modular route definitions
│       ├── tests/               # Pytest suite
│       ├── pyproject.toml       # Python dependencies, Ruff, pytest, and mypy config
│       ├── uv.lock              # Deterministic uv lockfile
│       └── package.json         # Workspace adapter for Turborepo
├── packages/
│   └── typescript-config/       # Shared TypeScript configuration
├── mise.toml                    # Mise tool versions and task definitions
├── turbo.json                   # Turborepo task pipeline configuration
├── package.json                 # Root workspace manifest
└── bun.lock                     # Root Bun lockfile
```

---

## 🚀 Getting Started

### 1. Prerequisites

Ensure [mise](https://mise.jdx.dev/) is installed on your system:

```bash
# macOS / Linux
curl https://mise.run | sh
```

### 2. Install Tools & Dependencies

With mise installed, activate the environment and install all dependencies:

```bash
# Install toolchains (Node, Bun, uv, Python 3.12)
mise install

# Install all workspace dependencies (Bun packages and uv virtualenv)
mise run install
```

---

## 🛠 Everyday Development

### Run Development Servers

To run both Next.js (port `3000`) and FastAPI (port `8000`) concurrently with hot-reloading:

```bash
mise run dev
```

Or run individual apps:

```bash
# Run only Next.js frontend
mise run dev:web

# Run only FastAPI backend
mise run dev:api
```

### Access Endpoints

- **Web App:** [http://localhost:3000](http://localhost:3000)
- **FastAPI Direct:** [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs) (or [http://localhost:3000/docs](http://localhost:3000/docs) via Next.js proxy)
- **API Health Check:** [http://localhost:8000/api/health](http://localhost:8000/api/health)

---

## 🧪 Testing, Linting & Building

Mise tasks delegate directly to Turborepo, running tasks in parallel with smart caching:

| Action | Mise Command | Underlying Command |
|---|---|---|
| **Install Dependencies** | `mise run install` | `bun install && (cd apps/api && uv sync)` |
| **Run All Tests** | `mise run test` | `turbo test` (`bun test` + `pytest`) |
| **Lint Everything** | `mise run lint` | `turbo lint` (`eslint` + `ruff check`) |
| **Fix Lint Issues** | `mise run lint:fix` | `turbo lint:fix` (`eslint --fix` + `ruff check --fix & ruff format`) |
| **Typecheck Everything** | `mise run typecheck` | `turbo typecheck` (`tsc` + `mypy`) |
| **Production Build** | `mise run build` | `turbo build` (`next build` + `uv sync`) |

---

## 📦 Adding Dependencies

### Adding Frontend Packages (Bun)

```bash
# To apps/web
bun add <package-name> --cwd apps/web

# Development dependency
bun add -d <package-name> --cwd apps/web
```

### Adding Backend Packages (uv)

```bash
cd apps/api
uv add <package-name>

# Development dependency
uv add --dev <package-name>
```
