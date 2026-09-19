"""Abtract Regeneration Report Generator.

Transforms episode telemetry and evaluation metrics into actionable
friction maps, AST transformation directives, and diagnostic reports
tailored for Step 5 (Design Regeneration Engine).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.evals.metrics import (
    A2AEvalMetrics,
    ABBenchmarkComparison,
    VariantMetrics,
    aggregate_variant_metrics,
)
from app.reports.models import (
    AgentNativeReport,
    DirectiveType,
    FrictionHotspot,
    Priority,
    TransformationDirective,
)
from app.schemas.contracts import (
    ElementAffordance,
    FrictionType,
    SandboxEpisodeContract,
)


class RegenerationReportGenerator:
    """Generates agent-native audit reports and transformation directives."""

    def generate_report(
        self,
        episodes: Sequence[SandboxEpisodeContract],
        app_name: str = "Abtract Target App",
        target_url: str = "https://example.com",
        benchmark_comparison: ABBenchmarkComparison | None = None,
    ) -> AgentNativeReport:
        """Analyzes episodes and compiles the full AgentNativeReport."""
        if not episodes:
            raise ValueError("Cannot generate report from empty episodes list")

        variant_id = episodes[0].variant_id
        variant_metrics = aggregate_variant_metrics(variant_id, episodes)
        a2a = variant_metrics.a2a_metrics
        ars = variant_metrics.agent_readiness_score

        # 1. Identify and aggregate Friction Hotspots
        hotspots = self._extract_friction_hotspots(episodes)

        # 2. Extract DOM and interactive elements for directive synthesis
        interactive_catalog = self._collect_interactive_elements(episodes)

        # 3. Generate prescriptive Transformation Directives for Step 5
        directives = self._synthesize_directives(
            hotspots=hotspots,
            catalog=interactive_catalog,
            a2a=a2a,
        )

        # 4. Calculate DOM token reduction target
        if a2a.dom_token_efficiency < 0.35:
            dom_reduction_target = 65.0
        elif a2a.dom_token_efficiency < 0.60:
            dom_reduction_target = 40.0
        else:
            dom_reduction_target = 15.0

        # 5. Executive summary text
        tcr_pct = round(variant_metrics.task_completion_rate * 100, 1)
        exec_summary = (
            f"{app_name} scored {ars.score}/100 ({ars.rating_band.value}) on the "
            f"Abtract Agent-Readiness Scale. Task completion rate was "
            f"{tcr_pct}% across {variant_metrics.total_episodes} episodes "
            f"with {variant_metrics.friction_frequency} friction events/run. "
            f"{len(hotspots)} friction hotspots detected; {len(directives)} "
            f"directives synthesized for Step 5 Regeneration."
        )

        # 6. Render Markdown content
        markdown = self._render_markdown(
            app_name=app_name,
            target_url=target_url,
            variant_id=variant_id,
            metrics=variant_metrics,
            hotspots=hotspots,
            directives=directives,
            dom_reduction_target=dom_reduction_target,
            benchmark=benchmark_comparison,
            summary=exec_summary,
        )

        report_id = f"rep_{uuid.uuid4().hex[:12]}"
        return AgentNativeReport(
            report_id=report_id,
            generated_at=datetime.now(UTC),
            app_name=app_name,
            target_url=target_url,
            variant_evaluated=variant_id,
            agent_readiness_score=ars,
            a2a_metrics=a2a,
            friction_hotspots=hotspots,
            transformation_directives=directives,
            dom_token_reduction_target_pct=dom_reduction_target,
            benchmark_comparison=benchmark_comparison,
            executive_summary=exec_summary,
            markdown_content=markdown,
        )

    def _extract_friction_hotspots(
        self, episodes: Sequence[SandboxEpisodeContract]
    ) -> list[FrictionHotspot]:
        """Groups step frictions into concrete UI hotspots."""
        grouped: dict[tuple[FrictionType, str], list[dict[str, Any]]] = defaultdict(
            list
        )

        for ep in episodes:
            for step in ep.steps:
                if not step.friction_detected:
                    continue
                selector = (
                    step.action_taken.target_selector
                    or step.action_taken.target_element_id
                    or "body"
                )
                url = step.observation_before.url
                reason = step.action_taken.reasoning

                tag = "element"
                if step.observation_before.interactive_elements:
                    for elem in step.observation_before.interactive_elements:
                        if (
                            elem.css_selector == selector
                            or elem.element_id == selector
                        ):
                            tag = elem.tag_name
                            break

                for f in step.friction_detected:
                    grouped[(f, selector)].append(
                        {
                            "url": url,
                            "tag": tag,
                            "reason": reason,
                        }
                    )

        hotspots: list[FrictionHotspot] = []
        for i, ((f_type, selector), instances) in enumerate(
            grouped.items(), start=1
        ):
            count = len(instances)
            tag = str(instances[0]["tag"])
            url = str(instances[0]["url"])
            sample_reason = next(
                (item["reason"] for item in instances if item["reason"]), None
            )

            if f_type in {
                FrictionType.SELECTOR_NOT_FOUND,
                FrictionType.ACTION_HALLUCINATION,
            } or count >= 3:
                severity = Priority.CRITICAL
            elif f_type in {
                FrictionType.AMBIGUOUS_AFFORDANCE,
                FrictionType.UNRESPONSIVE_STATE,
                FrictionType.MISCLICK,
            }:
                severity = Priority.HIGH
            elif f_type == FrictionType.DOM_TOKEN_OVERFLOW:
                severity = Priority.MEDIUM
            else:
                severity = Priority.LOW

            impact = (
                f"Agent experienced {f_type.value} on `{selector}` ({tag}) "
                f"{count} time(s). Led to step delay and potential task failure."
            )

            hotspots.append(
                FrictionHotspot(
                    hotspot_id=f"hotspot_{i:03d}",
                    friction_type=f_type,
                    severity=severity,
                    target_selector=selector,
                    element_tag=tag,
                    location_url=url,
                    occurrence_count=count,
                    sample_agent_reasoning=sample_reason,
                    impact_description=impact,
                )
            )

        severity_order = {
            Priority.CRITICAL: 0,
            Priority.HIGH: 1,
            Priority.MEDIUM: 2,
            Priority.LOW: 3,
        }
        hotspots.sort(key=lambda h: (severity_order[h.severity], -h.occurrence_count))
        return hotspots

    def _collect_interactive_elements(
        self, episodes: Sequence[SandboxEpisodeContract]
    ) -> dict[str, ElementAffordance]:
        """Collects unique interactive elements seen across all steps."""
        catalog: dict[str, ElementAffordance] = {}
        for ep in episodes:
            for step in ep.steps:
                for elem in step.observation_before.interactive_elements:
                    key = elem.css_selector or elem.element_id
                    if key not in catalog:
                        catalog[key] = elem
        return catalog

    def _synthesize_directives(
        self,
        hotspots: list[FrictionHotspot],
        catalog: dict[str, ElementAffordance],
        a2a: A2AEvalMetrics,
    ) -> list[TransformationDirective]:
        """Synthesizes actionable transformation directives for Step 5."""
        directives: list[TransformationDirective] = []
        d_idx = 1

        for h in hotspots:
            if h.friction_type in {
                FrictionType.SELECTOR_NOT_FOUND,
                FrictionType.MISCLICK,
            }:
                slug = (
                    h.target_selector.replace(".", "_")
                    .replace("#", "")
                    .replace(" ", "_")[:24]
                )
                directives.append(
                    TransformationDirective(
                        directive_id=f"dir_{d_idx:03d}",
                        directive_type=DirectiveType.INJECT_DATA_AGENT_ID,
                        priority=h.severity,
                        target_selector=h.target_selector,
                        rationale=(
                            f"Selector '{h.target_selector}' encountered "
                            f"{h.friction_type.value}. Injecting explicit "
                            f"data-agent-id creates an immutable targeting anchor."
                        ),
                        current_code_snippet=(
                            f"<{h.element_tag} class=\"{h.target_selector}\">"
                            f"...</{h.element_tag}>"
                        ),
                        suggested_patch_code=(
                            f"<{h.element_tag} data-agent-id=\"{slug}\" "
                            f"data-agent-action=\"action-{slug}\">"
                            f"...</{h.element_tag}>"
                        ),
                        expected_impact=(
                            "Eliminates selector lookup failures; reduces misclicks."
                        ),
                    )
                )
                d_idx += 1

            elif h.friction_type == FrictionType.AMBIGUOUS_AFFORDANCE:
                directives.append(
                    TransformationDirective(
                        directive_id=f"dir_{d_idx:03d}",
                        directive_type=DirectiveType.ADD_ARIA_LABEL,
                        priority=Priority.HIGH,
                        target_selector=h.target_selector,
                        rationale=(
                            f"Ambiguous affordance detected on '{h.target_selector}'. "
                            f"Element lacks an explicit, unique accessible name."
                        ),
                        current_code_snippet=(
                            f"<{h.element_tag} class=\"btn-icon\"><svg>...</svg>"
                            f"</{h.element_tag}>"
                        ),
                        suggested_patch_code=(
                            f"<{h.element_tag} aria-label=\"Descriptive Action Name\" "
                            f"data-agent-id=\"{h.target_selector}\">"
                            f"<svg aria-hidden=\"true\">...</svg></{h.element_tag}>"
                        ),
                        expected_impact=(
                            "+15% Semantic Affordance Index; resolves agent hesitation."
                        ),
                    )
                )
                d_idx += 1

            elif h.friction_type == FrictionType.UNRESPONSIVE_STATE:
                directives.append(
                    TransformationDirective(
                        directive_id=f"dir_{d_idx:03d}",
                        directive_type=DirectiveType.ADD_ARIA_LIVE,
                        priority=Priority.HIGH,
                        target_selector=h.target_selector,
                        rationale=(
                            "Action executed without detectable state change. "
                            "Adding an aria-live region announces async updates."
                        ),
                        current_code_snippet="<div id=\"result\"></div>",
                        suggested_patch_code=(
                            "<div id=\"result\" aria-live=\"polite\" "
                            "aria-atomic=\"true\" aria-busy=\"{isLoading}\">"
                            "{content}</div>"
                        ),
                        expected_impact=(
                            "Ensures 100% State Transition Determinism (STD)."
                        ),
                    )
                )
                d_idx += 1

        for _sel, elem in catalog.items():
            if elem.tag_name in {"button", "a"} and not elem.accessible_name:
                directives.append(
                    TransformationDirective(
                        directive_id=f"dir_{d_idx:03d}",
                        directive_type=DirectiveType.ADD_ARIA_LABEL,
                        priority=Priority.HIGH,
                        target_selector=elem.css_selector,
                        target_element_id=elem.element_id,
                        rationale=(
                            f"Interactive {elem.tag_name} has no accessible name "
                            f"in accessibility tree."
                        ),
                        current_code_snippet=(
                            f"<{elem.tag_name}>...</{elem.tag_name}>"
                        ),
                        suggested_patch_code=(
                            f"<{elem.tag_name} aria-label=\"Action Description\" "
                            f"data-agent-id=\"{elem.element_id}\">"
                            f"...</{elem.tag_name}>"
                        ),
                        expected_impact="Elevates Semantic Affordance Index (SAI).",
                    )
                )
                d_idx += 1

            elif (
                elem.tag_name in {"input", "textarea", "select"}
                and not elem.accessible_name
            ):
                directives.append(
                    TransformationDirective(
                        directive_id=f"dir_{d_idx:03d}",
                        directive_type=DirectiveType.ASSOCIATE_FORM_LABEL,
                        priority=Priority.CRITICAL,
                        target_selector=elem.css_selector,
                        target_element_id=elem.element_id,
                        rationale=(
                            f"Form input '{elem.css_selector}' lacks an explicit "
                            f"<label for=\"...\"> association."
                        ),
                        current_code_snippet=(
                            f"<input id=\"{elem.element_id}\" type=\"text\" />"
                        ),
                        suggested_patch_code=(
                            f"<label htmlFor=\"{elem.element_id}\">Field Name</label>\n"
                            f"<input id=\"{elem.element_id}\" type=\"text\" "
                            f"data-agent-id=\"input-{elem.element_id}\" />"
                        ),
                        expected_impact=(
                            "Provides deterministic context to VLM/AXTree agents."
                        ),
                    )
                )
                d_idx += 1

        if a2a.dom_token_efficiency < 0.40:
            dte_pct = round(a2a.dom_token_efficiency * 100, 1)
            directives.append(
                TransformationDirective(
                    directive_id=f"dir_{d_idx:03d}",
                    directive_type=DirectiveType.FLATTEN_DOM_WRAPPERS,
                    priority=Priority.HIGH,
                    target_selector="main, section, [class*='container']",
                    rationale=(
                        f"Current DOM Token Efficiency is {dte_pct}% (target >= 40%). "
                        f"Excessive wrapper divs bloat agent prompt tokens."
                    ),
                    current_code_snippet=(
                        "<div class=\"wrap\"><div class=\"inner\"><div class=\"card\">"
                        "<button>Submit</button></div></div></div>"
                    ),
                    suggested_patch_code=(
                        "<main className=\"flex flex-col gap-4\">\n"
                        "  <button data-agent-id=\"btn-submit\">Submit</button>\n"
                        "</main>"
                    ),
                    expected_impact=(
                        "Reduces raw DOM prompt tokens by 40-70%; cuts costs."
                    ),
                )
            )
            d_idx += 1

            directives.append(
                TransformationDirective(
                    directive_id=f"dir_{d_idx:03d}",
                    directive_type=DirectiveType.SIMPLIFY_SVG_PAYLOAD,
                    priority=Priority.MEDIUM,
                    target_selector="svg",
                    rationale=(
                        "Inline SVG path definitions flood DOM token budgets with "
                        "meaningless coordinate strings."
                    ),
                    current_code_snippet=(
                        "<svg viewBox=\"0 0 100 100\">"
                        "<path d=\"M10 20 L30 40 ...\" /></svg>"
                    ),
                    suggested_patch_code=(
                        "<span aria-hidden=\"true\" className=\"icon-search\">"
                        "<svg aria-hidden=\"true\">"
                        "<use href=\"#icon-search\" /></svg></span>"
                    ),
                    expected_impact="Saves 500-2,000 DOM tokens per page view.",
                )
            )

        return directives

    def _render_markdown(
        self,
        app_name: str,
        target_url: str,
        variant_id: str,
        metrics: VariantMetrics,
        hotspots: list[FrictionHotspot],
        directives: list[TransformationDirective],
        dom_reduction_target: float,
        benchmark: ABBenchmarkComparison | None,
        summary: str,
    ) -> str:
        """Renders the comprehensive Agent-Native Regeneration Report in Markdown."""
        ars = metrics.agent_readiness_score
        a2a = metrics.a2a_metrics

        md: list[str] = [
            f"# 🤖 Abtract Agent-Native Regeneration Report: {app_name}",
            f"> **Target URL:** `{target_url}` | **Variant:** `{variant_id}` | "
            f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n",
            "## 1. Executive Summary",
            f"{summary}\n",
        ]

        badge_color = "🟢" if ars.score >= 90 else ("🟡" if ars.score >= 70 else "🔴")
        tcr_w = round(ars.task_completion_weight * ars.task_completion_component, 2)
        sai_w = round(
            ars.semantic_affordance_weight * ars.semantic_affordance_component, 2
        )
        dte_w = round(ars.dom_efficiency_weight * ars.dom_efficiency_component, 2)
        fric_w = round(
            ars.friction_mitigation_weight * ars.friction_mitigation_component, 2
        )
        cmr_w = round(
            ars.cross_model_robustness_weight * ars.cross_model_robustness_component, 2
        )

        md.extend(
            [
                "### Agent-Readiness Score (ARS)",
                "| Metric | Value | Rating Tier |",
                "|---|---|---|",
                f"| **Overall ARS Score** | **{ars.score} / 100** | "
                f"{badge_color} **{ars.rating_band.value}** |\n",
                "#### ARS Component Contribution Breakdown",
                "| Factor | Weight | Score (0-100) | Weighted Contribution |",
                "|---|---|---|---|",
                f"| **Task Completion Rate (TCR)** | "
                f"{int(ars.task_completion_weight*100)}% | "
                f"{ars.task_completion_component} | {tcr_w} |",
                f"| **Semantic Affordance Index (SAI)** | "
                f"{int(ars.semantic_affordance_weight*100)}% | "
                f"{ars.semantic_affordance_component} | {sai_w} |",
                f"| **DOM Token Efficiency (DTE)** | "
                f"{int(ars.dom_efficiency_weight*100)}% | "
                f"{ars.dom_efficiency_component} | {dte_w} |",
                f"| **Friction Mitigation (1 - FF)** | "
                f"{int(ars.friction_mitigation_weight*100)}% | "
                f"{ars.friction_mitigation_component} | {fric_w} |",
                f"| **Cross-Model Robustness (CMR)** | "
                f"{int(ars.cross_model_robustness_weight*100)}% | "
                f"{ars.cross_model_robustness_component} | {cmr_w} |\n",
            ]
        )

        def status_icon(
            val: float, target: float, higher_is_better: bool = True
        ) -> str:
            ok = val >= target if higher_is_better else val <= target
            return "✅ Pass" if ok else "⚠️ Needs Regen"

        md.extend(
            [
                "## 2. Layer 1: Agent Usability & Accessibility (A2A) Evals",
                "| Metric | Measured | Target Goal | Status |",
                "|---|---|---|---|",
                f"| **Semantic Affordance Index (SAI)** | "
                f"{round(a2a.semantic_affordance_index * 100, 1)}% | $\\ge 95\\%$ | "
                f"{status_icon(a2a.semantic_affordance_index, 0.95)} |",
                f"| **DOM Token Efficiency (DTE)** | "
                f"{round(a2a.dom_token_efficiency * 100, 1)}% | $\\ge 40\\%$ | "
                f"{status_icon(a2a.dom_token_efficiency, 0.40)} |",
                f"| **Affordance Ambiguity Rate (AAR)** | "
                f"{round(a2a.affordance_ambiguity_rate * 100, 1)}% | $\\le 2\\%$ | "
                f"{status_icon(a2a.affordance_ambiguity_rate, 0.02, False)} |",
                f"| **Visual Groundability (VGS)** | "
                f"{round(a2a.visual_groundability_score * 100, 1)}% | $\\ge 90\\%$ | "
                f"{status_icon(a2a.visual_groundability_score, 0.90)} |",
                f"| **State Transition Determinism (STD)** | "
                f"{round(a2a.state_transition_determinism * 100, 1)}% | $\\ge 98\\%$ | "
                f"{status_icon(a2a.state_transition_determinism, 0.98)} |",
                f"| **Error Recoverability (ERS)** | "
                f"{round(a2a.error_recoverability_score * 100, 1)}% | $\\ge 80\\%$ | "
                f"{status_icon(a2a.error_recoverability_score, 0.80)} |\n",
            ]
        )

        if metrics.model_performances:
            md.extend(
                [
                    "### Multi-Model Execution Matrix",
                    "| Model Family | Episodes | Success Rate | Avg Steps | "
                    "Avg Cost (USD) | Latency | Frictions/Ep |",
                    "|---|---|---|---|---|---|---|",
                ]
            )
            for mp in metrics.model_performances:
                md.append(
                    f"| `{mp.model_name}` | {mp.episode_count} | "
                    f"{round(mp.success_rate * 100, 1)}% | {mp.avg_steps} | "
                    f"${mp.avg_cost_usd:.4f} | {int(mp.avg_latency_ms)}ms | "
                    f"{mp.friction_events_per_episode} |"
                )
            md.append("")

        if benchmark:
            sig = (
                f"p={benchmark.p_value:.4f} (Sig)"
                if benchmark.statistically_significant
                else f"p={benchmark.p_value:.4f} (Not Sig)"
            )
            md.extend(
                [
                    "## 3. Layer 2: A/B Comparative Benchmark",
                    f"> **Verdict:** {benchmark.summary_verdict}\n",
                    "| Metric | Variant A | Variant B | Delta (B - A) | Note |",
                    "|---|---|---|---|---|",
                    f"| **Task Completion** | "
                    f"{round(benchmark.baseline.task_completion_rate*100,1)}% | "
                    f"{round(benchmark.candidate.task_completion_rate*100,1)}% | "
                    f"**+{round(benchmark.delta_tcr*100,1)}%** | {sig} |",
                    f"| **Cost per Task** | "
                    f"${benchmark.baseline.cost_per_successful_task_usd:.4f} | "
                    f"${benchmark.candidate.cost_per_successful_task_usd:.4f} | "
                    f"**-{benchmark.cost_reduction_pct}%** | Economic Gain |",
                    f"| **Step Efficiency** | {benchmark.baseline.avg_steps} | "
                    f"{benchmark.candidate.avg_steps} | "
                    f"**SER={benchmark.step_efficiency_ratio}** | "
                    f"-{benchmark.step_reduction_pct}% steps |",
                    f"| **Friction Frequency** | "
                    f"{benchmark.baseline.friction_frequency}/ep | "
                    f"{benchmark.candidate.friction_frequency}/ep | "
                    f"**-{benchmark.friction_reduction_pct}%** | Less Loops |",
                    f"| **ARS Score** | "
                    f"{benchmark.baseline.agent_readiness_score.score} | "
                    f"{benchmark.candidate.agent_readiness_score.score} | "
                    f"**+{benchmark.delta_ars}** | Usability Leap |\n",
                ]
            )

        md.append("## 4. Friction Hotspots Map")
        if hotspots:
            md.extend(
                [
                    "| Hotspot ID | Friction Type | Severity | Target Selector | "
                    "Tag | Count | Impact |",
                    "|---|---|---|---|---|---|---|",
                ]
            )
            for h in hotspots:
                md.append(
                    f"| `{h.hotspot_id}` | `{h.friction_type.value}` | "
                    f"**{h.severity.value}** | `{h.target_selector}` | "
                    f"`{h.element_tag}` | {h.occurrence_count} | "
                    f"{h.impact_description} |"
                )
            md.append("")
        else:
            md.append("🎉 *No recurring friction hotspots detected.*\n")

        md.extend(
            [
                "## 5. Step 5 Prescriptive Transformation Directives",
                (
                    f"> **Target Token Reduction:** {dom_reduction_target}% "
                    "DOM footprint\n"
                ),
                (
                    "The following directives are formatted for direct AST "
                    "patching in Step 5:\n"
                ),
            ]
        )

        for d in directives:
            clean_type = d.directive_type.value.replace("_", " ").title()
            md.extend(
                [
                    (
                        f"### `[{d.priority.value}]` Directive `{d.directive_id}`: "
                        f"{clean_type}"
                    ),
                    f"- **Target Selector:** `{d.target_selector}`",
                    f"- **Rationale:** {d.rationale}",
                    f"- **Expected Impact:** *{d.expected_impact}*",
                    "```tsx",
                    "// Suggested Agent-Native Code Patch:",
                    d.suggested_patch_code,
                    "```\n",
                ]
            )

        md.extend(
            [
                "---",
                "## 6. Next Steps for Step 5 Regeneration",
                (
                    "1. **Apply AST Patches**: Ingest the JSON payload into "
                    "Step 5 (`RegenerationEngine`)."
                ),
                (
                    "2. **Deploy Candidate (Variant B)**: Spin up candidate "
                    "branch on disposable sandbox."
                ),
                (
                    "3. **Re-run Swarm Trials**: Execute multi-model matrix "
                    "across Gemini, Claude, and GPT."
                ),
                (
                    "4. **Verify ARS $\\ge 90$**: Confirm elevation to "
                    "**Agent-Native** rating."
                ),
            ]
        )

        return "\n".join(md)


report_generator = RegenerationReportGenerator()
