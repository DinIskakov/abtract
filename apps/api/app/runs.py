"""Async Modal runner. No scoring or custom agent tools."""

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import uuid4

import modal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.config import settings
from app.telemetry import Telemetry, parse_telemetry

Harness = Literal["codex", "claude"]
VERSIONS = {"codex": "0.155.0", "claude": "2.1.278"}
PACKAGES = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code"}


class HarnessConfig(BaseModel):
    name: Harness
    model: str | None = Field(default=None, min_length=1, max_length=200)


class RunRequest(BaseModel):
    url: HttpUrl
    tasks: list[str] = Field(min_length=1, max_length=10)
    harnesses: list[HarnessConfig] = Field(min_length=1, max_length=4)
    repetitions: int = Field(default=1, ge=1, le=5)
    timeout_seconds: int = Field(default=300, ge=10, le=900)
    max_concurrency: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if any(not task.strip() or len(task) > 10000 for task in self.tasks):
            raise ValueError("Tasks must contain 1–10000 nonblank characters")
        if len(self.tasks) * len(self.harnesses) * self.repetitions > 20:
            raise ValueError("At most 20 runs per request")
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
    task_index: int
    repetition: int
    harness: HarnessConfig
    harness_version: str
    status: Literal["completed", "error"] = "error"
    duration_seconds: float = 0
    execution_duration_seconds: float | None = None
    telemetry: Telemetry = Field(default_factory=Telemetry)
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
    key = settings.openai_api_key if name == "codex" else settings.anthropic_api_key
    variable = "CODEX_API_KEY" if name == "codex" else "ANTHROPIC_API_KEY"
    if key is None or not key.get_secret_value().strip():
        required = "OPENAI_API_KEY" if name == "codex" else variable
        raise ValueError(f"Set {required} in apps/api/.env before running {name}")
    return {variable: key.get_secret_value()}


def command(harness: HarnessConfig, prompt: str) -> list[str]:
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


def image_for(name: Harness) -> modal.Image:
    # Non-root user is required by Claude's unattended permission mode.
    return (
        modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
        .apt_install("git", "curl", "ca-certificates")
        .run_commands(
            f"npm install -g {PACKAGES[name]}@{VERSIONS[name]}",
            "mkdir -p /workspace && chown node:node /workspace",
        )
        .dockerfile_commands("USER node", "ENV HOME=/home/node")
    )


async def run_one(
    request: RunRequest,
    harness: HarnessConfig,
    task_index: int,
    repetition: int,
) -> RunResult:
    result = RunResult(
        task=request.tasks[task_index],
        task_index=task_index,
        repetition=repetition,
        harness=harness,
        harness_version=VERSIONS[harness.name],
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
            image=image_for(harness.name),
            workdir="/workspace",
            timeout=request.timeout_seconds + 60,
            cpu=2,
            memory=2048,
            secrets=[
                modal.Secret.from_dict({key: value for key, value in env.items()})
            ],
        )
        result.sandbox_id = sandbox.object_id
        prompt = (
            f"Platform URL: {request.url}\nTask: {result.task}\n\n"
            "Use your native capabilities to research and answer this task. "
            "Include code in the answer when useful. Write /workspace/result.json "
            "using your file tools or shell. It must match this JSON schema: "
            f"{json.dumps(AgentReport.model_json_schema())}\n"
            "Report only actions you actually took and sources you actually used. "
            "Describe any blockers in limitations. Do not grade your answer."
        )
        process = await sandbox.exec.aio(
            "runuser",
            "-u",
            "node",
            "--",
            *command(harness, prompt),
            timeout=request.timeout_seconds,
            pty=harness.name == "claude",
        )
        # Codex reads piped stdin even with a positional prompt. Without EOF,
        # it waits for more input indefinitely before starting the task.
        if harness.name == "codex":
            process.stdin.write_eof()
            await process.stdin.drain.aio()
        result.execution_started_at = datetime.now(UTC)
        try:
            result.stdout, result.stderr, result.exit_code = await asyncio.gather(
                process.stdout.read.aio(),
                process.stderr.read.aio(),
                process.wait.aio(),
            )
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
    # Prevent accidental credential echoes in logs or agent-authored output.
    encoded = result.model_dump_json()
    for value in secret_values:
        encoded = encoded.replace(json.dumps(value)[1:-1], "[REDACTED]")
    return RunResult.model_validate_json(encoded)
