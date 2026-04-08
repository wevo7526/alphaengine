"use client";

import { useState, useCallback } from "react";
import type { IntelligenceMemo } from "@/lib/types";
import { api } from "@/lib/api";

export type AnalysisPhase =
  | "idle"
  | "interpreting"
  | "researching"
  | "risk_assessment"
  | "strategizing"
  | "synthesizing"
  | "complete"
  | "error";

const PHASE_ORDER: AnalysisPhase[] = [
  "interpreting",
  "researching",
  "risk_assessment",
  "strategizing",
  "synthesizing",
];

export interface AnalysisRun {
  id: string;
  query: string;
  phase: AnalysisPhase;
  result: IntelligenceMemo | null;
  error: string | null;
  startedAt: number;
}

export function useAnalysis() {
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [activeRun, setActiveRun] = useState<string | null>(null);

  const updateRun = useCallback(
    (id: string, patch: Partial<AnalysisRun>) => {
      setRuns((prev) =>
        prev.map((r) => (r.id === id ? { ...r, ...patch } : r))
      );
    },
    []
  );

  const analyze = useCallback(
    async (query: string) => {
      const id = `${Date.now()}`;
      const run: AnalysisRun = {
        id,
        query,
        phase: "interpreting",
        result: null,
        error: null,
        startedAt: Date.now(),
      };

      setRuns((prev) => [...prev, run]);
      setActiveRun(id);

      // Step through phases on a timer while the real API call runs
      const phaseTimer = setInterval(() => {
        setRuns((prev) => {
          const current = prev.find((r) => r.id === id);
          if (
            !current ||
            current.phase === "complete" ||
            current.phase === "error"
          )
            return prev;

          const idx = PHASE_ORDER.indexOf(current.phase);
          if (idx >= 0 && idx < PHASE_ORDER.length - 1) {
            return prev.map((r) =>
              r.id === id ? { ...r, phase: PHASE_ORDER[idx + 1] } : r
            );
          }
          return prev;
        });
      }, 8000); // ~8s per phase — research desk takes longer than old pipeline

      try {
        const result = (await api.analyze(query)) as IntelligenceMemo;
        clearInterval(phaseTimer);
        updateRun(id, { phase: "complete", result });
      } catch (err) {
        clearInterval(phaseTimer);
        const message =
          err instanceof Error ? err.message : "Analysis failed";
        updateRun(id, { phase: "error", error: message });
      }

      setActiveRun(null);
    },
    [updateRun]
  );

  return { runs, activeRun, analyze };
}
