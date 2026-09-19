"use client";

import React, { useEffect } from "react";
import { ViewMode } from "@/types";
import { Eye, Bot, Sparkles, Cpu } from "lucide-react";

interface ViewToggleProps {
  currentView: ViewMode;
  onToggle: (view: ViewMode) => void;
  compact?: boolean;
}

export function ViewToggle({ currentView, onToggle, compact = false }: ViewToggleProps) {
  // Listen for 'V' or 'v' key to toggle views effortlessly
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger if user is typing in an input or textarea
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.isComposing
      ) {
        return;
      }

      if (e.key === "v" || e.key === "V") {
        e.preventDefault();
        onToggle(currentView === "human" ? "agent" : "human");
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentView, onToggle]);

  return (
    <div
      role="group"
      aria-label="Perspective View Toggle"
      className="inline-flex items-center gap-1.5 p-1 rounded-full bg-zinc-900/90 border border-zinc-800 shadow-xl backdrop-blur-md transition-all select-none"
    >
      {/* Human View Button */}
      <button
        type="button"
        data-agent-id="toggle-human-view"
        data-agent-action="switch_view_mode:human"
        onClick={() => onToggle("human")}
        className={`relative flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium transition-all duration-200 cursor-pointer ${
          currentView === "human"
            ? "bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm shadow-emerald-500/20 font-semibold"
            : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 border border-transparent"
        }`}
      >
        <Eye className={`w-3.5 h-3.5 ${currentView === "human" ? "text-emerald-400 animate-pulse" : "text-zinc-400"}`} />
        <span>Human View</span>
        {currentView === "human" && (
          <span className="hidden sm:inline-flex items-center gap-1 text-[10px] text-emerald-400/80 font-mono bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-500/30">
            <Sparkles className="w-2.5 h-2.5" /> Shaders
          </span>
        )}
      </button>

      {/* Agent View Button */}
      <button
        type="button"
        data-agent-id="toggle-agent-view"
        data-agent-action="switch_view_mode:agent"
        onClick={() => onToggle("agent")}
        className={`relative flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium transition-all duration-200 cursor-pointer ${
          currentView === "agent"
            ? "bg-gradient-to-r from-cyan-500/20 to-blue-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm shadow-cyan-500/20 font-semibold"
            : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 border border-transparent"
        }`}
      >
        <Bot className={`w-3.5 h-3.5 ${currentView === "agent" ? "text-cyan-400" : "text-zinc-400"}`} />
        <span>Agent View</span>
        {currentView === "agent" && (
          <span className="hidden sm:inline-flex items-center gap-1 text-[10px] text-cyan-400/80 font-mono bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-500/30">
            <Cpu className="w-2.5 h-2.5" /> -94% Tokens
          </span>
        )}
      </button>

      {/* Shortcut hint */}
      {!compact && (
        <div className="hidden md:flex items-center px-2 py-0.5 text-[10px] font-mono text-zinc-500">
          <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 mr-1 shadow-xs">V</kbd>
          <span>toggle</span>
        </div>
      )}
    </div>
  );
}
