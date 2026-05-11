"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { IntelligenceMemo } from "@/lib/types";
import { MemoPanel } from "@/components/MemoPanel";

export default function MemosPage() {
  const [memos, setMemos] = useState<IntelligenceMemo[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [flushing, setFlushing] = useState(false);
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

  return (
    <div className="p-8 max-w-4xl">
      {apiError && (
        <div className="mb-4 flex items-start justify-between rounded-xl border border-signal-red/25 bg-signal-red/[0.06] p-3">
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

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
            Analyses
          </h1>
          <p className="text-sm text-text-tertiary">
            Every research memo your account has produced. Click to expand.
          </p>
        </div>
        {memos.length > 0 && (
          <button
            onClick={handleFlush}
            disabled={flushing}
            title="Hard-delete all analyses for your account"
            className="px-3 py-1.5 rounded-lg border border-signal-red/30 bg-signal-red/[0.06] text-signal-red text-xs font-medium hover:bg-signal-red/[0.12] transition-colors disabled:opacity-30"
          >
            {flushing ? "Flushing..." : `Flush All (${memos.length})`}
          </button>
        )}
      </div>

      {loading ? (
        <p className="text-sm text-text-quaternary">Loading analyses...</p>
      ) : memos.length === 0 ? (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
          <p className="text-[13px] text-text-secondary mb-2">No analyses yet</p>
          <p className="text-xs text-text-tertiary max-w-sm mx-auto">
            Go to <a href="/analysis" className="text-accent hover:underline">Analysis</a> to run your first query.
          </p>
        </div>
      ) : (
        <>
          <p className="text-[11px] text-text-quaternary mb-3">
            {memos.length} {memos.length === 1 ? "analysis" : "analyses"}
          </p>
          <div className="space-y-2">
            {memos.map((memo, i) => (
              <div key={memo.id ?? i}>
                <div
                  onClick={() => setExpanded(expanded === i ? null : i)}
                  className="rounded-xl border border-border-primary bg-bg-surface p-4 hover:border-zinc-600 transition-colors cursor-pointer"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[13px] font-medium text-text-primary">
                      {memo.title || memo.query}
                    </span>
                    <div className="flex items-center gap-2">
                      {memo.trade_ideas && memo.trade_ideas.length > 0 && (
                        <div className="flex gap-1">
                          {memo.trade_ideas.slice(0, 5).map((ti, j) => (
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
                      )}
                      <span className="text-[10px] text-text-quaternary">
                        {memo.created_at
                          ? new Date(memo.created_at).toLocaleDateString()
                          : ""}
                      </span>
                      <span className="text-text-quaternary text-xs">
                        {expanded === i ? "−" : "+"}
                      </span>
                    </div>
                  </div>
                  {expanded !== i && (
                    <p className="text-xs text-text-tertiary line-clamp-2">
                      {memo.executive_summary}
                    </p>
                  )}
                </div>
                {expanded === i && (
                  <div className="mt-2">
                    <MemoPanel
                      memo={memo}
                      onDelete={(id) =>
                        setMemos((prev) => prev.filter((m) => m.id !== id))
                      }
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
