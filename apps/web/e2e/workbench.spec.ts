import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import type {
  EvaluationReport,
  Experiment,
  ExperimentOptions,
  ExperimentRequest,
  HarnessConfig,
  RunResult,
} from "../src/lib/types";

// These are isolated browser fixtures, never product data or live agent results.
const screenshots = resolve(process.cwd(), "../../docs/frontend-smoke");
mkdirSync(screenshots, { recursive: true });
const url = "https://example.test/docs/sandboxes";
const harnesses: HarnessConfig[] = [
  { name: "codex", model: "gpt-5.4-mini" },
  { name: "gemini", model: "gemini-3-flash-preview" },
];
const options: ExperimentOptions = {
  supervisor: { name: "gemini", model: "gemini-3-flash-preview", available: true },
  harnesses: [
    { ...harnesses[0], id: "codex-mini", label: "GPT-5.4 mini", available: true, reason: null },
    { ...harnesses[1], id: "gemini-flash", label: "Gemini Flash", available: true, reason: null },
    { id: "claude", name: "claude", model: "claude-sonnet-4-6", label: "Sonnet", available: false, reason: "API key needed" },
  ],
};
const tasks = ["How do I create a sandbox?", "How do I set its timeout?", "How do I read a file?"]
  .map((task, task_index) => ({
    task_id: `task-${task_index}`, task_index, task,
    criteria: [{ id: "correctness", kind: "llm_judge", description: "The answer follows the documented API." }],
  }));

function runs(variant: boolean): RunResult[] {
  return tasks.flatMap(task => harnesses.map((harness, index) => ({
    run_id: `${variant ? "b" : "a"}-${task.task_index}-${index}`,
    sandbox_id: `sb-fixture-${variant ? "b" : "a"}-${task.task_index}-${index}`,
    task: task.task, task_index: task.task_index, repetition: 1, harness,
    harness_version: "fixture-version", status: "completed", duration_seconds: 12,
    execution_duration_seconds: 10, variant_id: variant ? "variant-fixture" : "baseline",
    telemetry: {
      tokens: { input_tokens: 1000, cached_input_tokens: 100, output_tokens: 200, reasoning_output_tokens: null },
      models_reported: [harness.model!], tool_calls: 2, failed_tool_calls: 0,
      estimated_cost_usd: 0.002, cost_source: "token_price_estimate", trace_complete: true,
    },
    report: { answer: variant ? "Initialize the application before creating the sandbox." : "Create a sandbox from an uninitialized app.", actions: ["Read documentation"], sources: [url], limitations: [] },
    error: null,
    observations: { capture_http: true, applied_patch_ids: [], unobserved_patch_ids: variant ? ["patch-fixture"] : [], capture_error: null, coverage: "sandbox HTTP only" },
  })));
}

function evaluation(variant: boolean): EvaluationReport {
  return {
    evaluation_id: variant ? "eval-b" : "eval-a", grader_version: "fixture-grader",
    passed: variant ? 6 : 5, failed: variant ? 0 : 1, unknown: 0,
    runs: runs(variant).map((run, index) => {
      const failed = !variant && index === 0;
      return {
        run_id: run.run_id, task_id: `task-${run.task_index}`, task_index: run.task_index,
        outcome: failed ? "fail" : "pass",
        checks: [{
          check_id: "correctness", kind: "llm_judge", description: "The answer follows the documented API.",
          outcome: failed ? "fail" : "pass", method: "llm_judge", error: null,
          reason: failed ? "The answer creates a sandbox with an uninitialized application." : "The answer matches the documented setup.",
          evidence: failed ? ["Create a sandbox from an uninitialized app."] : ["Initialize the application first."],
        }],
        variant_exposure: variant ? "unverified" : "baseline",
        variant_attribution_eligible: false,
        variant_exposure_note: variant ? "No modified response was observed." : "Original page.",
      };
    }),
  };
}

