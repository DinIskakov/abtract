"use client";

import { useCallback, useEffect, useState } from "react";

interface HealthResponse {
  status: string;
  service: string;
  version: string;
  timestamp: string;
}

export default function Home() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/health");
      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }
      const data = await res.json();
      setHealth(data);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not connect to FastAPI backend"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;

    async function load() {
      try {
        const res = await fetch("/api/health");
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }
        const data = await res.json();
        if (!ignore) {
          setHealth(data);
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not connect to FastAPI backend"
          );
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      ignore = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col justify-between selection:bg-teal-500 selection:text-black">
      {/* Header */}
      <header className="border-b border-zinc-800/80 backdrop-blur px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center font-bold text-white shadow-lg shadow-cyan-500/20">
              A
            </div>
            <span className="font-semibold tracking-tight text-lg">Abtract Monorepo</span>
          </div>
          <div className="flex items-center gap-4 text-sm text-zinc-400">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-zinc-800 bg-zinc-900/60">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
              Next.js 16 + FastAPI
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-6 py-16 flex-1 w-full flex flex-col items-center justify-center text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-zinc-800 bg-zinc-900/80 text-xs font-mono text-zinc-400 mb-8">
          <span>mise</span>
          <span>•</span>
          <span>turborepo</span>
          <span>•</span>
          <span>bun</span>
          <span>•</span>
          <span>uv</span>
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight max-w-3xl bg-gradient-to-b from-white via-zinc-200 to-zinc-500 bg-clip-text text-transparent">
          Modern Fullstack Monorepo Architecture
        </h1>

        <p className="mt-4 text-base sm:text-lg text-zinc-400 max-w-2xl">
          Next.js App Router frontend orchestrated with Bun and Turborepo, paired with a high-performance Python FastAPI backend managed by uv.
        </p>

        {/* Backend Connectivity Card */}
        <div className="mt-10 w-full max-w-md p-6 rounded-2xl border border-zinc-800 bg-zinc-900/50 shadow-2xl backdrop-blur-sm text-left">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
              FastAPI Backend Status
            </h2>
            <button
              onClick={fetchHealth}
              className="text-xs text-cyan-400 hover:text-cyan-300 font-medium transition cursor-pointer"
            >
              Refresh
            </button>
          </div>

          <div className="p-4 rounded-xl bg-zinc-950/80 border border-zinc-800 font-mono text-xs">
            {loading ? (
              <div className="text-zinc-500 flex items-center gap-2">
                <span className="inline-block h-3 w-3 border-2 border-zinc-500 border-t-transparent rounded-full animate-spin"></span>
                Checking backend health (/api/health)...
              </div>
            ) : health ? (
              <div className="space-y-1.5 text-zinc-300">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-500">Status:</span>
                  <span className="text-emerald-400 font-bold">{health.status}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-500">Service:</span>
                  <span>{health.service}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-500">Version:</span>
                  <span>{health.version}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-500">Timestamp:</span>
                  <span className="text-[10px] text-zinc-400">{health.timestamp}</span>
                </div>
              </div>
            ) : (
              <div className="text-amber-400/90 text-[11px] leading-relaxed">
                <div className="font-semibold mb-1">Backend not responding:</div>
                <div className="text-zinc-400 mb-2">{error}</div>
                <div className="text-zinc-500 text-[10px]">
                  Run <code className="text-zinc-300 bg-zinc-900 px-1 py-0.5 rounded">mise run dev</code> or start the backend with <code className="text-zinc-300 bg-zinc-900 px-1 py-0.5 rounded">bun --filter api dev</code>.
                </div>
              </div>
            )}
          </div>

          <div className="mt-4 flex gap-2">
            <a
              href="/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 py-2 text-center text-xs font-medium rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition"
            >
              Open Swagger Docs →
            </a>
            <a
              href="/api/health"
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 py-2 text-center text-xs font-medium rounded-lg border border-zinc-800 hover:bg-zinc-800/60 text-zinc-300 transition"
            >
              Raw /api/health →
            </a>
          </div>
        </div>

        {/* Quick Start Commands */}
        <div className="mt-10 grid grid-cols-1 sm:grid-cols-3 gap-4 w-full max-w-3xl text-left font-mono text-xs">
          <div className="p-4 rounded-xl border border-zinc-800/80 bg-zinc-900/30">
            <span className="text-zinc-500 text-[11px]">Start Development</span>
            <div className="mt-1 text-cyan-400 font-semibold">mise run dev</div>
            <p className="mt-1 text-zinc-500 text-[11px] font-sans">
              Runs Next.js & FastAPI concurrently via Turborepo
            </p>
          </div>
          <div className="p-4 rounded-xl border border-zinc-800/80 bg-zinc-900/30">
            <span className="text-zinc-500 text-[11px]">Run Tests</span>
            <div className="mt-1 text-emerald-400 font-semibold">mise run test</div>
            <p className="mt-1 text-zinc-500 text-[11px] font-sans">
              Runs bun test (frontend) and pytest (backend)
            </p>
          </div>
          <div className="p-4 rounded-xl border border-zinc-800/80 bg-zinc-900/30">
            <span className="text-zinc-500 text-[11px]">Code Quality</span>
            <div className="mt-1 text-purple-400 font-semibold">mise run lint</div>
            <p className="mt-1 text-zinc-500 text-[11px] font-sans">
              Runs ESLint for web and Ruff for Python
            </p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-800/80 py-6 px-6 text-center text-xs text-zinc-500">
        Engineered with Next.js, FastAPI, Bun, uv, Turborepo & mise.
      </footer>
    </div>
  );
}
