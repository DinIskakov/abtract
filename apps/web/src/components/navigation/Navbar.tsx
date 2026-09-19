"use client";

import React from "react";
import Link from "next/link";
import { ViewMode } from "@/types";
import { ViewToggle } from "./ViewToggle";
import { Terminal } from "lucide-react";

interface NavbarProps {
  currentView: ViewMode;
  onToggleView: (view: ViewMode) => void;
  backendHealthy: boolean | null;
}

export function Navbar({ currentView, onToggleView, backendHealthy }: NavbarProps) {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-xl transition-colors duration-300">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Brand / Logo */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-2.5 group"
            data-agent-id="brand-home-link"
            data-agent-action="navigate:home"
          >
            <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-tr from-emerald-500 via-teal-500 to-cyan-500 text-black font-mono font-black text-base shadow-lg shadow-emerald-500/20 group-hover:scale-105 transition-transform">
              <span>A</span>
              <div className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full bg-cyan-400 ring-2 ring-zinc-950 animate-ping" />
            </div>
            <div className="flex flex-col">
              <span className="font-semibold tracking-tight text-zinc-100 text-base leading-none">
                abtract<span className="text-emerald-400">.ai</span>
              </span>
              <span className="text-[10px] text-zinc-500 font-mono tracking-wider mt-0.5 uppercase">
                Agent A/B Testing & Eval
              </span>
            </div>
          </Link>

          {/* Backend Status Tag */}
          <div className="hidden lg:flex items-center gap-1.5 ml-4 px-2.5 py-1 rounded-full text-[11px] font-mono border border-zinc-800 bg-zinc-900/50">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                backendHealthy === true
                  ? "bg-emerald-400 shadow-xs shadow-emerald-400 animate-pulse"
                  : backendHealthy === false
                  ? "bg-amber-400"
                  : "bg-zinc-500"
              }`}
            />
            <span className="text-zinc-400">
              API {backendHealthy ? "Connected" : "Standby"}
            </span>
          </div>
        </div>

        {/* Center: Interactive Perspective Switcher */}
        <div className="flex items-center">
          <ViewToggle currentView={currentView} onToggle={onToggleView} />
        </div>

        {/* Right Action Items */}
        <div className="flex items-center gap-3">
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            data-agent-id="nav-api-docs-link"
            data-agent-action="navigate:swagger_docs"
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900 border border-transparent hover:border-zinc-800 transition"
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>OpenAPI Docs</span>
          </a>

          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            data-agent-id="nav-github-link"
            aria-label="GitHub Repository"
            className="p-2 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900 border border-zinc-850 transition"
          >
            <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
              <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
            </svg>
          </a>
        </div>
      </div>
    </header>
  );
}