function experiment(phase: Experiment["phase"]): Experiment {
  const baselineReady = ["proposing", "variant", "completed"].includes(phase);
  const patchReady = ["variant", "completed"].includes(phase);
  return {
    experiment_id: "browser-fixture", url, phase,
    created_at: "2026-09-19T12:00:00Z", updated_at: "2026-09-19T12:01:00Z",
    tasks: phase === "planning" ? [] : tasks, harnesses,
    baseline_runs: baselineReady ? runs(false) : [],
    baseline_evaluation: baselineReady ? evaluation(false) : null,
    proposal: patchReady ? {
      proposal_id: "proposal-fixture", evaluation_id: "eval-a", variant_id: "variant-fixture",
      variant_sha256: "b".repeat(64), summary: "Clarify application initialization before sandbox creation.",
      patches: [{ patch: { patch_id: "patch-fixture", url, expected_sha256: "a".repeat(64), old_text: "Create an app.", new_text: "Look up an initialized app before creating a sandbox." }, rationale: "The baseline answer omitted required initialization.", failed_check_refs: ["a-0-0:correctness"] }],
      interpretation: "A hypothesis to verify with independent tasks.",
    } : null,
    variant_runs: phase === "completed" ? runs(true) : [],
    variant_evaluation: phase === "completed" ? evaluation(true) : null,
    error: null, note: null, concurrency: 6,
  };
}

async function mockOptions(page: Page) {
  await page.route("**/api/experiments/options", route => route.fulfill({ json: options }));
}

