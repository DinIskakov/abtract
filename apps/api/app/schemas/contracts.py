"""Abtract Agent Schema Contracts (Pydantic v2).

Defines the telemetry and episode exchange format between sandboxed agents
and the Abtract Engine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionType(StrEnum):
    CLICK = "click"
    TYPE_TEXT = "type_text"
    SELECT_OPTION = "select_option"
    HOVER = "hover"
    SCROLL = "scroll"
    KEY_PRESS = "key_press"
    NAVIGATE = "navigate"
    WAIT_FOR_ELEMENT = "wait_for_element"
    TERMINATE = "terminate"


class FrictionType(StrEnum):
    # Clicked non-interactive element or empty coordinates
    MISCLICK = "misclick"
    # Agent visited page/state, got confused, looped or hit back
    BACKTRACKING = "backtracking"
    # Target selector did not resolve in DOM
    SELECTOR_NOT_FOUND = "selector_not_found"
    # DOM context window exceeded or truncated
    DOM_TOKEN_OVERFLOW = "dom_token_overflow"
    # Multiple identical unlabelled buttons/inputs
    AMBIGUOUS_AFFORDANCE = "ambiguous_affordance"
    # Action performed but UI state did not update
    UNRESPONSIVE_STATE = "unresponsive_state"
    # Tried to interact with an element not in observation
    ACTION_HALLUCINATION = "action_hallucination"
    # Async change occurred without aria-live/signal
    UNANNOUNCED_DYNAMIC_UPDATE = "unannounced_dynamic_update"


class TerminalStatus(StrEnum):
    SUCCESS = "success"
    FAILED_GOAL_NOT_REACHED = "failed_goal_not_reached"
    FAILED_MAX_STEPS_EXCEEDED = "failed_max_steps_exceeded"
    FAILED_TIMEOUT = "failed_timeout"
    FAILED_FATAL_ERROR = "failed_fatal_error"


class ModelFamily(StrEnum):
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    CLAUDE_3_7_SONNET = "claude-3-7-sonnet"
    CLAUDE_3_5_HAIKU = "claude-3-5-haiku"
    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    OTHER = "other"


class BoundingBox(BaseModel):
    """Coordinates and dimensions of an element in viewport pixels."""

    model_config = ConfigDict(extra="ignore")

    x: float = Field(ge=0.0, description="X coordinate of top-left corner in px")
    y: float = Field(ge=0.0, description="Y coordinate of top-left corner in px")
    width: float = Field(ge=0.0, description="Width in px")
    height: float = Field(ge=0.0, description="Height in px")


class ElementAffordance(BaseModel):
    """Normalized representation of an interactive target on the page."""

    model_config = ConfigDict(extra="ignore")

    element_id: str = Field(description="Unique element identifier or data-agent-id")
    tag_name: str = Field(description="HTML tag name, e.g. button, a, input, select")
    role: str | None = Field(
        default=None, description="ARIA role or inferred semantic role"
    )
    accessible_name: str | None = Field(
        default=None, description="Computed accessible name or label"
    )
    css_selector: str = Field(
        description="Unique or primary CSS selector to target this element"
    )
    xpath: str | None = Field(default=None, description="XPath representation")
    bounding_box: BoundingBox = Field(
        description="Bounding box in viewport pixels"
    )
    is_visible: bool = Field(
        default=True, description="Whether the element is visible in the viewport"
    )
    is_interactive: bool = Field(
        default=True, description="Whether the element accepts user input"
    )
    is_disabled: bool = Field(
        default=False, description="Whether the element is disabled"
    )
    data_agent_id: str | None = Field(
        default=None, description="Explicit data-agent-id attribute if present"
    )
    data_agent_action: str | None = Field(
        default=None, description="Semantic action tag e.g. submit-form"
    )
    has_aria_label: bool = Field(
        default=False, description="Whether element has an aria-label"
    )
    aria_live: str | None = Field(
        default=None, description="aria-live setting: polite, assertive, or off"
    )
    aria_describedby: str | None = Field(
        default=None, description="Associated description element ID"
    )


class AgentObservation(BaseModel):
    """Observation perceived by the agent at a given step."""

    model_config = ConfigDict(extra="ignore")

    step_index: int = Field(ge=0)
    url: str = Field(description="Current page URL")
    page_title: str = Field(default="", description="Current document title")
    viewport_dimensions: dict[str, int] = Field(
        default_factory=lambda: {"width": 1280, "height": 800},
        description="Viewport width and height",
    )
    accessibility_tree_snippet: str = Field(
        default="",
        description="Filtered AXTree representation for agent perception",
    )
    dom_token_count: int = Field(
        ge=0,
        description="Raw DOM tokens presented to or scraped from the environment",
    )
    axtree_token_count: int | None = Field(
        default=None,
        ge=0,
        description="Filtered AXTree / actionable graph tokens",
    )
    interactive_elements_count: int = Field(
        default=0,
        ge=0,
        description="Total interactive elements detected",
    )
    interactive_elements: list[ElementAffordance] = Field(
        default_factory=list,
        description="List of detected interactive affordances",
    )
    screenshot_url: str | None = Field(
        default=None,
        description="Optional object storage URI for step screenshot",
    )
    network_idle: bool = Field(
        default=True,
        description="Whether network requests had settled before taking observation",
    )
    active_error_messages: list[str] = Field(
        default_factory=list,
        description="Active form validation or inline alert error messages",
    )


class AgentAction(BaseModel):
    """Action dispatched by the agent in the sandbox."""

    model_config = ConfigDict(extra="ignore")

    step_index: int = Field(ge=0)
    action_type: ActionType
    target_selector: str | None = Field(
        default=None, description="Target CSS selector"
    )
    target_element_id: str | None = Field(
        default=None, description="Target data-agent-id or element_id"
    )
    target_coordinates: dict[str, float] | None = Field(
        default=None,
        description="Visual gaze/click coordinates {'x': float, 'y': float}",
    )
    input_value: str | None = Field(
        default=None, description="Text entered or option selected"
    )
    reasoning: str | None = Field(
        default=None,
        description="Chain-of-thought rationale emitted by the agent for this action",
    )


class StepTelemetry(BaseModel):
    """Execution telemetry captured for each step in the sandbox."""

    model_config = ConfigDict(extra="ignore")

    step_index: int = Field(ge=0)
    timestamp_start: datetime = Field(default_factory=lambda: datetime.now(UTC))
    timestamp_end: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = Field(
        ge=0.0, description="Step duration in milliseconds"
    )
    observation_before: AgentObservation
    action_taken: AgentAction
    action_succeeded: bool = Field(
        description="Whether the sandbox successfully dispatched the action"
    )
    action_error: str | None = Field(
        default=None, description="Error message if dispatch failed"
    )
    state_changed: bool = Field(
        description="Did the DOM/URL/Visual state change after this action?"
    )
    friction_detected: list[FrictionType] = Field(
        default_factory=list,
        description="Friction categories identified during step execution",
    )

    # Model inference resource tracking
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    inference_cost_usd: float = Field(default=0.0, ge=0.0)
    inference_latency_ms: float = Field(default=0.0, ge=0.0)


class TaskDefinition(BaseModel):
    """The benchmark task given to the agent."""

    model_config = ConfigDict(extra="ignore")

    task_id: str
    name: str
    instruction: str
    start_url: str
    target_goal_predicate: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic assertion rules (url_matches, text_present, etc.)",
    )
    max_allowed_steps: int = Field(default=25, gt=0)
    timeout_seconds: int = Field(default=120, gt=0)


class SandboxEpisodeContract(BaseModel):
    """The contract emitted by each sandbox run into the Abtract Engine."""

    model_config = ConfigDict(extra="ignore")

    episode_id: str
    session_id: str
    sandbox_id: str
    variant_id: str = Field(
        description="'A' (baseline) or 'B' (candidate/regenerated)"
    )
    app_version_hash: str
    task: TaskDefinition
    agent_model: str = Field(
        description="e.g. gemini-2.5-flash, claude-3-7-sonnet, gpt-4o"
    )
    agent_framework: str = Field(
        default="browser-use", description="Underlying execution harness"
    )

    # Trajectory
    steps: list[StepTelemetry] = Field(default_factory=list)
    terminal_status: TerminalStatus
    goal_completion_score: float = Field(
        ge=0.0,
        le=1.0,
        description="1.0 for full success, 0.0-0.9 for partial progress",
    )

    # Aggregated Performance Telemetry
    total_steps: int = Field(default=0, ge=0)
    total_wall_clock_ms: float = Field(default=0.0, ge=0.0)
    total_prompt_tokens: int = Field(default=0, ge=0)
    total_completion_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    total_friction_events: int = Field(default=0, ge=0)
    friction_breakdown: dict[FrictionType, int] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BatchEvaluationPayload(BaseModel):
    """Container for batch evaluation across variants and models."""

    model_config = ConfigDict(extra="ignore")

    suite_id: str
    app_name: str
    baseline_variant: str = "A"
    candidate_variant: str | None = "B"
    episodes: list[SandboxEpisodeContract] = Field(default_factory=list)
