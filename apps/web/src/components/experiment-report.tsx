import type {
  Experiment,
  EvaluationReport,
  RunResult,
  Outcome,
} from "@/lib/types";
import { Arrow } from "./lab-visuals";

function seconds(value: number | null | undefined) {
  return value == null ? "—" : `${value.toFixed(1)}s`;
}
function money(value: number | null | undefined) {
  return value == null ? "Unavailable" : `$${value.toFixed(4)}`;
}
export function friendlyName(name: string) {
  return name === "codex"
    ? "Codex"
    : name === "claude"
      ? "Claude Code"
      : "Gemini CLI";
}
function outcomeLabel(outcome: Outcome | undefined) {
  return outcome === "pass"
    ? "Passed"
    : outcome === "fail"
      ? "Failed"
      : outcome === "unknown"
        ? "Uncertain"
        : "Checking";
}
function safeLink(value: string) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function RunDetails({
  run,
  evaluation,
}: {
  run: RunResult;
  evaluation?: EvaluationReport["runs"][number];
}) {
  return (
    <details className="run-card">
      <summary>
        <span className={`result-dot ${evaluation?.outcome ?? "pending"}`} />
        <span className="run-title">
          <strong>{run.task.split("\n")[0]}</strong>
          <span>
            {friendlyName(run.harness.name)}{" "}
            <span className="separator">/</span>{" "}
            {run.harness.model ?? "Default model"}
          </span>
        </span>
        <span className="run-time">
          {seconds(run.execution_duration_seconds ?? run.duration_seconds)}
        </span>
        <span className={`outcome ${evaluation?.outcome ?? "pending"}`}>
          {outcomeLabel(evaluation?.outcome)}
        </span>
        <span className="expand-sign">+</span>
      </summary>
      <div className="run-detail-body">
        {run.error ? <p className="error-message">{run.error}</p> : null}
        {evaluation ? (
          <div className="checks">
            {evaluation.checks.map((check) => (
              <div className="check" key={check.check_id}>
                <span className={`result-dot ${check.outcome}`} />
                <div>
                  <strong>{check.description}</strong>
                  <p>{check.reason}</p>
                  {check.evidence.map((quote, i) => (
                    <blockquote key={i}>{quote}</blockquote>
                  ))}
                  {check.error ? (
                    <p className="error-message">{check.error}</p>
                  ) : null}
                </div>
                <span className="micro-label">
                  {check.method === "llm_judge"
                    ? "GEMINI REVIEW"
                    : "AUTOMATED CHECK"}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">Evaluation is in progress.</p>
        )}
        <div className="run-metrics">
          <span>
            Tool calls <strong>{run.telemetry.tool_calls ?? "—"}</strong>
          </span>
          <span>
            Input tokens{" "}
            <strong>
              {run.telemetry.tokens.input_tokens?.toLocaleString() ?? "—"}
            </strong>
          </span>
          <span>
            Output tokens{" "}
            <strong>
              {run.telemetry.tokens.output_tokens?.toLocaleString() ?? "—"}
            </strong>
          </span>
          <span>
            Model cost est.{" "}
            <strong>{money(run.telemetry.estimated_cost_usd)}</strong>
          </span>
        </div>
        {evaluation && evaluation.variant_exposure !== "baseline" ? (
          <p
            className={`exposure ${evaluation.variant_attribution_eligible ? "verified" : ""}`}
          >
            {evaluation.variant_attribution_eligible
              ? "Patch delivery verified for this run. This alone does not prove improvement."
              : "Patch exposure unverified. Do not attribute this answer to the changes."}
          </p>
        ) : null}
        {run.report ? (
          <>
            <h4>Agent answer</h4>
            <pre className="answer">{run.report.answer}</pre>
            {run.report.sources.length ? (
              <div className="sources">
                <span className="micro-label">REPORTED SOURCES</span>
                {run.report.sources.map((source, i) =>
                  safeLink(source) ? (
                    <a
                      key={i}
                      href={safeLink(source)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {source}
                      <Arrow diagonal />
                    </a>
                  ) : (
                    <span key={i}>{source}</span>
                  ),
                )}
              </div>
            ) : null}
          </>
        ) : null}
        <a
          className="text-link"
          href={`/api/runs/${encodeURIComponent(run.run_id)}`}
          target="_blank"
          rel="noreferrer"
        >
          Open full result & execution trace <Arrow diagonal />
        </a>
      </div>
    </details>
  );
}

export function Report({
  runs,
  evaluation,
  variant,
}: {
  runs: RunResult[];
  evaluation: EvaluationReport | null;
  variant: boolean;
}) {
  const costs = runs.map((run) => run.telemetry.estimated_cost_usd);
  const totalCost =
    costs.length && costs.every((cost) => cost != null)
      ? costs.reduce<number>((sum, cost) => sum + (cost ?? 0), 0)
      : null;
  const averageTime = runs.length
    ? runs.reduce(
        (sum, run) =>
          sum + (run.execution_duration_seconds ?? run.duration_seconds),
        0,
      ) / runs.length
    : null;
  return (
    <div className="report">
      <div className="metric-grid">
        <div>
          <span className="micro-label">TASKS PASSED</span>
          <strong>
            {evaluation
              ? `${evaluation.passed}/${evaluation.runs.length}`
              : "—"}
          </strong>
          <span>
            {evaluation
              ? `${evaluation.failed} failed · ${evaluation.unknown} uncertain`
              : "Waiting for evaluation"}
          </span>
        </div>
        <div>
          <span className="micro-label">AVG. AGENT TIME</span>
          <strong>{seconds(averageTime)}</strong>
          <span>Per isolated run</span>
        </div>
        <div>
          <span className="micro-label">MODEL COST EST.</span>
          <strong>{totalCost == null ? "—" : money(totalCost)}</strong>
          <span>Excludes sandbox & supervisor</span>
        </div>
      </div>
      <div className="section-heading">
        <h3>{variant ? "Patched page results" : "Original page results"}</h3>
        <span className="micro-label">
          {runs.length} RUN{runs.length === 1 ? "" : "S"}
        </span>
      </div>
      <div className="run-list">
        {runs.map((run) => (
          <RunDetails
            key={run.run_id}
            run={run}
            evaluation={evaluation?.runs.find(
              (item) => item.run_id === run.run_id,
            )}
          />
        ))}
      </div>
      {!runs.length ? (
        <div className="empty-state">
          <span className="spinner" />
          Each agent is working in its own sandbox. Results arrive when this
          batch completes.
        </div>
      ) : null}
    </div>
  );
}

export function Comparison({ experiment }: { experiment: Experiment }) {
  if (!experiment.variant_evaluation || !experiment.baseline_evaluation)
    return null;
  return (
    <div className="comparison">
      <div className="section-heading">
        <h3>The same tasks. A new version.</h3>
        <span className="micro-label">PAIRED RESULTS</span>
      </div>
      <div className="comparison-head">
        <span>Agent / task</span>
        <span>Original A</span>
        <span>Variant B</span>
      </div>
      {experiment.baseline_runs.map((run) => {
        const after = experiment.variant_runs.find(
          (item) =>
            item.task_index === run.task_index &&
            item.harness.name === run.harness.name &&
            item.harness.model === run.harness.model &&
            item.repetition === run.repetition,
        );
        const beforeEval = experiment.baseline_evaluation?.runs.find(
          (item) => item.run_id === run.run_id,
        );
        const afterEval = experiment.variant_evaluation?.runs.find(
          (item) => item.run_id === after?.run_id,
        );
        return (
          <div className="comparison-row" key={run.run_id}>
            <span>
              <strong>{friendlyName(run.harness.name)}</strong>Task{" "}
              {run.task_index + 1}
              {afterEval && !afterEval.variant_attribution_eligible ? (
                <small>Exposure unverified</small>
              ) : null}
            </span>
            <span>
              <span className={`outcome ${beforeEval?.outcome}`}>
                {outcomeLabel(beforeEval?.outcome)}
              </span>
              <small>
                {seconds(
                  run.execution_duration_seconds ?? run.duration_seconds,
                )}
              </small>
            </span>
            <span>
              <span className={`outcome ${afterEval?.outcome}`}>
                {outcomeLabel(afterEval?.outcome)}
              </span>
              <small>
                {seconds(
                  after?.execution_duration_seconds ?? after?.duration_seconds,
                )}
              </small>
            </span>
          </div>
        );
      })}
      <p className="fine-print">
        One run per task is an initial signal. Repeat with unseen tasks before
        claiming an improvement.
      </p>
    </div>
  );
}
