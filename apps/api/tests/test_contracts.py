"""Tests for Abtract Agent Schema Contracts (Pydantic v2)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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


def test_enums() -> None:
    assert ActionType.CLICK == "click"
    assert ActionType.TERMINATE == "terminate"
    assert FrictionType.MISCLICK == "misclick"
    assert FrictionType.AMBIGUOUS_AFFORDANCE == "ambiguous_affordance"
    assert TerminalStatus.SUCCESS == "success"
    assert TerminalStatus.FAILED_MAX_STEPS_EXCEEDED == "failed_max_steps_exceeded"
    assert ModelFamily.GEMINI_2_5_FLASH == "gemini-2.5-flash"
    assert ModelFamily.CLAUDE_3_7_SONNET == "claude-3-7-sonnet"
    assert ModelFamily.GPT_4O == "gpt-4o"


def test_element_affordance_valid() -> None:
    box = BoundingBox(x=10.0, y=20.0, width=120.0, height=40.0)
    affordance = ElementAffordance(
        element_id="btn-login",
        tag_name="button",
        role="button",
        accessible_name="Log In",
        css_selector="button#login",
        bounding_box=box,
        is_visible=True,
        is_interactive=True,
        data_agent_id="login-btn",
        data_agent_action="submit-login",
        has_aria_label=True,
    )
    assert affordance.element_id == "btn-login"
    assert affordance.bounding_box.width == 120.0
    assert affordance.data_agent_action == "submit-login"


def test_bounding_box_validation() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x=-1.0, y=0.0, width=10.0, height=10.0)


def test_agent_observation_and_action() -> None:
    obs = AgentObservation(
        step_index=0,
        url="https://app.example.com",
        page_title="Dashboard",
        dom_token_count=1200,
        axtree_token_count=450,
        interactive_elements_count=1,
        interactive_elements=[
            ElementAffordance(
                element_id="elem-1",
                tag_name="a",
                role="link",
                accessible_name="Home",
                css_selector="a.home",
                bounding_box=BoundingBox(x=0.0, y=0.0, width=50.0, height=20.0),
            )
        ],
    )
    assert obs.dom_token_count == 1200
    assert obs.axtree_token_count == 450
    assert len(obs.interactive_elements) == 1

    act = AgentAction(
        step_index=0,
        action_type=ActionType.CLICK,
        target_selector="a.home",
        target_coordinates={"x": 25.0, "y": 10.0},
        reasoning="Navigating to home view.",
    )
    assert act.action_type == ActionType.CLICK
    assert act.reasoning == "Navigating to home view."


def test_sandbox_episode_contract_full_cycle() -> None:
    task = TaskDefinition(
        task_id="t1",
        name="Search",
        instruction="Search for product",
        start_url="https://example.com",
    )
    obs = AgentObservation(
        step_index=0,
        url="https://example.com",
        dom_token_count=500,
    )
    act = AgentAction(step_index=0, action_type=ActionType.CLICK)
    step = StepTelemetry(
        step_index=0,
        timestamp_start=datetime.now(UTC),
        timestamp_end=datetime.now(UTC),
        duration_ms=500.0,
        observation_before=obs,
        action_taken=act,
        action_succeeded=True,
        state_changed=True,
        friction_detected=[FrictionType.MISCLICK],
        prompt_tokens=100,
        completion_tokens=20,
        inference_cost_usd=0.001,
    )

    contract = SandboxEpisodeContract(
        episode_id="ep_123",
        session_id="sess_123",
        sandbox_id="sb_123",
        variant_id="A",
        app_version_hash="hash123",
        task=task,
        agent_model="gemini-2.5-flash",
        steps=[step],
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=1,
        total_wall_clock_ms=500.0,
        total_cost_usd=0.001,
        total_friction_events=1,
        friction_breakdown={FrictionType.MISCLICK: 1},
    )

    # Test serialization and deserialization
    data = contract.model_dump()
    reconstituted = SandboxEpisodeContract.model_validate(data)
    assert reconstituted.episode_id == "ep_123"
    assert reconstituted.variant_id == "A"
    assert reconstituted.terminal_status == TerminalStatus.SUCCESS
    assert reconstituted.steps[0].friction_detected == [FrictionType.MISCLICK]


def test_batch_evaluation_payload() -> None:
    payload = BatchEvaluationPayload(
        suite_id="suite_1",
        app_name="TestApp",
        baseline_variant="A",
        candidate_variant="B",
        episodes=[],
    )
    assert payload.suite_id == "suite_1"
    assert payload.baseline_variant == "A"
    assert payload.candidate_variant == "B"
