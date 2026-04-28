"use client";

import { useState, useEffect } from "react";
import type { AnalysisRun, DeskState, DeskActivity, DeskStatus } from "@/hooks/useAnalysis";
import { MemoPanel } from "./MemoPanel";

const DESK_LABELS: Record<string, string> = {
  query: "Query Interpretation",
  research: "Research Desk",
  risk: "Risk Desk",
  portfolio: "Portfolio Construction",
  cio: "CIO Desk",
};

// Desks we always render placeholders for — gives a clear skeleton
const DEFAULT_DESK_ORDER = ["query", "research", "risk", "portfolio", "cio"];

function ElapsedTimer({ startedAt, frozen }: { startedAt: number; frozen?: number }) {
  const [elapsed, setElapsed] = useState(frozen ?? Math.floor((Date.now() - startedAt) / 1000));
  useEffect(() => {
    if (frozen !== undefined) {
      setElapsed(frozen);
      return;
    }
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startedAt, frozen]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return (
    <span className="text-[10px] font-mono text-text-quaternary tabular-nums">
      {mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}
    </span>
  );
}

function IconTool() {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 1L2 7H5.5L5 11L10 5H6.5L7 1Z" />
    </svg>
  );
}

function IconThinking() {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="6" cy="6" r="4" />
      <path d="M6 4V6L7.5 7" />
    </svg>
  );
}

function IconShield() {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 1L2 2.5V6C2 8.5 3.5 10.5 6 11C8.5 10.5 10 8.5 10 6V2.5L6 1Z" />
    </svg>
  );
}

function IconError() {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="6" cy="6" r="4.5" />
      <path d="M6 3.5V6.5M6 8.5V8.5" />
    </svg>
  );
}

function IconChevron({ open }: { open: boolean }) {
  return (
    <svg
      width="10" height="10" viewBox="0 0 12 12" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
      style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.15s ease" }}
    >
      <path d="M4 2L8 6L4 10" />
    </svg>
  );
}

