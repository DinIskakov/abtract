"""Abtract Evals and Regeneration Report Router.

Provides API endpoints for episode evaluation, A/B benchmarking,
and agent-native regeneration report generation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.evals.engine import eval_engine
from app.evals.metrics import ABBenchmarkComparison, VariantMetrics
from app.reports.generator import report_generator
from app.reports.models import AgentNativeReport
from app.schemas.contracts import (
    ActionType,
    AgentAction,
    AgentObservation,
    BatchEvaluationPayload,
    BoundingBox,
    ElementAffordance,
    FrictionType,
    ModelFamily,
    SandboxEpisodeContract,
    StepTelemetry,
    TaskDefinition,
    TerminalStatus,
)

router = APIRouter(prefix="/evals", tags=["evals"])


class ReportGenerationRequest(BaseModel):
    """Request payload for generating an agent-native regeneration report."""

    model_config = ConfigDict(extra="ignore")

    app_name: str = Field(default="Abtract Target App")
    target_url: str = Field(default="https://app.example.com")
    episodes: list[SandboxEpisodeContract] = Field(
        min_length=1,
        description="List of sandbox episode traces to evaluate",
    )
    compare_with_candidate_episodes: list[SandboxEpisodeContract] | None = Field(
        default=None,
        description="Optional candidate (Variant B) episodes for A/B comparison",
    )


@router.post(
    "/evaluate",
    response_model=VariantMetrics,
    summary="Evaluate episode telemetry",
    status_code=status.HTTP_200_OK,
)
async def evaluate_episodes(
    episodes: list[SandboxEpisodeContract],
) -> VariantMetrics:
    """Evaluates a batch of episode traces for a single variant."""
    if not episodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Episode list cannot be empty",
        )
    variant_id = episodes[0].variant_id
    return eval_engine.evaluate_variant(variant_id=variant_id, episodes=episodes)


@router.post(
    "/benchmark",
    response_model=ABBenchmarkComparison,
    summary="Run A/B comparative benchmarking",
    status_code=status.HTTP_200_OK,
)
async def run_ab_benchmark(
    payload: BatchEvaluationPayload,
) -> ABBenchmarkComparison:
    """Runs A/B comparative benchmarking between baseline and candidate variants."""
    if not payload.episodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must contain episodes for A/B benchmarking",
        )
    return eval_engine.evaluate_benchmark(payload)


@router.post(
    "/report",
    response_model=AgentNativeReport,
    summary="Generate Agent-Native Regeneration Report",
    status_code=status.HTTP_200_OK,
)
async def generate_regeneration_report(
    req: ReportGenerationRequest,
) -> AgentNativeReport:
    """Generates an Agent-Native Regeneration Report with friction map & directives."""
    benchmark_comp: ABBenchmarkComparison | None = None
    if req.compare_with_candidate_episodes:
        benchmark_comp = eval_engine.evaluate_benchmark(
            BatchEvaluationPayload(
                suite_id="custom-benchmark",
                app_name=req.app_name,
                baseline_variant=req.episodes[0].variant_id,
                candidate_variant=req.compare_with_candidate_episodes[0].variant_id,
                episodes=req.episodes + req.compare_with_candidate_episodes,
            )
        )

    return report_generator.generate_report(
        episodes=req.episodes,
        app_name=req.app_name,
        target_url=req.target_url,
        benchmark_comparison=benchmark_comp,
    )


@router.get(
    "/sample-report",
    response_model=AgentNativeReport,
    summary="Get a sample agent-native regeneration report",
    status_code=status.HTTP_200_OK,
)
async def get_sample_report(
    include_benchmark: bool = Query(
        default=True,
        description="Whether to include A/B benchmark comparison in the sample",
    ),
) -> AgentNativeReport:
    """Returns a realistic sample regeneration report for an e-commerce checkout app."""
    episodes_a, episodes_b = _build_sample_scenario()

    benchmark_comp: ABBenchmarkComparison | None = None
    if include_benchmark:
        benchmark_comp = eval_engine.evaluate_benchmark(
            BatchEvaluationPayload(
                suite_id="sample-suite",
                app_name="ShopAgent Checkout",
                baseline_variant="A",
                candidate_variant="B",
                episodes=episodes_a + episodes_b,
            )
        )

    return report_generator.generate_report(
        episodes=episodes_a,
        app_name="ShopAgent Checkout",
        target_url="https://shop.example.com/checkout",
        benchmark_comparison=benchmark_comp,
    )


def _build_sample_scenario() -> tuple[
    list[SandboxEpisodeContract], list[SandboxEpisodeContract]
]:
    """Builds realistic sample episode trajectories for Variant A and Variant B."""
    task = TaskDefinition(
        task_id="task_checkout_01",
        name="Checkout cart with coupon SAVE20",
        instruction="Apply coupon code SAVE20, enter shipping, and place order.",
        start_url="https://shop.example.com/checkout",
        target_goal_predicate={"order_confirmed": True},
        max_allowed_steps=15,
        timeout_seconds=90,
    )

    # Elements for Variant A (Baseline: lacks accessible names, wrappers, icons)
    btn_coupon_a = ElementAffordance(
        element_id="elem_coupon",
        tag_name="button",
        role=None,
        accessible_name=None,
        css_selector="div.cart-wrap > div.box > button.btn-apply",
        bounding_box=BoundingBox(x=100.0, y=250.0, width=80.0, height=36.0),
        is_interactive=True,
        is_visible=True,
    )
    input_coupon_a = ElementAffordance(
        element_id="elem_input_code",
        tag_name="input",
        role="textbox",
        accessible_name=None,
        css_selector="div.cart-wrap > div.box > input.code",
        bounding_box=BoundingBox(x=100.0, y=200.0, width=200.0, height=40.0),
        is_interactive=True,
        is_visible=True,
    )
    btn_submit_a = ElementAffordance(
        element_id="elem_submit",
        tag_name="button",
        role=None,
        accessible_name=None,
        css_selector="div.footer-wrap > div > button.action-btn",
        bounding_box=BoundingBox(x=100.0, y=400.0, width=150.0, height=45.0),
        is_interactive=True,
        is_visible=True,
    )

    # Variant A Episodes: 3 models with friction
    models = [
        ModelFamily.GEMINI_2_5_FLASH.value,
        ModelFamily.CLAUDE_3_7_SONNET.value,
        ModelFamily.GPT_4O.value,
    ]
    episodes_a: list[SandboxEpisodeContract] = []

    for idx, model in enumerate(models):
        success = idx != 0  # Gemini failed due to ambiguous coupon button in Variant A
        step1 = StepTelemetry(
            step_index=0,
            timestamp_start=datetime.now(UTC),
            timestamp_end=datetime.now(UTC),
            duration_ms=1800.0,
            observation_before=AgentObservation(
                step_index=0,
                url="https://shop.example.com/checkout",
                page_title="Checkout",
                accessibility_tree_snippet="<AXTree: 3 unlabeled buttons>",
                dom_token_count=18500,
                axtree_token_count=3200,
                interactive_elements_count=3,
                interactive_elements=[btn_coupon_a, input_coupon_a, btn_submit_a],
            ),
            action_taken=AgentAction(
                step_index=0,
                action_type=ActionType.TYPE_TEXT,
                target_selector=input_coupon_a.css_selector,
                input_value="SAVE20",
                reasoning="Entering promo code into unlabelled input field.",
            ),
            action_succeeded=True,
            state_changed=True,
            friction_detected=[FrictionType.AMBIGUOUS_AFFORDANCE],
            prompt_tokens=4200,
            completion_tokens=150,
            inference_cost_usd=0.0035,
            inference_latency_ms=1200.0,
        )
        step2 = StepTelemetry(
            step_index=1,
            timestamp_start=datetime.now(UTC),
            timestamp_end=datetime.now(UTC),
            duration_ms=2100.0,
            observation_before=AgentObservation(
                step_index=1,
                url="https://shop.example.com/checkout",
                page_title="Checkout",
                accessibility_tree_snippet="<AXTree: code entered, no aria-live>",
                dom_token_count=18500,
                axtree_token_count=3200,
                interactive_elements_count=3,
                interactive_elements=[btn_coupon_a, input_coupon_a, btn_submit_a],
            ),
            action_taken=AgentAction(
                step_index=1,
                action_type=ActionType.CLICK,
                target_selector=btn_coupon_a.css_selector,
                target_coordinates={"x": 140.0, "y": 268.0},
                reasoning="Clicking apply promo code button.",
            ),
            action_succeeded=True,
            state_changed=False,
            friction_detected=[
                FrictionType.UNRESPONSIVE_STATE,
                FrictionType.DOM_TOKEN_OVERFLOW,
            ],
            prompt_tokens=4300,
            completion_tokens=120,
            inference_cost_usd=0.0036,
            inference_latency_ms=1300.0,
        )
        step3 = StepTelemetry(
            step_index=2,
            timestamp_start=datetime.now(UTC),
            timestamp_end=datetime.now(UTC),
            duration_ms=1900.0,
            observation_before=AgentObservation(
                step_index=2,
                url="https://shop.example.com/checkout",
                page_title="Checkout",
                accessibility_tree_snippet="<AXTree: 3 unlabeled buttons>",
                dom_token_count=18500,
                axtree_token_count=3200,
                interactive_elements_count=3,
                interactive_elements=[btn_coupon_a, input_coupon_a, btn_submit_a],
            ),
            action_taken=AgentAction(
                step_index=2,
                action_type=ActionType.CLICK,
                target_selector=btn_submit_a.css_selector,
                target_coordinates={"x": 175.0, "y": 422.0},
                reasoning="Placing order.",
            ),
            action_succeeded=True,
            state_changed=True,
            friction_detected=[],
            prompt_tokens=4400,
            completion_tokens=90,
            inference_cost_usd=0.0034,
            inference_latency_ms=1100.0,
        )

        steps = [step1, step2, step3] if success else [step1, step2]
        episodes_a.append(
            SandboxEpisodeContract(
                episode_id=f"ep_a_{idx+1}",
                session_id=f"sess_a_{idx+1}",
                sandbox_id=f"sb_a_{idx+1}",
                variant_id="A",
                app_version_hash="v1_baseline_dom",
                task=task,
                agent_model=model,
                terminal_status=(
                    TerminalStatus.SUCCESS
                    if success
                    else TerminalStatus.FAILED_MAX_STEPS_EXCEEDED
                ),
                goal_completion_score=1.0 if success else 0.4,
                total_steps=len(steps),
                total_wall_clock_ms=sum(s.duration_ms for s in steps),
                total_prompt_tokens=sum(s.prompt_tokens for s in steps),
                total_completion_tokens=sum(s.completion_tokens for s in steps),
                total_cost_usd=round(sum(s.inference_cost_usd for s in steps), 4),
                total_friction_events=sum(len(s.friction_detected) for s in steps),
                friction_breakdown={
                    FrictionType.AMBIGUOUS_AFFORDANCE: 1,
                    FrictionType.UNRESPONSIVE_STATE: 1,
                    FrictionType.DOM_TOKEN_OVERFLOW: 1,
                },
                steps=steps,
            )
        )

    # Variant B: Candidate Agent-Native DOM
    btn_coupon_b = ElementAffordance(
        element_id="btn_apply_coupon",
        tag_name="button",
        role="button",
        accessible_name="Apply Coupon Code",
        css_selector="[data-agent-id='btn-apply-coupon']",
        data_agent_id="btn-apply-coupon",
        data_agent_action="apply-coupon",
        has_aria_label=True,
        bounding_box=BoundingBox(x=100.0, y=250.0, width=80.0, height=36.0),
        is_interactive=True,
        is_visible=True,
    )
    input_coupon_b = ElementAffordance(
        element_id="input_coupon_code",
        tag_name="input",
        role="textbox",
        accessible_name="Coupon Code",
        css_selector="[data-agent-id='input-coupon-code']",
        data_agent_id="input-coupon-code",
        has_aria_label=True,
        bounding_box=BoundingBox(x=100.0, y=200.0, width=200.0, height=40.0),
        is_interactive=True,
        is_visible=True,
    )
    btn_submit_b = ElementAffordance(
        element_id="btn_place_order",
        tag_name="button",
        role="button",
        accessible_name="Place Order Now",
        css_selector="[data-agent-id='btn-place-order']",
        data_agent_id="btn-place-order",
        data_agent_action="submit-order",
        has_aria_label=True,
        bounding_box=BoundingBox(x=100.0, y=400.0, width=150.0, height=45.0),
        is_interactive=True,
        is_visible=True,
    )

    episodes_b: list[SandboxEpisodeContract] = []
    for idx, model in enumerate(models):
        b_step1 = StepTelemetry(
            step_index=0,
            timestamp_start=datetime.now(UTC),
            timestamp_end=datetime.now(UTC),
            duration_ms=650.0,
            observation_before=AgentObservation(
                step_index=0,
                url="https://shop.example.com/checkout",
                page_title="Checkout",
                accessibility_tree_snippet="<AXTree: lean agent-native layout>",
                dom_token_count=3200,
                axtree_token_count=2100,
                interactive_elements_count=3,
                interactive_elements=[btn_coupon_b, input_coupon_b, btn_submit_b],
            ),
            action_taken=AgentAction(
                step_index=0,
                action_type=ActionType.TYPE_TEXT,
                target_selector=input_coupon_b.css_selector,
                target_element_id=input_coupon_b.data_agent_id,
                input_value="SAVE20",
                reasoning="Entering coupon code into accessible field.",
            ),
            action_succeeded=True,
            state_changed=True,
            friction_detected=[],
            prompt_tokens=950,
            completion_tokens=40,
            inference_cost_usd=0.0006,
            inference_latency_ms=450.0,
        )
        b_step2 = StepTelemetry(
            step_index=1,
            timestamp_start=datetime.now(UTC),
            timestamp_end=datetime.now(UTC),
            duration_ms=700.0,
            observation_before=AgentObservation(
                step_index=1,
                url="https://shop.example.com/checkout",
                page_title="Checkout",
                accessibility_tree_snippet="<AXTree: live discount applied>",
                dom_token_count=3200,
                axtree_token_count=2100,
                interactive_elements_count=3,
                interactive_elements=[btn_coupon_b, input_coupon_b, btn_submit_b],
            ),
            action_taken=AgentAction(
                step_index=1,
                action_type=ActionType.CLICK,
                target_selector=btn_submit_b.css_selector,
                target_element_id=btn_submit_b.data_agent_id,
                target_coordinates={"x": 175.0, "y": 422.0},
                reasoning="Placing order with verified discount applied.",
            ),
            action_succeeded=True,
            state_changed=True,
            friction_detected=[],
            prompt_tokens=980,
            completion_tokens=35,
            inference_cost_usd=0.0006,
            inference_latency_ms=480.0,
        )
        b_steps = [b_step1, b_step2]
        episodes_b.append(
            SandboxEpisodeContract(
                episode_id=f"ep_b_{idx+1}",
                session_id=f"sess_b_{idx+1}",
                sandbox_id=f"sb_b_{idx+1}",
                variant_id="B",
                app_version_hash="v2_agent_native_dom",
                task=task,
                agent_model=model,
                terminal_status=TerminalStatus.SUCCESS,
                goal_completion_score=1.0,
                total_steps=len(b_steps),
                total_wall_clock_ms=sum(s.duration_ms for s in b_steps),
                total_prompt_tokens=sum(s.prompt_tokens for s in b_steps),
                total_completion_tokens=sum(s.completion_tokens for s in b_steps),
                total_cost_usd=round(sum(s.inference_cost_usd for s in b_steps), 4),
                total_friction_events=0,
                friction_breakdown={},
                steps=b_steps,
            )
        )

    return episodes_a, episodes_b
