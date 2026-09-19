"""Abtract Evals Engine.

Orchestrates telemetry evaluation across episodes, variants, and multi-model swarms.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.evals.metrics import (
    ABBenchmarkComparison,
    VariantMetrics,
    aggregate_variant_metrics,
    compare_variants,
)
from app.schemas.contracts import BatchEvaluationPayload, SandboxEpisodeContract


class AbtractEvalEngine:
    """Core evaluation engine for the Abtract platform."""

    def evaluate_episode(self, episode: SandboxEpisodeContract) -> VariantMetrics:
        """Evaluates a single episode trace."""
        return aggregate_variant_metrics(
            variant_id=episode.variant_id, episodes=[episode]
        )

    def evaluate_variant(
        self, variant_id: str, episodes: Sequence[SandboxEpisodeContract]
    ) -> VariantMetrics:
        """Evaluates a collection of episodes for a single variant."""
        return aggregate_variant_metrics(variant_id=variant_id, episodes=episodes)

    def evaluate_benchmark(
        self, payload: BatchEvaluationPayload
    ) -> ABBenchmarkComparison:
        """Splits a batch of episodes by variant and computes A/B benchmarking."""
        baseline_id = payload.baseline_variant
        candidate_id = payload.candidate_variant or "B"

        episodes_a = [
            ep for ep in payload.episodes if ep.variant_id == baseline_id
        ]
        episodes_b = [
            ep for ep in payload.episodes if ep.variant_id == candidate_id
        ]

        return compare_variants(
            variant_a_episodes=episodes_a,
            variant_b_episodes=episodes_b,
            variant_a_id=baseline_id,
            variant_b_id=candidate_id,
        )


eval_engine = AbtractEvalEngine()
