"""Shared data contracts. Every module speaks in these types; keep them stable.

Storage layout (under settings.data_dir, which is the Modal Volume in the cloud):
  sites/<site_id>/<version>/...                 the site files for one version (v0, v1, ...)
  sites/<site_id>/versions.json                 list[SiteVersion]
  runs/<run_id>/run.json                        RunSummary
  runs/<run_id>/episodes/<episode_id>.json      Episode (full trace + metrics)
  runs/<run_id>/screenshots/<episode_id>/NN.png vision-agent screenshots
  events/<site_id>/<version>.jsonl              SiteEvent, appended by the site server (form submits etc.)
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# --------------------------------------------------------------------------- tasks

class TaskKind(str, Enum):
    answer = "answer"  # agent must report a fact found on the site
    url = "url"        # agent must end on a particular page
    action = "action"  # agent must do something the site records as a SiteEvent (e.g. submit a form)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    kind: TaskKind
    prompt: str                                   # what a user would ask an agent to do
    expected_answer: str | None = None            # for kind=answer
    answer_aliases: list[str] = []                # alternative acceptable spellings, e.g. ["$3.95", "3.95/hr"]
    expected_url_pattern: str | None = None       # for kind=url: regex against the final path relative to site root
    expected_event: str | None = None             # for kind=action: SiteEvent.name that must be recorded
    expected_event_match: dict[str, Any] = {}     # subset of SiteEvent.payload that must match
    max_steps: int = 15
    timeout_s: float | None = Field(default=None, gt=0, le=600)
    tags: list[str] = []
    trap: str | None = None                       # for the demo: which agent-trap this task exercises


# --------------------------------------------------------------------------- agents & models

class AgentKind(str, Enum):
    text = "text"      # plain HTTP fetch, HTML->text, follows links; no JavaScript
    dom = "dom"        # real browser (Playwright); observes a simplified DOM / accessibility tree
    vision = "vision"  # real browser; observes screenshots with numbered element labels (computer-use style)


class ModelSpec(BaseModel):
    id: str                                        # our short id, e.g. "deepseek-v4.1-flash"
    provider: Literal["modal", "gemini", "mock"]
    model: str                                     # string sent to the provider (endpoint hostname for Modal)
    display_name: str
    supports_vision: bool = False
    input_price_per_m: float = 0.0                 # USD per 1M input tokens
    output_price_per_m: float = 0.0                # USD per 1M output tokens
    max_output_tokens: int = 2048


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    llm_latency_ms: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.llm_calls += other.llm_calls
        self.llm_latency_ms += other.llm_latency_ms

    def cost_usd(self, spec: ModelSpec) -> float:
        return (self.input_tokens * spec.input_price_per_m + self.output_tokens * spec.output_price_per_m) / 1_000_000


# --------------------------------------------------------------------------- actions (what an agent can do)

ActionType = Literal[
    "navigate",  # {"type": "navigate", "url": "..."}  absolute or relative to current page
    "click",     # {"type": "click", "id": 12}          id = numbered interactive element in the observation
    "type",      # {"type": "type", "id": 12, "text": "..."}  types into a field (clears first)
    "select",    # {"type": "select", "id": 12, "value": "..."}
    "scroll",    # {"type": "scroll", "direction": "down"|"up"}
    "back",      # {"type": "back"}
    "answer",    # {"type": "answer", "text": "..."}      terminal: agent reports its answer / declares the task done
    "give_up",   # {"type": "give_up", "reason": "..."}   terminal
    "noop",      # {"type": "noop"}  recorded by the agent loop when the model reply could not be parsed; nothing happens
]


class Action(BaseModel):
    type: ActionType
    url: str | None = None
    id: int | None = None
    text: str | None = None
    value: str | None = None
    direction: str | None = None
    reason: str | None = None


class Step(BaseModel):
    index: int
    url: str                          # page URL before the action
    observation_chars: int = 0        # size of what the model saw (proxy for context cost)
    thought: str | None = None        # model's stated reasoning, if any
    action: Action
    latency_ms: int = 0               # wall time for observe + think + act
    error: str | None = None          # action failed (element not found, timeout, ...)
    screenshot_path: str | None = None


# --------------------------------------------------------------------------- episodes & runs

FailureMode = Literal["wrong_answer", "wrong_page", "no_event", "max_steps", "gave_up", "error", "timeout"]


class Episode(BaseModel):
    """One agent x one model x one task x one site version."""
    id: str = Field(default_factory=lambda: new_id("ep"))
    run_id: str
    site_id: str
    site_version: str
    task_id: str
    agent_kind: AgentKind
    model_id: str
    started_at: float = Field(default_factory=time.time)
    finished_at: float | None = None
    steps: list[Step] = []
    final_answer: str | None = None
    final_url: str | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    success: bool | None = None       # None until judged
    judge_reason: str | None = None
    failure_mode: FailureMode | None = None
    error: str | None = None

    @property
    def duration_s(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at

    @property
    def n_steps(self) -> int:
        return len(self.steps)


class SiteEvent(BaseModel):
    """Something the hosted site recorded (form submit, button press). Written by the site server."""
    name: str                          # e.g. "waitlist_submit"
    payload: dict[str, Any] = {}
    site_id: str
    version: str
    episode_id: str | None = None      # agents pass ?abtract_ep=<id> / header X-Abtract-Episode so we can attribute
    ts: float = Field(default_factory=time.time)


class SiteVersion(BaseModel):
    site_id: str
    version: str                       # "v0", "v1", ...
    parent: str | None = None
    created_at: float = Field(default_factory=time.time)
    notes: str = ""                    # optimizer's summary of what it changed and why
    changed_files: list[str] = []


class MetricBlock(BaseModel):
    episodes: int = 0
    success_rate: float = 0.0
    avg_steps: float = 0.0
    avg_duration_s: float = 0.0
    avg_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    failure_modes: dict[str, int] = {}


class RunSummary(BaseModel):
    """Aggregate of all episodes for one swarm run against one site version."""
    run_id: str = Field(default_factory=lambda: new_id("run"))
    site_id: str
    site_version: str
    site_url: str
    scan_mode: Literal["quick", "full"] = "full"
    created_at: float = Field(default_factory=time.time)
    finished_at: float | None = None
    tasks: list[Task] = []
    model_ids: list[str] = []
    agent_kinds: list[AgentKind] = []
    overall: MetricBlock = Field(default_factory=MetricBlock)
    per_model: dict[str, MetricBlock] = {}
    per_agent: dict[str, MetricBlock] = {}
    per_task: dict[str, MetricBlock] = {}
    per_trap: dict[str, MetricBlock] = {}


# --------------------------------------------------------------------------- jobs (product flow)

JobType = Literal["intake", "loop"]
JobStatus = Literal["queued", "running", "done", "failed"]


class PreviewAttempt(BaseModel):
    episode_id: str
    task_id: str
    prompt: str
    model_id: str
    agent_kind: AgentKind
    outcome: Literal["passed", "failed", "error", "skipped"]
    reason: str = ""


class ActiveAttempt(BaseModel):
    task_id: str
    prompt: str
    model_id: str
    agent_kind: AgentKind


class PageSummary(BaseModel):
    title: str = ""
    heading: str = ""
    links: int = 0
    forms: int = 0


class JobPreview(BaseModel):
    """Small, provisional snapshot; no traces or additional LLM inference."""
    site_version: str = "v0"
    page: PageSummary | None = None
    pages_scanned: int = 0
    observations: list[str] = Field(default_factory=list)
    task_sample: list[str] = Field(default_factory=list)
    total: int = 0
    completed: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    findings: list[str] = Field(default_factory=list)
    recent: list[PreviewAttempt] = Field(default_factory=list)
    active: list[ActiveAttempt] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)


class Job(BaseModel):
    """A background unit of work started from the landing page.

    intake: mirror the URL -> import as <site_id>/v0 -> pick tasks -> swarm -> findings report.
    loop:   optimize -> new version -> swarm, repeated `iterations` times.
    Stored at jobs/<job_id>.json; the progress page polls it.
    """
    id: str = Field(default_factory=lambda: new_id("job"))
    type: JobType
    scan_mode: Literal["quick", "full"] = "full"  # old saved jobs retain their full-audit meaning
    status: JobStatus = "queued"
    phase: str = ""                       # human-readable, e.g. "Mirroring site", "Running swarm"
    progress_done: int = 0
    progress_total: int = 0
    url: str | None = None                # intake: what the user typed
    site_id: str | None = None
    site_version: str | None = None       # version the latest run used
    run_ids: list[str] = []               # every run this job produced, in order
    baseline_run_id: str | None = None    # explicit baseline; do not infer from timestamps
    model_ids: list[str] = []
    agent_kinds: list[AgentKind] = []
    iterations: int = 1                   # loop only
    budget_usd: float | None = None       # abort before launching a swarm that would exceed this
    swarm_spent_usd: float = 0.0          # cumulative episode inference spend across this job
    findings: str | None = None           # plain-language report for the user (Gemini or rule-based)
    live_preview: JobPreview | None = None
    error: str | None = None
    log: list[str] = []
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