function ActivityRow({ activity }: { activity: DeskActivity }) {
  const { type, tool, args_summary, result_summary, text, error, approved, reasons, decision, reason } = activity;

  if (type === "tool_call" || type === "tool_result") {
    const hasResult = !!result_summary;
    return (
      <div
        className="flex items-start gap-2 py-1"
        style={{ animation: "fade-in 0.25s ease-out" }}
      >
        <div className={`mt-1 ${hasResult ? "text-signal-green" : "text-accent"}`}>
          <IconTool />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-[11px] font-mono text-text-secondary">
              {tool}
            </span>
            {args_summary && (
              <span className="text-[10px] font-mono text-text-quaternary">
                ({args_summary})
              </span>
            )}
          </div>
          {hasResult && (
            <p className="text-[11px] text-text-tertiary mt-0.5 break-words">
              → {result_summary}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (type === "tool_error") {
    return (
      <div className="flex items-start gap-2 py-1" style={{ animation: "fade-in 0.25s ease-out" }}>
        <div className="mt-1 text-signal-red"><IconError /></div>
        <div className="flex-1 min-w-0">
          <span className="text-[11px] font-mono text-signal-red">{tool}</span>
          <p className="text-[11px] text-text-tertiary mt-0.5">{error}</p>
        </div>
      </div>
    );
  }

  if (type === "agent_thinking") {
    return (
      <div className="flex items-start gap-2 py-1" style={{ animation: "fade-in 0.25s ease-out" }}>
        <div className="mt-1 text-text-quaternary"><IconThinking /></div>
        <p className="flex-1 text-[11px] text-text-tertiary italic">{text}</p>
      </div>
    );
  }

  if (type === "risk_gate") {
    return (
      <div className="flex items-start gap-2 py-1" style={{ animation: "fade-in 0.25s ease-out" }}>
        <div className={`mt-1 ${approved ? "text-signal-green" : "text-signal-red"}`}>
          <IconShield />
        </div>
        <div className="flex-1 min-w-0">
          <span className={`text-[11px] font-medium ${approved ? "text-signal-green" : "text-signal-red"}`}>
            {approved ? "APPROVED" : "BLOCKED"}
          </span>
          {reasons && reasons.length > 0 && (
            <ul className="mt-0.5 space-y-0.5">
              {reasons.map((r, i) => (
                <li key={i} className="text-[11px] text-text-tertiary">· {r}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  if (type === "decision") {
    const color =
      decision === "GO" ? "text-signal-green" :
      decision === "NO-GO" ? "text-signal-red" :
      "text-signal-yellow";
    return (
      <div className="flex items-start gap-2 py-1" style={{ animation: "fade-in 0.25s ease-out" }}>
        <div className={`mt-1 ${color}`}><IconShield /></div>
        <div className="flex-1 min-w-0">
          <span className={`text-[11px] font-medium ${color}`}>{decision}</span>
          {reason && <p className="text-[11px] text-text-tertiary mt-0.5">{reason}</p>}
        </div>
      </div>
    );
  }

  return null;
}

function DeskCard({
  desk,
  isLast,
  runStartedAt,
}: {
  desk: DeskState;
  isLast: boolean;
  runStartedAt: number;
}) {
  const [expanded, setExpanded] = useState(desk.status === "active");

  // Auto-expand when desk becomes active
  useEffect(() => {
    if (desk.status === "active") setExpanded(true);
  }, [desk.status]);

  const duration = desk.durationMs;
  const hasActivities = desk.activities.length > 0;

  const dotClass =
    desk.status === "done"
      ? "bg-signal-green border-signal-green"
      : desk.status === "active"
        ? "bg-accent border-accent"
        : "bg-bg-primary border-border-primary";

  return (
    <div
      className={[
        "relative pl-8 pb-4",
        !isLast ? "border-l border-border-primary ml-3" : "ml-3",
      ].join(" ")}
      style={{
        opacity: desk.status === "pending" ? 0.35 : 1,
        transition: "opacity 0.3s ease",
      }}
    >
      {/* Node dot */}
      <div
        className={`absolute -left-[5px] top-1 w-[10px] h-[10px] rounded-full border-2 ${dotClass}`}
        style={desk.status === "active" ? { animation: "pulse-subtle 2s ease-in-out infinite" } : undefined}
      />

      {/* Header */}
      <button
        type="button"
        onClick={() => hasActivities && setExpanded((v) => !v)}
        className={[
          "w-full flex items-center gap-2 text-left",
          hasActivities ? "cursor-pointer hover:opacity-80" : "cursor-default",
        ].join(" ")}
        disabled={!hasActivities}
      >
        {hasActivities && (
          <span className="text-text-quaternary">
            <IconChevron open={expanded} />
          </span>
        )}
        <span className="text-[13px] font-medium text-text-primary">{desk.label}</span>

        {desk.status === "active" && (
          <>
            <div
              className="w-2.5 h-2.5 rounded-full border-[1.5px] border-accent border-t-transparent"
              style={{ animation: "spin-slow 0.8s linear infinite" }}
            />
            <ElapsedTimer startedAt={desk.startedAt} />
          </>
        )}
        {desk.status === "done" && duration !== undefined && (
          <ElapsedTimer startedAt={desk.startedAt} frozen={Math.round(duration / 1000)} />
        )}
        {desk.status === "done" && (
          <span className="text-[10px] text-signal-green font-medium">done</span>
        )}
        {desk.summary && (
          <span className="text-[10px] text-text-quaternary truncate ml-auto pl-2">
            {desk.summary}
          </span>
        )}
      </button>

      {/* Activity feed */}
      {expanded && hasActivities && (
        <div
          className="mt-2 pl-2 border-l border-border-subtle space-y-0.5"
          style={{ animation: "fade-in 0.3s ease-out" }}
        >
          {desk.activities.map((activity, i) => (
            <ActivityRow key={`${activity.timestamp}-${i}`} activity={activity} />
          ))}
        </div>
      )}
    </div>
  );
}

export function AnalysisTrace({ run, onDeleteMemo }: { run: AnalysisRun; onDeleteMemo?: (id: string) => void }) {
  // Build a desk list that includes all default desks as placeholders
  const deskMap = new Map<string, DeskState>();
  for (const d of run.desks) {
    deskMap.set(d.desk, d);
  }

  const allDesks: DeskState[] = DEFAULT_DESK_ORDER.map((deskName) => {
    const existing = deskMap.get(deskName);
    if (existing) return existing;
    return {
      desk: deskName,
      label: DESK_LABELS[deskName] || deskName,
      status: "pending" as DeskStatus,
      activities: [],
      startedAt: run.startedAt,
    };
  });

  // Append any desks we don't know about
  for (const d of run.desks) {
    if (!DEFAULT_DESK_ORDER.includes(d.desk)) {
      allDesks.push(d);
    }
  }

  return (
    <div style={{ animation: "fade-in 0.3s ease-out" }}>
      {/* Plan-confidence note: only surfaces when query was ambiguous */}
      {run.planConfidence !== undefined && run.planConfidence < 60 && run.phase !== "complete" && (
        <div className="mb-3 flex items-start gap-2 rounded-lg border border-signal-yellow/25 bg-signal-yellow/[0.04] px-3 py-2">
          <div className="text-[11px] font-mono text-signal-yellow shrink-0">Plan {run.planConfidence}</div>
          <p className="text-[11px] text-text-tertiary">
            {run.planConfidenceReason || "Query was ambiguous; some inferences were made about intent or universe."}
          </p>
        </div>
      )}

      {/* Desk timeline */}
      <div className="mb-6">
        {allDesks.map((desk, i) => (
          <DeskCard
            key={desk.desk}
            desk={desk}
            isLast={i === allDesks.length - 1}
            runStartedAt={run.startedAt}
          />
        ))}
      </div>

      {/* Final memo */}
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
