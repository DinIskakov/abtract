"use client";

import React, { useState, useEffect } from "react";
import { ModelOption, BenchmarkStep } from "@/types";
import {
  Play,
  Pause,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Zap,
} from "lucide-react";

const MODELS: ModelOption[] = [
  {
    id: "claude-3-7-sonnet",
    name: "Claude 3.7 Sonnet",
    provider: "Anthropic",
    badge: "Computer Use",
    defaultSuccessA: 48,
    defaultSuccessB: 98,
    tokenCostRatio: "6.1x Cheaper on B",
    avatarColor: "from-amber-500 to-orange-600",
  },
  {
    id: "gemini-2-5-flash",
    name: "Gemini 2.5 Flash",
    provider: "Google",
    badge: "Ultra-Fast Reasoning",
    defaultSuccessA: 41,
    defaultSuccessB: 97,
    tokenCostRatio: "5.8x Cheaper on B",
    avatarColor: "from-blue-500 to-cyan-500",
  },
  {
    id: "gpt-4o",
    name: "GPT-4o",
    provider: "OpenAI",
    badge: "Operator Native",
    defaultSuccessA: 44,
    defaultSuccessB: 95,
    tokenCostRatio: "5.4x Cheaper on B",
    avatarColor: "from-emerald-500 to-green-600",
  },
];

const BENCHMARK_STEPS: BenchmarkStep[] = [
  {
    stepIndex: 1,
    phase: "PERCEPTION",
    description: "Inspect DOM & Build Actionable Tree",
    variantA: {
      state: "DOM Scraped (14,850 tokens)",
      tokens: 14850,
      friction: "DOM_TOKEN_OVERFLOW",
      reasoning:
        "Parsing 38 nested <div> wrappers. Encountered 4 unlabelled <svg> icons and ambiguous 'button' classes.",
      success: false,
    },
    variantB: {
      state: "AXTree Extracted (2,420 tokens)",
      tokens: 2420,
      reasoning:
        "Parsed clean semantic tree. Identified target data-agent-id='pricing-tier-enterprise' instantly.",
      success: true,
    },
  },
  {
    stepIndex: 2,
    phase: "PLANNING",
    description: "Target Identification & Coordinate Grounding",
    variantA: {
      state: "Target Ambiguity Warning",
      tokens: 8200,
      friction: "AMBIGUOUS_AFFORDANCE",
      reasoning:
        "Found two identical unlabelled buttons with class '.btn-primary'. Estimating coordinates from visual bounding box...",
      success: false,
    },
    variantB: {
      state: "Exact Selector Resolved",
      tokens: 950,
      reasoning:
        "Target matched data-agent-id='select-plan-pro'. Zero coordinate guessing required.",
      success: true,
    },
  },
  {
    stepIndex: 3,
    phase: "DISPATCH",
    description: "Action Execution & State Mutation",
    variantA: {
      state: "Misclick & Backtracking",
      tokens: 9400,
      friction: "MISCLICK / BACKTRACKING",
      reasoning:
        "Dispatched click on (x: 482, y: 310). Click fell on non-interactive parent wrapper. Page state did not transition.",
      success: false,
    },
    variantB: {
      state: "Action Dispatched Successfully",
      tokens: 410,
      reasoning:
        "Dispatched click('button[data-agent-id=select-plan-pro]'). Deterministic state change confirmed.",
      success: true,
    },
  },
  {
    stepIndex: 4,
    phase: "EVALUATION",
    description: "Assertion of Goal Predicate",
    variantA: {
      state: "Max Steps / Timeout Exceeded",
      tokens: 32450,
      friction: "FAILED_MAX_STEPS_EXCEEDED",
      reasoning:
        "Agent attempted 4 recovery loops. Token limit approached. Goal not satisfied.",
      success: false,
    },
    variantB: {
      state: "Terminal Success (100% Verified)",
      tokens: 3780,
      reasoning:
        "Target assertion predicate { checkout_step: 'complete' } evaluated TRUE in 3 steps.",
      success: true,
    },
  },
];

