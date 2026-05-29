"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { IntelligenceMemo } from "@/lib/types";
import { MemoPanel } from "@/components/MemoPanel";
import { TerminalHeader } from "@/components/TerminalHeader";
import { TerminalPanel } from "@/components/TerminalPanel";
import { StatusPill } from "@/components/StatusPill";

export default function MemosPage() {
  const [memos, setMemos] = useState<IntelligenceMemo[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [flushing, setFlushing] = useState(false);
  // Per-row delete state — track which memo id is currently being deleted
  // so the row can show a spinner / disabled state without blocking others.
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api
      .latestMemos(50)
      .then((d: unknown) => {
        setMemos((d as { memos: IntelligenceMemo[] }).memos || []);
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        setApiError(msg);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleFlush = async () => {
    if (flushing) return;
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        `Delete ALL ${memos.length} analyses for your account? This cannot be undone.`
      );
      if (!ok) return;
    }
    setFlushing(true);
    try {
      const res = await api.flushAnalyses("all");
      setMemos([]);
      setApiError(
        `Flushed ${res.deleted} ${res.deleted === 1 ? "analysis" : "analyses"}`
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setApiError(`flush: ${msg}`);
    }
    setFlushing(false);
  };

  // Delete a single memo from the row. Stops propagation so clicking the
  // delete button doesn't also toggle expand.
  const handleDeleteOne = async (e: React.MouseEvent, memo: IntelligenceMemo) => {
    e.stopPropagation();
    const id = memo.id;
    if (!id || deletingId) return;
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        `Delete "${(memo.title || memo.query || "this analysis").slice(0, 80)}"? This cannot be undone.`
      );
      if (!ok) return;
    }
    setDeletingId(id);
    try {
      await api.deleteMemo(id);
      setMemos((prev) => prev.filter((m) => m.id !== id));
      // Collapse the expanded view if we just deleted the open one
      setExpanded((cur) => (cur != null && memos[cur]?.id === id ? null : cur));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setApiError(`delete: ${msg}`);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="p-8 max-w-[1280px] mx-auto">
      {apiError && (
        <div className="mb-6 flex items-start justify-between rounded-md border border-signal-red/25 bg-signal-red/[0.06] p-3">
          <div>
            <p className="text-xs font-medium text-signal-red">Notice</p>
            <p className="text-[11px] text-text-tertiary mt-0.5">{apiError}</p>
          </div>
          <button
            onClick={() => setApiError(null)}
            className="text-text-quaternary hover:text-text-primary text-xs px-2"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <TerminalHeader
        eyebrow="MEMO ARCHIVE"
        title="Analyses"
        sub="Every research memo your account has produced. Click any row to expand. Use the × on each row to delete a single analysis."
        meta={
          <span>
            {memos.length} {memos.length === 1 ? "ENTRY" : "ENTRIES"}
          </span>
        }
        className="mb-8"
      />

      {loading ? (
        <p className="text-sm text-text-quaternary font-mono">Loading…</p>
      ) : memos.length === 0 ? (
        <TerminalPanel label="EMPTY" status="0 ENTRIES">
          <div className="text-center py-6">
            <p className="text-[13px] text-text-secondary mb-2">No analyses yet.</p>
            <p className="text-[12px] text-text-tertiary mb-5 max-w-sm mx-auto">
              Run your first query from the Analysis page and it will land here
              with its full thesis, trade ideas, and source ledger.
            </p>
            <Link
              href="/analysis"
              className="inline-block px-4 py-2 rounded-md bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-200 transition-colors"
            >
              Run an analysis
            </Link>
          </div>
        </TerminalPanel>
      ) : (
        <TerminalPanel
          label="LEDGER"
          status={`${memos.length} ${memos.length === 1 ? "ENTRY" : "ENTRIES"}`}
          bodyClassName="p-0"
        >
          <div className="divide-y divide-border-primary/40">
            {memos.map((memo, i) => {
              const isDeleting = deletingId != null && deletingId === memo.id;
              return (
              <div key={memo.id ?? i}>
                <div
                  onClick={() => !isDeleting && setExpanded(expanded === i ? null : i)}
                  className={`text-left grid grid-cols-[auto_1fr_auto_auto_auto] items-center gap-4 px-4 py-3 transition-colors ${
                    isDeleting ? "opacity-50" : "hover:bg-bg-elevated/40 cursor-pointer"
                  }`}
                >
                  {/* Decision pill (or neutral MEMO) */}
                  <StatusPill
                    label={memo.decision ?? "MEMO"}
                    tone={
                      memo.decision === "GO"
                        ? "green"
                        : memo.decision === "NO-GO"
                        ? "red"
                        : memo.decision === "WATCH"
                        ? "yellow"
                        : "blue"
                    }
                  />
                  {/* Title + executive summary */}
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-text-primary truncate">
                      {memo.title || memo.query}
                    </p>
                    {expanded !== i && (
                      <p className="text-[11px] text-text-tertiary line-clamp-1">
                        {memo.executive_summary}
                      </p>
                    )}
                  </div>
                  {/* Ticker chips */}
                  {memo.trade_ideas && memo.trade_ideas.length > 0 ? (
                    <div className="hidden md:flex gap-1">
                      {memo.trade_ideas.slice(0, 4).map((ti, j) => (
                        <span
                          key={j}
                          className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                            ti.direction?.includes("bullish")
                              ? "text-signal-green bg-signal-green/10"
                              : ti.direction?.includes("bearish")
                              ? "text-signal-red bg-signal-red/10"
                              : "text-text-quaternary bg-bg-elevated"
                          }`}
                        >
                          {ti.ticker}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span />
                  )}
                  {/* Date + expand chevron */}
                  <div className="flex items-center gap-3 text-[10px] font-mono text-text-quaternary shrink-0">
                    <span>
                      {memo.created_at
                        ? new Date(memo.created_at).toLocaleDateString()
                        : ""}
                    </span>
                    <span className="text-text-quaternary text-[12px] w-3 text-center">
                      {expanded === i ? "−" : "+"}
                    </span>
                  </div>
                  {/* Per-row delete — stays quiet until hover, then surfaces.
                      Click stops propagation so it doesn't toggle expand. */}
                  <button
                    onClick={(e) => handleDeleteOne(e, memo)}
                    disabled={isDeleting || !memo.id}
                    title="Delete this analysis"
                    aria-label="Delete this analysis"
                    className="shrink-0 w-7 h-7 flex items-center justify-center rounded-md text-text-quaternary hover:text-signal-red hover:bg-signal-red/10 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    {isDeleting ? (
                      <span
                        className="w-3 h-3 rounded-full border-[1.5px] border-current border-t-transparent"
                        style={{ animation: "spin-slow 0.8s linear infinite" }}
                      />
                    ) : (
                      <span className="text-[16px] leading-none">×</span>
                    )}
                  </button>
                </div>
                {expanded === i && (
                  <div className="px-4 pt-3 pb-5 border-t border-border-primary/40 bg-bg-primary/40">
                    <MemoPanel
                      memo={memo}
                      onDelete={(id) =>
                        setMemos((prev) => prev.filter((m) => m.id !== id))
                      }
                    />
                  </div>
                )}
              </div>
              );
            })}
          </div>
        </TerminalPanel>
      )}

      {/* Bulk-delete moved to a quiet footer — it's a rare destructive
          action, not something to keep promoted in the header. */}
      {memos.length > 1 && (
        <div className="mt-6 flex items-center justify-end">
          <button
            onClick={handleFlush}
            disabled={flushing}
            title="Hard-delete every analysis on your account"
            className="px-2.5 py-1 rounded-md border border-border-primary text-text-tertiary text-[10px] font-mono tracking-wider hover:text-signal-red hover:border-signal-red/40 transition-colors disabled:opacity-30"
          >
            {flushing ? "FLUSHING…" : "FLUSH ALL"}
          </button>
        </div>
      )}
    </div>
  );
}
