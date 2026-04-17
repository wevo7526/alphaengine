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

export type DeskStatus = "pending" | "active" | "done";

export interface DeskActivity {
  type:
    | "tool_call"
    | "tool_result"
    | "tool_error"
    | "agent_thinking"
    | "risk_gate"
    | "decision";
  desk: string;
  agent?: string;
  tool?: string;
  args_summary?: string;
  result_summary?: string;
  text?: string;
  error?: string;
  approved?: boolean;
  reasons?: string[];
  decision?: string;
  reason?: string;
  confidence?: number;
  duration_ms?: number;
  timestamp: number;
}

export interface DeskState {
  desk: string;
  label: string;
  agent?: string;
  status: DeskStatus;
  activities: DeskActivity[];
  summary?: string;
  durationMs?: number;
  startedAt: number;
}

export interface AnalysisRun {
  id: string;
  query: string;
  phase: AnalysisPhase;
  result: IntelligenceMemo | null;
  error: string | null;
  startedAt: number;
  phaseDetail?: string;
  desks: DeskState[];
}

const DESK_ORDER = ["query", "research", "risk", "portfolio", "cio"];

export function useAnalysis() {
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [activeRun, setActiveRun] = useState<string | null>(null);

  const updateRun = useCallback(
    (id: string, patch: Partial<AnalysisRun> | ((r: AnalysisRun) => Partial<AnalysisRun>)) => {
      setRuns((prev) =>
        prev.map((r) => {
          if (r.id !== id) return r;
          const p = typeof patch === "function" ? patch(r) : patch;
          return { ...r, ...p };
        })
      );
    },
    []
  );

  const applyDeskEvent = useCallback(
    (id: string, event: Record<string, unknown>) => {
      setRuns((prev) =>
        prev.map((r) => {
          if (r.id !== id) return r;

          const desks = [...r.desks];
          const type = event.type as string;

          if (type === "desk_start") {
            const deskName = event.desk as string;
            const existing = desks.findIndex((d) => d.desk === deskName);
            const newDesk: DeskState = {
              desk: deskName,
              label: (event.label as string) || deskName,
              agent: event.agent as string,
              status: "active",
              activities: [],
              startedAt: Date.now(),
            };
            // Mark prior active desks as done
            for (const d of desks) {
              if (d.status === "active") d.status = "done";
            }
            if (existing >= 0) {
              desks[existing] = { ...desks[existing], status: "active", agent: newDesk.agent, label: newDesk.label };
            } else {
              desks.push(newDesk);
            }
            return { ...r, desks };
          }

          if (type === "desk_done") {
            const deskName = event.desk as string;
            const idx = desks.findIndex((d) => d.desk === deskName);
            if (idx >= 0) {
              desks[idx] = {
                ...desks[idx],
                status: "done",
                summary: event.summary as string | undefined,
                durationMs: event.duration_ms as number | undefined,
              };
            }
            return { ...r, desks };
          }

          // Activity event (tool_call, tool_result, etc.)
          const deskName = (event.desk as string) || "";
          const idx = desks.findIndex((d) => d.desk === deskName);
          if (idx < 0) return r;

          const activity: DeskActivity = {
            type: type as DeskActivity["type"],
            desk: deskName,
            agent: event.agent as string,
            tool: event.tool as string,
            args_summary: event.args_summary as string,
            result_summary: event.result_summary as string,
            text: event.text as string,
            error: event.error as string,
            approved: event.approved as boolean,
            reasons: event.reasons as string[],
            decision: event.decision as string,
            reason: event.reason as string,
            confidence: event.confidence as number,
            duration_ms: event.duration_ms as number,
            timestamp: (event.timestamp as number) || Date.now() / 1000,
          };

          // Merge tool_result into preceding tool_call with same tool name
          if (type === "tool_result") {
            const acts = desks[idx].activities;
            for (let i = acts.length - 1; i >= 0; i--) {
              if (acts[i].type === "tool_call" && acts[i].tool === activity.tool && !acts[i].result_summary) {
                acts[i] = { ...acts[i], result_summary: activity.result_summary, duration_ms: activity.duration_ms };
                desks[idx] = { ...desks[idx], activities: [...acts] };
                return { ...r, desks };
              }
            }
          }

          desks[idx] = {
            ...desks[idx],
            activities: [...desks[idx].activities, activity],
          };
          return { ...r, desks };
        })
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
        desks: [],
      };

      setRuns((prev) => [...prev, run]);
      setActiveRun(id);

      try {
        const streamUrl = api.analyzeStreamUrl();
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

              // NEW: desk events
              if (event.type) {
                applyDeskEvent(id, event);
              }

              // LEGACY: phase events (kept for backward compat)
              if (event.phase === "interpreting") {
                updateRun(id, { phase: "interpreting", phaseDetail: undefined });
              } else if (event.phase === "interpreting_done") {
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
                // Mark any active desks as done
                setRuns((prev) => prev.map((r) => {
                  if (r.id !== id) return r;
                  return {
                    ...r,
                    desks: r.desks.map((d) => d.status === "active" ? { ...d, status: "done" as DeskStatus } : d),
                  };
                }));
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
    [updateRun, applyDeskEvent]
  );

  const removeRun = useCallback((id: string) => {
    setRuns((prev) => prev.filter((r) => r.id !== id));
  }, []);

  return { runs, activeRun, analyze, removeRun };
}

export { DESK_ORDER };
