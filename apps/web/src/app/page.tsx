"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { answerOutcome } from "@/lib/report-metrics";
import { fetchExperiment, fetchOptions, startExperiment } from "@/lib/api";
import type {
  Experiment,
  ExperimentOptions,
  Phase,
  Difficulty,
} from "@/lib/types";

import { Arrow, Mark, Scene } from "@/components/lab-visuals";
import {
  Report,
  Comparison,
  friendlyName,
} from "@/components/experiment-report";

const STORAGE_KEY = "uptrack.experiment.v1";
const phaseLabels: Record<Phase, string> = {
  planning: "Gemini is getting to know your product",
  baseline: "Agents are exploring your original page",
  baseline_evaluation: "Gemini is checking each answer",
  proposing: "Gemini is looking for a better version",
  variant: "Agents are testing the proposed changes",
  variant_evaluation: "Gemini is comparing the new answers",
  completed: "Your experiment is complete",
  failed: "This experiment needs attention",
};

export default function Home() {
  const [options, setOptions] = useState<ExperimentOptions | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [url, setUrl] = useState("");
  const [taskCount, setTaskCount] = useState(3);
  const [difficulty, setDifficulty] = useState<Difficulty>("easy");
  const [latencyBudget, setLatencyBudget] = useState(15);
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [optionsAttempt, setOptionsAttempt] = useState(0);
  const [tab, setTab] = useState<"baseline" | "variant">("baseline");
  const seenVariant = useRef(false);
  const experimentId = experiment?.experiment_id;
  const running =
    !!experiment && !["completed", "failed"].includes(experiment.phase);
  const stage = !experiment
    ? 0
    : ["planning", "baseline", "baseline_evaluation"].includes(experiment.phase)
      ? 1
      : 2;

  useEffect(() => {
    const controller = new AbortController();
    fetchOptions(controller.signal)
      .then((data) => {
        setOptions(data);
        setSelected(
          data.harnesses
            .filter((h) => h.available && ["codex", "gemini"].includes(h.name))
            .map((h) => h.id),
        );
        setError(null);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not connect to the experiment service.",
          );
      });
    return () => controller.abort();
  }, [optionsAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    let id: string | null = null;
    try {
      id = localStorage.getItem(STORAGE_KEY);
    } catch {
      /* Storage may be unavailable in private browsing. */
    }
    if (id)
      fetchExperiment(id, controller.signal)
        .then((data) => {
          setExperiment(data);
          setUrl(data.url);
          setDifficulty(data.difficulty ?? "easy");
          setLatencyBudget(data.latency_budget_seconds ?? 15);
          seenVariant.current = !!data.variant_evaluation;
          if (data.variant_evaluation) setTab("variant");
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            try {
              localStorage.removeItem(STORAGE_KEY);
            } catch {
              /* Optional persistence. */
            }
          }
        });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!experimentId || !running) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await fetchExperiment(experimentId!, controller.signal);
        setExperiment(data);
        setError(null);
        if (data.variant_evaluation && !seenVariant.current) {
          seenVariant.current = true;
          setTab("variant");
        }
        if (!["completed", "failed"].includes(data.phase))
          timer = setTimeout(poll, 1500);
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(
            `Connection interrupted. Retrying… ${reason instanceof Error ? reason.message : ""}`,
          );
          timer = setTimeout(poll, 4000);
        }
      }
    }
    timer = setTimeout(poll, 1000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [experimentId, running]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!options || submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const harnesses = options.harnesses
        .filter((h) => selected.includes(h.id))
        .map((h) => ({ name: h.name, model: h.model }));
      const data = await startExperiment({
        url,
        harnesses,
        task_count: taskCount,
        difficulty,
        latency_budget_seconds: latencyBudget,
      });
      setExperiment(data);
      setTab("baseline");
      seenVariant.current = false;
      try {
        localStorage.setItem(STORAGE_KEY, data.experiment_id);
      } catch {
        /* The experiment also stays in memory. */
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The experiment could not start.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    setExperiment(null);
    setError(null);
    setTab("baseline");
    seenVariant.current = false;
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* Optional persistence. */
    }
  }

  return (
    <div className={`workbench stage-${stage}`}>
      <div className="moving-grid" aria-hidden="true" />
      <header className="site-header">
        <Link href="/" className="wordmark" aria-label="UpTrack home">
          <Mark />
          <span>
            uptrack<span className="brand-period">.</span>
          </span>
        </Link>
        <div className="header-center">THE AGENT EXPERIENCE LAB</div>
        <a href="#workspace" className="header-action">
          Open the lab <Arrow diagonal />
        </a>
      </header>
      <main>
        <section className={`hero ${experiment ? "hero-compact" : ""}`}>
          <div className="hero-copy">
            <div className="eyebrow">
              <span className="orange-square" /> BETTER PRODUCTS, FOR AGENTS.
            </div>
            <h1>
              {experiment ? (
                <>
                  A better experience.
                  <br />
                  <span>One experiment away.</span>
                </>
              ) : (
                <>
                  Make your product
                  <br />
                  work for{" "}
                  <span className="agent-word">
                    agents
                    <svg viewBox="0 0 270 13" fill="none" aria-hidden="true">
                      <path
                        d="M2 9C76 2 179 1 268 7"
                        stroke="currentColor"
                        strokeWidth="3"
                      />
                    </svg>
                  </span>
                  .
                </>
              )}
            </h1>
            <p>
              See where agents get stuck. Test a better version.
              <br className="desktop-break" /> Turn real runs into a product
              they can actually use.
            </p>
            <div className="hero-caption">
              <span>01 / OBSERVE</span>
              <span>02 / IMPROVE</span>
              <span>03 / VERIFY</span>
            </div>
          </div>
          <Scene active={running} />
        </section>
        <section id="workspace" className="workspace">
          <div className="workspace-top">
            <span className="micro-label">YOUR EXPERIMENT WORKBENCH</span>
            <span className="lab-status">
              <i className={options ? "connected" : ""} />
              {options ? "LAB CONNECTED" : "CONNECTING TO LAB"}
            </span>
          </div>
          <ol className="step-rail">
            {["Configure", "Baseline", "Improve & compare"].map(
              (label, index) => (
                <li
                  key={label}
                  className={
                    stage === index ? "active" : stage > index ? "done" : ""
                  }
                >
                  <span>{stage > index ? "✓" : `0${index + 1}`}</span>
                  {label}
                  {index < 2 ? <Arrow /> : null}
                </li>
              ),
            )}
          </ol>
          {error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              {!options ? (
                <button onClick={() => setOptionsAttempt((value) => value + 1)}>
                  Try again
                </button>
              ) : null}
            </div>
          ) : null}
          {!experiment ? (
            <form onSubmit={submit} className="configuration">
              <div className="form-heading">
                <div>
                  <span className="micro-label">START WITH YOUR PRODUCT</span>
                  <h2>One URL. A fresh perspective.</h2>
                </div>
                <span className="corner-index">[ 01 ]</span>
              </div>
              <label className="field-label" htmlFor="product-url">
                Product or documentation URL
              </label>
              <div className="url-field">
                <span aria-hidden="true">↗</span>
                <input
                  id="product-url"
                  name="url"
                  type="url"
                  required
                  placeholder="https://your-product.com/docs"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  autoComplete="url"
                />
              </div>
              <p className="field-hint">
                Start with a public documentation page. Gemini creates
                answerable tasks grounded in the page.
              </p>
              <div className="field-heading">
                <span className="field-label" id="agents-label">
                  Choose your test agents
                </span>
                <span className="micro-label">NATIVE HARNESS · REAL TOOLS</span>
              </div>
              <div
                className="agent-grid"
                role="group"
                aria-labelledby="agents-label"
              >
                {options ? (
                  options.harnesses.map((h, index) => (
                    <label
                      className={`agent-option ${selected.includes(h.id) ? "selected" : ""} ${!h.available ? "unavailable" : ""}`}
                      key={h.id}
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(h.id)}
                        disabled={!h.available || submitting}
                        onChange={(event) =>
                          setSelected((current) =>
                            event.target.checked
                              ? [...current, h.id]
                              : current.filter((id) => id !== h.id),
                          )
                        }
                      />
                      <span className="agent-icon" aria-hidden="true">
                        {h.name === "codex"
                          ? "⌘"
                          : h.name === "gemini"
                            ? "✧"
                            : "✳"}
                      </span>
                      <span className="agent-name">{friendlyName(h.name)}</span>
                      <span className="agent-model">{h.label || h.model}</span>
                      <span className="agent-status">
                        {h.available ? (
                          <>
                            <i />
                            Ready to run
                          </>
                        ) : (
                          h.reason || "API key needed"
                        )}
                      </span>
                      <span className="agent-number">0{index + 1}</span>
                    </label>
                  ))
                ) : (
                  <div className="options-loading">
                    <span className="spinner" />
                    Loading available agents…
                  </div>
                )}
              </div>
              <div className="supervisor">
                <span className="supervisor-icon">✧</span>
                <div>
                  <strong>Gemini is your experiment supervisor</strong>
                  <p>
                    Creates the tasks, reviews the answers, and proposes
                    targeted improvements.
                  </p>
                </div>
                <span
                  className={`supervisor-state ${options?.supervisor.available ? "ready" : ""}`}
                >
                  {!options
                    ? "CONNECTING"
                    : options.supervisor.available
                      ? "ALWAYS INCLUDED"
                      : "API KEY NEEDED"}
                </span>
              </div>
              <div className="test-settings">
                <div>
                  <label className="field-label" htmlFor="difficulty">
                    Task difficulty
                  </label>
                  <select
                    id="difficulty"
                    value={difficulty}
                    onChange={(event) =>
                      setDifficulty(event.target.value as Difficulty)
                    }
                  >
                    <option value="easy">Easy — direct questions</option>
                    <option value="medium">
                      Medium — connect a few details
                    </option>
                    <option value="hard">Hard — apply the documentation</option>
                  </select>
                  <p className="field-hint">
                    Hard tasks include code only when the page supports it.
                  </p>
                </div>
                <div>
                  <label className="field-label" htmlFor="latency-budget">
                    Agent time target (seconds)
                  </label>
                  <input
                    id="latency-budget"
                    type="number"
                    required
                    min="0.1"
                    max="180"
                    step="0.1"
                    value={latencyBudget}
                    onChange={(event) =>
                      setLatencyBudget(
                        event.target.value === ""
                          ? 0
                          : Number(event.target.value),
                      )
                    }
                  />
                  <p className="field-hint">
                    Agent execution only. Sandbox startup is excluded.
                  </p>
                </div>
              </div>
              <div className="launch-row">
                <div className="parallel-copy">
                  <label htmlFor="task-count">
                    Quick test{" "}
                    <select
                      id="task-count"
                      value={taskCount}
                      onChange={(event) =>
                        setTaskCount(Number(event.target.value))
                      }
                    >
                      <option value={1}>1 task</option>
                      <option value={2}>2 tasks</option>
                      <option value={3}>3 tasks</option>
                    </select>
                  </label>
                  <span>
                    {taskCount} task{taskCount === 1 ? "" : "s"} ×{" "}
                    {selected.length} agent{selected.length === 1 ? "" : "s"} ={" "}
                    <strong>
                      {taskCount * selected.length} parallel sandboxes
                    </strong>
                  </span>
                </div>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={
                    submitting ||
                    !options?.supervisor.available ||
                    !selected.length
                  }
                >
                  {submitting ? (
                    <>
                      <span className="spinner" />
                      Starting experiment
                    </>
                  ) : (
                    <>
                      Run experiment
                      <Arrow />
                    </>
                  )}
                </button>
              </div>
              <p className="fine-print">
                Every task gets a fresh sandbox. All combinations start
                together, subject to provider capacity.
              </p>
            </form>
          ) : (
            <div className="experiment-body">
              <div className="experiment-heading">
                <div>
                  <span className="micro-label">
                    EXPERIMENT {experiment.experiment_id.slice(0, 8)}
                  </span>
                  <h2>{new URL(experiment.url).hostname}</h2>
                  <a
                    href={experiment.url}
                    target="_blank"
                    rel="noreferrer"
                    className="experiment-url"
                  >
                    {experiment.url}
                    <Arrow diagonal />
                  </a>
                </div>
                {!running ? (
                  <button className="secondary-button" onClick={reset}>
                    New experiment <span>+</span>
                  </button>
                ) : (
                  <span className="parallel-badge">
                    {experiment.concurrency} PARALLEL RUNS
                  </span>
                )}
              </div>
              <p className="experiment-settings">
                <span>{experiment.difficulty ?? "easy"} difficulty</span>
                <span>
                  {experiment.latency_budget_seconds ?? 15}s agent time target
                </span>
                <span>Excludes sandbox startup</span>
              </p>
              <div
                className={`progress-message ${experiment.phase === "failed" ? "has-error" : ""}`}
                role="status"
              >
                {running ? (
                  <span className="spinner" />
                ) : (
                  <span className="progress-symbol">
                    {experiment.phase === "failed" ? "!" : "✓"}
                  </span>
                )}
                <div>
                  <strong>{phaseLabels[experiment.phase]}</strong>
                  <p>
                    {experiment.error ||
                      (experiment.phase === "planning"
                        ? "Reading the page and creating questions at your chosen difficulty."
                        : experiment.phase === "completed"
                          ? "Inspect the evidence below, then decide what to improve."
                          : "You can leave this tab open. Each stage appears as it finishes.")}
                  </p>
                </div>
              </div>
              {experiment.tasks.length ? (
                <details className="task-plan">
                  <summary>
                    <span>Gemini’s test plan</span>
                    <span className="micro-label">
                      {experiment.tasks.length} TASKS{" "}
                      <span className="expand-sign">+</span>
                    </span>
                  </summary>
                  <ol>
                    {experiment.tasks.map((task) => (
                      <li key={task.task_id}>{task.task.split("\n")[0]}</li>
                    ))}
                  </ol>
                </details>
              ) : null}
              {experiment.baseline_runs.length ? (
                <>
                  <div
                    className="report-tabs"
                    role="tablist"
                    aria-label="Experiment reports"
                  >
                    <button
                      id="baseline-tab"
                      role="tab"
                      aria-selected={tab === "baseline"}
                      aria-controls="report-panel"
                      onClick={() => setTab("baseline")}
                    >
                      A <span>Original page</span>
                      {experiment.baseline_evaluation ? (
                        <span className="tab-count">
                          {
                            experiment.baseline_evaluation.runs.filter(
                              (run) => answerOutcome(run) === "pass",
                            ).length
                          }
                          /{experiment.baseline_evaluation.runs.length}
                        </span>
                      ) : null}
                    </button>
                    <button
                      id="variant-tab"
                      role="tab"
                      aria-selected={tab === "variant"}
                      aria-controls="report-panel"
                      disabled={!experiment.variant_runs.length}
                      onClick={() => setTab("variant")}
                    >
                      B <span>Improved version</span>
                      {experiment.variant_evaluation ? (
                        <span className="tab-count">
                          {
                            experiment.variant_evaluation.runs.filter(
                              (run) => answerOutcome(run) === "pass",
                            ).length
                          }
                          /{experiment.variant_evaluation.runs.length}
                        </span>
                      ) : null}
                    </button>
                  </div>
                  <div
                    id="report-panel"
                    role="tabpanel"
                    aria-labelledby={
                      tab === "baseline" ? "baseline-tab" : "variant-tab"
                    }
                  >
                    <Report
                      runs={
                        tab === "baseline"
                          ? experiment.baseline_runs
                          : experiment.variant_runs
                      }
                      evaluation={
                        tab === "baseline"
                          ? experiment.baseline_evaluation
                          : experiment.variant_evaluation
                      }
                      variant={tab === "variant"}
                    />
                  </div>
                </>
              ) : null}
              {experiment.proposal ? (
                <section className="proposal">
                  <div className="section-heading">
                    <div>
                      <span className="micro-label">GEMINI’S PROPOSAL</span>
                      <h3>
                        {experiment.proposal.patches.length
                          ? "Small changes. Testable hypotheses."
                          : "No supported changes to test."}
                      </h3>
                    </div>
                    <span className="proposal-glyph" aria-hidden="true">
                      ✧
                    </span>
                  </div>
                  <p>{experiment.proposal.summary}</p>
                  {experiment.proposal.patches.map(({ patch, rationale }) => (
                    <details className="patch" key={patch.patch_id}>
                      <summary>
                        <span>{patch.url}</span>
                        <span className="micro-label">VIEW CHANGE +</span>
                      </summary>
                      <p>{rationale}</p>
                      <div className="patch-diff">
                        <div>
                          <span className="micro-label">− ORIGINAL</span>
                          <pre>{patch.old_text}</pre>
                        </div>
                        <div>
                          <span className="micro-label">+ PROPOSED</span>
                          <pre>{patch.new_text}</pre>
                        </div>
                      </div>
                    </details>
                  ))}
                </section>
              ) : null}
              {tab === "variant" ? (
                <Comparison experiment={experiment} />
              ) : null}
              {experiment.note ? (
                <p className="experiment-note">{experiment.note}</p>
              ) : null}
            </div>
          )}
        </section>
        {!experiment ? (
          <section className="process-notes">
            <div>
              <span>01</span>
              <h3>Watch real agents.</h3>
              <p>
                Your models. Their native tools. Fresh sandboxes for every task.
              </p>
            </div>
            <div>
              <span>02</span>
              <h3>Find the friction.</h3>
              <p>
                Follow each answer back to the evidence and see exactly what
                failed.
              </p>
            </div>
            <div>
              <span>03</span>
              <h3>Measure the change.</h3>
              <p>Test targeted page improvements against the same questions.</p>
            </div>
          </section>
        ) : null}
      </main>
      <footer>
        <Link href="/" className="footer-brand">
          uptrack.
        </Link>
        <span>LESS FRICTION. MORE FORWARD.</span>
        <span>
          BUILT FOR THE AGENT WEB <Arrow diagonal />
        </span>
      </footer>
    </div>
  );
}
