"use client";

import React from "react";
import { ViewMode } from "@/types";
import { DitheringCanvas, PALETTES } from "../shaders/DitheringCanvas";
import { InteractiveSandbox } from "../sandbox/InteractiveSandbox";
import { CodeDiffViewer } from "../diff/CodeDiffViewer";
import { DitheringStudio } from "../shaders/DitheringStudio";
import {
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Zap,
  BarChart3,
  Cpu,
  Layers,
  Terminal,
  Bot,
  Activity,
  CheckCircle,
  ExternalLink,
} from "lucide-react";

interface HumanViewProps {
  onToggleView: (mode: ViewMode) => void;
  backendHealthy: boolean | null;
}

export function HumanView({ onToggleView, backendHealthy }: HumanViewProps) {
  return (
    <div className="flex flex-col w-full min-h-screen text-zinc-100 selection:bg-emerald-500 selection:text-black">
      {/* HERO SECTION */}
      <section className="relative w-full min-h-[90vh] flex items-center justify-center overflow-hidden border-b border-zinc-850 px-4 sm:px-6 lg:px-8 py-20">
        {/* Paper Design Dithering Shader Background */}
        <div className="absolute inset-0 z-0 opacity-45 pointer-events-none">
          <DitheringCanvas
            mode="procedural"
            shape="warp"
            type="4x4"
            size={2.5}
            speed={0.4}
            scale={0.7}
            colorBack="#050d0a"
            colorFront="#10b981"
            className="w-full h-full"
          />
          {/* Vignette & Radial Gradient Overlays */}
          <div className="absolute inset-0 bg-radial from-transparent via-zinc-950/60 to-zinc-950" />
          <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/40 via-transparent to-zinc-950" />
        </div>

        {/* Hero Content */}
        <div className="relative z-10 max-w-5xl mx-auto flex flex-col items-center text-center">
          {/* Top Pill Announcement */}
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border border-emerald-500/30 bg-emerald-950/40 text-emerald-300 text-xs font-mono mb-8 backdrop-blur-md shadow-lg shadow-emerald-500/10">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>The World's First A/B Testing Engine for AI Agents</span>
            <span className="text-zinc-600">•</span>
            <span className="text-zinc-400">Abtract v1.2</span>
          </div>

          {/* Main Headline */}
          <h1 className="text-4xl sm:text-6xl md:text-7xl font-extrabold tracking-tight max-w-4xl leading-[1.1] bg-gradient-to-b from-white via-zinc-100 to-zinc-400 bg-clip-text text-transparent">
            The Web Wasn't Built for Agents.{" "}
            <span className="bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 bg-clip-text text-transparent">
              Until Now.
            </span>
          </h1>

          {/* Subtitle */}
          <p className="mt-6 text-base sm:text-xl text-zinc-300 max-w-2xl leading-relaxed">
            Abtract benchmarks, evaluates, and automatically regenerates web applications for autonomous AI agents — raising task completion from <span className="text-rose-400 font-semibold">42%</span> to <span className="text-emerald-400 font-semibold">98%</span> while slashing DOM token cost by <span className="text-emerald-400 font-semibold">84%</span>.
          </p>

          {/* CTAs */}
          <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <a
              href="#sandbox"
              data-agent-id="hero-cta-sandbox"
              data-agent-action="scroll_to:sandbox"
              className="flex items-center gap-2 px-6 py-3.5 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-black font-bold text-sm tracking-wide shadow-xl shadow-emerald-500/25 transition-all transform hover:-translate-y-0.5 cursor-pointer"
            >
              <span>Explore Live A/B Sandbox</span>
              <ArrowRight className="w-4 h-4" />
            </a>

            <button
              type="button"
              data-agent-id="hero-cta-agent-view"
              data-agent-action="switch_view_mode:agent"
              onClick={() => onToggleView("agent")}
              className="flex items-center gap-2 px-6 py-3.5 rounded-2xl bg-zinc-900/80 hover:bg-zinc-800 text-zinc-200 border border-zinc-700/80 font-medium text-sm backdrop-blur-md transition-all cursor-pointer shadow-lg"
            >
              <Bot className="w-4 h-4 text-cyan-400" />
              <span>Switch to Agent View</span>
              <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-[10px] font-mono text-zinc-400 ml-1">
                V
              </kbd>
            </button>
          </div>

          {/* Metrics Teaser */}
          <div className="mt-16 grid grid-cols-2 sm:grid-cols-4 gap-4 sm:gap-6 w-full max-w-4xl text-left">
            <div className="p-4 rounded-2xl bg-zinc-900/50 border border-zinc-800/80 backdrop-blur-sm">
              <div className="text-[11px] font-mono uppercase text-zinc-500">Task Completion</div>
              <div className="text-2xl sm:text-3xl font-extrabold text-emerald-400 mt-1">4.2x</div>
              <div className="text-[11px] text-zinc-400 mt-0.5">Average benchmark lift</div>
            </div>

            <div className="p-4 rounded-2xl bg-zinc-900/50 border border-zinc-800/80 backdrop-blur-sm">
              <div className="text-[11px] font-mono uppercase text-zinc-500">Token Reduction</div>
              <div className="text-2xl sm:text-3xl font-extrabold text-cyan-400 mt-1">-84%</div>
              <div className="text-[11px] text-zinc-400 mt-0.5">Context window savings</div>
            </div>

            <div className="p-4 rounded-2xl bg-zinc-900/50 border border-zinc-800/80 backdrop-blur-sm">
              <div className="text-[11px] font-mono uppercase text-zinc-500">Agent Readiness</div>
              <div className="text-2xl sm:text-3xl font-extrabold text-amber-400 mt-1">96 / 100</div>
              <div className="text-[11px] text-zinc-400 mt-0.5">Composite ARS rating</div>
            </div>

            <div className="p-4 rounded-2xl bg-zinc-900/50 border border-zinc-800/80 backdrop-blur-sm">
              <div className="text-[11px] font-mono uppercase text-zinc-500">Model Coverage</div>
              <div className="text-2xl sm:text-3xl font-extrabold text-purple-400 mt-1">All LLMs</div>
              <div className="text-[11px] text-zinc-400 mt-0.5">Claude, Gemini, GPT-4o</div>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 2: LIVE A/B BENCHMARK SANDBOX */}
      <section id="sandbox" className="w-full py-24 px-4 sm:px-6 lg:px-8 border-b border-zinc-850 bg-zinc-950 relative">
        <div className="max-w-6xl mx-auto mb-12 text-center">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs font-mono mb-4">
            <Zap className="w-3.5 h-3.5" /> Interactive Sandbox
          </div>
          <h2 className="text-3xl sm:text-5xl font-bold tracking-tight text-zinc-100">
            See Agents Run Variant A vs Variant B
          </h2>
          <p className="mt-4 text-zinc-400 max-w-2xl mx-auto text-sm sm:text-base">
            Watch autonomous agents attempt standard e-commerce and SaaS workflows. Witness friction events on legacy markup disappear under Abtract's agent-native regenerations.
          </p>
        </div>

        <InteractiveSandbox />
      </section>

      {/* SECTION 3: THE 3-LAYER EVALUATION FRAMEWORK */}
      <section className="w-full py-24 px-4 sm:px-6 lg:px-8 border-b border-zinc-850 bg-gradient-to-b from-zinc-950 via-zinc-900/30 to-zinc-950">
        <div className="max-w-6xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-16">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 text-xs font-mono mb-4">
              <Layers className="w-3.5 h-3.5" /> Scientific Measurement
            </div>
            <h2 className="text-3xl sm:text-5xl font-bold tracking-tight text-zinc-100">
              The 3-Layer Evaluation Framework
            </h2>
            <p className="mt-4 text-zinc-400 text-sm sm:text-base">
              Abtract doesn't just guess whether an agent can use your website. It executes multi-step telemetry across three rigorous layers.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Layer 1 */}
            <div className="p-6 rounded-3xl bg-zinc-900/50 border border-zinc-800 flex flex-col justify-between hover:border-zinc-700 transition">
              <div>
                <div className="w-10 h-10 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 flex items-center justify-center font-mono font-bold text-sm mb-4">
                  01
                </div>
                <h3 className="text-lg font-bold text-zinc-100 mb-2">
                  Layer 1: A2A Usability Metrics
                </h3>
                <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                  Evaluates accessibility from the perspective of an LLM agent perceiving the DOM.
                </p>
                <ul className="space-y-2 text-xs font-mono text-zinc-300">
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span><strong>SAI:</strong> Semantic Affordance Index</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span><strong>DTE:</strong> DOM Token Efficiency</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span><strong>VGS:</strong> Visual Groundability Score</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span><strong>STD:</strong> State Transition Determinism</span>
                  </li>
                </ul>
              </div>
              <div className="mt-6 pt-4 border-t border-zinc-800 text-[11px] font-mono text-emerald-400">
                Pydantic contract: A2AEvalMetrics
              </div>
            </div>

            {/* Layer 2 */}
            <div className="p-6 rounded-3xl bg-zinc-900/50 border border-zinc-800 flex flex-col justify-between hover:border-zinc-700 transition">
              <div>
                <div className="w-10 h-10 rounded-2xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 flex items-center justify-center font-mono font-bold text-sm mb-4">
                  02
                </div>
                <h3 className="text-lg font-bold text-zinc-100 mb-2">
                  Layer 2: Comparative A/B Telemetry
                </h3>
                <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                  Side-by-side execution across sandboxed browser episodes, measuring speed and inference cost.
                </p>
                <ul className="space-y-2 text-xs font-mono text-zinc-300">
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                    <span><strong>Friction Hotspots:</strong> Misclicks & loops</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                    <span><strong>Inference Latency:</strong> Wall-clock ms</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                    <span><strong>Cost Allocation:</strong> USD / episode</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                    <span><strong>Trajectory Graph:</strong> Episode step logs</span>
                  </li>
                </ul>
              </div>
              <div className="mt-6 pt-4 border-t border-zinc-800 text-[11px] font-mono text-cyan-400">
                Pydantic contract: SandboxEpisodeContract
              </div>
            </div>

            {/* Layer 3 */}
            <div className="p-6 rounded-3xl bg-zinc-900/50 border border-zinc-800 flex flex-col justify-between hover:border-zinc-700 transition">
              <div>
                <div className="w-10 h-10 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-400 flex items-center justify-center font-mono font-bold text-sm mb-4">
                  03
                </div>
                <h3 className="text-lg font-bold text-zinc-100 mb-2">
                  Layer 3: Composite ARS Score
                </h3>
                <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                  A unified 0-100 benchmark score classifying application agent-friendliness into four distinct tiers.
                </p>
                <div className="space-y-2 text-xs font-mono">
                  <div className="flex items-center justify-between p-1.5 rounded bg-zinc-950 border border-emerald-500/30 text-emerald-300">
                    <span>Agent-Native</span>
                    <span className="font-bold">90 - 100</span>
                  </div>
                  <div className="flex items-center justify-between p-1.5 rounded bg-zinc-950 border border-cyan-500/30 text-cyan-300">
                    <span>Agent-Ready</span>
                    <span className="font-bold">70 - 89</span>
                  </div>
                  <div className="flex items-center justify-between p-1.5 rounded bg-zinc-950 border border-amber-500/30 text-amber-300">
                    <span>Agent-Fragile</span>
                    <span className="font-bold">50 - 69</span>
                  </div>
                  <div className="flex items-center justify-between p-1.5 rounded bg-zinc-950 border border-rose-500/30 text-rose-300">
                    <span>Agent-Hostile</span>
                    <span className="font-bold">&lt; 50</span>
                  </div>
                </div>
              </div>
              <div className="mt-6 pt-4 border-t border-zinc-800 text-[11px] font-mono text-amber-400">
                Pydantic contract: AgentReadinessScore
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 4: CODE REGENERATION & PATCHES */}
      <section className="w-full py-24 px-4 sm:px-6 lg:px-8 border-b border-zinc-850 bg-zinc-950">
        <div className="max-w-6xl mx-auto mb-12 text-center">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 text-xs font-mono mb-4">
            <Cpu className="w-3.5 h-3.5" /> Step 5 Engine
          </div>
          <h2 className="text-3xl sm:text-5xl font-bold tracking-tight text-zinc-100">
            Autonomous Design Regeneration
          </h2>
          <p className="mt-4 text-zinc-400 max-w-2xl mx-auto text-sm sm:text-base">
            Abtract doesn't just find issues; it generates deterministic code patches with exact JSX/HTML directives to upgrade your app into Variant B.
          </p>
        </div>

        <CodeDiffViewer />
      </section>

      {/* SECTION 5: PAPER DESIGN DITHERING SHADER STUDIO */}
      <section className="w-full py-24 px-4 sm:px-6 lg:px-8 border-b border-zinc-850 bg-gradient-to-b from-zinc-950 via-zinc-900/40 to-zinc-950">
        <div className="max-w-6xl mx-auto mb-12 text-center">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs font-mono mb-4">
            <Sparkles className="w-3.5 h-3.5" /> Visual Dithering Shaders
          </div>
          <h2 className="text-3xl sm:text-5xl font-bold tracking-tight text-zinc-100">
            Paper Design Dithering Studio
          </h2>
          <p className="mt-4 text-zinc-400 max-w-2xl mx-auto text-sm sm:text-base">
            Powered by <a href="https://shaders.paper.design" target="_blank" rel="noopener noreferrer" className="text-emerald-400 underline underline-offset-4 hover:text-emerald-300">shaders.paper.design</a> WebGL2 dithering shaders. Interactive matrix controls, Bayer 4x4 & 8x8 grids, and cyber color palettes.
          </p>
        </div>

        <DitheringStudio />
      </section>

      {/* SECTION 6: BACKEND & FULLSTACK ARCHITECTURE STATUS */}
      <section className="w-full py-20 px-4 sm:px-6 lg:px-8 bg-zinc-950 border-b border-zinc-850">
        <div className="max-w-4xl mx-auto p-6 sm:p-8 rounded-3xl border border-zinc-800 bg-zinc-900/40 backdrop-blur-xl">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-zinc-800">
            <div>
              <h3 className="text-base font-bold text-zinc-100 font-mono">
                Fullstack Monorepo Health & Backend Connectivity
              </h3>
              <p className="text-xs text-zinc-400 mt-1">
                FastAPI Pydantic v2 engine connected via Next.js proxy rewrite.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  backendHealthy ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
                }`}
              />
              <span className="text-xs font-mono text-zinc-300">
                {backendHealthy ? "FastAPI Online" : "FastAPI Standby"}
              </span>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4 font-mono text-xs">
            <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-850">
              <div className="text-zinc-500 text-[10px]">FastAPI Router</div>
              <div className="text-emerald-400 font-semibold mt-0.5">/api/health</div>
              <div className="text-[10px] text-zinc-500 mt-1">Uvicorn + uv sync</div>
            </div>
            <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-850">
              <div className="text-zinc-500 text-[10px]">OpenAPI Schema</div>
              <div className="text-cyan-400 font-semibold mt-0.5">/docs</div>
              <div className="text-[10px] text-zinc-500 mt-1">Interactive Swagger UI</div>
            </div>
            <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-850">
              <div className="text-zinc-500 text-[10px]">Monorepo Tools</div>
              <div className="text-purple-400 font-semibold mt-0.5">Turborepo + mise</div>
              <div className="text-[10px] text-zinc-500 mt-1">Bun + uv unified CLI</div>
            </div>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="w-full py-12 px-4 sm:px-6 lg:px-8 bg-zinc-950 text-zinc-500 text-xs">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-gradient-to-tr from-emerald-500 to-cyan-500 text-black font-mono font-bold flex items-center justify-center text-xs">
              A
            </div>
            <span className="text-zinc-300 font-semibold">Abtract Agent A/B Platform</span>
            <span>• Next.js 16 + FastAPI + Paper Shaders</span>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={() => onToggleView("agent")}
              className="text-emerald-400 hover:text-emerald-300 font-mono text-xs flex items-center gap-1.5 transition cursor-pointer"
            >
              <Bot className="w-3.5 h-3.5" />
              <span>Switch to Agent View (Press 'V')</span>
            </button>
            <span>•</span>
            <a href="/docs" target="_blank" rel="noopener noreferrer" className="hover:text-zinc-300">
              API Docs
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
