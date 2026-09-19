"""Abtract Evals Metrics (Layers 1, 2, and 3).

Calculates Agent Usability & Accessibility (A2A), A/B Comparative Benchmarking,
and the composite Agent-Readiness Score (ARS).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.contracts import (
    BoundingBox,
    ElementAffordance,
    FrictionType,
    SandboxEpisodeContract,
    TerminalStatus,
)


class RatingBand(StrEnum):
    AGENT_NATIVE = "Agent-Native"  # 90-100
    AGENT_READY = "Agent-Ready"  # 70-89
    AGENT_FRAGILE = "Agent-Fragile"  # 50-69
    AGENT_HOSTILE = "Agent-Hostile"  # < 50


class A2AEvalMetrics(BaseModel):
    """Layer 1: Agent Usability & Accessibility Evaluation Metrics."""

    model_config = ConfigDict(extra="ignore")

    semantic_affordance_index: float = Field(
        description="SAI (0-1): Accessible name and role ratio",
        ge=0.0,
        le=1.0,
    )
    dom_token_efficiency: float = Field(
        description="DTE (0-1): AXTree tokens / raw DOM tokens",
        ge=0.0,
        le=1.0,
    )
    affordance_ambiguity_rate: float = Field(
        description="AAR (0-1): Ratio of ambiguous affordances",
        ge=0.0,
        le=1.0,
    )
    visual_groundability_score: float = Field(
        description="VGS (0-1): Mean IoU of gaze/click to target bounds",
        ge=0.0,
        le=1.0,
    )
    state_transition_determinism: float = Field(
        description="STD (0-1): % actions triggering state updates",
        ge=0.0,
        le=1.0,
    )
    error_recoverability_score: float = Field(
        description="ERS (0-1): Recovery rate from validation errors",
        ge=0.0,
        le=1.0,
    )

    total_interactive_elements_analyzed: int = 0
    total_actions_evaluated: int = 0
    total_observations_analyzed: int = 0


class AgentReadinessScore(BaseModel):
    """Layer 3: Composite Agent-Readiness Score (0-100)."""

    model_config = ConfigDict(extra="ignore")

    score: float = Field(ge=0.0, le=100.0, description="Composite score (0-100)")
    rating_band: RatingBand
    task_completion_weight: float = 0.35
    semantic_affordance_weight: float = 0.20
    dom_efficiency_weight: float = 0.15
    friction_mitigation_weight: float = 0.15
    cross_model_robustness_weight: float = 0.15

    # Component contributions (each out of 100)
    task_completion_component: float
    semantic_affordance_component: float
    dom_efficiency_component: float
    friction_mitigation_component: float
    cross_model_robustness_component: float


class ModelPerformance(BaseModel):
    """Performance breakdown for a single model family."""

    model_config = ConfigDict(extra="ignore")

    model_name: str
    episode_count: int
    success_rate: float
    avg_steps: float
    avg_cost_usd: float
    avg_latency_ms: float
    friction_events_per_episode: float


class VariantMetrics(BaseModel):
    """Aggregated metrics for a single variant (e.g. A or B)."""

    model_config = ConfigDict(extra="ignore")

    variant_id: str
    total_episodes: int
    successful_episodes: int
    task_completion_rate: float = Field(ge=0.0, le=1.0)
    avg_steps: float
    avg_wall_clock_ms: float
    avg_cost_usd: float
    cost_per_successful_task_usd: float
    total_friction_events: int
    friction_frequency: float = Field(description="Friction events per episode")
    friction_breakdown: dict[FrictionType, int] = Field(default_factory=dict)
    a2a_metrics: A2AEvalMetrics
    agent_readiness_score: AgentReadinessScore
    model_performances: list[ModelPerformance] = Field(default_factory=list)
    cross_model_robustness: float = Field(
        ge=0.0,
        le=1.0,
        description="Cross-model consistency (1.0 = identical performance)",
    )


class ABBenchmarkComparison(BaseModel):
    """Layer 2: A/B Comparative Benchmarking between Variant A and Variant B."""

    model_config = ConfigDict(extra="ignore")

    baseline: VariantMetrics
    candidate: VariantMetrics

    # Deltas (Candidate - Baseline)
    delta_tcr: float = Field(description="Task Completion Rate Delta (B - A)")
    tcr_relative_change_pct: float
    p_value: float = Field(description="Two-proportion Z-test p-value")
    statistically_significant: bool = Field(description="True if p_value < 0.05")

    delta_cost_per_task_usd: float = Field(description="Cost Per Task Delta in USD")
    cost_reduction_pct: float = Field(description="Percentage cost reduction")

    step_efficiency_ratio: float = Field(
        description="SER = AvgSteps_B / AvgSteps_A (< 1.0 is more efficient)"
    )
    step_reduction_pct: float

    latency_reduction_pct: float
    friction_reduction_pct: float
    delta_ars: float = Field(description="Change in Agent-Readiness Score")
    summary_verdict: str


# ============================================================================
# Math & Statistical Helpers
# ============================================================================


def normal_cdf(z: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def compute_two_proportion_z_test(
    successes_a: int, total_a: int, successes_b: int, total_b: int
) -> tuple[float, float]:
    """Computes two-proportion pooled Z-test.

    Returns (z_score, two_tailed_p_value).
    """
    if total_a <= 0 or total_b <= 0:
        return 0.0, 1.0

    p_a = successes_a / total_a
    p_b = successes_b / total_b

    p_pool = (successes_a + successes_b) / (total_a + total_b)
    if p_pool == 0.0 or p_pool == 1.0:
        return 0.0, 1.0

    standard_error = math.sqrt(
        p_pool * (1.0 - p_pool) * (1.0 / total_a + 1.0 / total_b)
    )
    if standard_error == 0.0:
        return 0.0, 1.0

    z_score = (p_b - p_a) / standard_error
    p_value = 2.0 * (1.0 - normal_cdf(abs(z_score)))
    return z_score, max(0.0, min(1.0, p_value))


def compute_point_in_box_iou(point: dict[str, float], box: BoundingBox) -> float:
    """Computes simulated IoU between a 24x24px click touch-target and box."""
    px, py = point.get("x", 0.0), point.get("y", 0.0)
    touch_size = 24.0
    half_touch = touch_size / 2.0

    c_left = px - half_touch
    c_top = py - half_touch
    c_right = px + half_touch
    c_bottom = py + half_touch

    b_left = box.x
    b_top = box.y
    b_right = box.x + box.width
    b_bottom = box.y + box.height

    inter_left = max(c_left, b_left)
    inter_top = max(c_top, b_top)
    inter_right = min(c_right, b_right)
    inter_bottom = min(c_bottom, b_bottom)

    if inter_right <= inter_left or inter_bottom <= inter_top:
        if b_left <= px <= b_right and b_top <= py <= b_bottom:
            return 0.75
        return 0.0

    inter_area = (inter_right - inter_left) * (inter_bottom - inter_top)
    touch_area = touch_size * touch_size
    box_area = max(1.0, box.width * box.height)
    union_area = touch_area + box_area - inter_area

    return max(0.0, min(1.0, inter_area / union_area))


# ============================================================================
# Layer 1: A2A Usability Metric Evaluators
# ============================================================================


def evaluate_a2a_metrics(
    episodes: Sequence[SandboxEpisodeContract],
) -> A2AEvalMetrics:
    """Computes Layer 1 Agent Usability & Accessibility metrics."""
    all_interactive_elements: list[ElementAffordance] = []
    total_dom_tokens = 0
    total_axtree_tokens = 0
    observation_count = 0

    ious: list[float] = []
    state_change_success_count = 0
    total_successful_actions = 0

    error_encounters = 0
    error_recoveries = 0

    for episode in episodes:
        prev_had_errors = False
        for step in episode.steps:
            obs = step.observation_before
            observation_count += 1
            total_dom_tokens += obs.dom_token_count
            total_axtree_tokens += (
                obs.axtree_token_count
                if obs.axtree_token_count is not None
                else int(obs.dom_token_count * 0.35)
            )
            all_interactive_elements.extend(obs.interactive_elements)

            # Error recoverability tracking
            has_errors_now = len(obs.active_error_messages) > 0
            if prev_had_errors:
                error_encounters += 1
                if not has_errors_now and step.action_succeeded:
                    error_recoveries += 1
            prev_had_errors = has_errors_now

            # State transition determinism
            if step.action_succeeded:
                total_successful_actions += 1
                if step.state_changed:
                    state_change_success_count += 1

            # Visual groundability
            coords = step.action_taken.target_coordinates
            if coords and obs.interactive_elements:
                target_sel = step.action_taken.target_selector
                target_id = step.action_taken.target_element_id
                matched: ElementAffordance | None = None
                for elem in obs.interactive_elements:
                    if (target_id and elem.element_id == target_id) or (
                        target_sel and elem.css_selector == target_sel
                    ):
                        matched = elem
                        break
                if matched:
                    ious.append(compute_point_in_box_iou(coords, matched.bounding_box))
                else:
                    ious.append(0.0)

    # 1. Semantic Affordance Index (SAI)
    total_interactive = len(all_interactive_elements)
    if total_interactive > 0:
        valid_semantic = sum(
            1
            for elem in all_interactive_elements
            if elem.accessible_name
            and elem.accessible_name.strip()
            and elem.role
            and elem.role.strip()
        )
        sai = valid_semantic / total_interactive
    else:
        sai = 1.0

    # 2. DOM Token Efficiency (DTE)
    if total_dom_tokens > 0:
        dte = min(1.0, max(0.0, total_axtree_tokens / total_dom_tokens))
    else:
        dte = 0.50

    # 3. Affordance Ambiguity Rate (AAR)
    if total_interactive > 0:
        names = [
            elem.accessible_name.strip().lower()
            for elem in all_interactive_elements
            if elem.accessible_name and elem.accessible_name.strip()
        ]
        name_counts = Counter(names)
        ambiguous_generic = {
            "click",
            "click here",
            "button",
            "link",
            "submit",
            "more",
            "view",
            "edit",
            "x",
        }
        ambiguous_count = sum(
            1
            for elem in all_interactive_elements
            if (not elem.accessible_name or not elem.accessible_name.strip())
            or (
                elem.accessible_name.strip().lower() in ambiguous_generic
                and name_counts[elem.accessible_name.strip().lower()] > 1
            )
        )
        aar = ambiguous_count / total_interactive
    else:
        aar = 0.0

    # 4. Visual Groundability Score (VGS)
    vgs = (sum(ious) / len(ious)) if ious else 0.95

    # 5. State Transition Determinism (STD)
    std = (
        (state_change_success_count / total_successful_actions)
        if total_successful_actions > 0
        else 1.0
    )

    # 6. Error Recoverability Score (ERS)
    ers = (error_recoveries / error_encounters) if error_encounters > 0 else 1.0

    return A2AEvalMetrics(
        semantic_affordance_index=round(sai, 4),
        dom_token_efficiency=round(dte, 4),
        affordance_ambiguity_rate=round(aar, 4),
        visual_groundability_score=round(vgs, 4),
        state_transition_determinism=round(std, 4),
        error_recoverability_score=round(ers, 4),
        total_interactive_elements_analyzed=total_interactive,
        total_actions_evaluated=total_successful_actions,
        total_observations_analyzed=observation_count,
    )


# ============================================================================
# Layer 3: Composite Agent-Readiness Score (ARS)
# ============================================================================


def compute_agent_readiness_score(
    tcr: float,
    sai: float,
    dte: float,
    friction_frequency: float,
    cross_model_robustness: float,
) -> AgentReadinessScore:
    """Computes the composite ARS (0-100) using the weighted multi-factor formula."""
    tcr_comp = min(1.0, max(0.0, tcr)) * 100.0
    sai_comp = min(1.0, max(0.0, sai)) * 100.0
    dte_comp = min(1.0, max(0.0, dte)) * 100.0

    norm_friction = min(1.0, max(0.0, friction_frequency / 5.0))
    friction_comp = (1.0 - norm_friction) * 100.0
    cmr_comp = min(1.0, max(0.0, cross_model_robustness)) * 100.0

    w_tcr = 0.35
    w_sai = 0.20
    w_dte = 0.15
    w_fric = 0.15
    w_cmr = 0.15

    total_score = (
        w_tcr * tcr_comp
        + w_sai * sai_comp
        + w_dte * dte_comp
        + w_fric * friction_comp
        + w_cmr * cmr_comp
    )
    score_clamped = round(min(100.0, max(0.0, total_score)), 2)

    if score_clamped >= 90.0:
        band = RatingBand.AGENT_NATIVE
    elif score_clamped >= 70.0:
        band = RatingBand.AGENT_READY
    elif score_clamped >= 50.0:
        band = RatingBand.AGENT_FRAGILE
    else:
        band = RatingBand.AGENT_HOSTILE

    return AgentReadinessScore(
        score=score_clamped,
        rating_band=band,
        task_completion_weight=w_tcr,
        semantic_affordance_weight=w_sai,
        dom_efficiency_weight=w_dte,
        friction_mitigation_weight=w_fric,
        cross_model_robustness_weight=w_cmr,
        task_completion_component=round(tcr_comp, 2),
        semantic_affordance_component=round(sai_comp, 2),
        dom_efficiency_component=round(dte_comp, 2),
        friction_mitigation_component=round(friction_comp, 2),
        cross_model_robustness_component=round(cmr_comp, 2),
    )


# ============================================================================
# Aggregators & A/B Benchmarking
# ============================================================================


def aggregate_variant_metrics(
    variant_id: str, episodes: Sequence[SandboxEpisodeContract]
) -> VariantMetrics:
    """Aggregates telemetry and evaluates all metric layers for a single variant."""
    total_episodes = len(episodes)
    if total_episodes == 0:
        a2a_empty = A2AEvalMetrics(
            semantic_affordance_index=0.0,
            dom_token_efficiency=0.0,
            affordance_ambiguity_rate=0.0,
            visual_groundability_score=0.0,
            state_transition_determinism=0.0,
            error_recoverability_score=0.0,
        )
        empty_ars = compute_agent_readiness_score(0.0, 0.0, 0.0, 0.0, 1.0)
        return VariantMetrics(
            variant_id=variant_id,
            total_episodes=0,
            successful_episodes=0,
            task_completion_rate=0.0,
            avg_steps=0.0,
            avg_wall_clock_ms=0.0,
            avg_cost_usd=0.0,
            cost_per_successful_task_usd=0.0,
            total_friction_events=0,
            friction_frequency=0.0,
            friction_breakdown={},
            a2a_metrics=a2a_empty,
            agent_readiness_score=empty_ars,
            model_performances=[],
            cross_model_robustness=1.0,
        )

    successful = sum(
        1 for ep in episodes if ep.terminal_status == TerminalStatus.SUCCESS
    )
    tcr = successful / total_episodes

    total_steps = sum(ep.total_steps for ep in episodes)
    total_wall_clock = sum(ep.total_wall_clock_ms for ep in episodes)
    total_cost = sum(ep.total_cost_usd for ep in episodes)
    total_friction = sum(ep.total_friction_events for ep in episodes)

    friction_counter: Counter[FrictionType] = Counter()
    for ep in episodes:
        for f_type, count in ep.friction_breakdown.items():
            friction_counter[f_type] += count
        for step in ep.steps:
            for f in step.friction_detected:
                if f not in ep.friction_breakdown:
                    friction_counter[f] += 1

    avg_steps = total_steps / total_episodes
    avg_wall_clock_ms = total_wall_clock / total_episodes
    avg_cost = total_cost / total_episodes
    cpt = (total_cost / successful) if successful > 0 else avg_cost * 2.0
    friction_freq = total_friction / total_episodes

    # Per-model breakdown
    by_model: dict[str, list[SandboxEpisodeContract]] = {}
    for ep in episodes:
        by_model.setdefault(ep.agent_model, []).append(ep)

    model_perfs: list[ModelPerformance] = []
    model_success_rates: list[float] = []
    for model_name, m_episodes in by_model.items():
        m_total = len(m_episodes)
        m_success = sum(
            1 for e in m_episodes if e.terminal_status == TerminalStatus.SUCCESS
        )
        m_rate = m_success / m_total
        model_success_rates.append(m_rate)
        m_steps = sum(e.total_steps for e in m_episodes) / m_total
        m_cost = sum(e.total_cost_usd for e in m_episodes) / m_total
        m_lat = sum(e.total_wall_clock_ms for e in m_episodes) / m_total
        m_fric = sum(e.total_friction_events for e in m_episodes) / m_total

        model_perfs.append(
            ModelPerformance(
                model_name=model_name,
                episode_count=m_total,
                success_rate=round(m_rate, 4),
                avg_steps=round(m_steps, 2),
                avg_cost_usd=round(m_cost, 4),
                avg_latency_ms=round(m_lat, 2),
                friction_events_per_episode=round(m_fric, 2),
            )
        )

    # Cross model robustness (1.0 - 2 * standard deviation of success rates)
    if len(model_success_rates) > 1:
        mean_rate = sum(model_success_rates) / len(model_success_rates)
        variance = sum((r - mean_rate) ** 2 for r in model_success_rates) / len(
            model_success_rates
        )
        std_dev = math.sqrt(variance)
        cross_model_robustness = max(0.0, min(1.0, 1.0 - 2.0 * std_dev))
    else:
        cross_model_robustness = 1.0

    a2a = evaluate_a2a_metrics(episodes)
    ars = compute_agent_readiness_score(
        tcr=tcr,
        sai=a2a.semantic_affordance_index,
        dte=a2a.dom_token_efficiency,
        friction_frequency=friction_freq,
        cross_model_robustness=cross_model_robustness,
    )

    return VariantMetrics(
        variant_id=variant_id,
        total_episodes=total_episodes,
        successful_episodes=successful,
        task_completion_rate=round(tcr, 4),
        avg_steps=round(avg_steps, 2),
        avg_wall_clock_ms=round(avg_wall_clock_ms, 2),
        avg_cost_usd=round(avg_cost, 4),
        cost_per_successful_task_usd=round(cpt, 4),
        total_friction_events=total_friction,
        friction_frequency=round(friction_freq, 2),
        friction_breakdown=dict(friction_counter),
        a2a_metrics=a2a,
        agent_readiness_score=ars,
        model_performances=model_perfs,
        cross_model_robustness=round(cross_model_robustness, 4),
    )


def compare_variants(
    variant_a_episodes: Sequence[SandboxEpisodeContract],
    variant_b_episodes: Sequence[SandboxEpisodeContract],
    variant_a_id: str = "A",
    variant_b_id: str = "B",
) -> ABBenchmarkComparison:
    """Performs Layer 2 A/B Comparative Benchmarking."""
    metrics_a = aggregate_variant_metrics(variant_a_id, variant_a_episodes)
    metrics_b = aggregate_variant_metrics(variant_b_id, variant_b_episodes)

    # 1. Delta Task Completion Rate & Hypothesis Testing
    delta_tcr = metrics_b.task_completion_rate - metrics_a.task_completion_rate
    tcr_rel = (
        (delta_tcr / metrics_a.task_completion_rate * 100.0)
        if metrics_a.task_completion_rate > 0
        else (100.0 if delta_tcr > 0 else 0.0)
    )

    _, p_value = compute_two_proportion_z_test(
        successes_a=metrics_a.successful_episodes,
        total_a=metrics_a.total_episodes,
        successes_b=metrics_b.successful_episodes,
        total_b=metrics_b.total_episodes,
    )
    stat_sig = p_value < 0.05

    # 2. Cost Per Task Delta & Cost Reduction %
    delta_cpt = (
        metrics_b.cost_per_successful_task_usd
        - metrics_a.cost_per_successful_task_usd
    )
    cost_reduction = (
        (
            (
                metrics_a.cost_per_successful_task_usd
                - metrics_b.cost_per_successful_task_usd
            )
            / metrics_a.cost_per_successful_task_usd
            * 100.0
        )
        if metrics_a.cost_per_successful_task_usd > 0
        else 0.0
    )

    # 3. Step Efficiency Ratio (SER)
    ser = (
        (metrics_b.avg_steps / metrics_a.avg_steps)
        if metrics_a.avg_steps > 0
        else 1.0
    )
    step_reduction = (
        ((metrics_a.avg_steps - metrics_b.avg_steps) / metrics_a.avg_steps * 100.0)
        if metrics_a.avg_steps > 0
        else 0.0
    )

    # 4. Latency & Friction Deltas
    latency_reduction = (
        (
            (metrics_a.avg_wall_clock_ms - metrics_b.avg_wall_clock_ms)
            / metrics_a.avg_wall_clock_ms
            * 100.0
        )
        if metrics_a.avg_wall_clock_ms > 0
        else 0.0
    )
    friction_reduction = (
        (
            (metrics_a.friction_frequency - metrics_b.friction_frequency)
            / metrics_a.friction_frequency
            * 100.0
        )
        if metrics_a.friction_frequency > 0
        else 0.0
    )

    delta_ars = (
        metrics_b.agent_readiness_score.score - metrics_a.agent_readiness_score.score
    )

    # Verdict synthesis
    if delta_ars >= 15.0 and delta_tcr >= 0.10:
        verdict = (
            f"WIN: Variant {variant_b_id} demonstrates decisive superiority "
            f"(+{round(delta_tcr * 100, 1)}% success, "
            f"{round(cost_reduction, 1)}% cost savings, "
            f"+{round(delta_ars, 1)} ARS increase)."
        )
    elif delta_ars > 0:
        verdict = (
            f"PROGRESS: Variant {variant_b_id} improves agent usability "
            f"(+{round(delta_ars, 1)} ARS)."
        )
    else:
        verdict = f"REGRESSION: Variant {variant_b_id} did not outperform baseline."

    return ABBenchmarkComparison(
        baseline=metrics_a,
        candidate=metrics_b,
        delta_tcr=round(delta_tcr, 4),
        tcr_relative_change_pct=round(tcr_rel, 2),
        p_value=round(p_value, 4),
        statistically_significant=stat_sig,
        delta_cost_per_task_usd=round(delta_cpt, 4),
        cost_reduction_pct=round(cost_reduction, 2),
        step_efficiency_ratio=round(ser, 3),
        step_reduction_pct=round(step_reduction, 2),
        latency_reduction_pct=round(latency_reduction, 2),
        friction_reduction_pct=round(friction_reduction, 2),
        delta_ars=round(delta_ars, 2),
        summary_verdict=verdict,
    )
