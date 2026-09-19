"use client";

import React, { useState } from "react";
import { Check, Copy, Wand2, ArrowRightLeft, FileCode, CheckCircle2 } from "lucide-react";

interface CodeExample {
  title: string;
  directive: string;
  impact: string;
  before: string;
  after: string;
}

const EXAMPLES: CodeExample[] = [
  {
    title: "Action Affordance Resolution",
    directive: "inject_data_agent_id",
    impact: "+64% Visual Groundability (VGS)",
    before: `// Before: Fragile DOM with unlabelled SVG icon
<button 
  className="p-2 rounded-lg bg-zinc-800 hover:bg-zinc-700"
  onClick={handleProceedToPayment}
>
  <svg className="w-5 h-5 text-white" viewBox="0 0 24 24">
    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
  </svg>
</button>`,
    after: `// After: Abtract Agent-Native Transformation
<button 
  data-agent-id="checkout-proceed-to-payment"
  data-agent-action="navigate:payment_gateway"
  aria-label="Proceed to secure payment gateway"
  className="p-2 rounded-lg bg-zinc-800 hover:bg-zinc-700"
  onClick={handleProceedToPayment}
>
  <svg aria-hidden="true" className="w-5 h-5 text-white" viewBox="0 0 24 24">
    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
  </svg>
  <span className="sr-only">Proceed to Payment</span>
</button>`,
  },
  {
    title: "DOM Wrapper Flattening",
    directive: "flatten_dom_wrappers",
    impact: "-78% Token Consumption (DTE)",
    before: `// Before: Div soup causing DOM token overflow
<div className="outer-box-942">
  <div className="flex-center-shim">
    <div className="relative-pos-container">
      <div className="card-inner-layer">
        <span className="label-text">Deploy Application</span>
      </div>
    </div>
  </div>
</div>`,
    after: `// After: Semantic flattening with direct affordance
<button 
  data-agent-id="action-deploy-app"
  data-agent-action="trigger_deployment"
  className="btn-deploy-card"
>
  Deploy Application
</button>`,
  },
  {
    title: "Async Dynamic State Signal",
    directive: "add_aria_live",
    impact: "Eliminates Unannounced Dynamic Update friction",
    before: `// Before: Agent polls or assumes state is unchanged
<div>
  {isProcessing && <div className="spinner" />}
  {orderId && <div>Order confirmed: #{orderId}</div>}
</div>`,
    after: `// After: Agent immediately perceives asynchronous state
<div 
  aria-live="polite" 
  data-agent-id="order-status-stream"
  data-agent-state={isProcessing ? "processing" : orderId ? "complete" : "idle"}
>
  {isProcessing && <div className="spinner" aria-label="Processing transaction..." />}
  {orderId && <div>Order confirmed: #{orderId}</div>}
</div>`,
  },
];

export function CodeDiffViewer() {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [copied, setCopied] = useState(false);

  const activeExample = EXAMPLES[selectedIdx];

  const handleCopy = () => {
    navigator.clipboard.writeText(activeExample.after);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="w-full max-w-5xl mx-auto rounded-3xl border border-zinc-800 bg-zinc-950/80 shadow-2xl backdrop-blur-xl overflow-hidden">
      {/* Header Tabs */}
      <div className="p-4 sm:p-6 border-b border-zinc-800/80 bg-zinc-900/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Wand2 className="w-4 h-4 text-emerald-400" />
            <h3 className="text-base font-semibold text-zinc-100">
              Autonomous Design Regeneration Directives
            </h3>
          </div>
          <p className="text-xs text-zinc-400 mt-1">
            How Abtract automatically rewrites fragile DOM markup into agent-resilient interfaces.
          </p>
        </div>

        {/* Example Switchers */}
        <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-zinc-950 border border-zinc-800">
          {EXAMPLES.map((ex, i) => (
            <button
              key={ex.directive}
              onClick={() => setSelectedIdx(i)}
              data-agent-id={`select-diff-${ex.directive}`}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono transition cursor-pointer ${
                selectedIdx === i
                  ? "bg-zinc-800 text-emerald-400 border border-zinc-700 font-semibold"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {ex.directive}
            </button>
          ))}
        </div>
      </div>

      {/* Directive Impact Pill */}
      <div className="px-6 py-2.5 bg-zinc-900/20 border-b border-zinc-800/60 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className="text-zinc-500 font-mono text-[11px]">Directive:</span>
          <span className="font-mono text-zinc-200 font-bold">{activeExample.directive}</span>
          <span className="text-zinc-600">•</span>
          <span className="text-emerald-400 font-medium">{activeExample.impact}</span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-[11px] font-mono text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400">Copied Patch</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy Patch</span>
            </>
          )}
        </button>
      </div>

      {/* Diff Code Columns */}
      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-zinc-800 font-mono text-xs">
        {/* Before (Variant A) */}
        <div className="p-5 bg-zinc-950/40">
          <div className="flex items-center justify-between mb-3">
            <span className="text-rose-400 font-semibold text-[11px] flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-rose-500" />
              Legacy DOM (Agent-Hostile)
            </span>
            <span className="text-[10px] text-zinc-500">Unlabelled / Fragile</span>
          </div>
          <pre className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-850 text-zinc-400 overflow-x-auto leading-relaxed whitespace-pre font-mono text-[11px]">
            {activeExample.before}
          </pre>
        </div>

        {/* After (Variant B) */}
        <div className="p-5 bg-emerald-950/10">
          <div className="flex items-center justify-between mb-3">
            <span className="text-emerald-400 font-semibold text-[11px] flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Agent-Native Patch (Regenerated)
            </span>
            <span className="text-[10px] text-emerald-400/80 font-mono">Verified Native</span>
          </div>
          <pre className="p-4 rounded-xl bg-zinc-950/90 border border-emerald-500/30 text-emerald-200 overflow-x-auto leading-relaxed whitespace-pre font-mono text-[11px]">
            {activeExample.after}
          </pre>
        </div>
      </div>
    </div>
  );
}
