"use client";

import type { Citation, IntelligenceMemo } from "@/lib/types";

type LineageSource = NonNullable<IntelligenceMemo["lineage"]>["sources"][number];

// Build a human-readable label from a raw lineage source. Mirrors the
// shape backend/infra/citations_resolver._label_for_lineage emits so
// fallback-rendered citations look identical to resolver-emitted ones.
function labelFromLineage(src: LineageSource): string {
  const t = (src.type ?? "other").toLowerCase();
  const id = src.id ?? "";
  const ticker = src.ticker ?? "";
  const form = src.form_type ?? "";
  if (t === "sec_filing") return form ? `SEC ${form} · ${id}` : `SEC filing · ${id}`;
  if (t === "sec_insider") return `Insider transaction (Form 4) · ${id}`;
  if (t === "sec_13f") return `13F · ${id}`;
  if (t === "fred_series") return `FRED · ${id}`;
  if (t === "market_price") return `Market data · ${ticker || id}`;
  if (t === "news_article") return `News · ${id.slice(0, 80)}`;
  if (t === "web_search") return `Web · ${id}`;
  if (t === "technical") return `Technical · ${id}`;
  if (t === "screen") return `Screen · ${src.screen ?? id}`;
  if (t === "computed") return `Computed · ${id}`;
  return `${t} · ${id}`;
}

/**
 * Build a citation list for a ticker by scanning the memo's lineage.
 *
 * Used as a last-line-of-defense fallback when the backend resolver
 * didn't attach explicit citations to a trade idea — the user still
 * sees the source rail with the tool calls that touched the ticker.
 *
 * Matches sources whose `ticker` field equals the requested ticker OR
 * whose `id` starts with `TICKER@` (the market_price convention used
 * by infra/lineage.py).
 */
export function citationsFromLineage(
  lineage: IntelligenceMemo["lineage"] | undefined,
  ticker: string | undefined,
  max = 4,
): Citation[] {
  if (!lineage || !ticker) return [];
  const want = ticker.toUpperCase();
  const out: Citation[] = [];
  const seen = new Set<string>();
  // Priority: market_price > sec_filing > sec_insider > sec_13f > technical > news > web > screen > computed > other
  const priority: Record<string, number> = {
    market_price: 0, sec_filing: 1, sec_insider: 2, sec_13f: 3,
    technical: 4, news_article: 5, web_search: 6, screen: 7,
    computed: 8, other: 9,
  };
  const candidates: LineageSource[] = [];
  for (const src of lineage.sources ?? []) {
    const srcTicker = (src.ticker ?? "").toUpperCase();
    const idPrefix = (src.id ?? "").split("@")[0]?.toUpperCase() ?? "";
    if (srcTicker === want || idPrefix === want) {
      candidates.push(src);
    }
  }
  candidates.sort(
    (a, b) =>
      (priority[(a.type ?? "other").toLowerCase()] ?? 9) -
      (priority[(b.type ?? "other").toLowerCase()] ?? 9),
  );
  for (const src of candidates) {
    const t = (src.type ?? "other").toLowerCase();
    const id = src.id ?? "";
    const key = `${t}:${id}`;
    if (!id || seen.has(key)) continue;
    seen.add(key);
    out.push({
      source_type: t,
      source_id: id,
      url: src.url ?? null,
      label: labelFromLineage(src),
      excerpt: null,
    });
    if (out.length >= max) break;
  }
  return out;
}

/**
 * Citation components — render the per-claim citation system end-to-end.
 *
 *   CitationsRail        — bottom rail on a trade-idea / risk-factor card.
 *                          Shows a compact list of resolved sources as
 *                          tiny clickable type pills.
 *   CitationChip         — single citation shown as a numbered footnote
 *                          chip. Hover for label, click to open URL.
 *   CitationIndexPanel   — the deduplicated, numbered list of every
 *                          citation in a memo. Drives the "Citations [N]"
 *                          section near the lineage panel.
 *
 * All three live in this one file because they share label/color logic
 * and stay small enough to read together.
 */

// Human-readable + color treatment per source_type, aligned with the
// terminal design system tokens.
const SOURCE_TYPE_META: Record<
  string,
  { label: string; chip: string; ring: string }
