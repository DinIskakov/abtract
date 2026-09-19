# UpTrack workbench

A Next.js frontend for URL → Gemini tasks → baseline report → proposed
patches → variant report. Gemini always supervises; Codex and Gemini CLI can be
selected independently as tested harnesses. Choose Easy, Medium, or Hard tasks
and an agent-time target (15 seconds by default). Correct but slow answers can
trigger efficiency patches as well as correctness fixes. Unconfigured harnesses stay visible
and disabled with an explanation.

From the repository root, install with `bun install`. Start FastAPI on port8000
(see `apps/api/README.md`), then run `bun run --cwd apps/web dev`. Open
http://localhost:3000. `BACKEND_URL` changes the Next.js API proxy target.
Provider keys stay in the backend environment, never in browser code.

The interface uses a moving technical grid, phase-based transitions, expanded
per-task correctness and time-target evidence, source patch comparisons,
paired agent-runtime differences, and saved experiment restoration.
Reduced-motion preferences disable animation. The browser polls short endpoints;
closing the tab does not stop the experiment.

Checks from `apps/web`:

```sh
bun run lint
bun run typecheck
bun run test
bun run build
bunx playwright install chromium
bun run test:e2e
```

Playwright tests exercise the full workflow with explicit synthetic API fixtures,
including errors, unverified patch exposure, restored reports, and mobile layouts.
Screenshots and traces are written to ignored `docs/frontend-smoke/`. Real Modal
smoke results are stored there separately and never replaced with fixtures.
