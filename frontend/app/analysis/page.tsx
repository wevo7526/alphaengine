"use client";

import { useState, useRef, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAnalysisContext } from "@/hooks/AnalysisContext";
import { AnalysisTrace } from "@/components/AnalysisTrace";
import { TerminalHeader } from "@/components/TerminalHeader";
import { StatusPill } from "@/components/StatusPill";

const SUGGESTED_QUERIES = [
  "Find alpha given geopolitical trends",
  "Deep analysis of AAPL",
  "What's the macro outlook?",
  "Best risk-adjusted trade in tech",
];

function AnalysisView() {
  const [input, setInput] = useState("");
  const { runs, activeRun, analyze, removeRun } = useAnalysisContext();
  const scrollRef = useRef<HTMLDivElement>(null);
  const searchParams = useSearchParams();
  const router = useRouter();

  // Auto-submit when navigated from a memo follow-up (?q=...&parent=memo_id)
  // or a scan finding (?q=...).
  useEffect(() => {
    const q = searchParams.get("q");
    const parent = searchParams.get("parent");
    if (q && !activeRun) {
      router.replace("/analysis");
      analyze(q.trim(), parent || undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [runs, activeRun]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || activeRun) return;
    setInput("");
    analyze(q);
  };

  const hasRuns = runs.length > 0;

  return (
    <div className="flex flex-col h-screen">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {!hasRuns ? (
          <EmptyState
            input={input}
            setInput={setInput}
            onSubmit={handleSubmit}
            activeRun={!!activeRun}
          />
        ) : (
          <div className="max-w-4xl mx-auto px-6 py-10 space-y-10">
            <TerminalHeader
              eyebrow="ANALYSIS · LIVE THREAD"
              title={`${runs.length} ${runs.length === 1 ? "run" : "runs"} in this thread`}
              sub="Each run streams desk-by-desk. Follow-ups continue the thread without restarting. Every claim resolves to a source — open the citations rail under any trade idea."
              meta={
                <div className="flex items-center gap-2 justify-end flex-wrap">
                  {activeRun ? (
                    <StatusPill label="RUNNING" tone="blue" pulse />
                  ) : (
                    <StatusPill label="IDLE" tone="neutral" />
                  )}
                </div>
              }
            />
            {runs.map((run, idx) => (
              <div key={run.id}>
                {/* Per-run breadcrumb pill — design-system consistent. */}
                <div className="mb-3 flex items-center justify-between gap-3">
                  <span className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary">
                    <span className="text-accent">///</span> RUN {String(idx + 1).padStart(2, "0")}
                  </span>
                  <div className="bg-accent/[0.06] border border-accent/15 rounded-md px-4 py-2.5 max-w-md">
                    <p className="text-[13px] text-text-primary truncate" title={run.query}>
                      {run.query}
                    </p>
                  </div>
                </div>
                <AnalysisTrace run={run} onDeleteMemo={() => removeRun(run.id)} />
              </div>
            ))}
          </div>
        )}
      </div>

      {hasRuns && (
        <div className="border-t border-border-primary bg-bg-primary px-6 py-4">
          <form
            onSubmit={handleSubmit}
            className="max-w-4xl mx-auto flex items-center gap-3"
          >
            <div className="flex-1 flex items-center gap-2 bg-bg-surface border border-border-primary rounded-md px-3 py-2.5 focus-within:border-zinc-600 transition-colors">
              <span className="text-accent font-mono text-[13px] shrink-0">{">"}</span>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={activeRun ? "Analysis in progress…" : "Follow up or ask something new…"}
                disabled={!!activeRun}
                className="flex-1 bg-transparent text-[13px] font-mono text-text-primary placeholder:text-text-quaternary outline-none disabled:opacity-40"
              />
            </div>
            <button
              type="submit"
              disabled={!!activeRun}
              className="px-4 py-2.5 rounded-md bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
            >
              Run
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

/**
 * Empty state — terminal command frame (red/yellow/green dots + blinking
 * cursor) wrapping the prompt input. Mirrors the marketing hero motif.
 */
function EmptyState({
  input,
  setInput,
  onSubmit,
  activeRun,
}: {
  input: string;
  setInput: (s: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  activeRun: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center min-h-full px-6 py-16">
      <div className="w-full max-w-xl">
        <div className="text-center mb-10">
          <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-4">
            <span className="text-accent">///</span> NEW ANALYSIS
          </p>
          <h1 className="text-[28px] sm:text-[32px] font-semibold tracking-[-0.02em] leading-[1.05] text-text-primary mb-3">
            What would you like to analyze?
          </h1>
          <p className="text-[13px] text-text-tertiary max-w-md mx-auto leading-relaxed">
            Ask in plain language. Tickers, themes, macro, risk — the desk
            will run the full pipeline and surface a memo with receipts.
          </p>
        </div>

        {/* Terminal command frame */}
        <form
          onSubmit={onSubmit}
          className="rounded-md border border-border-primary bg-bg-surface/70 backdrop-blur-sm overflow-hidden mb-6 focus-within:border-zinc-600 transition-colors"
        >
          <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center gap-1.5 text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
            <span className="w-1.5 h-1.5 rounded-full bg-signal-red/60" />
            <span className="w-1.5 h-1.5 rounded-full bg-signal-yellow/60" />
            <span className="w-1.5 h-1.5 rounded-full bg-signal-green/60" />
            <span className="ml-2">ANALYSIS · NEW</span>
            <span className="ml-auto text-[9px]">~10 min</span>
          </div>
          <div className="flex items-center gap-2 px-4 py-3.5">
            <span className="text-accent font-mono text-[14px] shrink-0">{">"}</span>
            <input
              type="text"
              autoFocus
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="long/short setup in regional banks ahead of FOMC"
              disabled={activeRun}
              className="flex-1 bg-transparent text-[14px] font-mono text-text-primary placeholder:text-text-quaternary outline-none disabled:opacity-40"
            />
            <button
              type="submit"
              disabled={activeRun || !input.trim()}
              className="px-3 py-1.5 rounded-md bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-200 transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
            >
              Run ↵
            </button>
          </div>
        </form>

        <div className="flex flex-col gap-1.5">
          <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
            <span className="text-accent">///</span> TRY ONE
          </p>
          {SUGGESTED_QUERIES.map((q) => (
            <button
              key={q}
              onClick={() => setInput(q)}
              className="text-left px-3 py-2 rounded-md border border-border-primary bg-bg-surface/40 hover:bg-bg-surface hover:border-zinc-600 transition-colors group"
            >
              <span className="text-accent font-mono text-[12px] mr-2.5">{">"}</span>
              <span className="text-[12px] font-mono text-text-secondary group-hover:text-text-primary transition-colors">
                {q}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AnalysisPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-text-tertiary">Loading…</div>}>
      <AnalysisView />
    </Suspense>
  );
}
