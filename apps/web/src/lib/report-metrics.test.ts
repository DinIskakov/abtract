import { expect, test } from "bun:test";
import type { EvaluatedRun, Outcome } from "./types";
import {
  answerOutcome,
  compareAgentTime,
  overTimeTarget,
} from "./report-metrics";

function evaluated(
  correctness: Outcome,
  slow = false,
  exposed = true,
): EvaluatedRun {
  return {
    run_id: "run",
    task_id: "task",
    task_index: 0,
    outcome: slow ? "fail" : correctness,
    checks: [
      {
        check_id: "answer",
        kind: "semantic",
        description: "Answer correctness",
        outcome: correctness,
        reason: "Fixture",
        evidence: [],
        method: "llm_judge",
        error: null,
      },
      {
        check_id: "speed",
        kind: "execution_duration_budget",
        description: "Agent time target",
        outcome: slow ? "fail" : "pass",
        reason: "Fixture",
        evidence: [],
        method: "deterministic",
        error: null,
      },
    ],
    variant_exposure: exposed ? "observed" : "unverified",
    variant_attribution_eligible: exposed,
    variant_exposure_note: "Fixture",
  };
}

test("correct but slow is a latency failure, not an incorrect answer", () => {
  const before = evaluated("pass", true);
  expect(answerOutcome(before)).toBe("pass");
  expect(overTimeTarget(before)).toBe(true);
  expect(compareAgentTime(20, 10, before, evaluated("pass"))).toEqual({
    delta: -10,
    percent: -50,
    label: "Faster, correctness preserved",
  });
});

test("faster timing cannot hide regression, uncertain answers, or missing exposure", () => {
  const before = evaluated("pass");
  expect(compareAgentTime(20, 10, before, evaluated("fail")).label).toBe(
    "Correctness regression",
  );
  expect(compareAgentTime(20, 10, before, evaluated("unknown")).label).toBe(
    "Correctness not preserved or unverified",
  );
  expect(
    compareAgentTime(20, 10, before, evaluated("pass", false, false)).label,
  ).toBe("Exposure unverified");
  expect(answerOutcome(evaluated("unknown", true))).toBe("unknown");
});

test("missing execution telemetry never falls back to cold-start wall time", () => {
  expect(
    compareAgentTime(null, 10, evaluated("pass"), evaluated("pass")),
  ).toEqual({ delta: null, percent: null, label: "Agent timing unavailable" });
  expect(
    compareAgentTime(0, 10, evaluated("pass"), evaluated("pass")).percent,
  ).toBeNull();
  expect(
    compareAgentTime(10, 20, evaluated("pass"), evaluated("pass")).label,
  ).toBe("Slower, correctness preserved");
});
