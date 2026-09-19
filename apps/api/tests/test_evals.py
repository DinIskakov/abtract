"""Tests for Abtract Evals Metrics and Scoring Engine."""

from app.evals.engine import eval_engine
from app.evals.metrics import (
    RatingBand,
    compare_variants,
    compute_agent_readiness_score,
    compute_point_in_box_iou,
    compute_two_proportion_z_test,
    evaluate_a2a_metrics,
    normal_cdf,
)
from app.schemas.contracts import (
    ActionType,
    AgentAction,
    AgentObservation,
    BatchEvaluationPayload,
    BoundingBox,
    ElementAffordance,
    SandboxEpisodeContract,
    StepTelemetry,
    TaskDefinition,
    TerminalStatus,
)


def test_normal_cdf_and_z_test() -> None:
    # Test normal CDF symmetry
    assert abs(normal_cdf(0.0) - 0.5) < 1e-6
    assert normal_cdf(1.96) > 0.97
    assert normal_cdf(-1.96) < 0.03

    # Test two-proportion z-test with obvious difference (60/100 vs 95/100)
    z, p = compute_two_proportion_z_test(60, 100, 95, 100)
    assert z > 0
    assert p < 0.001

    # Test identical proportions
    z_eq, p_eq = compute_two_proportion_z_test(50, 100, 50, 100)
    assert abs(z_eq) < 1e-6
    assert abs(p_eq - 1.0) < 1e-6


def test_point_in_box_iou() -> None:
    box = BoundingBox(x=100.0, y=100.0, width=50.0, height=50.0)
    # Direct hit inside center of box
    iou_inside = compute_point_in_box_iou({"x": 125.0, "y": 125.0}, box)
    assert iou_inside > 0.0

    # Point far outside
    iou_outside = compute_point_in_box_iou({"x": 500.0, "y": 500.0}, box)
    assert iou_outside == 0.0


def test_compute_agent_readiness_score_bands() -> None:
    # Perfect scenario -> Agent-Native (>= 90)
    ars_native = compute_agent_readiness_score(
        tcr=1.0,
        sai=1.0,
        dte=0.8,
        friction_frequency=0.0,
        cross_model_robustness=1.0,
    )
    assert ars_native.score >= 90.0
    assert ars_native.rating_band == RatingBand.AGENT_NATIVE

    # High but imperfect -> Agent-Ready (70-89)
    ars_ready = compute_agent_readiness_score(
        tcr=0.85,
        sai=0.85,
        dte=0.5,
        friction_frequency=1.0,
        cross_model_robustness=0.85,
    )
    assert 70.0 <= ars_ready.score < 90.0
    assert ars_ready.rating_band == RatingBand.AGENT_READY

    # Fragile -> 50-69
    ars_fragile = compute_agent_readiness_score(
        tcr=0.60,
        sai=0.50,
        dte=0.3,
        friction_frequency=2.5,
        cross_model_robustness=0.60,
    )
    assert 50.0 <= ars_fragile.score < 70.0
    assert ars_fragile.rating_band == RatingBand.AGENT_FRAGILE

    # Hostile -> < 50
    ars_hostile = compute_agent_readiness_score(
        tcr=0.20,
        sai=0.20,
        dte=0.1,
        friction_frequency=4.5,
        cross_model_robustness=0.30,
    )
    assert ars_hostile.score < 50.0
    assert ars_hostile.rating_band == RatingBand.AGENT_HOSTILE


def test_evaluate_a2a_metrics_calculation() -> None:
    box = BoundingBox(x=0.0, y=0.0, width=50.0, height=20.0)
    elem_accessible = ElementAffordance(
        element_id="btn-1",
        tag_name="button",
        role="button",
        accessible_name="Submit",
        css_selector="button.submit",
        bounding_box=box,
    )
    elem_unlabeled = ElementAffordance(
        element_id="btn-2",
        tag_name="button",
        role=None,
        accessible_name=None,
        css_selector="button.icon",
        bounding_box=box,
    )

    obs = AgentObservation(
        step_index=0,
        url="https://example.com",
        dom_token_count=1000,
        axtree_token_count=500,
        interactive_elements=[elem_accessible, elem_unlabeled],
        active_error_messages=["Invalid email"],
    )

    # Step 1: Encounter error, action succeeds, state changes
    step1 = StepTelemetry(
        step_index=0,
        duration_ms=200.0,
        observation_before=obs,
        action_taken=AgentAction(
            step_index=0,
            action_type=ActionType.CLICK,
            target_selector="button.submit",
            target_coordinates={"x": 25.0, "y": 10.0},
        ),
        action_succeeded=True,
        state_changed=True,
        friction_detected=[],
    )

    # Step 2: Error cleared in next step (recovered!)
    obs_recovered = AgentObservation(
        step_index=1,
        url="https://example.com",
        dom_token_count=1000,
        axtree_token_count=500,
        interactive_elements=[elem_accessible],
        active_error_messages=[],
    )
    step2 = StepTelemetry(
        step_index=1,
        duration_ms=100.0,
        observation_before=obs_recovered,
        action_taken=AgentAction(step_index=1, action_type=ActionType.TERMINATE),
        action_succeeded=True,
        state_changed=True,
    )

    task = TaskDefinition(
        task_id="t1", name="Task", instruction="Run", start_url="https://example.com"
    )
    episode = SandboxEpisodeContract(
        episode_id="ep1",
        session_id="s1",
        sandbox_id="sb1",
        variant_id="A",
        app_version_hash="hash1",
        task=task,
        agent_model="gemini-2.5-flash",
        steps=[step1, step2],
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=2,
        total_wall_clock_ms=300.0,
        total_cost_usd=0.002,
        total_friction_events=0,
    )

    metrics = evaluate_a2a_metrics([episode])
    # 3 total elements analyzed across steps: [elem_accessible, elem_unlabeled] + [elem]
    # 2 out of 3 have accessible name and role -> 2/3 = 0.6667
    assert metrics.semantic_affordance_index == 0.6667
    # DTE: 1000 axtree / 2000 raw DOM = 0.50
    assert metrics.dom_token_efficiency == 0.5
    # STD: both actions succeeded and state_changed=True -> 1.0
    assert metrics.state_transition_determinism == 1.0
    # Error recoverability: 1 error encountered and recovered -> 1.0
    assert metrics.error_recoverability_score == 1.0


