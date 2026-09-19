import type { EvaluatedRun, Outcome } from "./types";

const budgetKinds = new Set([
  "execution_duration_budget",
  "duration_budget",
  "cost_budget",
]);

/** Budget misses are not evidence of an incorrect answer. */
export function answerOutcome(
  evaluation: EvaluatedRun | undefined,
): Outcome | undefined {
  if (!evaluation) return undefined;
  const checks = evaluation.checks.filter(
    (check) => !budgetKinds.has(check.kind),
  );
  if (!checks.length) return "unknown";
  if (checks.some((check) => check.outcome === "fail")) return "fail";
  if (checks.some((check) => check.outcome === "unknown")) return "unknown";
  return "pass";
}

export function overTimeTarget(evaluation: EvaluatedRun | undefined) {
  return (
    evaluation?.checks.some(
      (check) =>
        check.kind === "execution_duration_budget" && check.outcome === "fail",
    ) ?? false
  );
}

export function compareAgentTime(
  before: number | null | undefined,
  after: number | null | undefined,
  beforeEvaluation: EvaluatedRun | undefined,
  afterEvaluation: EvaluatedRun | undefined,
) {
  const delta = before == null || after == null ? null : after - before;
  const percent = delta == null || !before ? null : (delta / before) * 100;
  let label: string;
  if (!afterEvaluation?.variant_attribution_eligible)
    label = "Exposure unverified";
  else if (
    answerOutcome(beforeEvaluation) === "pass" &&
    answerOutcome(afterEvaluation) === "fail"
  )
    label = "Correctness regression";
  else if (
    answerOutcome(beforeEvaluation) !== "pass" ||
    answerOutcome(afterEvaluation) !== "pass"
  )
    label = "Correctness not preserved or unverified";
  else if (delta == null) label = "Agent timing unavailable";
  else if (delta < 0) label = "Faster, correctness preserved";
  else if (delta > 0) label = "Slower, correctness preserved";
  else label = "Same time, correctness preserved";
  return { delta, percent, label };
}
