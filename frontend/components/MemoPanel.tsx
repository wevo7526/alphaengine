"use client";

import { useState, useEffect } from "react";
import type { IntelligenceMemo, TradeIdea, RiskFactor, EnrichmentData } from "@/lib/types";
import { DIRECTION_STYLE, RISK_LEVEL_STYLE } from "@/lib/types";
import { ConvictionBar } from "./ConvictionBar";
import { TickerAnalyticsPanel } from "./TickerAnalytics";
import { CorrelationHeatmap } from "./CorrelationHeatmap";
import { OptionsPanel } from "./OptionsPanel";
import { api } from "@/lib/api";

const ACTION_MAP: Record<string, { label: string; color: string }> = {
  strong_bullish: { label: "LONG", color: "bg-signal-green/10 text-signal-green border-signal-green/20" },
  bullish: { label: "LONG", color: "bg-signal-green/10 text-signal-green border-signal-green/20" },
  bearish: { label: "SHORT", color: "bg-signal-red/10 text-signal-red border-signal-red/20" },
  strong_bearish: { label: "SHORT", color: "bg-signal-red/10 text-signal-red border-signal-red/20" },
  neutral: { label: "NEUTRAL", color: "bg-bg-elevated text-text-tertiary border-border-primary" },
};

interface TakeTradeResponse {
  id?: string;
  status?: string;
  entry_price?: number;
  entry_filled_at_market?: boolean;
  size_adjusted?: boolean;
  adjustment_reasons?: string[];
  // Surfaced when the gate decided to size down or warn (success paths only)
  liquidity?: {
    pct_of_adv?: number;
    days_to_liquidate?: number;
    spread_bps?: number;
    recommendation?: "ok" | "warn" | "block";
    reasons?: string[];
  };
}

