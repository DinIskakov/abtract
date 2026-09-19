"""Async Modal runner. No scoring or custom agent tools."""

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

import modal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.config import settings
from app.gemini_harness import GEMINI_VERSION, gemini_command
from app.observability import HTTPObservation, Observations, tool_events
from app.telemetry import Telemetry, parse_telemetry
from app.variants import VariantPatch, origin, sha256, variant_hash

Harness = Literal["codex", "claude", "gemini"]
VERSIONS = {"codex": "0.155.0", "claude": "2.1.278", "gemini": GEMINI_VERSION}
PACKAGES = {
    "codex": "@openai/codex",
    "claude": "@anthropic-ai/claude-code",
    "gemini": "@google/gemini-cli",
}


class HarnessConfig(BaseModel):
    name: Harness
    model: str | None = Field(default=None, min_length=1, max_length=200)


class RunRequest(BaseModel):
    url: HttpUrl
    tasks: list[str] = Field(min_length=1, max_length=10)
    harnesses: list[HarnessConfig] = Field(min_length=1, max_length=4)
    repetitions: int = Field(default=1, ge=1, le=5)
    timeout_seconds: int = Field(default=300, ge=10, le=900)
    max_concurrency: int | None = Field(default=None, ge=1, le=20)
    capture_http: bool = False
    retrieval_mode: Literal["native", "direct_http"] = "native"
    variant_id: str = Field(default="baseline", min_length=1, max_length=100)
    patches: list[VariantPatch] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if any(not task.strip() or len(task) > 10000 for task in self.tasks):
            raise ValueError("Tasks must contain 1–10000 nonblank characters")
        if len(self.tasks) * len(self.harnesses) * self.repetitions > 20:
            raise ValueError("At most 20 runs per request")
        if self.patches and (not self.capture_http or self.variant_id == "baseline"):
            raise ValueError(
                "Patches require capture_http and a non-baseline variant_id"
            )
        if len({str(p.url) for p in self.patches}) != len(self.patches):
            raise ValueError("Combine changes into one patch per URL")
        if len({p.patch_id for p in self.patches}) != len(self.patches):
            raise ValueError("Patch IDs must be unique")
        if any(origin(str(p.url)) != origin(str(self.url)) for p in self.patches):
            raise ValueError("Patch URLs must share the target origin")
        return self


class AgentReport(BaseModel):
    """Agent-authored observations, not trusted evaluation scores."""

    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1)
    actions: list[str]
    sources: list[str]
    limitations: list[str]


