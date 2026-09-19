"""Abtract Regeneration Report Models.

Defines the structured output ingested by Step 5 (Design Regeneration Engine)
to rewrite application markup into an agent-native interface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.evals.metrics import (
    A2AEvalMetrics,
    ABBenchmarkComparison,
    AgentReadinessScore,
)
from app.schemas.contracts import FrictionType


class DirectiveType(StrEnum):
    INJECT_DATA_AGENT_ID = "inject_data_agent_id"
    ADD_ARIA_LABEL = "add_aria_label"
    ADD_ARIA_LIVE = "add_aria_live"
    FLATTEN_DOM_WRAPPERS = "flatten_dom_wrappers"
    ASSOCIATE_FORM_LABEL = "associate_form_label"
    ADD_INLINE_ERROR_ANNOUNCEMENT = "add_inline_error_announcement"
    SIMPLIFY_SVG_PAYLOAD = "simplify_svg_payload"


class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FrictionHotspot(BaseModel):
    """Specific UI location or element where agent friction repeatedly occurred."""

    model_config = ConfigDict(extra="ignore")

    hotspot_id: str
    friction_type: FrictionType
    severity: Priority
    target_selector: str
    element_tag: str
    location_url: str
    occurrence_count: int
    sample_agent_reasoning: str | None = None
    impact_description: str


class TransformationDirective(BaseModel):
    """Prescriptive code modification instruction for the Design Regeneration Engine."""

    model_config = ConfigDict(extra="ignore")

    directive_id: str
    directive_type: DirectiveType
    priority: Priority
    target_selector: str
    target_element_id: str | None = None
    rationale: str
    current_code_snippet: str | None = None
    suggested_patch_code: str = Field(
        description="Exact JSX/HTML code pattern to replace the target element"
    )
    expected_impact: str = Field(
        description="Predicted metric improvement from this transformation"
    )


class AgentNativeReport(BaseModel):
    """Complete diagnostic and regeneration report for Step 5."""

    model_config = ConfigDict(extra="ignore")

    report_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    app_name: str
    target_url: str
    variant_evaluated: str
    agent_readiness_score: AgentReadinessScore
    a2a_metrics: A2AEvalMetrics
    friction_hotspots: list[FrictionHotspot] = Field(default_factory=list)
    transformation_directives: list[TransformationDirective] = Field(
        default_factory=list
    )
    dom_token_reduction_target_pct: float = Field(
        default=0.0,
        description="Target percentage reduction for raw DOM tokens",
    )
    benchmark_comparison: ABBenchmarkComparison | None = None
    executive_summary: str
    markdown_content: str
