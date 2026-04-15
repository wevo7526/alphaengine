"use client";

import { useState, useRef, useEffect } from "react";
import { useAnalysisContext } from "@/hooks/AnalysisContext";
import { AnalysisTrace } from "@/components/AnalysisTrace";

export default function AnalysisPage() {
  const [input, setInput] = useState("");
  const { runs, activeRun, analyze, removeRun } = useAnalysisContext();
  const scrollRef = useRef<HTMLDivElement>(null);

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
          <div className="flex flex-col items-center justify-center h-full px-6">
            <h2 className="text-2xl font-semibold tracking-tight text-text-primary mb-6">
              What would you like to analyze?
            </h2>

            <form
              onSubmit={handleSubmit}
              className="w-full max-w-lg flex items-center gap-3 mb-6"
            >
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask anything — tickers, themes, macro, risk..."
                className="flex-1 bg-bg-surface border border-border-primary rounded-xl px-4 py-2.5 text-[13px] text-text-primary placeholder:text-text-quaternary outline-none focus:border-zinc-600 transition-colors"
              />
              <button
                type="submit"
                className="px-4 py-2.5 rounded-xl bg-white text-bg-primary text-[13px] font-medium hover:bg-zinc-200 transition-colors"
              >
                Run
              </button>
            </form>

            <div className="flex flex-wrap items-center justify-center gap-2 max-w-lg">
              {[
                "Find alpha given geopolitical trends",
                "Deep analysis of AAPL",
                "What's the macro outlook?",
                "Best risk-adjusted trade in tech",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className="px-3 py-1.5 rounded-lg border border-border-primary text-xs font-medium text-text-tertiary hover:text-text-secondary hover:border-zinc-600 transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto px-6 py-8 space-y-10">
            {runs.map((run) => (
              <div key={run.id}>
                <div className="mb-4 flex justify-end">
                  <div className="bg-accent/[0.06] border border-accent/10 rounded-xl px-4 py-2.5 max-w-sm">
                    <p className="text-[13px] text-text-primary">{run.query}</p>
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
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={activeRun ? "Analysis in progress..." : "Follow up or ask something new..."}
              disabled={!!activeRun}
              className="flex-1 bg-bg-surface border border-border-primary rounded-xl px-4 py-2.5 text-[13px] text-text-primary placeholder:text-text-quaternary outline-none focus:border-zinc-600 transition-colors disabled:opacity-40"
            />
            <button
              type="submit"
              disabled={!!activeRun}
              className="px-4 py-2.5 rounded-xl bg-white text-bg-primary text-[13px] font-medium hover:bg-zinc-200 transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
            >
              Run
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
