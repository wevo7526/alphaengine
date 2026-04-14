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
        const streamUrl = api.analyzeStreamUrl();
        // Get auth token for streaming request
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        try {
          // @ts-expect-error Clerk global
          const clerk = window?.Clerk;
          if (clerk?.session) {
            const token = await clerk.session.getToken();
            if (token) headers["Authorization"] = `Bearer ${token}`;
          }
        } catch { /* no auth */ }

        const response = await fetch(streamUrl, {
          method: "POST",
          headers,
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

              // Phase starts — show agent as active
              if (event.phase === "interpreting") {
                updateRun(id, { phase: "interpreting", phaseDetail: undefined });
              } else if (event.phase === "interpreting_done") {
                // Advance to next phase — researching will start
                updateRun(id, { phase: "researching", phaseDetail: `${event.tickers?.length || 0} tickers → researching` });
              } else if (event.phase === "researching") {
                updateRun(id, { phase: "researching", phaseDetail: undefined });
              } else if (event.phase === "researching_done") {
                updateRun(id, { phase: "risk_assessment", phaseDetail: "data gathered → assessing risk" });
              } else if (event.phase === "risk_assessment") {
                updateRun(id, { phase: "risk_assessment", phaseDetail: undefined });
              } else if (event.phase === "risk_assessment_done") {
                updateRun(id, { phase: "strategizing", phaseDetail: `${event.macro_regime || "regime classified"} → building trades` });
              } else if (event.phase === "strategizing") {
                updateRun(id, { phase: "strategizing", phaseDetail: undefined });
              } else if (event.phase === "strategizing_done") {
                updateRun(id, { phase: "synthesizing", phaseDetail: `${event.trade_count || 0} ideas → writing memo` });
              } else if (event.phase === "synthesizing") {
                updateRun(id, { phase: "synthesizing", phaseDetail: undefined });
              } else if (event.phase === "complete" && event.memo) {
                updateRun(id, { phase: "complete", result: event.memo as IntelligenceMemo, phaseDetail: undefined });
              } else if (event.phase === "error") {
                updateRun(id, { phase: "error", error: event.error });
              }
            } catch {
              // Skip malformed SSE events
            }
          }
        }

        // If stream ended without a "complete" event, check if we have a result
        setRuns((prev) => {
          const current = prev.find((r) => r.id === id);
          if (current && current.phase !== "complete" && current.phase !== "error") {
            return prev.map((r) =>
              r.id === id ? { ...r, phase: "error" as AnalysisPhase, error: "Stream ended unexpectedly" } : r
            );
          }
          return prev;
        });
      } catch {
        // Fallback to non-streaming
        try {
          updateRun(id, { phase: "researching", phaseDetail: "using fallback..." });
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
