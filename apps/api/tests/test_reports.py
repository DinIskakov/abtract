"""Tests for Abtract Regeneration Report Models and Generator."""

from app.reports.generator import report_generator
from app.reports.models import DirectiveType
from app.schemas.contracts import (
    ActionType,
    AgentAction,
    AgentObservation,
    BoundingBox,
    ElementAffordance,
    FrictionType,
    SandboxEpisodeContract,
    StepTelemetry,
    TaskDefinition,
    TerminalStatus,
)


def test_regeneration_report_generator_full_pipeline() -> None:
    box = BoundingBox(x=10.0, y=10.0, width=50.0, height=30.0)
    btn_unlabeled = ElementAffordance(
        element_id="btn-cart",
        tag_name="button",
        role=None,
        accessible_name=None,
        css_selector="button.cart-icon",
        bounding_box=box,
    )
    input_unlabeled = ElementAffordance(
        element_id="input-search",
        tag_name="input",
        role="textbox",
        accessible_name=None,
        css_selector="input#search",
        bounding_box=box,
    )

    obs = AgentObservation(
        step_index=0,
        url="https://store.example.com",
        page_title="Store",
        dom_token_count=16000,
        axtree_token_count=1200,
        interactive_elements=[btn_unlabeled, input_unlabeled],
    )

    # Step with friction
    step = StepTelemetry(
        step_index=0,
        duration_ms=800.0,
        observation_before=obs,
        action_taken=AgentAction(
            step_index=0,
            action_type=ActionType.CLICK,
            target_selector="button.cart-icon",
            reasoning="Attempting to open shopping cart.",
        ),
        action_succeeded=True,
        state_changed=False,
        friction_detected=[
            FrictionType.AMBIGUOUS_AFFORDANCE,
            FrictionType.UNRESPONSIVE_STATE,
        ],
    )

    task = TaskDefinition(
        task_id="t1",
        name="Cart Task",
        instruction="Open cart",
        start_url="https://store.example.com",
    )
    episode = SandboxEpisodeContract(
        episode_id="ep_test",
        session_id="s1",
        sandbox_id="sb1",
        variant_id="A",
        app_version_hash="v1",
        task=task,
        agent_model="gemini-2.5-flash",
        steps=[step],
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=1,
        total_wall_clock_ms=800.0,
        total_cost_usd=0.002,
        total_friction_events=2,
    )

    report = report_generator.generate_report(
        episodes=[episode],
        app_name="Store Checkout",
        target_url="https://store.example.com",
    )

    # Verify report structure
    assert report.app_name == "Store Checkout"
    assert report.target_url == "https://store.example.com"
    assert report.variant_evaluated == "A"
    assert report.agent_readiness_score is not None

    # Verify Hotspots
    assert len(report.friction_hotspots) >= 2
    hotspot_types = {h.friction_type for h in report.friction_hotspots}
    assert FrictionType.AMBIGUOUS_AFFORDANCE in hotspot_types
    assert FrictionType.UNRESPONSIVE_STATE in hotspot_types

    # Verify Directives
    assert len(report.transformation_directives) > 0
    directive_types = {d.directive_type for d in report.transformation_directives}
    assert DirectiveType.ADD_ARIA_LABEL in directive_types
    assert DirectiveType.ADD_ARIA_LIVE in directive_types
    assert DirectiveType.ASSOCIATE_FORM_LABEL in directive_types

    # Verify Markdown rendering
    assert (
        "# 🤖 Abtract Agent-Native Regeneration Report: Store Checkout"
        in report.markdown_content
    )
    assert "## 1. Executive Summary" in report.markdown_content
    assert (
        "## 2. Layer 1: Agent Usability & Accessibility (A2A) Evals"
        in report.markdown_content
    )
    assert "## 4. Friction Hotspots Map" in report.markdown_content
    assert (
        "## 5. Step 5 Prescriptive Transformation Directives"
        in report.markdown_content
    )
    assert "Suggested Agent-Native Code Patch" in report.markdown_content
