export type HarnessName = "codex" | "claude" | "gemini";
export type Outcome = "pass" | "fail" | "unknown";
export type Phase =
  | "planning"
  | "baseline"
  | "baseline_evaluation"
  | "proposing"
  | "variant"
  | "variant_evaluation"
  | "completed"
  | "failed";

export interface HarnessConfig {
  name: HarnessName;
  model: string | null;
}

export interface ModelOption extends HarnessConfig {
  id: string;
  label: string;
  available: boolean;
  reason: string | null;
}

export interface ExperimentOptions {
  supervisor: { name: string; model: string; available: boolean };
  harnesses: ModelOption[];
}

export interface Criterion {
  id: string;
  kind: string;
  description: string;
  values?: string[];
  reference_answer?: string | null;
}

export interface TaskRubric {
  task_id: string;
  task_index: number;
  task: string;
  criteria: Criterion[];
}

export interface TokenUsage {
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  reasoning_output_tokens: number | null;
}

export interface Telemetry {
  tokens: TokenUsage;
  models_reported: string[];
  tool_calls: number | null;
  failed_tool_calls: number | null;
  estimated_cost_usd: number | null;
  cost_source: string | null;
  trace_complete: boolean;
}

export interface RunResult {
  run_id: string;
  sandbox_id: string | null;
  task: string;
  task_index: number;
  repetition: number;
  harness: HarnessConfig;
  harness_version: string;
  status: "completed" | "error";
  duration_seconds: number;
  execution_duration_seconds: number | null;
  variant_id: string;
  telemetry: Telemetry;
  report: {
    answer: string;
    actions: string[];
    sources: string[];
    limitations: string[];
  } | null;
  error: string | null;
  observations: {
    capture_http: boolean;
    applied_patch_ids: string[];
    unobserved_patch_ids: string[];
    capture_error: string | null;
    coverage: string;
  };
}

export interface CheckResult {
  check_id: string;
  kind: string;
  description: string;
  outcome: Outcome;
  reason: string;
  evidence: string[];
  method: "deterministic" | "llm_judge";
  error: string | null;
}

export interface EvaluatedRun {
  run_id: string;
  task_id: string;
  task_index: number;
  outcome: Outcome;
  checks: CheckResult[];
  variant_exposure: "baseline" | "observed" | "unverified";
  variant_attribution_eligible: boolean;
  variant_exposure_note: string;
}

export interface EvaluationReport {
  evaluation_id: string;
  grader_version: string;
  runs: EvaluatedRun[];
  passed: number;
  failed: number;
  unknown: number;
}

export interface ProposedPatch {
  patch: {
    patch_id: string;
    url: string;
    expected_sha256: string;
    old_text: string;
    new_text: string;
  };
  rationale: string;
  failed_check_refs: string[];
}

export interface ProposalReport {
  proposal_id: string;
  evaluation_id: string;
  variant_id: string;
  variant_sha256: string;
  summary: string;
  patches: ProposedPatch[];
  interpretation: string;
}

export interface Experiment {
  experiment_id: string;
  url: string;
  phase: Phase;
  created_at: string;
  updated_at: string;
  tasks: TaskRubric[];
  harnesses: HarnessConfig[];
  baseline_runs: RunResult[];
  baseline_evaluation: EvaluationReport | null;
  proposal: ProposalReport | null;
  variant_runs: RunResult[];
  variant_evaluation: EvaluationReport | null;
  error: string | null;
  note: string | null;
  concurrency: number;
}

export interface ExperimentRequest {
  url: string;
  harnesses: HarnessConfig[];
  task_count: number;
}
