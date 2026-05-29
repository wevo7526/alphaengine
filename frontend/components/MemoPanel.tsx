"use client";

import { useState, useEffect } from "react";
import type { IntelligenceMemo, TradeIdea, RiskFactor, EnrichmentData } from "@/lib/types";
import { DIRECTION_STYLE, RISK_LEVEL_STYLE } from "@/lib/types";
import { ConvictionBar } from "./ConvictionBar";
import { TickerAnalyticsPanel } from "./TickerAnalytics";
import { CorrelationHeatmap } from "./CorrelationHeatmap";
import { OptionsPanel } from "./OptionsPanel";
import { CitationsRail, CitationIndexPanel, citationsFromLineage } from "./Citations";
import { ProseWithCitations } from "./ProseWithCitations";
import { TerminalPanel } from "./TerminalPanel";
import { StatusPill } from "./StatusPill";
import { api } from "@/lib/api";

// Style classification → tailwind classes. Hedge-fund convention: growth in
// teal (capital appreciation), value in green (cheapness), defensive in
// blue (boring/safe), contrarian/short in red, hedge in yellow (risk).
const STYLE_LABEL_CLASSES: Record<string, string> = {
  growth: "bg-accent/10 text-accent border-accent/30",
  value: "bg-signal-green/10 text-signal-green border-signal-green/30",
  quality: "bg-signal-green/10 text-signal-green border-signal-green/30",
  momentum: "bg-accent/10 text-accent border-accent/30",
  low_vol: "bg-text-tertiary/10 text-text-secondary border-border-primary",
  gard: "bg-accent/10 text-accent border-accent/30",
  defensive: "bg-text-tertiary/10 text-text-secondary border-border-primary",
  cyclical: "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30",
  special_situation: "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30",
  event_driven: "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30",
  macro: "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30",
  contrarian: "bg-signal-red/10 text-signal-red border-signal-red/30",
  mean_reversion: "bg-signal-red/10 text-signal-red border-signal-red/30",
  secular_winner: "bg-accent/10 text-accent border-accent/30",
  small_cap: "bg-accent/10 text-accent border-accent/30",
  international: "bg-text-tertiary/10 text-text-secondary border-border-primary",
  yield: "bg-signal-green/10 text-signal-green border-signal-green/30",
  hedge: "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30",
  volatility: "bg-signal-yellow/10 text-signal-yellow border-signal-yellow/30",
};

function styleLabelClasses(label: string | null | undefined): string {
  if (!label) return "bg-bg-elevated text-text-tertiary border-border-primary";
  const key = label.toLowerCase().replace(/\s/g, "_");
  return STYLE_LABEL_CLASSES[key] || "bg-bg-elevated text-text-tertiary border-border-primary";
}

const ACTION_MAP: Record<string, { label: string; color: string }> = {
  strong_bullish: { label: "LONG", color: "bg-signal-green/10 text-signal-green border-signal-green/20" },
  bullish: { label: "LONG", color: "bg-signal-green/10 text-signal-green border-signal-green/20" },
  bearish: { label: "SHORT", color: "bg-signal-red/10 text-signal-red border-signal-red/20" },
  strong_bearish: { label: "SHORT", color: "bg-signal-red/10 text-signal-red border-signal-red/20" },
  neutral: { label: "NEUTRAL", color: "bg-bg-elevated text-text-tertiary border-border-primary" },
};

// A trade idea belongs in the "secondaries" sleeve when ANY of these signals
// indicates it's not a mega-cap core position. The Strategist tags ideas
// with tier / market_cap_bucket / screen_source — we read whichever it set.
// Missing tags default to "core" so the split is safe on legacy memos.
const _SECONDARY_BUCKETS = new Set(["mid_cap", "small_cap", "micro_cap"]);
function isSecondaryIdea(idea: TradeIdea): boolean {
  if (typeof idea.tier === "number" && idea.tier >= 2) return true;
  const bucket = (idea.market_cap_bucket || "").toLowerCase();
  if (_SECONDARY_BUCKETS.has(bucket)) return true;
  if (idea.screen_source) return true;
  return false;
}

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