class RunResult(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    sandbox_id: str | None = None
    task: str
    platform_url: str = ""
    task_index: int
    repetition: int
    harness: HarnessConfig
    harness_version: str
    status: Literal["completed", "error"] = "error"
    duration_seconds: float = 0
    execution_duration_seconds: float | None = None
    telemetry: Telemetry = Field(default_factory=Telemetry)
    retrieval_mode: Literal["native", "direct_http"] = "native"
    variant_id: str = "baseline"
    variant_sha256: str = Field(default_factory=lambda: variant_hash([]))
    task_sha256: str = ""
    observations: Observations = Field(default_factory=Observations)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    execution_started_at: datetime | None = None
    execution_finished_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    report: AgentReport | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    cleanup_error: str | None = None


def credentials(name: Harness) -> dict[str, str]:
    if name == "gemini":
        key = settings.gemini_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError(
                "Set GEMINI_API_KEY in apps/api/.env before running gemini"
            )
        return {"GEMINI_API_KEY": key.get_secret_value()}
    key = settings.openai_api_key if name == "codex" else settings.anthropic_api_key
    variable = "CODEX_API_KEY" if name == "codex" else "ANTHROPIC_API_KEY"
    if key is None or not key.get_secret_value().strip():
        required = "OPENAI_API_KEY" if name == "codex" else variable
        raise ValueError(f"Set {required} in apps/api/.env before running {name}")
    return {variable: key.get_secret_value()}


def command(harness: HarnessConfig, prompt: str) -> list[str]:
    if harness.name == "gemini":
        return gemini_command(harness.model or settings.gemini_model, prompt)
    if harness.name == "codex":
        args = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
    else:
        args = [
            "claude",
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]
    if harness.model:
        args.extend(["--model", harness.model])
    return [*args, prompt]


def image_for(name: Harness, capture_http: bool = False) -> modal.Image:
    # Non-root user is required by Claude's unattended permission mode.
    image = (
        modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
        .apt_install("git", "curl", "ca-certificates")
        .run_commands(
            f"npm install -g {PACKAGES[name]}@{VERSIONS[name]}",
            "mkdir -p /workspace && chown node:node /workspace",
        )
    )
    if capture_http:
        image = image.pip_install("mitmproxy==12.2.3", "pydantic>=2.10,<3")
        for module in (
            "__init__.py",
            "observability.py",
            "variants.py",
            "sandbox_proxy.py",
        ):
            image = image.add_local_file(
                Path(__file__).parent / module, f"/opt/uptrack/app/{module}", copy=True
            )
        image = image.env({"PYTHONPATH": "/opt/uptrack"})
    return image.dockerfile_commands("USER node", "ENV HOME=/home/node")


async def run_one(
    request: RunRequest,
    harness: HarnessConfig,
    task_index: int,
    repetition: int,
) -> RunResult:
    if harness.name == "gemini" and not harness.model:
        harness = harness.model_copy(update={"model": settings.gemini_model})
    result = RunResult(
        task=request.tasks[task_index],
        platform_url=str(request.url),
        task_index=task_index,
        repetition=repetition,
        harness=harness,
        harness_version=VERSIONS[harness.name],
        retrieval_mode=request.retrieval_mode,
        variant_id=request.variant_id,
        variant_sha256=variant_hash(request.patches),
        task_sha256=sha256(request.tasks[task_index].encode()),
        observations=Observations(capture_http=request.capture_http),
    )
    started = time.monotonic()
    sandbox = None
    secret_values: list[str] = []
    try:
        env = credentials(harness.name)
        secret_values = list(env.values())
        app = await modal.App.lookup.aio(
            settings.modal_app_name, create_if_missing=True
        )
        sandbox = await modal.Sandbox.create.aio(
            app=app,
            image=image_for(harness.name, request.capture_http),
            workdir="/workspace",
            timeout=request.timeout_seconds + 60,
            cpu=2,
            memory=2048,
            secrets=[
                modal.Secret.from_dict({key: value for key, value in env.items()})
            ],
        )
        result.sandbox_id = sandbox.object_id
        proxy_env: dict[str, str | None] | None = None
        if request.capture_http:
            config = json.dumps(
                {
                    "url": str(request.url),
                    "patches": [
                        patch.model_dump(mode="json") for patch in request.patches
                    ],
                }
            )
            setup = await sandbox.exec.aio(
                "python", "-m", "app.sandbox_proxy", config, timeout=30
            )
            if await setup.wait.aio() != 0:
                raise RuntimeError("Observation proxy setup failed")
            proxy_env = {
                "HTTP_PROXY": "http://127.0.0.1:8080",
                "HTTPS_PROXY": "http://127.0.0.1:8080",
                "http_proxy": "http://127.0.0.1:8080",
                "https_proxy": "http://127.0.0.1:8080",
                "NO_PROXY": "127.0.0.1,localhost",
                "SSL_CERT_FILE": "/tmp/uptrack-ca.pem",
                "REQUESTS_CA_BUNDLE": "/tmp/uptrack-ca.pem",
                "CURL_CA_BUNDLE": "/tmp/uptrack-ca.pem",
                "NODE_EXTRA_CA_CERTS": "/tmp/uptrack-ca.pem",
            }
        prompt = (
            f"Platform URL: {request.url}\nTask: {result.task}\n\n"
            "Use your native capabilities to research and answer this task. "
            "Include code in the answer when useful. Write /workspace/result.json "
            "using your file tools or shell. It must match this JSON schema: "
            f"{json.dumps(AgentReport.model_json_schema())}\n"
            "Report only actions you actually took and sources you actually used. "
            "Describe any blockers in limitations. Do not grade your answer."
        )
        if request.retrieval_mode == "direct_http":
            prompt += (
                "\nThis is a controlled single-page test. Use your native shell "
                "to fetch the exact Platform URL with curl or an HTTP client. "
                "Answer briefly using only that response; do not use hosted web "
                "search, follow links, or change proxy settings. Keep the answer "
                "concise but complete; include reasoning or code when the task "
                "requests it. If the page lacks the answer, say so."
            )
        process = await sandbox.exec.aio(
            "runuser",
            "-u",
            "node",
            "--",
            *command(harness, prompt),
            timeout=request.timeout_seconds,
            pty=harness.name == "claude",
            env=proxy_env,
        )
        # Codex reads piped stdin even with a positional prompt. Without EOF,
        # it waits for more input indefinitely before starting the task.
        if harness.name in {"codex", "gemini"}:
            process.stdin.write_eof()
            await process.stdin.drain.aio()
        result.execution_started_at = datetime.now(UTC)

        async def read_stdout() -> None:
            result.stdout = await process.stdout.read.aio()

        async def read_stderr() -> None:
            result.stderr = await process.stderr.read.aio()

        async def wait_process() -> None:
            result.exit_code = await process.wait.aio()

        try:
            outcomes = await asyncio.gather(
                read_stdout(), read_stderr(), wait_process(), return_exceptions=True
            )
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    raise outcome
        finally:
            result.execution_finished_at = datetime.now(UTC)
        if result.exit_code != 0:
            raise RuntimeError(f"Harness exited with code {result.exit_code}")
        info = await sandbox.filesystem.stat.aio("/workspace/result.json")
        if info.size > 1_000_000:
            raise ValueError("result.json exceeds 1 MB")
        raw = await sandbox.filesystem.read_text.aio("/workspace/result.json")
        result.report = AgentReport.model_validate_json(raw)
        result.status = "completed"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if sandbox is not None:
            if request.capture_http:
                try:
                    raw = await sandbox.filesystem.read_text.aio(
                        "/opt/uptrack-observations/http.jsonl"
                    )
                    result.observations.http = [
                        HTTPObservation.model_validate_json(line)
                        for line in raw.splitlines()
                        if line
                    ]
                    try:
                        await sandbox.filesystem.stat.aio(
                            "/opt/uptrack-observations/truncated"
                        )
                        result.observations.http_events_truncated = True
                    except Exception:
                        pass
                except Exception as exc:
                    result.observations.capture_error = f"{type(exc).__name__}: {exc}"
            try:
                await sandbox.terminate.aio()
            except Exception as exc:
                result.cleanup_error = f"{type(exc).__name__}: {exc}"
        result.duration_seconds = round(time.monotonic() - started, 3)
        result.finished_at = datetime.now(UTC)
    if result.execution_started_at and result.execution_finished_at:
        result.execution_duration_seconds = round(
            (
                result.execution_finished_at - result.execution_started_at
            ).total_seconds(),
            3,
        )
    result.telemetry = parse_telemetry(harness.name, result.stdout, harness.model)
    (
        result.observations.native_tool_events,
        result.observations.tool_events_truncated,
    ) = tool_events(result.stdout, secret_values)
    result.observations.applied_patch_ids = sorted(
        {
            item.patch.patch_id
            for item in result.observations.http
            if item.patch and item.patch.status == "applied"
        }
    )
    observed = {item.patch.patch_id for item in result.observations.http if item.patch}
    result.observations.unobserved_patch_ids = [
        patch.patch_id for patch in request.patches if patch.patch_id not in observed
    ]
    # Prevent accidental credential echoes in logs or agent-authored output.
    encoded = result.model_dump_json()
    for value in secret_values:
        encoded = encoded.replace(json.dumps(value)[1:-1], "[REDACTED]")
    return RunResult.model_validate_json(encoded)