> = {
  sec_filing: {
    label: "SEC",
    chip: "bg-accent/[0.08] text-accent border-accent/30",
    ring: "ring-accent/40",
  },
  sec_insider: {
    label: "FORM 4",
    chip: "bg-accent/[0.08] text-accent border-accent/30",
    ring: "ring-accent/40",
  },
  sec_13f: {
    label: "13F",
    chip: "bg-accent/[0.08] text-accent border-accent/30",
    ring: "ring-accent/40",
  },
  fred_series: {
    label: "FRED",
    chip: "bg-signal-yellow/[0.08] text-signal-yellow border-signal-yellow/30",
    ring: "ring-signal-yellow/40",
  },
  market_price: {
    label: "MARKET",
    chip: "bg-signal-green/[0.08] text-signal-green border-signal-green/30",
    ring: "ring-signal-green/40",
  },
  news_article: {
    label: "NEWS",
    chip: "bg-text-tertiary/15 text-text-secondary border-border-primary",
    ring: "ring-text-quaternary/40",
  },
  web_search: {
    label: "WEB",
    chip: "bg-text-tertiary/15 text-text-secondary border-border-primary",
    ring: "ring-text-quaternary/40",
  },
  technical: {
    label: "TA",
    chip: "bg-accent/[0.08] text-accent border-accent/30",
    ring: "ring-accent/40",
  },
  screen: {
    label: "SCREEN",
    chip: "bg-signal-yellow/[0.08] text-signal-yellow border-signal-yellow/30",
    ring: "ring-signal-yellow/40",
  },
  computed: {
    label: "COMPUTED",
    chip: "bg-text-tertiary/15 text-text-secondary border-border-primary",
    ring: "ring-text-quaternary/40",
  },
  other: {
    label: "OTHER",
    chip: "bg-text-tertiary/15 text-text-secondary border-border-primary",
    ring: "ring-text-quaternary/40",
  },
};

function metaFor(type: string) {
  return SOURCE_TYPE_META[type] ?? SOURCE_TYPE_META.other;
}

function CitationChipInline({ citation }: { citation: Citation }) {
  const meta = metaFor(citation.source_type);
  const inner = (
    <span
      className={[
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5",
        "text-[9px] font-mono tracking-[0.16em] uppercase",
        meta.chip,
      ].join(" ")}
      title={citation.label ?? `${meta.label} · ${citation.source_id}`}
    >
      {citation.n ? (
        <span className="font-semibold tabular-nums">{citation.n}</span>
      ) : null}
      <span>{meta.label}</span>
    </span>
  );
  if (citation.url) {
    return (
      <a
        href={citation.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block hover:opacity-80 transition-opacity"
      >
        {inner}
      </a>
    );
  }
  return inner;
}

/**
 * Compact source rail rendered at the bottom of a trade-idea or
 * risk-factor card. Empty → renders nothing (caller can rely on its
 * presence to gate the divider).
 */
export function CitationsRail({
  citations,
  className = "",
}: {
  citations?: Citation[];
  className?: string;
}) {
  if (!citations || citations.length === 0) return null;
  // De-dup by source_id so a rail never shows the same source twice
  const seen = new Set<string>();
  const unique = citations.filter((c) => {
    const k = `${c.source_type}:${c.source_id}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return (
    <div
      className={[
        "flex items-center gap-1.5 flex-wrap pt-2 mt-2 border-t border-border-primary/60",
        className,
      ].join(" ")}
    >
      <span className="text-[9px] font-mono tracking-[0.22em] text-text-quaternary mr-0.5">
        <span className="text-accent">///</span> SOURCES
      </span>
      {unique.map((c, i) => (
        <CitationChipInline key={`${c.source_type}:${c.source_id}:${i}`} citation={c} />
      ))}
    </div>
  );
}

/**
 * The full deduplicated index of every citation in the memo. Rendered
 * once per memo, between the lineage panel and the analysis prose.
 * Provides the targets for the inline `[N]` footnotes in prose.
 */
export function CitationIndexPanel({
  index,
}: {
  index?: Citation[];
}) {
  if (!index || index.length === 0) return null;
  return (
    <section className="rounded-md border border-border-primary bg-bg-surface overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border-primary/60">
        <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">
          <span className="text-accent">///</span> CITATIONS
        </span>
        <span className="text-[10px] font-mono tracking-wider text-text-quaternary">
          {index.length} {index.length === 1 ? "source" : "sources"}
        </span>
      </header>
      <ol className="divide-y divide-border-primary/40">
        {index.map((c) => {
          const meta = metaFor(c.source_type);
          return (
            <li
              key={`${c.n}-${c.source_id}`}
              id={`cite-${c.n}`}
              className="flex items-start gap-3 px-4 py-2.5 scroll-mt-24"
            >
              <span className="text-[10px] font-mono font-semibold tabular-nums text-accent shrink-0 pt-0.5">
                [{c.n}]
              </span>
              <span
                className={[
                  "shrink-0 inline-flex items-center rounded border px-1.5 py-0.5",
                  "text-[9px] font-mono tracking-[0.16em] uppercase",
                  meta.chip,
                ].join(" ")}
              >
                {meta.label}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[12px] text-text-secondary truncate">
                  {c.label ?? c.source_id}
                </p>
                {c.excerpt && (
                  <p className="text-[11px] text-text-tertiary mt-0.5 line-clamp-2">
                    {c.excerpt}
                  </p>
                )}
              </div>
              {c.url && (
                <a
                  href={c.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 text-[10px] font-mono tracking-wider text-text-tertiary hover:text-accent transition-colors"
                >
                  OPEN →
                </a>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
