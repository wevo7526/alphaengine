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

export interface AnalysisRun {
  id: string;
  query: string;
  phase: AnalysisPhase;
  result: IntelligenceMemo | null;
  error: string | null;
  startedAt: number;
  phaseDetail?: string;
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

      try {
        // Use SSE streaming endpoint
        const streamUrl = api.analyzeStreamUrl();
        const response = await fetch(streamUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query }),
        });

        if (!response.ok || !response.body) {
          throw new Error(`Stream failed: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const event = JSON.parse(line.slice(6));

              // Map SSE phase events to UI phases
              if (event.phase === "interpreting") {
                updateRun(id, { phase: "interpreting" });
              } else if (event.phase === "interpreting_done") {
                updateRun(id, {
                  phase: "interpreting",
                  phaseDetail: `${event.tickers?.length || 0} tickers identified`,
                });
              } else if (event.phase === "researching") {
                updateRun(id, { phase: "researching" });
              } else if (event.phase === "researching_done") {
                updateRun(id, { phase: "researching", phaseDetail: "data gathered" });
              } else if (event.phase === "risk_assessment") {
                updateRun(id, { phase: "risk_assessment" });
              } else if (event.phase === "risk_assessment_done") {
                updateRun(id, {
                  phase: "risk_assessment",
                  phaseDetail: event.macro_regime || "",
                });
              } else if (event.phase === "strategizing") {
                updateRun(id, { phase: "strategizing" });
              } else if (event.phase === "strategizing_done") {
                updateRun(id, {
                  phase: "strategizing",
                  phaseDetail: `${event.trade_count || 0} trade ideas`,
                });
              } else if (event.phase === "synthesizing") {
                updateRun(id, { phase: "synthesizing" });
              } else if (event.phase === "complete" && event.memo) {
                updateRun(id, {
                  phase: "complete",
                  result: event.memo as IntelligenceMemo,
                });
              } else if (event.phase === "error") {
                updateRun(id, { phase: "error", error: event.error });
              }
            } catch {
              // Skip malformed SSE events
            }
          }
        }
      } catch (err) {
        // Fallback to non-streaming if SSE fails
        try {
          const result = (await api.analyze(query)) as IntelligenceMemo;
          updateRun(id, { phase: "complete", result });
        } catch (fallbackErr) {
          const message = fallbackErr instanceof Error ? fallbackErr.message : "Analysis failed";
          updateRun(id, { phase: "error", error: message });
        }
      }

      setActiveRun(null);
    },
    [updateRun]
  );

  return { runs, activeRun, analyze };
}