export function InteractiveSandbox() {
  const [selectedModel, setSelectedModel] = useState<ModelOption>(MODELS[0]);
  const [activeStep, setActiveStep] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);

  // Auto-play stepper
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (isPlaying) {
      interval = setInterval(() => {
        setActiveStep((prev) => {
          if (prev >= BENCHMARK_STEPS.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 2600);
    }
    return () => clearInterval(interval);
  }, [isPlaying]);

  const handleReset = () => {
    setIsPlaying(false);
    setActiveStep(0);
  };

  const currentStepData = BENCHMARK_STEPS[activeStep];

  return (
    <div
      data-agent-id="interactive-sandbox-container"
      className="w-full max-w-6xl mx-auto rounded-3xl border border-zinc-800 bg-zinc-950/90 shadow-2xl backdrop-blur-xl overflow-hidden"
    >
      {/* Top Bar: Model Selection & Sandbox Header */}
      <div className="p-4 sm:p-6 border-b border-zinc-800/80 bg-zinc-900/40 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
            <h3 className="text-base font-semibold text-zinc-100 flex items-center gap-2">
              Live Agent A/B Benchmark Simulation
            </h3>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700/60">
              Abtract Engine v1.2
            </span>
          </div>
          <p className="text-xs text-zinc-400 mt-1">
            Comparing how leading foundation models navigate Variant A (Legacy DOM) vs Variant B (Agent-Native).
          </p>
        </div>

        {/* Model Selector Tabs */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-zinc-950 border border-zinc-800">
          {MODELS.map((model) => (
            <button
              key={model.id}
              onClick={() => {
                setSelectedModel(model);
                handleReset();
              }}
              data-agent-id={`select-model-${model.id}`}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
                selectedModel.id === model.id
                  ? "bg-zinc-800 text-zinc-100 shadow-sm border border-zinc-700"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full bg-gradient-to-r ${model.avatarColor}`}
              />
              <span>{model.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Stepper Navigation Bar */}
      <div className="px-4 sm:px-6 py-3 border-b border-zinc-800/60 bg-zinc-900/20 flex flex-wrap items-center justify-between gap-3">
        {/* Step dots */}
        <div className="flex items-center gap-2">
          {BENCHMARK_STEPS.map((step, idx) => (
            <button
              key={step.stepIndex}
              onClick={() => setActiveStep(idx)}
              className={`flex items-center gap-2 px-3 py-1 rounded-md text-xs font-mono transition cursor-pointer ${
                idx === activeStep
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                  : idx < activeStep
                  ? "bg-zinc-900 text-zinc-300 border border-zinc-800"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <span className="font-bold">{step.stepIndex}</span>
              <span className="hidden sm:inline text-[11px]">{step.phase}</span>
            </button>
          ))}
        </div>

        {/* Step Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsPlaying(!isPlaying)}
            data-agent-id="sandbox-play-toggle"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-500 hover:bg-emerald-400 text-black font-semibold transition cursor-pointer shadow-md shadow-emerald-500/20"
          >
            {isPlaying ? (
              <>
                <Pause className="w-3.5 h-3.5" /> Pause
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" /> Run Benchmark
              </>
            )}
          </button>
          <button
            onClick={handleReset}
            data-agent-id="sandbox-reset-btn"
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition cursor-pointer"
            title="Reset Simulation"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Dual Variant Canvas */}
      <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-zinc-800">
        {/* Variant A (Legacy DOM) */}
        <div className="p-6 flex flex-col justify-between bg-zinc-950/50">
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30">
                  VARIANT A
                </span>
                <span className="text-sm font-semibold text-zinc-300">
                  Legacy Human DOM
                </span>
              </div>
              <div className="text-right">
                <div className="text-[10px] uppercase font-mono text-zinc-500">
                  Agent Readiness Score
                </div>
                <div className="text-sm font-mono font-bold text-rose-400">
                  ARS: 38/100 (Hostile)
                </div>
              </div>
            </div>

            {/* Simulated Agent Perception Box */}
            <div className="p-4 rounded-2xl bg-zinc-900/60 border border-zinc-800 mb-4 font-mono text-xs">
              <div className="flex items-center justify-between text-zinc-400 pb-2 mb-2 border-b border-zinc-800/80">
                <span className="text-zinc-500">Step {currentStepData.stepIndex}: {currentStepData.phase}</span>
                <span className="text-rose-400/90 font-semibold">
                  {currentStepData.variantA.state}
                </span>
              </div>

              {/* Rationale / Monologue */}
              <div className="space-y-2 text-zinc-300 text-[11px] leading-relaxed">
                <div className="text-zinc-500 text-[10px] uppercase font-semibold">
                  {selectedModel.name} Observation & Reasoning:
                </div>
                <p className="p-2.5 rounded-lg bg-zinc-950/80 border border-zinc-850 text-zinc-300 italic">
                  &ldquo;{currentStepData.variantA.reasoning}&rdquo;
                </p>
              </div>

              {/* Friction Alert */}
              {currentStepData.variantA.friction && (
                <div className="mt-3 flex items-start gap-2 p-2.5 rounded-lg bg-rose-950/30 border border-rose-500/30 text-rose-300 text-[11px]">
                  <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">Friction Event Detected: </span>
                    <span className="font-mono">{currentStepData.variantA.friction}</span>
                  </div>
                </div>
              )}
            </div>

            {/* DOM Visual Mockup A */}
            <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80 text-xs">
              <div className="text-[10px] font-mono text-zinc-500 uppercase mb-2">
                DOM Inspector & Affordances:
              </div>
              <div className="p-3 rounded-lg bg-zinc-950 border border-zinc-800/60 font-mono text-[10px] text-zinc-400 space-y-1 overflow-x-auto">
                <div className="text-rose-400/80">&lt;div className=&quot;flex flex-col relative wrapper-9284&quot;&gt;</div>
                <div className="pl-4 text-zinc-500">&lt;div className=&quot;css-1a2b3c btn-container&quot;&gt;</div>
                <div className="pl-8 text-rose-300 bg-rose-500/10 py-0.5 px-1 rounded">
                  &lt;button className=&quot;btn btn-primary&quot;&gt;
                  <span className="text-zinc-500"> &lt;svg&gt;...&lt;/svg&gt; </span>
                  &lt;/button&gt; <span className="text-rose-400 font-bold">⚠️ [No aria-label, no data-agent-id]</span>
                </div>
                <div className="pl-4 text-zinc-500">&lt;/div&gt;</div>
                <div className="text-rose-400/80">&lt;/div&gt;</div>
              </div>
            </div>
          </div>

          {/* Bottom Telemetry Metrics A */}
          <div className="mt-6 pt-4 border-t border-zinc-800/80 grid grid-cols-3 gap-2 text-center font-mono">
            <div className="p-2 rounded-lg bg-zinc-900/40 border border-zinc-800">
              <div className="text-[10px] text-zinc-500">Cumulative Tokens</div>
              <div className="text-sm font-bold text-rose-400">
                {currentStepData.variantA.tokens.toLocaleString()}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-zinc-900/40 border border-zinc-800">
              <div className="text-[10px] text-zinc-500">Friction Rate</div>
              <div className="text-sm font-bold text-rose-400">75%</div>
            </div>
            <div className="p-2 rounded-lg bg-zinc-900/40 border border-zinc-800">
              <div className="text-[10px] text-zinc-500">Task Completion</div>
              <div className="text-sm font-bold text-rose-400">
                {selectedModel.defaultSuccessA}%
              </div>
            </div>
          </div>
        </div>

        {/* Variant B (Agent-Native) */}
        <div className="p-6 flex flex-col justify-between bg-zinc-950/50">
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  VARIANT B
                </span>
                <span className="text-sm font-semibold text-zinc-100 flex items-center gap-1.5">
                  Abtract Agent-Native DOM
                  <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                </span>
              </div>
              <div className="text-right">
                <div className="text-[10px] uppercase font-mono text-zinc-500">
                  Agent Readiness Score
                </div>
                <div className="text-sm font-mono font-bold text-emerald-400">
                  ARS: 96/100 (Native)
                </div>
              </div>
            </div>

            {/* Simulated Agent Perception Box */}
            <div className="p-4 rounded-2xl bg-emerald-950/10 border border-emerald-500/20 mb-4 font-mono text-xs">
              <div className="flex items-center justify-between text-zinc-400 pb-2 mb-2 border-b border-emerald-500/20">
                <span className="text-zinc-500">Step {currentStepData.stepIndex}: {currentStepData.phase}</span>
                <span className="text-emerald-400 font-semibold flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  {currentStepData.variantB.state}
                </span>
              </div>

              {/* Rationale / Monologue */}
              <div className="space-y-2 text-zinc-300 text-[11px] leading-relaxed">
                <div className="text-zinc-500 text-[10px] uppercase font-semibold">
                  {selectedModel.name} Observation & Reasoning:
                </div>
                <p className="p-2.5 rounded-lg bg-zinc-950/80 border border-emerald-500/30 text-emerald-200 italic">
                  &ldquo;{currentStepData.variantB.reasoning}&rdquo;
                </p>
              </div>

              {/* Optimization Highlight */}
              <div className="mt-3 flex items-center justify-between p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-500/30 text-emerald-300 text-[11px]">
                <div className="flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5 text-emerald-400" />
                  <span>0 Friction Events Detected • Direct Affordance</span>
                </div>
                <span className="font-mono text-emerald-400 font-bold">-84% Tokens</span>
              </div>
            </div>

            {/* DOM Visual Mockup B */}
            <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80 text-xs">
              <div className="text-[10px] font-mono text-zinc-500 uppercase mb-2">
                Abtract Directives Applied:
              </div>
              <div className="p-3 rounded-lg bg-zinc-950 border border-emerald-500/30 font-mono text-[10px] text-zinc-300 space-y-1 overflow-x-auto">
                <div className="text-emerald-400/90 bg-emerald-500/10 py-1 px-2 rounded border border-emerald-500/20">
                  &lt;button
                  <br />
                  &nbsp;&nbsp;<span className="text-cyan-300">data-agent-id=&quot;select-plan-pro&quot;</span>
                  <br />
                  &nbsp;&nbsp;<span className="text-cyan-300">data-agent-action=&quot;subscribe:pro&quot;</span>
                  <br />
                  &nbsp;&nbsp;<span className="text-cyan-300">aria-label=&quot;Subscribe to Pro Plan at $49/mo&quot;</span>
                  <br />
                  &nbsp;&nbsp;<span className="text-cyan-300">aria-live=&quot;polite&quot;</span>&gt;
                  <br />
                  &nbsp;&nbsp;Select Pro Plan
                  <br />
                  &lt;/button&gt;
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Telemetry Metrics B */}
          <div className="mt-6 pt-4 border-t border-zinc-800/80 grid grid-cols-3 gap-2 text-center font-mono">
            <div className="p-2 rounded-lg bg-emerald-950/20 border border-emerald-500/30">
              <div className="text-[10px] text-zinc-400">Cumulative Tokens</div>
              <div className="text-sm font-bold text-emerald-400">
                {currentStepData.variantB.tokens.toLocaleString()}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-emerald-950/20 border border-emerald-500/30">
              <div className="text-[10px] text-zinc-400">Cost Efficiency</div>
              <div className="text-sm font-bold text-emerald-400">
                {selectedModel.tokenCostRatio}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-emerald-950/20 border border-emerald-500/30">
              <div className="text-[10px] text-zinc-400">Task Completion</div>
              <div className="text-sm font-bold text-emerald-400">
                {selectedModel.defaultSuccessB}%
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
