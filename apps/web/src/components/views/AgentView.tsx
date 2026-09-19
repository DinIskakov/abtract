"use client";

import React, { useState } from "react";
import { ViewMode, Affordance } from "@/types";
import {
  Bot,
  Terminal,
  Cpu,
  Copy,
  Check,
  Send,
  Eye,
  Layers,
  FileCode,
  Shield,
  Activity,
  Sparkles,
  Zap,
} from "lucide-react";

interface AgentViewProps {
  onToggleView: (mode: ViewMode) => void;
  backendHealthy: boolean | null;
}

const AFFORDANCE_REGISTRY: Affordance[] = [
  {
    element_id: "affordance-01",
    tag_name: "button",
    role: "button",
    accessible_name: "Switch to Human View (Visual + Shaders)",
    css_selector: "button[data-agent-id='toggle-human-view']",
    bounding_box: { x: 580, y: 16, width: 120, height: 36 },
    data_agent_id: "toggle-human-view",
    data_agent_action: "switch_view_mode:human",
    aria_live: "polite",
  },
  {
    element_id: "affordance-02",
    tag_name: "button",
    role: "button",
    accessible_name: "Run Live Agent Benchmark on Sandbox",
    css_selector: "button[data-agent-id='sandbox-play-toggle']",
    bounding_box: { x: 920, y: 720, width: 140, height: 40 },
    data_agent_id: "sandbox-play-toggle",
    data_agent_action: "execute_benchmark_suite",
    aria_live: "assertive",
  },
  {
    element_id: "affordance-03",
    tag_name: "button",
    role: "tab",
    accessible_name: "Select Claude 3.7 Sonnet Model Suite",
    css_selector: "button[data-agent-id='select-model-claude-3-7-sonnet']",
    bounding_box: { x: 740, y: 680, width: 150, height: 32 },
    data_agent_id: "select-model-claude-3-7-sonnet",
    data_agent_action: "set_benchmark_model:claude-3-7-sonnet",
  },
  {
    element_id: "affordance-04",
    tag_name: "button",
    role: "tab",
    accessible_name: "Select Gemini 2.5 Flash Model Suite",
    css_selector: "button[data-agent-id='select-model-gemini-2-5-flash']",
    bounding_box: { x: 900, y: 680, width: 145, height: 32 },
    data_agent_id: "select-model-gemini-2-5-flash",
    data_agent_action: "set_benchmark_model:gemini-2-5-flash",
  },
  {
    element_id: "affordance-05",
    tag_name: "a",
    role: "link",
    accessible_name: "Fetch OpenAPI v3 Swagger Documentation",
    css_selector: "a[data-agent-id='nav-api-docs-link']",
    bounding_box: { x: 1140, y: 16, width: 110, height: 36 },
    data_agent_id: "nav-api-docs-link",
    data_agent_action: "navigate:/docs",
  },
  {
    element_id: "affordance-06",
    tag_name: "button",
    role: "button",
    accessible_name: "Apply inject_data_agent_id Code Patch",
    css_selector: "button[data-agent-id='select-diff-inject_data_agent_id']",
    bounding_box: { x: 800, y: 1400, width: 160, height: 34 },
    data_agent_id: "select-diff-inject_data_agent_id",
    data_agent_action: "preview_directive:inject_data_agent_id",
  },
];

const MCP_TOOL_SPEC = {
  name: "abtract_benchmark_suite",
  description:
    "Dispatches sandboxed autonomous browser episodes comparing Variant A (Baseline) vs Variant B (Candidate) and returns ARS readiness telemetry.",
  parameters: {
    type: "object",
    properties: {
      target_url: {
        type: "string",
        description: "Target web URL to benchmark.",
      },
      agent_model: {
        type: "string",
        enum: ["claude-3-7-sonnet", "gemini-2-5-flash", "gpt-4o"],
        description: "Autonomous browser foundation model.",
      },
      task_instruction: {
        type: "string",
        description: "Goal predicate instruction for the agent.",
      },
      max_steps: {
        type: "integer",
        default: 25,
      },
    },
    required: ["target_url", "agent_model", "task_instruction"],
  },
};