function TradeIdeaCard({ idea, rank, memoId }: { idea: TradeIdea; rank: number; memoId?: string }) {
  const [open, setOpen] = useState(false);
  const [taken, setTaken] = useState(false);
  const [takeError, setTakeError] = useState<string | null>(null);
  const [filledAt, setFilledAt] = useState<number | null>(null);
  const [tradeMeta, setTradeMeta] = useState<TakeTradeResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const action = ACTION_MAP[idea.direction] ?? ACTION_MAP.neutral;

  const handleTakeTrade = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (taken || submitting) return;
    setSubmitting(true);
    setTakeError(null);
    try {
      const res = (await api.takeTrade({
        memo_id: memoId,
        ticker: idea.ticker,
        direction: idea.direction,
        action: idea.direction.includes("bullish") ? "BUY" : idea.direction.includes("bearish") ? "SHORT" : "HOLD",
        // Backend marks at current market when entry_price is omitted.
        stop_loss: idea.stop_loss ?? undefined,
        take_profit: idea.take_profit ?? undefined,
        position_size_pct: idea.position_size_pct,
        conviction: idea.conviction,
        thesis: idea.thesis,
      })) as TakeTradeResponse;
      setTaken(true);
      setTradeMeta(res);
      if (res.entry_price) setFilledAt(res.entry_price);
    } catch (err) {
      // 422 from the risk gate carries structured detail we want to surface.
      const msg = err instanceof Error ? err.message : "Failed";
      setTakeError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="rounded-xl border border-border-primary bg-bg-primary p-4 cursor-pointer hover:border-zinc-600 transition-all"
      style={{ animation: `fade-in 0.3s ease-out ${rank * 0.1}s both` }}
      onClick={() => setOpen(!open)}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono text-text-quaternary w-4">
            #{rank}
          </span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[15px] font-mono font-bold text-text-primary">
                {idea.ticker}
              </span>
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${action.color}`}>
                {action.label}
              </span>
            </div>
            <p className="text-xs text-text-tertiary mt-0.5 max-w-md">
              {idea.thesis}
            </p>
          </div>
        </div>
        <div className="text-right shrink-0 ml-4">
          <ConvictionBar value={idea.conviction} size="sm" />
          <span className="text-[10px] text-text-quaternary">
            {idea.position_size_pct}% size · {idea.time_horizon}
          </span>
        </div>
      </div>

      {/* Price levels row */}
      <div className="flex items-center gap-4 text-xs mt-2 flex-wrap">
        {idea.entry_zone && (
          <div className="flex items-center gap-1.5">
            <span className="text-text-quaternary">Entry </span>
            <span className="font-mono text-text-primary">{idea.entry_zone}</span>
            {idea.price_corrected && idea.live_price_used && (
              <span
                className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-signal-yellow/10 text-signal-yellow border border-signal-yellow/30"
                title={`System auto-corrected from ${idea.original_entry_zone ?? "stale value"} to anchor on live price $${idea.live_price_used}.`}
              >
                Auto-anchored
              </span>
            )}
          </div>
        )}
        {idea.stop_loss && (
          <div>
            <span className="text-text-quaternary">Stop </span>
            <span className="font-mono text-signal-red">${idea.stop_loss}</span>
          </div>
        )}
        {idea.take_profit && (
          <div>
            <span className="text-text-quaternary">Target </span>
            <span className="font-mono text-signal-green">${idea.take_profit}</span>
          </div>
        )}
        {idea.risk_reward_ratio && (
          <div>
            <span className="text-text-quaternary">R/R </span>
            <span className="font-mono text-accent">{idea.risk_reward_ratio}:1</span>
          </div>
        )}
      </div>

      {/* Beta layering row — systematic exposure decomposition */}
      {(idea.beta_to_spy != null || idea.sector || idea.structure_type || idea.regime_conditional_size_pct != null) && (
        <div className="flex items-center gap-3 text-[11px] mt-2 flex-wrap">
          {idea.beta_to_spy != null && (
            <span className="text-text-quaternary">
              β-SPY <span className="font-mono text-text-tertiary">{Number(idea.beta_to_spy).toFixed(2)}</span>
            </span>
          )}
          {idea.sector && (
            <span className="text-text-quaternary">
              Sector <span className="font-mono text-text-tertiary">{idea.sector}</span>
            </span>
          )}
          {idea.structure_type && idea.structure_type !== "outright" && (
            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/30">
              {idea.structure_type}{idea.pair_short_leg ? ` (vs ${idea.pair_short_leg})` : ""}
            </span>
          )}
          {idea.regime_conditional_size_pct != null && idea.regime_conditional_size_pct !== idea.position_size_pct && (
            <span className="text-text-quaternary" title="Size adjusted for current regime per plan.regime_sensitivity">
              Regime size <span className="font-mono text-text-tertiary">{Number(idea.regime_conditional_size_pct).toFixed(1)}%</span>
            </span>
          )}
        </div>
      )}

      {open && (
        <div className="mt-3 pt-3 border-t border-border-primary space-y-2 text-xs" style={{ animation: "fade-in 0.2s ease-out" }}>
          {idea.catalysts?.length > 0 && (
            <div>
              <span className="text-text-quaternary font-medium">Catalysts: </span>
              <span className="text-text-secondary">{idea.catalysts?.join(" · ")}</span>
            </div>
          )}
          {idea.risks?.length > 0 && (
            <div>
              <span className="text-text-quaternary font-medium">Risks: </span>
              <span className="text-text-secondary">{idea.risks?.join(" · ")}</span>
            </div>
          )}
          <div className="mt-2 flex items-center gap-3 flex-wrap">
            <button
              onClick={handleTakeTrade}
              disabled={submitting || taken}
              className={`px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors ${
                taken
                  ? "bg-signal-green/10 text-signal-green border border-signal-green/20 cursor-default"
                  : submitting
                    ? "bg-zinc-300 text-bg-primary cursor-wait"
                    : "bg-white text-bg-primary hover:bg-zinc-200"
              }`}
            >
              {taken ? "Trade Logged" : submitting ? "Filling..." : "Take Trade @ Market"}
            </button>
            {filledAt && (
              <span className="text-[11px] text-signal-green font-mono">
                Filled @ ${filledAt.toFixed(2)}
              </span>
            )}
            {tradeMeta?.size_adjusted && (
              <span className="text-[11px] text-signal-yellow font-mono" title={(tradeMeta.adjustment_reasons || []).join(" · ")}>
                Size adjusted
              </span>
            )}
            {tradeMeta?.liquidity?.recommendation === "warn" && (
              <span
                className="text-[10px] text-signal-yellow border border-signal-yellow/30 bg-signal-yellow/[0.06] rounded px-1.5 py-0.5"
                title={(tradeMeta.liquidity.reasons || []).join(" · ")}
              >
                Liquidity: {tradeMeta.liquidity.pct_of_adv != null ? `${(tradeMeta.liquidity.pct_of_adv * 100).toFixed(1)}% ADV` : "warn"}
                {tradeMeta.liquidity.days_to_liquidate != null && ` · ${tradeMeta.liquidity.days_to_liquidate}d to exit`}
              </span>
            )}
            {takeError && (
              <span
                className="text-[11px] text-signal-red max-w-md break-words"
                title="Risk gate response"
              >
                {takeError}
              </span>
            )}
          </div>
          {tradeMeta?.adjustment_reasons && tradeMeta.adjustment_reasons.length > 0 && (
            <ul className="mt-1.5 text-[10px] text-text-quaternary space-y-0.5">
              {tradeMeta.adjustment_reasons.slice(0, 3).map((r, i) => (
                <li key={i}>· {r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function RiskMatrix({ factors }: { factors: RiskFactor[] }) {
  const sevOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  const sorted = [...factors].sort(
    (a, b) => (sevOrder[a.severity as keyof typeof sevOrder] ?? 4) - (sevOrder[b.severity as keyof typeof sevOrder] ?? 4)
  );

  return (
    <div className="space-y-2">
      {sorted.map((f, i) => {
        const sevColor =
          f.severity === "critical"
            ? "bg-signal-red text-white"
            : f.severity === "high"
              ? "bg-signal-red/20 text-signal-red"
              : f.severity === "medium"
                ? "bg-signal-yellow/20 text-signal-yellow"
                : "bg-bg-elevated text-text-tertiary";

        return (
          <div
            key={i}
            className="rounded-lg border border-border-primary bg-bg-primary p-3"
            style={{ animation: `fade-in 0.3s ease-out ${i * 0.05}s both` }}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${sevColor}`}>
                {f.severity}
              </span>
              <span className="text-[10px] text-text-quaternary uppercase tracking-wider">
                {f.category}
              </span>
            </div>
            <p className="text-xs text-text-secondary">{f.description}</p>
            <p className="text-[11px] text-text-quaternary mt-1">
              Mitigation: {f.mitigation}
            </p>
          </div>
        );
      })}
    </div>
  );
}

