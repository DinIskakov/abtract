# UpTrack runner MVP

`POST /api/runs` accepts a URL, questions, harness configurations, and repetitions.
It waits for the batch and returns one result per harness × task × repetition.
Runs execute concurrently using Modal's `.aio` APIs and `asyncio.gather`, each in a
fresh Modal Sandbox. A per-request semaphore defaults to five active runs. There is no
database, background queue, scoring, or custom agent tooling.

## Setup

From `apps/api`:

```sh
uv sync
cp .env.example .env
# Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY in .env.
uv run python -m modal setup
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Modal authentication is separate from model authentication. Only the selected
provider's key is injected into each sandbox. Local CLI account sessions are not
copied. This unauthenticated MVP endpoint is intended for local development.

### Production credentials

FastAPI can run on your chosen host and use the Modal SDK to create remote
sandboxes. Configure these in the hosting platform's secret/environment settings:

- `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`: authenticate the backend to Modal.
- `OPENAI_API_KEY`: authenticate Codex to OpenAI (separate API billing).
- `ANTHROPIC_API_KEY`: needed only when running Claude.

Create Modal credentials in the Modal dashboard's token settings. Team/Enterprise
workspaces can use a dedicated service user with Contributor access to the target
environment. Export Modal tokens as real process environment variables; the Modal
SDK does not receive them through this app's Pydantic `.env` settings.
See [Modal service users](https://modal.com/docs/guide/service-users).

The current endpoint is a development MVP, not a production deployment: it still
needs API authentication, global admission/concurrency limits, and durable result storage
before exposing it publicly. Long batches also need background execution rather
than relying on a single HTTP request staying open.

## Request

```sh
curl --max-time 1200 http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://modal.com/docs/guide/sandboxes",
    "tasks": ["How do I create a sandbox? Include Python code."],
    "harnesses": [{"name": "codex"}, {"name": "claude"}],
    "repetitions": 1,
    "timeout_seconds": 300,
    "max_concurrency": 5
  }'
```

An optional `model` on each harness configuration selects the model; omit it to
use the CLI default. CLI versions are pinned in `app/runs.py`. The first request
may take longer while Modal builds the images. Subsequent runs reuse images but
never reuse a task's sandbox. Native unattended execution permissions are enabled
inside the isolated sandbox, with no MCP servers, plugins, or custom tools added.
`max_concurrency` (1–10, default 5) limits in-flight runs within a batch, including
creation, execution, retrieval, and cleanup. Returned results retain input order;
a failed run does not cancel its siblings. Different requests have separate limits.
The Claude launch uses a PTY as in Modal's official agent example. Codex uses
JSONL over pipes and explicitly closes stdin to avoid waiting for extra input.

## Output contract

The agent must write `/workspace/result.json`:

```json
{
  "answer": "Markdown answer, including fenced code blocks when appropriate",
  "actions": ["What the agent actually did"],
  "sources": ["https://modal.com/docs/guide/sandboxes"],
  "limitations": []
}
```

The API validates this file against `AgentReport` and returns it as `report`,
alongside run identity, sandbox ID, requested model, CLI version, exit code,
total duration (including setup and cleanup), raw native stdout/stderr, and errors.
UTC timestamps record the run and harness execution start/end, making overlaps
inspectable. Execution timestamps are controller observations around the remote
process, not exact CPU scheduling timestamps inside the container.
`completed` means the harness exited successfully and produced a valid file;
it does **not** mean its answer is correct. Actions and sources are agent-reported;
stdout contains native execution events for the external evaluator to inspect.
No scores, token counts, or costs are fabricated. Missing or invalid files are
errors, without automatic retries. Cleanup is attempted even on failures; sandbox
lifetime limits provide a backstop, and cleanup failures are reported separately.

### Native telemetry

Each API run result includes `execution_duration_seconds` and a `telemetry` object
parsed from native CLI events, independently of the agent's answer file:

- `tokens`: total input, cached input, cache-write input, output, and reasoning
  tokens where reported. Input includes cache reads/writes; reasoning is a subset
  of output and is not billed a second time by our estimator.
- `tool_calls`, `tool_calls_by_type`, `failed_tool_calls`: observed native tool
  events, deduplicated by tool-call ID. Different harnesses expose different tool
  categories, so raw counts are descriptive rather than a universal quality score.
- `models_reported` and `per_model`: model IDs and usage/cost breakdowns reported
  by the harness. Requested models remain in `harness.model`; they are not passed
  off as observed models when the native stream does not report one.
- `estimated_cost_usd`, `cost_source`, `cost_scope`, `cost_model_source`: Claude's
  final reported cost is a client-side estimate. Codex token cost is calculated
  for supported models (`gpt-5.4-mini`, `gpt-5.4`) using a dated standard-rate price
  table, with cached tokens priced separately. This excludes search/tool charges,
  Modal compute, and pricing adjustments such as priority/long-context rates.
  Missing model prices or usage produce `null`. Prices are in `app/telemetry.py`.
- `trace_complete`: whether a terminal usage/result event was observed. A missing
  result can leave only partial telemetry. Unknown counts and costs stay `null`.
- `sandbox_cost_usd` stays `null` until actual Modal usage accounting is connected.

The original stdout/stderr remain available for auditing. Claude parsing has
fixture coverage; live verification requires an Anthropic API key. Metrics do not
grade correctness, and estimated cost is not a billing receipt.

Responses are not persisted. Save the response if you need it later. Requests can
be long-lived; keep batches small and configure client/proxy timeouts accordingly.
The endpoint caps each request at 20 runs. There is no global concurrency limit.

## Tests

```sh
uv run pytest -q
# Live tests create billable sandboxes and model requests:
UPTRACK_LIVE=1 UPTRACK_HARNESS=codex UPTRACK_MODEL=gpt-5.4-mini uv run pytest tests/test_live_runs.py -q
UPTRACK_LIVE=1 UPTRACK_HARNESS=claude uv run pytest tests/test_live_runs.py -q
```

Unit tests substitute Modal to check orchestration, validation, and cleanup.
The opt-in live test runs a real documentation question through the endpoint and
checks that a real sandbox returns a schema-valid answer and is cleaned up.
It requires network access, Modal authentication, and the selected provider key.
`UPTRACK_MODEL` optionally selects a model for the live test. API-key runs are
billed to the provider API account separately from a ChatGPT/Claude subscription.

For five tasks of increasing difficulty, run:

```sh
uv run python scripts/run_parallel_smoke.py
```

This exercises the actual FastAPI route through its ASGI interface. It saves the
request, each agent's `*.result.json`, full `*.run.json` records with native traces,
Modal active-sandbox observations, and a summary to the gitignored root `docs/`
directory. It checks five distinct sandboxes, successful reports and cleanup,
five overlapping execution intervals, and five simultaneously active sandboxes
observed through Modal. It uses Codex with `gpt-5.4-mini` and your OpenAI API key.

References: [Modal Sandboxes](https://modal.com/docs/guide/sandboxes),
[Modal async usage](https://modal.com/docs/guide/async),
[Modal's Claude Code example](https://modal.com/docs/examples/sandbox_agent),
[Modal filesystem API](https://modal.com/docs/guide/sandbox-files),
[Codex non-interactive mode](https://developers.openai.com/codex/noninteractive),
[Claude Code headless mode](https://code.claude.com/docs/en/headless).
