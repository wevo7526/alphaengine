"use client";

import { useState, useEffect } from "react";
import type { AnalysisRun, AnalysisPhase } from "@/hooks/useAnalysis";
import { AGENT_META } from "@/lib/types";
import { MemoPanel } from "./MemoPanel";

const PHASES: { key: AnalysisPhase; agent: string; sources: string[] }[] = [
  {
    key: "interpreting",
    agent: "query_interpreter",
    sources: ["Claude Sonnet"],
  },
  {
    key: "researching",
    agent: "research_analyst",
    sources: ["FRED", "Yahoo Finance", "NewsAPI", "Finnhub", "SEC EDGAR", "Alpha Vantage"],
  },
  {
    key: "risk_assessment",
    agent: "risk_manager",
    sources: ["FRED", "Macro indicators"],
  },
  {
    key: "strategizing",
    agent: "portfolio_strategist",
    sources: ["Yahoo Finance", "Price data"],
  },
  {
    key: "synthesizing",
    agent: "cio_synthesizer",
    sources: ["Claude Sonnet"],
  },
];

const PHASE_INDEX: Record<string, number> = {};
PHASES.forEach((p, i) => {
  PHASE_INDEX[p.key] = i;
});

function ElapsedTimer({ startedAt }: { startedAt: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.round((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return (
    <span className="text-[10px] font-mono text-text-quaternary tabular-nums">
      {mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}
    </span>
  );
}

function PhaseCard({
  agent,
  sources,
  state,
  index,
  startedAt,
  detail,
}: {
  agent: string;
  sources: string[];
  state: "pending" | "active" | "done";
  index: number;
  startedAt: number;
  detail?: string;
}) {
  const meta = AGENT_META[agent] ?? { label: agent, role: "" };

  return (
    <div
      className={[
        "relative pl-8 pb-5",
        index < PHASES.length - 1 ? "border-l border-border-primary ml-3" : "ml-3",
      ].join(" ")}
      style={{
        animation: state !== "pending" ? `fade-in 0.4s ease-out` : undefined,
        opacity: state === "pending" ? 0.25 : 1,
        transition: "opacity 0.4s ease",
      }}
    >
      {/* Node dot */}
      <div
        className={[
          "absolute -left-[5px] top-1 w-[10px] h-[10px] rounded-full border-2",
          state === "done"
            ? "bg-signal-green border-signal-green"
            : state === "active"
              ? "bg-accent border-accent"
              : "bg-bg-primary border-border-primary",
        ].join(" ")}
        style={
          state === "active"
            ? { animation: "pulse-subtle 2s ease-in-out infinite" }
            : undefined
        }
      />

      {/* Content */}
      <div className="min-h-[28px]">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-[13px] font-medium text-text-primary">
            {meta.label}
          </span>
          {state === "active" && (
            <>
              <div
                className="w-2.5 h-2.5 rounded-full border-[1.5px] border-accent border-t-transparent"
                style={{ animation: "spin-slow 0.8s linear infinite" }}
              />
              <ElapsedTimer startedAt={startedAt} />
            </>
          )}
          {state === "done" && (
            <span className="text-[10px] text-signal-green font-medium">done</span>
          )}
          {detail && (
            <span className="text-[10px] text-text-quaternary font-mono">{detail}</span>
          )}
        </div>

        {state !== "pending" && !detail && (
          <p className="text-[11px] text-text-quaternary mb-1">{meta.role}</p>
        )}

        {state !== "pending" && sources.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {sources.map((s) => (
              <span
                key={s}
                className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-white/[0.04] text-text-quaternary border border-border-subtle"
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function AnalysisTrace({ run, onDeleteMemo }: { run: AnalysisRun; onDeleteMemo?: (id: string) => void }) {
  const currentIdx =
    run.phase === "complete" || run.phase === "error"
      ? PHASES.length
      : PHASE_INDEX[run.phase] ?? -1;

  return (
    <div style={{ animation: "fade-in 0.3s ease-out" }}>
      {/* Timeline trace */}
      <div className="mb-6">
        {PHASES.map((phase, i) => {
          let state: "pending" | "active" | "done";
          if (i < currentIdx) state = "done";
          else if (i === currentIdx) state = "active";
          else state = "pending";

          return (
            <PhaseCard
              key={phase.key}
              agent={phase.agent}
              sources={phase.sources}
              state={state}
              index={i}
              startedAt={run.startedAt}
              detail={state === "done" && run.phase === phase.key ? run.phaseDetail : undefined}
            />
          );
        })}
      </div>

      {/* Final output */}
      {run.phase === "complete" && run.result && (
        <MemoPanel memo={run.result} onDelete={onDeleteMemo} />
      )}

      {/* Error */}
      {run.phase === "error" && (
        <div
          className="rounded-xl border border-signal-red/20 bg-signal-red/[0.04] p-4"
          style={{ animation: "fade-in 0.3s ease-out" }}
        >
          <p className="text-[13px] text-signal-red font-medium mb-1">Analysis failed</p>
          <p className="text-xs text-text-tertiary mb-2">
            {run.error?.includes("timed out") ? "The analysis took too long. Try a simpler query or fewer tickers." :
             run.error?.includes("NetworkError") ? "Could not reach the backend. Check your connection." :
             run.error?.includes("500") ? "The server encountered an error. Try again in a moment." :
             run.error || "An unexpected error occurred."}
          </p>
          <p className="text-[10px] text-text-quaternary font-mono">{run.error}</p>
        </div>
      )}
    </div>
  );
}