export function MemoPanel({ memo, onDelete }: { memo: IntelligenceMemo; onDelete?: (id: string) => void }) {
  const [showFull, setShowFull] = useState(false);
  const [enrichment, setEnrichment] = useState<EnrichmentData | null>(null);
  const [enrichLoading, setEnrichLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const riskColor = RISK_LEVEL_STYLE[memo.overall_risk_level] ?? "text-text-tertiary";

  const handleDelete = async () => {
    const id = memo.id;
    if (!id || deleting) return;
    setDeleting(true);
    try {
      await api.deleteMemo(id);
      onDelete?.(id);
    } catch {
      setDeleting(false);
    }
  };

  const handleExport = async () => {
    const id = memo.id;
    if (!id || exporting) return;
    setExporting(true);
    try {
      await api.downloadPdf(api.exportMemoUrl(id), `alpha-engine-memo-${id.slice(0, 8)}.pdf`);
    } catch {
      // ignore
    } finally {
      setExporting(false);
    }
  };

  // Fetch computed enrichment data for all tickers in the memo
  useEffect(() => {
    const tickers = memo.tickers_analyzed?.length
      ? memo.tickers_analyzed
      : memo.trade_ideas?.map((t) => t.ticker) ?? [];
    const unique = [...new Set(tickers)].filter(Boolean);
    if (unique.length === 0) return;

    setEnrichLoading(true);
    api.enrich(unique).then((data: unknown) => {
      setEnrichment(data as EnrichmentData);
      setEnrichLoading(false);
    }).catch(() => setEnrichLoading(false));
  }, [memo]);

  // Decision badge styling
  const decision = memo.decision || "WATCH";
  const decisionColor =
    decision === "GO"
      ? "bg-signal-green/10 text-signal-green border-signal-green/30"
      : decision === "NO-GO"
        ? "bg-signal-red/10 text-signal-red border-signal-red/30"
        : "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30";

  return (
    <div className="space-y-4" style={{ animation: "fade-in 0.5s ease-out" }}>
      {/* Title + Executive Summary + Decision Badge */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-6">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1">
            {memo.decision && (
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-semibold uppercase tracking-wider ${decisionColor}`}>
                  <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M6 1L2 2.5V6C2 8.5 3.5 10.5 6 11C8.5 10.5 10 8.5 10 6V2.5L6 1Z" />
                  </svg>
                  {decision}
                </span>
                {memo.decision_confidence !== undefined && memo.decision_confidence > 0 && (
                  <span className="text-[10px] text-text-quaternary font-mono">
                    conviction {memo.decision_confidence}
                  </span>
                )}
                {/* Grounding tripwire: tells the audience whether the LLM cited real numbers */}
                {memo.grounding && memo.grounding.confidence && memo.grounding.confidence !== "n/a" && (
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-medium uppercase tracking-wider ${
                      memo.grounding.confidence === "high"
                        ? "bg-signal-green/10 text-signal-green border-signal-green/30"
                        : memo.grounding.confidence === "medium"
                          ? "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30"
                          : "bg-signal-red/10 text-signal-red border-signal-red/30"
                    }`}
                    title={`${memo.grounding.numeric_claims ?? 0} numeric claims, ${memo.grounding.ungrounded_count ?? 0} not traced to a tool result`}
                  >
                    {memo.grounding.confidence === "high"
                      ? "Grounded"
                      : memo.grounding.confidence === "medium"
                        ? `${memo.grounding.ungrounded_count ?? 0} unverified`
                        : `${memo.grounding.ungrounded_count ?? 0} unverified`}
                  </span>
                )}
                {/* Plan confidence: only flag when low — keeps the chrome quiet at 70+ */}
                {memo.plan_confidence !== undefined && memo.plan_confidence > 0 && memo.plan_confidence < 60 && (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-medium uppercase tracking-wider bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30"
                    title={memo.plan_confidence_reason || "Query was ambiguous; some inferences were made."}
                  >
                    Plan {memo.plan_confidence}
                  </span>
                )}
                {/* Data quality: surface only when degraded/critical */}
                {memo.data_quality && memo.data_quality !== "complete" && (
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-medium uppercase tracking-wider ${
                      memo.data_quality === "critical"
                        ? "bg-signal-red/10 text-signal-red border-signal-red/30"
                        : "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30"
                    }`}
                    title={`Some pipeline desks ran in ${memo.data_quality} mode (timeouts or failures). Treat results with care.`}
                  >
                    Data {memo.data_quality}
                  </span>
                )}
                {/* Sub-question coverage: flag if not all answered */}
                {memo.sub_question_coverage && memo.sub_question_coverage.length > 0 && (() => {
                  const total = memo.sub_question_coverage.length;
                  const answered = memo.sub_question_coverage.filter((c) => c.answered).length;
                  if (answered === total) return null;  // hide on full coverage
                  return (
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-medium uppercase tracking-wider bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30"
                      title={`${answered}/${total} sub-questions addressed in research.`}
                    >
                      Q {answered}/{total}
                    </span>
                  );
                })()}
                {/* Diversity flag: surfaced if Strategist output is monolithic */}
                {memo.diversity && memo.diversity.monolithic && (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-medium uppercase tracking-wider bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30"
                    title={memo.diversity.reason || "Trade ideas show low structural diversity"}
                  >
                    Concentrated
                  </span>
                )}
              </div>
            )}
            <h2 className="text-lg font-semibold text-text-primary leading-snug">
              {memo.title}
            </h2>
          </div>
          <div className="shrink-0 flex items-center gap-1">
            {memo.id && (
              <button
                onClick={handleExport}
                disabled={exporting}
                className="px-2 py-1 rounded-lg text-[11px] font-medium text-text-quaternary hover:text-text-primary hover:bg-white/[0.04] transition-colors disabled:opacity-30"
                title="Export as PDF"
              >
                {exporting ? "..." : "Export PDF"}
              </button>
            )}
            {memo.id && onDelete && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="px-2 py-1 rounded-lg text-[11px] font-medium text-text-quaternary hover:text-signal-red hover:bg-signal-red/10 transition-colors disabled:opacity-30"
                title="Delete this analysis"
              >
                {deleting ? "..." : "Delete"}
              </button>
            )}
          </div>
        </div>
        {memo.decision_reason && (
          <p className="text-[11px] text-text-tertiary mb-3 italic">
            {memo.decision_reason}
          </p>
        )}
        <p className="text-[13px] text-text-secondary leading-relaxed">
          {memo.executive_summary}
        </p>

        {/* Status strip */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-4 pt-4 border-t border-border-primary text-[11px]">
          {memo.macro_regime && (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-accent" />
              <span className="text-text-quaternary">Regime</span>
              <span className="text-text-primary font-medium">{memo.macro_regime}</span>
            </div>
          )}
          {memo.overall_risk_level && (
            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${memo.overall_risk_level === "low" || memo.overall_risk_level === "moderate" ? "bg-signal-green" : "bg-signal-red"}`} />
              <span className="text-text-quaternary">Risk</span>
              <span className={`font-medium ${riskColor}`}>{memo.overall_risk_level}</span>
            </div>
          )}
          {memo.portfolio_positioning && (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-signal-yellow" />
              <span className="text-text-quaternary">Positioning</span>
              <span className="text-text-primary font-medium">{memo.portfolio_positioning}</span>
            </div>
          )}
          {memo.tickers_analyzed?.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-quaternary">Tickers</span>
              <span className="font-mono text-text-primary">{memo.tickers_analyzed?.join(", ")}</span>
            </div>
          )}
        </div>
      </div>

      {/* Key Findings */}
      {memo.key_findings?.length > 0 && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
            Key Findings
          </h3>
          <div className="space-y-2">
            {(memo.key_findings || []).map((f, i) => (
              <div
                key={i}
                className="flex items-start gap-2.5 text-[13px] text-text-secondary"
                style={{ animation: `fade-in 0.3s ease-out ${i * 0.08}s both` }}
              >
                <span className="text-accent font-bold mt-0.5 shrink-0">{i + 1}</span>
                <span className="leading-relaxed">{f}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Plan Shape — surfaces what the Interpreter actually decided */}
      {(memo.question_type || memo.benchmark || memo.instrument_preference || (memo.idea_archetype && memo.idea_archetype.length > 0)) && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
            Plan Shape
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[12px]">
            {memo.question_type && (
              <div>
                <span className="text-text-quaternary">Question type</span>
                <span className="ml-2 font-mono text-text-primary">{memo.question_type.replace(/_/g, " ")}</span>
              </div>
            )}
            {memo.benchmark && (
              <div>
                <span className="text-text-quaternary">Benchmark</span>
                <span className="ml-2 font-mono text-text-primary">{memo.benchmark}</span>
              </div>
            )}
            {memo.instrument_preference && (
              <div>
                <span className="text-text-quaternary">Instrument</span>
                <span className="ml-2 font-mono text-text-primary">{memo.instrument_preference.replace(/_/g, " ")}</span>
              </div>
            )}
          </div>
          {memo.idea_archetype && memo.idea_archetype.length > 0 && (
            <div className="mt-3">
              <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1.5">Archetype directive</p>
              <div className="flex flex-wrap gap-1.5">
                {memo.idea_archetype.map((a, i) => (
                  <span key={i} className="text-[10px] font-mono px-2 py-0.5 rounded bg-bg-elevated text-text-secondary">
                    {a}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Sub-questions answered (if Research engaged with them) */}
      {memo.sub_question_coverage && memo.sub_question_coverage.length > 0 && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
            Sub-Questions ({memo.sub_question_coverage.filter((c) => c.answered).length}/{memo.sub_question_coverage.length} addressed)
          </h3>
          <ul className="space-y-1.5">
            {memo.sub_question_coverage.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-[12px]">
                <span className={`shrink-0 mt-0.5 text-[11px] font-mono ${c.answered ? "text-signal-green" : "text-signal-yellow"}`}>
                  {c.answered ? "✓" : "?"}
                </span>
                <span className={c.answered ? "text-text-secondary" : "text-text-tertiary"}>{c.question}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Falsification — what would change the view */}
      {memo.falsification_criteria && memo.falsification_criteria.length > 0 && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
            What Would Change Our View
          </h3>
          <ul className="space-y-1.5">
            {memo.falsification_criteria.map((c, i) => {
              const score = (memo.falsification_probabilities || []).find((fp) => fp.criterion === c);
              const prob = score?.probability;
              const probColor =
                prob === "high"
                  ? "text-signal-red"
                  : prob === "low"
                    ? "text-signal-green"
                    : "text-signal-yellow";
              return (
                <li key={i} className="flex items-start gap-2 text-[12px]">
                  {prob && (
                    <span className={`shrink-0 mt-0.5 text-[10px] font-mono uppercase ${probColor}`}>
                      [{prob}]
                    </span>
                  )}
                  <span className="text-text-secondary">{c}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Regime sensitivity */}
      {memo.regime_sensitivity && memo.regime_sensitivity.length > 0 && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
            Regime Sensitivity {memo.macro_context?.current_regime && (
              <span className="ml-1 text-text-tertiary normal-case">(current: {memo.macro_context.current_regime})</span>
            )}
          </h3>
          <div className="space-y-2">
            {memo.regime_sensitivity.map((rs, i) => {
              const isCurrent = rs.regime === memo.macro_context?.current_regime;
              return (
                <div
                  key={i}
                  className={`text-[12px] rounded-lg p-3 ${isCurrent ? "border border-accent/40 bg-accent/[0.04]" : "bg-bg-elevated"}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className={`font-mono uppercase ${isCurrent ? "text-accent" : "text-text-tertiary"}`}>
                      {rs.regime} {isCurrent && "★"}
                    </span>
                    {rs.conviction_multiplier !== undefined && (
                      <span className="text-[10px] font-mono text-text-tertiary">
                        size ×{rs.conviction_multiplier}
                      </span>
                    )}
                  </div>
                  {rs.ideal_position && (
                    <p className="text-text-secondary leading-relaxed mb-1">{rs.ideal_position}</p>
                  )}
                  {rs.key_assumption && (
                    <p className="text-[11px] text-text-quaternary italic">Assumes: {rs.key_assumption}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Trade Ideas */}
      {memo.trade_ideas?.length > 0 && (
        <div className="mb-4">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3 px-1">
            Trade Ideas — ranked by conviction
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {(memo.trade_ideas || []).map((idea, i) => (
              <TradeIdeaCard key={i} idea={idea} rank={i + 1} memoId={(memo as unknown as Record<string, unknown>).id as string} />
            ))}
          </div>
        </div>
      )}

      {/* Risk + Hedging side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {memo.risk_factors?.length > 0 && (
          <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
            <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
              Risk Factors
            </h3>
            <RiskMatrix factors={memo.risk_factors} />
          </div>
        )}

        {memo.hedging_recommendations?.length > 0 && (
          <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
            <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
              Hedging Recommendations
            </h3>
            <div className="space-y-2">
              {(memo.hedging_recommendations || []).map((h, i) => {
                // Try to split on " — " for instrument vs rationale
                const parts = h.split(" — ");
                const instrument = parts[0];
                const rationale = parts.length > 1 ? parts.slice(1).join(" — ") : null;
                return (
                  <div
                    key={i}
                    className="rounded-lg border border-border-primary bg-bg-primary p-3.5 flex items-start gap-3"
                    style={{ animation: `fade-in 0.3s ease-out ${i * 0.05}s both` }}
                  >
                    <span className="text-[10px] font-mono font-bold text-signal-yellow bg-signal-yellow/10 px-1.5 py-0.5 rounded shrink-0 mt-0.5">
                      H{i + 1}
                    </span>
                    <div>
                      <p className="text-[13px] text-text-primary font-medium leading-snug">
                        {instrument}
                      </p>
                      {rationale && (
                        <p className="text-xs text-text-tertiary mt-0.5">
                          {rationale}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Computed Analytics — this is what ChatGPT can't do */}
      {enrichLoading && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-4 flex items-center gap-2">
          <div className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent" style={{ animation: "spin-slow 0.8s linear infinite" }} />
          <span className="text-xs text-text-tertiary">Computing analytics...</span>
        </div>
      )}

      {enrichment && Object.keys(enrichment.analytics).length > 0 && (
        <div className="mb-4">
          <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3 px-1">
            Computed Analytics
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {Object.entries(enrichment.analytics).map(([ticker, data]) => (
              <TickerAnalyticsPanel key={ticker} ticker={ticker} analytics={data} />
            ))}
          </div>
        </div>
      )}

      {/* Options Flow Analytics */}
      {enrichment && Object.keys(enrichment.analytics).length > 0 && (
        (() => {
          const tickersWithOptions = Object.entries(enrichment.analytics)
            .filter(([, data]) => data.options && !("error" in (data.options as Record<string, unknown>)))
            .slice(0, 4);
          if (tickersWithOptions.length === 0) return null;
          return (
            <div>
              <h3 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3 px-1">
                Options Flow
              </h3>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {tickersWithOptions.map(([ticker, data]) => (
                  <OptionsPanel
                    key={ticker}
                    ticker={ticker}
                    data={data.options as never}
                  />
                ))}
              </div>
            </div>
          );
        })()
      )}

      {enrichment?.correlation && enrichment.correlation.matrix.length > 1 && (
        <div className="mb-4">
          <CorrelationHeatmap
            tickers={enrichment.correlation.tickers}
            matrix={enrichment.correlation.matrix}
          />
        </div>
      )}

      {/* Full Analysis (collapsible) */}
      {memo.analysis && (
        <div className="rounded-xl border border-border-primary bg-bg-surface overflow-hidden">
          <button
            onClick={() => setShowFull(!showFull)}
            className="w-full px-5 py-3 text-left text-[11px] font-medium text-text-quaternary uppercase tracking-wider hover:text-text-tertiary transition-colors flex items-center justify-between"
          >
            Full Analysis
            <span className="text-text-quaternary">{showFull ? "−" : "+"}</span>
          </button>
          {showFull && (
            <div
              className="px-5 pb-5 text-[13px] text-text-secondary leading-relaxed whitespace-pre-wrap"
              style={{ animation: "fade-in 0.3s ease-out" }}
            >
              {memo.analysis}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
