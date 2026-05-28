"use client";

import { useEffect, useState } from "react";
import { getApiBase } from "@/lib/api";

/**
 * TickerBand — full-width scrolling marquee of tickers + % changes.
 *
 * Used as the live macro tape at the top of /dashboard. The marketing
 * landing page intentionally does not use this — the home dashboard is
 * the only surface where the tape lives.
 *
 * Two modes:
 *   - <TickerBand items={[...]} />                   static custom tape
 *   - <TickerBand live />                            polls live market data
 *                                                    for a default macro set
 *
 * The live mode uses /api/data/market/{ticker} (one call per symbol),
 * cached by the backend market client at 15min TTL so this is cheap.
 */
export type TickerItem = {
  ticker: string;
  change_pct: number;
  /** Optional sub-label (e.g., "10Y" instead of "TNX"). */
  label?: string;
};

export type TickerBandProps = {
  items?: TickerItem[];
  live?: boolean;
  /** Polling interval in ms for live mode. Defaults to 60s. */
  refreshMs?: number;
  className?: string;
};

const DEFAULT_LIVE_TAPE: { ticker: string; label?: string }[] = [
  { ticker: "SPY" },
  { ticker: "QQQ" },
  { ticker: "IWM" },
  { ticker: "DIA" },
  { ticker: "VIX", label: "VIX" },
  { ticker: "TLT" },
  { ticker: "HYG" },
  { ticker: "GLD" },
  { ticker: "USO" },
  { ticker: "UUP" },
  { ticker: "XLF" },
  { ticker: "XLE" },
  { ticker: "XLK" },
  { ticker: "XLV" },
  { ticker: "SMH" },
];

const FALLBACK_TAPE: TickerItem[] = [
  { ticker: "SPY", change_pct: 0.34 },
  { ticker: "QQQ", change_pct: 0.51 },
  { ticker: "IWM", change_pct: 1.08 },
  { ticker: "VIX", change_pct: -2.45 },
  { ticker: "TLT", change_pct: -0.74 },
  { ticker: "HYG", change_pct: 0.11 },
  { ticker: "GLD", change_pct: -0.18 },
  { ticker: "USO", change_pct: 1.92 },
  { ticker: "UUP", change_pct: -0.34 },
  { ticker: "XLF", change_pct: 0.42 },
  { ticker: "XLE", change_pct: 1.27 },
  { ticker: "XLK", change_pct: 0.86 },
];

export function TickerBand({
  items,
  live = false,
  refreshMs = 60_000,
  className = "",
}: TickerBandProps) {
  const [liveItems, setLiveItems] = useState<TickerItem[] | null>(null);

  useEffect(() => {
    if (!live) return;
    let cancelled = false;

    async function load() {
      try {
        const base = getApiBase();
        const results = await Promise.all(
          DEFAULT_LIVE_TAPE.map(async ({ ticker, label }) => {
            try {
              const res = await fetch(`${base}/api/data/market/${ticker}`);
              if (!res.ok) return null;
              const data = await res.json();
              // Backend shape: { fundamentals, price_history }
              // We use price_history's last two closes to compute change_pct
              const bars: Array<{ close: number }> | undefined =
                data?.price_history;
              if (!bars || bars.length < 2) return null;
              const last = bars[bars.length - 1]?.close;
              const prev = bars[bars.length - 2]?.close;
              if (typeof last !== "number" || typeof prev !== "number" || prev === 0)
                return null;
              const change_pct = ((last - prev) / prev) * 100;
              return { ticker, label, change_pct } as TickerItem;
            } catch {
              return null;
            }
          })
        );
        if (cancelled) return;
        const ok = results.filter(Boolean) as TickerItem[];
        if (ok.length) setLiveItems(ok);
      } catch {
        /* fall back to default tape */
      }
    }

    load();
    const id = window.setInterval(load, refreshMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [live, refreshMs]);

  const tape = items ?? liveItems ?? (live ? FALLBACK_TAPE : FALLBACK_TAPE);
  // Duplicate for seamless loop
  const loop = [...tape, ...tape];

  return (
    <div
      className={[
        "relative border-y border-border-primary/60 bg-bg-surface/30 overflow-hidden",
        className,
      ].join(" ")}
      aria-label="Live macro tape"
    >
      <div className="pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-bg-primary to-transparent z-10" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-bg-primary to-transparent z-10" />

      <div className="ticker-scroll flex items-center py-2.5 whitespace-nowrap">
        {loop.map((x, i) => {
          const up = x.change_pct >= 0;
          return (
            <div
              key={i}
              className="inline-flex items-center gap-2 px-5 text-[11px] font-mono"
            >
              <span className="text-text-secondary">{x.label ?? x.ticker}</span>
              <span className={up ? "text-signal-green" : "text-signal-red"}>
                {up ? "▲" : "▼"} {Math.abs(x.change_pct).toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