function TradeIdeaCard({ idea, rank, memoId, lineage }: { idea: TradeIdea; rank: number; memoId?: string; lineage?: IntelligenceMemo["lineage"] }) {
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
      className="rounded-md border border-border-primary bg-bg-primary p-4 cursor-pointer hover:border-zinc-600 transition-all"
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

      {/* Style + market-cap pills — hedge-fund classification, surfaced prominently */}
      {(idea.style_label || idea.market_cap_bucket) && (
        <div className="flex items-center gap-1.5 mt-2 flex-wrap">
          {idea.style_label && (
            <span
              className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border font-medium ${styleLabelClasses(idea.style_label)}`}
              title="Hedge-fund style classification"
            >
              {idea.style_label.replace(/_/g, " ")}
            </span>
          )}
          {idea.market_cap_bucket && idea.market_cap_bucket !== "mega_cap" && (
            <span
              className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border bg-accent/10 text-accent border-accent/30 font-medium"
              title="Non-mega-cap alpha — sourced from the Interpreter's secondary_universe"
            >
              {idea.market_cap_bucket.replace(/_/g, " ")}
            </span>
          )}
        </div>
      )}

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

      {/* Source rail — uses the resolver-attached citations when present;
          falls back to ticker-matched lineage sources so the rail is
          almost never empty when the memo touched the ticker at all. */}
      <CitationsRail
        citations={
          idea.citations && idea.citations.length > 0
            ? idea.citations
            : citationsFromLineage(lineage, idea.ticker)
        }
      />
    </div>
  );
}

function RiskMatrix({ factors, lineage, primaryTicker }: { factors: RiskFactor[]; lineage?: IntelligenceMemo["lineage"]; primaryTicker?: string }) {
  const sevOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  const sorted = [...factors].sort(
    (a, b) => (sevOrder[a.severity as keyof typeof sevOrder] ?? 4) - (sevOrder[b.severity as keyof typeof sevOrder] ?? 4)
  );

  return (
    <div className="space-y-2">
      {sorted.map((f, i) => {
        // Severity drives both the left bar color and the bracket-tag color
        const sevBar =
          f.severity === "critical"
            ? "bg-signal-red"
            : f.severity === "high"
              ? "bg-signal-red/70"
              : f.severity === "medium"
                ? "bg-signal-yellow"
                : "bg-text-quaternary";
        const sevText =
          f.severity === "critical" || f.severity === "high"
            ? "text-signal-red"
            : f.severity === "medium"
              ? "text-signal-yellow"
              : "text-text-tertiary";

        return (
          <div
            key={i}
            className="rounded-md border border-border-primary bg-bg-primary overflow-hidden flex"
            style={{ animation: `fade-in 0.3s ease-out ${i * 0.05}s both` }}
          >
            {/* Severity left bar — mirrors the PDF treatment so in-app and
                exported memos read the same way. */}
            <span aria-hidden className={`w-[3px] shrink-0 ${sevBar}`} />
            <div className="flex-1 min-w-0 p-3">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[9px] font-mono tracking-[0.18em] uppercase font-semibold ${sevText}`}>
                  [{f.severity}]
                </span>
                <span className="text-[10px] text-text-quaternary uppercase tracking-wider">
                  {f.category}
                </span>
              </div>
              <p className="text-xs text-text-secondary">{f.description}</p>
              {f.mitigation && (
                <p className="text-[11px] text-text-quaternary mt-1">
                  <span className="text-text-tertiary font-medium">Mitigation:</span> {f.mitigation}
                </p>
              )}
              <CitationsRail
                citations={
                  f.citations && f.citations.length > 0
                    ? f.citations
                    : citationsFromLineage(lineage, primaryTicker)
                }
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Human-readable label for each source_type code from infra/lineage.py.
const SOURCE_TYPE_LABEL: Record<string, string> = {
  sec_filing: "SEC filings",
  sec_insider: "Insider trades (Form 4)",
  sec_13f: "13F holdings",
  fred_series: "Fed (FRED)",
  market_price: "Market data",
  news_article: "News",
  web_search: "Web research",
  technical: "Technicals",
  screen: "Discovery screens",
  computed: "Computed analytics",
  other: "Other",
};

function LineagePanel({ lineage }: { lineage: NonNullable<IntelligenceMemo["lineage"]> }) {
  const [expanded, setExpanded] = useState(false);

  // Group sources by source_type for the collapsed summary view
  const byType: Record<string, typeof lineage.sources> = {};
  for (const src of lineage.sources) {
    const t = src.type || "other";
    if (!byType[t]) byType[t] = [];
    byType[t].push(src);
  }
  const orderedTypes = Object.keys(byType).sort(
    (a, b) => (byType[b]?.length || 0) - (byType[a]?.length || 0)
  );

  return (
    <div className="rounded-md border border-border-primary bg-bg-surface overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border-primary/60">
        <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">
          <span className="text-accent">///</span> SOURCES &amp; PROVENANCE
        </span>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] font-mono tracking-wider text-text-tertiary hover:text-text-primary transition-colors"
        >
          {expanded ? "HIDE" : "SHOW"}
        </button>
      </header>
      <div className="p-5">
      <p className="text-[11px] text-text-tertiary mb-3">
        {lineage.n_tool_calls} tool calls produced {lineage.n_unique_sources}{" "}
        unique sources. Every number in this memo traces back to one of these.
      </p>

      {/* Compact summary by source type */}
      <div className="flex flex-wrap gap-1.5">
        {orderedTypes.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-1 rounded-md border border-border-primary bg-bg-primary px-2 py-0.5 text-[11px] text-text-secondary"
            title={SOURCE_TYPE_LABEL[t] ?? t}
          >
            <span className="text-text-tertiary">{SOURCE_TYPE_LABEL[t] ?? t}</span>
            <span className="font-mono text-text-primary">{byType[t].length}</span>
          </span>
        ))}
      </div>

      {expanded && (
        <div className="mt-4 space-y-3">
          {orderedTypes.map((t) => (
            <div key={t}>
              <p className="text-[11px] text-text-quaternary uppercase tracking-wider mb-1">
                {SOURCE_TYPE_LABEL[t] ?? t}
              </p>
              <ul className="space-y-1">
                {byType[t].map((src, i) => (
                  <li
                    key={`${t}-${i}`}
                    className="text-[12px] text-text-secondary flex items-baseline gap-2"
                  >
                    <span className="text-text-quaternary font-mono text-[10px] shrink-0">
                      {src.tool ?? "—"}
                    </span>
                    {src.url ? (
                      <a
                        href={src.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent hover:underline truncate"
                      >
                        {src.id}
                      </a>
                    ) : (
                      <span className="truncate font-mono">{src.id}</span>
                    )}
                    {src.form_type && (
                      <span className="text-text-tertiary text-[10px] shrink-0">
                        ({src.form_type})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="text-[10px] text-text-quaternary pt-2 border-t border-border-primary">
            Captured at{" "}
            {lineage.generated_at
              ? new Date(lineage.generated_at).toLocaleString()
              : "—"}
          </p>
        </div>
      )}
      </div>
    </div>
  );
}


export function MemoPanel({ memo, onDelete }: { memo: IntelligenceMemo; onDelete?: (id: string) => void }) {
  const [showFull, setShowFull] = useState(false);
  const [showSources, setShowSources] = useState(false);
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

  // Phase G — citation coverage drives a VERIFIED / PARTIAL / UNVERIFIED
  // pill on the header. Falls back to the legacy `Grounded` chip on memos
  // persisted before verification_status existed.
  const verification = memo.verification_status;
  const verificationTone: "green" | "yellow" | "red" =
    verification === "verified" ? "green"
      : verification === "partial" ? "yellow"
        : "red";
  const verificationLabel =
    verification === "verified" ? "VERIFIED"
      : verification === "partial" ? "PARTIAL"
        : verification === "unverified" ? "UNVERIFIED"
          : null;

  return (
    <div className="space-y-4" style={{ animation: "fade-in 0.5s ease-out" }}>
      {/* Title + Executive Summary + Decision Badge */}
      <div className="rounded-md border border-border-primary bg-bg-surface p-6">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1">
            {memo.decision && (
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[11px] font-semibold uppercase tracking-wider ${decisionColor}`}>
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
                {/* Phase G — citation coverage. Replaces the legacy
                    grounding chip below when the new field is present. */}
                {verificationLabel && (
                  <StatusPill
                    label={
                      verification === "verified"
                        ? `${verificationLabel} ${memo.coverage?.citation_coverage_pct ?? 100}%`
                        : verification === "partial"
                          ? `${verificationLabel} ${memo.coverage?.citation_coverage_pct ?? 0}%`
                          : verificationLabel
                    }
                    tone={verificationTone}
                  />
                )}
                {/* Legacy grounding fallback — only for memos persisted
                    before verification_status existed. */}
                {!verificationLabel && memo.grounding && memo.grounding.confidence && memo.grounding.confidence !== "n/a" && (
                  <StatusPill
                    label={
                      memo.grounding.confidence === "high"
                        ? "GROUNDED"
                        : `${memo.grounding.ungrounded_count ?? 0} UNVERIFIED`
                    }
                    tone={
                      memo.grounding.confidence === "high" ? "green"
                        : memo.grounding.confidence === "medium" ? "yellow"
                          : "red"
                    }
                  />
                )}
                {memo.plan_confidence !== undefined && memo.plan_confidence > 0 && memo.plan_confidence < 60 && (
                  <StatusPill label={`PLAN ${memo.plan_confidence}`} tone="yellow" />
                )}
                {memo.data_quality && memo.data_quality !== "complete" && (
                  <StatusPill
                    label={`DATA ${memo.data_quality.toUpperCase()}`}
                    tone={memo.data_quality === "critical" ? "red" : "yellow"}
                  />
                )}
                {memo.sub_question_coverage && memo.sub_question_coverage.length > 0 && (() => {
                  const total = memo.sub_question_coverage.length;
                  const answered = memo.sub_question_coverage.filter((c) => c.answered).length;
                  if (answered === total) return null;
                  return <StatusPill label={`Q ${answered}/${total}`} tone="yellow" />;
                })()}
                {memo.diversity && memo.diversity.monolithic && (
                  <StatusPill label="CONCENTRATED" tone="yellow" />
                )}
                {memo.mandate_warnings && memo.mandate_warnings.length > 0 && (
                  <StatusPill
                    label={`MANDATE · ${memo.mandate_warnings.length}`}
                    tone="yellow"
                  />
                )}
              </div>
            )}
            <h2 className="text-lg font-semibold text-text-primary leading-snug">
              {memo.title}
            </h2>
          </div>
          <div className="shrink-0 flex items-center gap-1">
            {memo.id && (
              <a
                href={`/analysis?q=${encodeURIComponent("Follow up: ")}&parent=${memo.id}`}
                className="px-2 py-1 rounded-md text-[11px] font-medium text-text-quaternary hover:text-accent hover:bg-accent/10 transition-colors"
                title="Continue this research thread"
              >
                Follow up
              </a>
            )}
            {memo.id && (
              <button
                onClick={handleExport}
                disabled={exporting}
                className="px-2 py-1 rounded-md text-[11px] font-medium text-text-quaternary hover:text-text-primary hover:bg-white/[0.04] transition-colors disabled:opacity-30"
                title="Export as PDF"
              >
                {exporting ? "..." : "Export PDF"}
              </button>
            )}
            {memo.id && onDelete && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="px-2 py-1 rounded-md text-[11px] font-medium text-text-quaternary hover:text-signal-red hover:bg-signal-red/10 transition-colors disabled:opacity-30"
                title="Delete this analysis"
              >
                {deleting ? "..." : "Delete"}
              </button>
            )}
          </div>
        </div>
        {/* Thread badge — show when this memo is part of a thread */}
        {memo.thread_id && (memo.sequence_in_thread ?? 0) > 0 && (
          <div className="mb-2 flex items-center gap-2 text-[10px] text-text-quaternary">
            <span className="inline-flex items-center gap-1 rounded-md border border-border-primary bg-bg-primary px-2 py-0.5">
              Thread #{memo.sequence_in_thread}
            </span>
            {memo.query_class && memo.query_class !== "fresh" && (
              <span className="inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/10 text-accent px-2 py-0.5">
                {memo.query_class.replace(/_/g, " ")}
              </span>
            )}
          </div>
        )}
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

      {/* Sources, citations + provenance now render at the BOTTOM, after the
          Full Analysis, in a single collapsible section (see end of memo). */}

      {/* Key Findings */}
      {memo.key_findings?.length > 0 && (
        <TerminalPanel label="KEY FINDINGS">
          <div className="space-y-2">
            {(memo.key_findings || []).map((f, i) => (
              <div
                key={i}
                className="flex items-start gap-2.5 text-[13px] text-text-secondary"
                style={{ animation: `fade-in 0.3s ease-out ${i * 0.08}s both` }}
              >
                <span className="text-accent font-mono font-semibold tabular-nums mt-0.5 shrink-0">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="leading-relaxed">{f}</span>
              </div>
            ))}
          </div>
        </TerminalPanel>
      )}

      {/* Plan Shape — surfaces what the Interpreter actually decided */}
      {(memo.question_type || memo.benchmark || memo.instrument_preference || (memo.idea_archetype && memo.idea_archetype.length > 0)) && (
        <TerminalPanel label="PLAN SHAPE">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]">
            {memo.question_type && (
              <div>
                <span className="text-text-quaternary">Question</span>
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
            {memo.target_idea_count !== undefined && memo.target_idea_count > 0 && (
              <div>
                <span className="text-text-quaternary">Ideas</span>
                <span className="ml-2 font-mono text-text-primary">{memo.target_idea_count}</span>
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
          {memo.required_style_labels && memo.required_style_labels.length > 0 && (
            <div className="mt-3">
              <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1.5">Required style coverage</p>
              <div className="flex flex-wrap gap-1.5">
                {memo.required_style_labels.map((s, i) => {
                  const covered = memo.diversity?.styles_covered?.includes(s);
                  return (
                    <span
                      key={i}
                      className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border font-medium ${
                        covered
                          ? styleLabelClasses(s)
                          : "bg-signal-red/10 text-signal-red border-signal-red/30"
                      }`}
                      title={covered ? "Covered in trade ideas" : "MISSING — Strategist did not produce a trade with this label"}
                    >
                      {covered ? "✓ " : "✗ "}{s.replace(/_/g, " ")}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
          {memo.secondary_universe && memo.secondary_universe.length > 0 && (
            <div className="mt-3">
              <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1.5">
                Secondary universe (non-mega-cap candidates)
              </p>
              <div className="flex flex-wrap gap-1">
                {memo.secondary_universe.map((tk, i) => (
                  <span key={i} className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-bg-elevated text-text-secondary">
                    {tk}
                  </span>
                ))}
              </div>
            </div>
          )}
        </TerminalPanel>
      )}

      {/* Sub-questions answered (if Research engaged with them) */}
      {memo.sub_question_coverage && memo.sub_question_coverage.length > 0 && (
        <TerminalPanel
          label="SUB-QUESTIONS"
          status={`${memo.sub_question_coverage.filter((c) => c.answered).length} / ${memo.sub_question_coverage.length} ADDRESSED`}
        >
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
        </TerminalPanel>
      )}

      {/* Falsification — what would change the view */}
      {memo.falsification_criteria && memo.falsification_criteria.length > 0 && (
        <TerminalPanel label="WHAT WOULD CHANGE OUR VIEW">
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
        </TerminalPanel>
      )}

      {/* Regime sensitivity */}
      {memo.regime_sensitivity && memo.regime_sensitivity.length > 0 && (
        <TerminalPanel
          label="REGIME SENSITIVITY"
          status={
            memo.macro_context?.current_regime
              ? `CURRENT · ${memo.macro_context.current_regime.toUpperCase()}`
              : undefined
          }
        >
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
        </TerminalPanel>
      )}

      {/* Trade Ideas — split into CORE and SECONDARIES so non-mega-cap
          alpha names get their own visual sleeve instead of being buried
          inside one long ranked list. Classification reads tier /
          market_cap_bucket / screen_source on the TradeIdea object.
          Legacy memos with no tagging fall entirely into CORE — no
          regression. */}
      {memo.trade_ideas?.length > 0 && (() => {
        const all = memo.trade_ideas || [];
        const memoId = (memo as unknown as Record<string, unknown>).id as string;
        const core: { idea: TradeIdea; rank: number }[] = [];
        const secondaries: { idea: TradeIdea; rank: number }[] = [];
        all.forEach((idea, i) => {
          const bucket = isSecondaryIdea(idea) ? secondaries : core;
          bucket.push({ idea, rank: i + 1 });
        });
        return (
          <>
            {core.length > 0 && (
              <TerminalPanel
                label={`TRADE IDEAS · ${core.length}`}
                status="CORE · RANKED BY CONVICTION"
                bodyClassName="p-4"
              >
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {core.map(({ idea, rank }) => (
                    <TradeIdeaCard
                      key={rank}
                      idea={idea}
                      rank={rank}
                      memoId={memoId}
                      lineage={memo.lineage}
                    />
                  ))}
                </div>
              </TerminalPanel>
            )}
            {secondaries.length > 0 && (
              <TerminalPanel
                label={`SECONDARIES · ${secondaries.length}`}
                status="ALPHA SLEEVE · MID / SMALL / SPECIAL"
                bodyClassName="p-4"
              >
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {secondaries.map(({ idea, rank }) => (
                    <TradeIdeaCard
                      key={rank}
                      idea={idea}
                      rank={rank}
                      memoId={memoId}
                      lineage={memo.lineage}
                    />
                  ))}
                </div>
              </TerminalPanel>
            )}
          </>
        );
      })()}

      {/* Risk + Hedging side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {memo.risk_factors?.length > 0 && (
          <TerminalPanel label="RISK FACTORS">
            <RiskMatrix
              factors={memo.risk_factors}
              lineage={memo.lineage}
              primaryTicker={memo.tickers_analyzed?.[0]}
            />
          </TerminalPanel>
        )}

        {memo.hedging_recommendations?.length > 0 && (
          <TerminalPanel label="HEDGING RECOMMENDATIONS">
            <div className="space-y-2">
              {(memo.hedging_recommendations || []).map((h, i) => {
                const parts = h.split(" — ");
                const instrument = parts[0];
                const rationale = parts.length > 1 ? parts.slice(1).join(" — ") : null;
                return (
                  <div
                    key={i}
                    className="rounded-md border border-border-primary bg-bg-primary p-3.5 flex items-start gap-3"
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
          </TerminalPanel>
        )}
      </div>

      {/* Mandate warnings — surfaced if the Strategist breached the user's
          mandate. Empty array hides the block entirely. */}
      {memo.mandate_warnings && memo.mandate_warnings.length > 0 && (
        <TerminalPanel label={`MANDATE CHECK · ${memo.mandate_warnings.length}`}>
          <ul className="space-y-1.5">
            {memo.mandate_warnings.map((w, i) => (
              <li key={i} className="flex items-start gap-2 text-[12px]">
                <span className="text-signal-yellow shrink-0 mt-0.5">▲</span>
                <span className="text-text-secondary">{w}</span>
              </li>
            ))}
          </ul>
        </TerminalPanel>
      )}

      {/* Computed Analytics — this is what ChatGPT can't do */}
      {enrichLoading && (
        <div className="rounded-md border border-border-primary bg-bg-surface p-4 flex items-center gap-2">
          <div className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent" style={{ animation: "spin-slow 0.8s linear infinite" }} />
          <span className="text-xs text-text-tertiary">Computing analytics...</span>
        </div>
      )}

      {enrichment && Object.keys(enrichment.analytics).length > 0 && (
        <TerminalPanel label="COMPUTED ANALYTICS" bodyClassName="p-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {Object.entries(enrichment.analytics).map(([ticker, data]) => (
              <TickerAnalyticsPanel key={ticker} ticker={ticker} analytics={data} />
            ))}
          </div>
        </TerminalPanel>
      )}

      {/* Options Flow Analytics */}
      {enrichment && Object.keys(enrichment.analytics).length > 0 && (
        (() => {
          const tickersWithOptions = Object.entries(enrichment.analytics)
            .filter(([, data]) => data.options && !("error" in (data.options as Record<string, unknown>)))
            .slice(0, 4);
          if (tickersWithOptions.length === 0) return null;
          return (
            <TerminalPanel label="OPTIONS FLOW" bodyClassName="p-4">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {tickersWithOptions.map(([ticker, data]) => (
                  <OptionsPanel
                    key={ticker}
                    ticker={ticker}
                    data={data.options as never}
                  />
                ))}
              </div>
            </TerminalPanel>
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
        <div className="rounded-md border border-border-primary bg-bg-surface overflow-hidden">
          <button
            onClick={() => setShowFull(!showFull)}
            className="w-full px-4 py-2.5 text-left flex items-center justify-between border-b border-border-primary/60 hover:bg-bg-elevated/40 transition-colors"
          >
            <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">
              <span className="text-accent">///</span> FULL ANALYSIS
            </span>
            <span className="text-text-quaternary text-[13px]">{showFull ? "−" : "+"}</span>
          </button>
          {showFull && (
            <div
              className="px-5 pb-5"
              style={{ animation: "fade-in 0.3s ease-out" }}
            >
              {/* Renders inline [N] anchors as accent superscripts that
                  open the source URL or jump to the CitationIndexPanel.
                  Falls back to raw text when memo has no citations. */}
              <ProseWithCitations text={memo.analysis} index={memo.citation_index} />
            </div>
          )}
        </div>
      )}

      {/* Sources, Citations & Provenance — collapsible, at the very bottom
          AFTER the full analysis. Combines the numbered citation index
          (every receipt) and the bulk tool-call lineage. Renders nothing
          when there's no provenance at all. */}
      {((memo.citation_index && memo.citation_index.length > 0) ||
        (memo.lineage && (memo.lineage.n_tool_calls ?? 0) > 0)) && (
        <div className="rounded-md border border-border-primary bg-bg-surface overflow-hidden">
          <button
            onClick={() => setShowSources(!showSources)}
            className="w-full px-4 py-2.5 text-left flex items-center justify-between border-b border-border-primary/60 hover:bg-bg-elevated/40 transition-colors"
          >
            <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">
              <span className="text-accent">///</span> SOURCES &amp; CITATIONS
              {memo.citation_index && memo.citation_index.length > 0 && (
                <span className="ml-2 text-text-tertiary">{memo.citation_index.length} receipts</span>
              )}
            </span>
            <span className="text-text-quaternary text-[13px]">{showSources ? "−" : "+"}</span>
          </button>
          {showSources && (
            <div className="px-4 pb-4 pt-3 space-y-4" style={{ animation: "fade-in 0.3s ease-out" }}>
              <CitationIndexPanel index={memo.citation_index} />
              {memo.lineage && (memo.lineage.n_tool_calls ?? 0) > 0 && (
                <LineagePanel lineage={memo.lineage} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
