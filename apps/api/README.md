# UpTrack runner MVP

`POST /api/runs` accepts a URL, questions, harness configurations, and repetitions.
It waits for the batch and returns one result per harness × task × repetition.
Runs execute concurrently using Modal's `.aio` APIs and `asyncio.gather`, each in a
fresh Modal Sandbox. A per-request semaphore defaults to five active runs. There is no
database or background queue. Evaluation and proposal endpoints operate outside
the sandboxes; harnesses retain their native tools.

## Setup

From `apps/api`:

```sh
uv sync
cp .env.example .env
# Set OPENAI_API_KEY, ANTHROPIC_API_KEY, and/or GEMINI_API_KEY in .env.
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
- `GEMINI_API_KEY`: Gemini CLI runs and the optional semantic judge/proposer.
- `GEMINI_MODEL`: explicit judge/proposer and Gemini CLI default model
  (`gemini-3.8-flash`).
- `MODAL_PROXY_TOKEN`: separate inference-endpoint credential; not a Modal
  deployment token and not required for the existing native provider runs.

Create Modal credentials in the Modal dashboard's token settings. Team/Enterprise
workspaces can use a dedicated service user with Contributor access to the target
environment. Export Modal tokens as real process environment variables; the Modal
SDK does not receive them through this app's Pydantic `.env` settings.
See [Modal service users](https://modal.com/docs/guide/service-users).

The current endpoint is a development MVP, not a production deployment: it still
needs API authentication, global admission/concurrency limits, and shared durable storage
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
use the Codex/Claude CLI default or configured `GEMINI_MODEL`. `name` accepts
`codex`, `claude`, or `gemini`. CLI versions are pinned in `app/runs.py`. The first request
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
  tokens where reported. Input includes cache reads/writes. Codex output includes
  reasoning and our estimator does not bill it twice. Gemini CLI exposes candidate
  output tokens but omits reasoning usage; its cost remains unknown.
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

Run, evaluation, proposal, and evaluation-input JSON records are saved locally in
the gitignored root `docs/artifacts/` directory. Set `ARTIFACT_DIR` to change it.
Files are written atomically with private permissions. This is a single-backend
MVP store, not a distributed database. Requests can
be long-lived; keep batches small and configure client/proxy timeouts accordingly.
The endpoint caps each request at 20 runs. There is no global concurrency limit.

## Request capture and frozen variants

Set `capture_http: true` on **both** A and B. The sandbox starts a separate
mitmproxy process and configures proxy/CA environment variables for native HTTP
clients. No custom agent tool is installed. It records same-origin public GETs
that honor these settings: URL, status, timing, content type, original/modified
SHA-256 hashes, response bodies, and patch outcomes. Authenticated/cookie-bearing
response bodies are not retained or modified in this MVP.

`observations.native_tool_events` contains exposed native tool arguments/results
with trace-line references. Bodies/tool events are bounded to 32 KiB and 200 events,
with truncation flags; known credentials and sensitive URL query parameters are
redacted. Hashes cover full decoded entity bytes before redaction/truncation.
The harness user cannot write the root-owned proxy records. Raw native stdout and
stderr remain harness-authored evidence, not an independent audit trail.

Provider-hosted search and clients bypassing the proxy remain outside coverage.
The `coverage`, `capture_error`, `applied_patch_ids`, and `unobserved_patch_ids`
fields make this explicit. An applied response proves delivery, not that the agent
used it. Unverified variant exposure cannot support an A/B improvement claim.

To test B, also supply `variant_id` and `patches`:

```json
{
  "capture_http": true,
  "variant_id": "docs-v2",
  "patches": [{
    "patch_id": "sandbox-example",
    "url": "https://example.com/docs/sandboxes",
    "expected_sha256": "<SHA-256 of the original UTF-8 response body>",
    "old_text": "Exact original text occurring once",
    "new_text": "Improved text"
  }]
}
```

These fields extend the usual `/api/runs` request. One patch per URL is supported;
combine related edits into one replacement. A hash mismatch, ambiguous span,
unsupported encoding, or ineligible response leaves the original intact and is
recorded. Patches never modify the actual website. Each run records platform URL,
task hash, variant identity, and patch-set hash.

## Evaluate, inspect failures, then propose

- `POST /api/evaluations`: submit run records and explicit task rubrics.
- `POST /api/proposals`: submit the saved evaluation, identical run records, and
  source documents (`url`, `body`). Gemini proposes exact replacement patches.
- `GET /api/runs/{run_id}`, `/api/evaluations/{evaluation_id}`, and
  `/api/proposals/{proposal_id}` reload records for the frontend.

An evaluation request has this shape (`runs` contains full `/api/runs` results):

```json
{
  "runs": [],
  "semantic_judge": true,
  "rubrics": [{
    "task_id": "create-sandbox",
    "task_index": 0,
    "task": "How do I create a sandbox? Include Python code.",
    "criteria": [
      {"id": "syntax", "kind": "python_syntax", "description": "Python parses"},
      {"id": "correctness", "kind": "semantic", "description": "Uses an initialized Modal App", "reference_answer": "Resolve the App with modal.App.lookup before passing it to modal.Sandbox.create, or use an active app.run context."}
    ]
  }]
}
```

Replace `runs: []` with at least one actual run. Task text and indices must match.
Deterministic criterion kinds are `required_text`, `forbidden_text`,
`required_sources` (each uses `values`), `python_syntax`, `duration_budget`, and
`cost_budget` (each budget uses `limit`). Python checks parse code without executing
it; source checks verify reported URLs, not factual support. Cost checks use the
available model-cost estimate and exclude unknown charges.

Semantic checks require a supplied reference answer and explicit
`semantic_judge: true`. Gemini must return exact answer quotes as evidence.
Missing metrics, disabled judging, and judge failures yield `unknown`, not a
fabricated pass. Each check includes its method, outcome, reason, evidence, and
error, allowing the frontend to show where a task failed. Reports record grader,
rubric, model, and run versions. Variant exposure is separate from answer quality.

Proposals link to failed check IDs and exact source spans. Their patch-set hash is
fixed before B runs; the endpoint never applies or publishes them automatically.
It rejects changed evaluation/run evidence and invented source spans. A proposer
may return no changes when failures do not justify a platform edit. Proposed
changes are hypotheses, not established causes or improvements. Run the same
rubrics on B, repeat trials, and check held-out tasks before claiming a gain.

## Modal model endpoints

Native harness API credentials and Modal inference credentials are separate.
The requested dedicated endpoint commands are:

```sh
uv run modal endpoint create --name uptrack-kimi-k3 --model moonshotai/Kimi-K3
uv run modal endpoint create --name uptrack-qwen --model Qwen/Qwen3.6-27B-FP8
uv run modal endpoint list --json
```

Authenticated endpoints require a workspace proxy token. Dedicated endpoints
scale to zero by default and incur compute charges while running. GPU deployment
requires the workspace's billing setup; endpoint creation does not automatically
connect a new model to the evaluation harness matrix. Model-provider integration
for these endpoints is a separate step.

## Tests

```sh
uv run pytest -q
# Live tests create billable sandboxes and model requests:
UPTRACK_LIVE=1 UPTRACK_HARNESS=codex UPTRACK_MODEL=gpt-5.4-mini uv run pytest tests/test_live_runs.py -q
UPTRACK_LIVE=1 UPTRACK_HARNESS=claude uv run pytest tests/test_live_runs.py -q
UPTRACK_LIVE=1 UPTRACK_HARNESS=gemini UPTRACK_MODEL=gemini-3.8-flash uv run pytest tests/test_live_runs.py -q
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