export function AgentView({ onToggleView, backendHealthy }: AgentViewProps) {
  const [selectedActionType, setSelectedActionType] = useState<string>("click");
  const [targetSelector, setTargetSelector] = useState<string>(
    "button[data-agent-id='sandbox-play-toggle']"
  );
  const [inputValue, setInputValue] = useState<string>("");
  const [executionOutput, setExecutionOutput] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const handleCopy = (key: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleDispatchAction = () => {
    setIsExecuting(true);
    setExecutionOutput(null);

    setTimeout(() => {
      const response = {
        step_index: 1,
        timestamp: new Date().toISOString(),
        action_dispatched: {
          action_type: selectedActionType,
          target_selector: targetSelector,
          input_value: inputValue || null,
        },
        duration_ms: 124.6,
        action_succeeded: true,
        state_changed: true,
        friction_detected: [],
        telemetry: {
          prompt_tokens: 340,
          completion_tokens: 42,
          inference_latency_ms: 310,
          estimated_cost_usd: 0.00045,
        },
        observation_after: {
          url: "http://localhost:3000/#sandbox",
          page_title: "Abtract - Agent A/B Platform",
          interactive_elements_count: 6,
          accessibility_tree_status: "SYNCHRONIZED",
          dom_token_reduction_pct: 84.2,
        },
      };

      setExecutionOutput(JSON.stringify(response, null, 2));
      setIsExecuting(false);
    }, 400);
  };

  return (
    <div
      data-agent-view="active"
      className="w-full min-h-screen bg-black text-cyan-400 font-mono text-xs selection:bg-cyan-500 selection:text-black p-4 sm:p-6 lg:p-10"
    >
      <div className="max-w-6xl mx-auto space-y-8">
        {/* TOP STATUS BANNER (TOKEN SAVINGS & AGENT MANIFEST) */}
        <div className="p-4 rounded-xl border border-cyan-500/30 bg-cyan-950/20 backdrop-blur-md flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 flex items-center justify-center font-bold">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm text-white tracking-tight">
                  AGENT COCKPIT MODE: ACTIVE
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                  PROTOCOL v1.2
                </span>
              </div>
              <p className="text-[11px] text-zinc-400 mt-0.5">
                Zero styling bloat • Quantized AXTree semantic affordances • Deterministic target grounding.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="px-3 py-1.5 rounded-lg bg-black border border-cyan-500/40 text-center">
              <div className="text-[9px] text-zinc-500 uppercase">Context Reduction</div>
              <div className="text-emerald-400 font-bold text-sm">-93.9% Tokens</div>
            </div>

            <button
              onClick={() => onToggleView("human")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-zinc-700 transition cursor-pointer"
            >
              <Eye className="w-3.5 h-3.5 text-emerald-400" />
              <span>Switch to Human View</span>
              <kbd className="px-1 py-0.5 rounded bg-zinc-800 text-[9px] text-zinc-400">V</kbd>
            </button>
          </div>
        </div>

        {/* SYSTEM PROTOCOL METADATA & LLMS.TXT */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-950">
            <div className="text-zinc-500 text-[10px] uppercase font-semibold">Endpoint Protocol</div>
            <div className="text-white font-bold mt-1 text-sm">/.well-known/agent-protocol</div>
            <div className="text-zinc-400 text-[11px] mt-1">Machine-readable capability discovery</div>
          </div>

          <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-950">
            <div className="text-zinc-500 text-[10px] uppercase font-semibold">FastAPI Engine</div>
            <div className="text-white font-bold mt-1 text-sm flex items-center gap-2">
              <span>{backendHealthy ? "ONLINE (Port 8000)" : "LOCAL PROXY"}</span>
              <span className={`w-2 h-2 rounded-full ${backendHealthy ? "bg-emerald-400" : "bg-amber-400"}`} />
            </div>
            <div className="text-zinc-400 text-[11px] mt-1">Contracts: Pydantic v2 schemas</div>
          </div>

          <div className="p-4 rounded-xl border border-zinc-800 bg-zinc-950">
            <div className="text-zinc-500 text-[10px] uppercase font-semibold">Evaluation Mode</div>
            <div className="text-white font-bold mt-1 text-sm">A2A + ARS Composite</div>
            <div className="text-zinc-400 text-[11px] mt-1">Multi-model benchmark active</div>
          </div>
        </div>

        {/* SECTION 1: ACTIONABLE AFFORDANCE MAP (ACCESSIBILITY TREE) */}
        <div className="rounded-2xl border border-zinc-800 bg-zinc-950 overflow-hidden">
          <div className="p-4 bg-zinc-900/60 border-b border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-cyan-400" />
              <h3 className="font-bold text-zinc-100 text-sm">
                Actionable Affordance Registry (AXTree)
              </h3>
              <span className="text-zinc-500 text-[11px]">
                ({AFFORDANCE_REGISTRY.length} registered targets)
              </span>
            </div>
            <button
              onClick={() =>
                handleCopy("affordances", JSON.stringify(AFFORDANCE_REGISTRY, null, 2))
              }
              className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white transition cursor-pointer"
            >
              {copiedKey === "affordances" ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Copied JSON</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy Registry</span>
                </>
              )}
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-zinc-850 text-[10px] uppercase text-zinc-500 bg-zinc-900/20">
                  <th className="p-3">Data-Agent-ID</th>
                  <th className="p-3">Role</th>
                  <th className="p-3">Accessible Name</th>
                  <th className="p-3">CSS Selector</th>
                  <th className="p-3">Action</th>
                  <th className="p-3">Actionable</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-850 text-[11px]">
                {AFFORDANCE_REGISTRY.map((aff) => (
                  <tr
                    key={aff.element_id}
                    className="hover:bg-cyan-950/20 transition group"
                  >
                    <td className="p-3 font-bold text-cyan-300">
                      {aff.data_agent_id}
                    </td>
                    <td className="p-3 text-zinc-400">
                      <span className="px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-800">
                        {aff.role}
                      </span>
                    </td>
                    <td className="p-3 text-zinc-200">{aff.accessible_name}</td>
                    <td className="p-3 text-zinc-400 text-[10px] font-mono">
                      {aff.css_selector}
                    </td>
                    <td className="p-3 text-emerald-400 text-[10px]">
                      {aff.data_agent_action}
                    </td>
                    <td className="p-3">
                      <button
                        onClick={() => {
                          setTargetSelector(aff.css_selector);
                          setSelectedActionType(
                            aff.tag_name === "input" ? "type_text" : "click"
                          );
                        }}
                        className="px-2 py-1 rounded bg-zinc-850 hover:bg-cyan-500 hover:text-black text-cyan-400 transition cursor-pointer text-[10px]"
                      >
                        Ground
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* SECTION 2: INTERACTIVE AGENT ACTION DISPATCHER (REPL) */}
        <div className="rounded-2xl border border-zinc-800 bg-zinc-950 overflow-hidden">
          <div className="p-4 bg-zinc-900/60 border-b border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-emerald-400" />
              <h3 className="font-bold text-zinc-100 text-sm">
                Interactive Action Dispatcher (Agent REPL)
              </h3>
            </div>
            <span className="text-[10px] text-zinc-500">
              Dispatches deterministic StepTelemetry
            </span>
          </div>

          <div className="p-4 sm:p-6 space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="text-[10px] uppercase text-zinc-500 mb-1 block">
                  Action Type
                </label>
                <select
                  value={selectedActionType}
                  onChange={(e) => setSelectedActionType(e.target.value)}
                  className="w-full p-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-200 focus:outline-none focus:border-cyan-500 cursor-pointer"
                >
                  <option value="click">click</option>
                  <option value="type_text">type_text</option>
                  <option value="select_option">select_option</option>
                  <option value="hover">hover</option>
                  <option value="terminate">terminate</option>
                </select>
              </div>

              <div className="sm:col-span-2">
                <label className="text-[10px] uppercase text-zinc-500 mb-1 block">
                  Target Selector / Element ID
                </label>
                <input
                  type="text"
                  value={targetSelector}
                  onChange={(e) => setTargetSelector(e.target.value)}
                  className="w-full p-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-200 focus:outline-none focus:border-cyan-500 font-mono"
                  placeholder="e.g. button[data-agent-id='run-benchmark']"
                />
              </div>
            </div>

            {selectedActionType === "type_text" && (
              <div>
                <label className="text-[10px] uppercase text-zinc-500 mb-1 block">
                  Input Value
                </label>
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  className="w-full p-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-200 focus:outline-none focus:border-cyan-500 font-mono"
                  placeholder="Text to dispatch into input"
                />
              </div>
            )}

            <div className="flex justify-end">
              <button
                onClick={handleDispatchAction}
                disabled={isExecuting}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-black font-bold transition cursor-pointer shadow-lg shadow-cyan-500/20 disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                <span>{isExecuting ? "Executing..." : "Dispatch Action"}</span>
              </button>
            </div>

            {/* Execution Result Box */}
            {executionOutput && (
              <div className="mt-4 p-4 rounded-xl bg-black border border-emerald-500/40 text-[11px] font-mono">
                <div className="flex items-center justify-between pb-2 mb-2 border-b border-zinc-850 text-emerald-400 font-bold">
                  <span>SANDBOX DISPATCH TELEMETRY (200 OK)</span>
                  <span className="text-zinc-500 text-[10px]">State Mutated</span>
                </div>
                <pre className="text-zinc-300 overflow-x-auto whitespace-pre leading-relaxed">
                  {executionOutput}
                </pre>
              </div>
            )}
          </div>
        </div>

        {/* SECTION 3: MCP (MODEL CONTEXT PROTOCOL) TOOL DEFINITION */}
        <div className="rounded-2xl border border-zinc-800 bg-zinc-950 overflow-hidden">
          <div className="p-4 bg-zinc-900/60 border-b border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-purple-400" />
              <h3 className="font-bold text-zinc-100 text-sm">
                Model Context Protocol (MCP) Tool Schema
              </h3>
            </div>
            <button
              onClick={() => handleCopy("mcp", JSON.stringify(MCP_TOOL_SPEC, null, 2))}
              className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white transition cursor-pointer"
            >
              {copiedKey === "mcp" ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Copied Schema</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy MCP Tool Spec</span>
                </>
              )}
            </button>
          </div>

          <div className="p-4 sm:p-6">
            <p className="text-zinc-400 text-xs mb-3">
              Add this MCP tool definition to Claude Desktop, Gemini CLI, Cursor, or your autonomous agent harness to control Abtract evaluations programmatically:
            </p>
            <pre className="p-4 rounded-xl bg-black border border-zinc-800 text-purple-300 overflow-x-auto text-[11px] leading-relaxed">
              {JSON.stringify(MCP_TOOL_SPEC, null, 2)}
            </pre>
          </div>
        </div>

        {/* SECTION 4: PROMPT-OPTIMIZED CONTEXT INJECTION */}
        <div className="p-6 rounded-2xl border border-zinc-800 bg-zinc-950">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold text-zinc-100 text-sm flex items-center gap-2">
              <FileCode className="w-4 h-4 text-amber-400" />
              LLM Prompt Injection (Markdown Context)
            </h3>
            <button
              onClick={() =>
                handleCopy(
                  "prompt",
                  `You are an autonomous web testing agent for Abtract.
Target URL: http://localhost:3000
Page Goal: Evaluate A/B performance for checkout and SaaS workflows.
Primary Directives:
1. Prefer targets with data-agent-id attributes.
2. Monitor aria-live regions for state transition confirmation.
3. Report any friction events (misclick, backtracking, selector_not_found) immediately.`
                )
              }
              className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white transition cursor-pointer"
            >
              {copiedKey === "prompt" ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Copied Prompt</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy System Prompt</span>
                </>
              )}
            </button>
          </div>
          <p className="text-zinc-400 text-xs mb-3">
            Minimal token footprint instructions ready to paste into any model's context window:
          </p>
          <div className="p-4 rounded-xl bg-black border border-zinc-850 text-amber-200/90 text-[11px] font-mono leading-relaxed">
            <code>
              You are an autonomous web testing agent for Abtract.
              <br />
              Target URL: http://localhost:3000
              <br />
              Page Goal: Evaluate A/B performance for checkout and SaaS workflows.
              <br />
              Primary Directives:
              <br />
              1. Prefer targets with explicit data-agent-id attributes.
              <br />
              2. Monitor aria-live regions for state transition confirmation.
              <br />
              3. Report any friction events (misclick, backtracking, selector_not_found) immediately.
            </code>
          </div>
        </div>
      </div>
    </div>
  );
}