def test_ab_comparative_benchmark() -> None:
    task = TaskDefinition(
        task_id="t1", name="Task", instruction="Run", start_url="https://example.com"
    )

    # Variant A: 1 success, 1 failure (50% TCR), cost $0.05
    ep_a1 = SandboxEpisodeContract(
        episode_id="a1",
        session_id="s_a1",
        sandbox_id="sb_a1",
        variant_id="A",
        app_version_hash="v1",
        task=task,
        agent_model="gemini-2.5-flash",
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=10,
        total_wall_clock_ms=20000.0,
        total_cost_usd=0.05,
        total_friction_events=3,
        steps=[],
    )
    ep_a2 = SandboxEpisodeContract(
        episode_id="a2",
        session_id="s_a2",
        sandbox_id="sb_a2",
        variant_id="A",
        app_version_hash="v1",
        task=task,
        agent_model="gpt-4o",
        terminal_status=TerminalStatus.FAILED_MAX_STEPS_EXCEEDED,
        goal_completion_score=0.3,
        total_steps=25,
        total_wall_clock_ms=50000.0,
        total_cost_usd=0.08,
        total_friction_events=6,
        steps=[],
    )

    # Variant B: 2 successes (100% TCR), avg steps 4, cost $0.015
    ep_b1 = SandboxEpisodeContract(
        episode_id="b1",
        session_id="s_b1",
        sandbox_id="sb_b1",
        variant_id="B",
        app_version_hash="v2",
        task=task,
        agent_model="gemini-2.5-flash",
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=4,
        total_wall_clock_ms=4000.0,
        total_cost_usd=0.012,
        total_friction_events=0,
        steps=[],
    )
    ep_b2 = SandboxEpisodeContract(
        episode_id="b2",
        session_id="s_b2",
        sandbox_id="sb_b2",
        variant_id="B",
        app_version_hash="v2",
        task=task,
        agent_model="gpt-4o",
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=4,
        total_wall_clock_ms=4500.0,
        total_cost_usd=0.018,
        total_friction_events=0,
        steps=[],
    )

    comp = compare_variants(
        variant_a_episodes=[ep_a1, ep_a2],
        variant_b_episodes=[ep_b1, ep_b2],
    )

    assert comp.baseline.task_completion_rate == 0.5
    assert comp.candidate.task_completion_rate == 1.0
    assert comp.delta_tcr == 0.5
    assert comp.step_efficiency_ratio < 1.0
    assert comp.cost_reduction_pct > 50.0
    assert comp.delta_ars > 0.0
    assert "WIN" in comp.summary_verdict or "PROGRESS" in comp.summary_verdict


def test_eval_engine_batch_evaluation() -> None:
    task = TaskDefinition(
        task_id="t1", name="Task", instruction="Run", start_url="https://example.com"
    )
    ep_a = SandboxEpisodeContract(
        episode_id="a1",
        session_id="s1",
        sandbox_id="sb1",
        variant_id="A",
        app_version_hash="v1",
        task=task,
        agent_model="gemini-2.5-flash",
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=5,
        total_wall_clock_ms=5000.0,
        total_cost_usd=0.01,
        total_friction_events=0,
    )
    ep_b = SandboxEpisodeContract(
        episode_id="b1",
        session_id="s2",
        sandbox_id="sb2",
        variant_id="B",
        app_version_hash="v2",
        task=task,
        agent_model="gemini-2.5-flash",
        terminal_status=TerminalStatus.SUCCESS,
        goal_completion_score=1.0,
        total_steps=3,
        total_wall_clock_ms=3000.0,
        total_cost_usd=0.005,
        total_friction_events=0,
    )

    payload = BatchEvaluationPayload(
        suite_id="suite_test",
        app_name="TestApp",
        baseline_variant="A",
        candidate_variant="B",
        episodes=[ep_a, ep_b],
    )
    benchmark = eval_engine.evaluate_benchmark(payload)
    assert benchmark.baseline.variant_id == "A"
    assert benchmark.candidate.variant_id == "B"
    assert benchmark.candidate.avg_steps == 3.0
    assert benchmark.baseline.avg_steps == 5.0
