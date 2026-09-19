"use client";

import { useEffect, useState, useCallback } from "react";
import { ViewMode } from "@/types";
import { Navbar } from "@/components/navigation/Navbar";
import { HumanView } from "@/components/views/HumanView";
import { AgentView } from "@/components/views/AgentView";

export default function Home() {
  const [viewMode, setViewMode] = useState<ViewMode>("human");
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null);

  // Sync with URL query parameter or localStorage if present
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const queryView = params.get("view");
      if (queryView === "agent" || queryView === "human") {
        setViewMode(queryView);
      } else {
        const savedView = localStorage.getItem("abtract_view_mode") as ViewMode;
        if (savedView === "agent" || savedView === "human") {
          setViewMode(savedView);
        }
      }
    }
  }, []);

  const handleToggleView = useCallback((mode: ViewMode) => {
    setViewMode(mode);
    if (typeof window !== "undefined") {
      localStorage.setItem("abtract_view_mode", mode);
      const url = new URL(window.location.href);
      url.searchParams.set("view", mode);
      window.history.replaceState({}, "", url.toString());
    }
  }, []);

  // Check backend health
  useEffect(() => {
    let ignore = false;
    async function checkHealth() {
      try {
        const res = await fetch("/api/health");
        if (!ignore) {
          setBackendHealthy(res.ok);
        }
      } catch {
        if (!ignore) {
          setBackendHealthy(false);
        }
      }
    }
    checkHealth();
    return () => {
      ignore = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col font-sans transition-colors duration-300">
      <Navbar
        currentView={viewMode}
        onToggleView={handleToggleView}
        backendHealthy={backendHealthy}
      />

      <main className="flex-1 w-full">
        {viewMode === "human" ? (
          <HumanView
            onToggleView={handleToggleView}
            backendHealthy={backendHealthy}
          />
        ) : (
          <AgentView
            onToggleView={handleToggleView}
            backendHealthy={backendHealthy}
          />
        )}
      </main>
    </div>
  );
}