test("runs the full matrix and shows failure evidence, patches, and unverified comparisons", async ({ page }) => {
  let phase: Experiment["phase"] = "planning";
  let submitted: ExperimentRequest | undefined;
  await mockOptions(page);
  await page.route("**/api/experiments", async route => {
    submitted = route.request().postDataJSON() as ExperimentRequest;
    await route.fulfill({ status: 202, json: experiment(phase) });
  });
  await page.route("**/api/experiments/browser-fixture", route => route.fulfill({ json: experiment(phase) }));
  await page.goto("/");
  await expect(page.getByRole("checkbox", { name: /Claude Code/ })).toBeDisabled();
  await expect(page.getByText("6 parallel sandboxes", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: /Gemini CLI/ }).uncheck();
  await expect(page.getByText("3 parallel sandboxes", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: /Gemini CLI/ }).check();
  await page.getByLabel("Product or documentation URL").fill(url);
  await page.getByLabel("Task difficulty").selectOption("medium");
  await page.getByLabel("Agent time target (seconds)").fill("20");
  await page.screenshot({ path: resolve(screenshots, "configure-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Run experiment" }).click();
  await expect(page.getByRole("status")).toContainText("Gemini is getting to know your product");
  expect(submitted).toEqual({ url, harnesses, task_count: 3, difficulty: "medium", latency_budget_seconds: 20 });
  // The backend derives maximum concurrency from this matrix; the client never sends a smaller cap.
  expect(submitted).not.toHaveProperty("max_concurrency");
  phase = "baseline";
  await expect(page.getByRole("status")).toContainText("Agents are exploring your original page");
  await page.getByText("Gemini’s test plan", { exact: true }).click();
  await expect(page.locator(".task-plan li")).toHaveCount(3);
  phase = "proposing";
  await expect(page.getByRole("status")).toContainText("Gemini is looking for a better version");
  await page.locator(".run-card summary").first().click();
  await expect(page.getByText("The answer creates a sandbox with an uninitialized application.")).toBeVisible();
  await expect(page.locator("blockquote").first()).toHaveText("Create a sandbox from an uninitialized app.");
  await page.screenshot({ path: resolve(screenshots, "baseline-desktop.png"), fullPage: true });
  phase = "variant";
  await expect(page.getByRole("status")).toContainText("Agents are testing the proposed changes");
  await page.getByText("VIEW CHANGE +", { exact: true }).click();
  await expect(page.locator(".patch-diff")).toContainText("Create an app.");
  await expect(page.locator(".patch-diff")).toContainText("Look up an initialized app before creating a sandbox.");
  phase = "completed";
  await expect(page.getByRole("status")).toContainText("Your experiment is complete");
  await expect(page.getByRole("tab", { name: /Improved version/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".comparison-row")).toHaveCount(6);
  await expect(page.getByText("Exposure unverified", { exact: true })).toHaveCount(6);
  await page.locator(".run-card summary").first().click();
  await expect(page.getByText("Patch exposure unverified. Do not attribute this answer to the changes.").first()).toBeVisible();
  await page.screenshot({ path: resolve(screenshots, "comparison-desktop.png"), fullPage: true });
  await page.reload();
  await expect(page.getByRole("status")).toContainText("Your experiment is complete");
  await expect(page.getByRole("tab", { name: /Improved version/ })).toHaveAttribute("aria-selected", "true");
});

test("shows backend launch errors without fabricated report data", async ({ page }) => {
  await mockOptions(page);
  await page.route("**/api/experiments", route => route.fulfill({ status: 503, json: { detail: "Gemini supervisor quota exhausted. Try again later." } }));
  await page.goto("/");
  await page.getByLabel("Product or documentation URL").fill(url);
  await page.getByRole("button", { name: "Run experiment" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Gemini supervisor quota exhausted" })).toHaveText("Gemini supervisor quota exhausted. Try again later.");
  await expect(page.getByRole("button", { name: "Run experiment" })).toBeEnabled();
  await expect(page.getByRole("tabpanel")).toHaveCount(0);
});

test("remains usable on mobile with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockOptions(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Run experiment" })).toBeEnabled();
  await page.getByLabel("Product or documentation URL").fill(url);
  await page.getByLabel("Quick test").selectOption("1");
  await expect(page.getByText("2 parallel sandboxes", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const motion = await page.locator(".moving-grid").evaluate(element => {
    const style = getComputedStyle(element);
    return { animation: style.animationDuration, transition: style.transitionDuration };
  });
  expect(parseFloat(motion.animation)).toBeLessThanOrEqual(0.01);
  expect(parseFloat(motion.transition)).toBeLessThanOrEqual(0.01);
  await page.screenshot({ path: resolve(screenshots, "configure-mobile.png"), fullPage: true });
  await page.route("**/api/experiments/browser-fixture", route => route.fulfill({ json: experiment("completed") }));
  await page.evaluate(() => localStorage.setItem("uptrack.experiment.v1", "browser-fixture"));
  await page.reload();
  await expect(page.getByRole("status")).toContainText("Your experiment is complete");
  await page.locator(".run-card summary").first().click();
  await page.getByText("VIEW CHANGE +", { exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: resolve(screenshots, "comparison-mobile.png"), fullPage: true });
});

test("shows a correct but slow baseline and a verified faster variant separately", async ({ page }) => {
  const completed = experiment("completed");
  completed.difficulty = "hard";
  completed.latency_budget_seconds = 15;
  for (const run of completed.baseline_runs) run.execution_duration_seconds = 20;
  for (const [report, slow] of [[completed.baseline_evaluation!, true], [completed.variant_evaluation!, false]] as const) {
    report.passed = slow ? 0 : 6;
    report.failed = slow ? 6 : 0;
    for (const result of report.runs) {
      result.outcome = slow ? "fail" : "pass";
      result.variant_attribution_eligible = true;
      result.checks[0].outcome = "pass";
      result.checks.push({ check_id: "agent-time", kind: "execution_duration_budget", description: "Agent time target", outcome: slow ? "fail" : "pass", reason: slow ? "20 seconds exceeds the 15 second target." : "10 seconds meets the 15 second target.", evidence: [], method: "deterministic", error: null });
    }
  }
  await mockOptions(page);
  await page.route("**/api/experiments/browser-fixture", route => route.fulfill({ json: completed }));
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("uptrack.experiment.v1", "browser-fixture"));
  await page.reload();
  await expect(page.getByText("hard difficulty", { exact: true })).toBeVisible();
  await expect(page.getByText("Faster, correctness preserved", { exact: true })).toHaveCount(6);
  await expect(page.getByText("-10.0s (-50.0%)", { exact: true })).toHaveCount(6);
  await page.getByRole("tab", { name: /Original page/ }).click();
  await expect(page.locator(".metric-grid > div").first()).toContainText("6/6");
  await expect(page.locator(".metric-grid")).toContainText("6 over target · startup excluded");
  await page.locator(".run-card summary").first().click();
  await expect(page.getByText("Answer checks: passed. Agent time exceeded the target.").first()).toBeVisible();
});
