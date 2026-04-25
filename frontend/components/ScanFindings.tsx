"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export interface ScanFinding {
  id: string;
  ticker: string;
  finding_type: string;
  priority: "high" | "medium" | "low";
  headline: string;
  detail: string;
  data: Record<string, unknown>;
  created_at: string | null;
}

interface ScanData {
  findings: ScanFinding[];
  by_priority: {
    high: ScanFinding[];
    medium: ScanFinding[];
    low: ScanFinding[];
  };
  run_id: string | null;
  completed_at: string | null;
  universe_size?: number;
  findings_count?: number;
  stale: boolean;
}

const FINDING_TYPE_LABELS: Record<string, string> = {
  rsi_extreme: "RSI",
  volume_spike: "Volume",
  ma_crossover: "MA",
  earnings_surprise: "Move",
  insider_cluster: "Insider",
  sentiment_shift: "Sentiment",
  macro_shift: "Macro",
  filing_alert: "Filing",
};

function formatWhen(iso: string | null): string {
  if (!iso) return "never";
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function FindingCard({ finding }: { finding: ScanFinding }) {
  const router = useRouter();

  const priorityColor =
    finding.priority === "high"
      ? "text-signal-red"
      : finding.priority === "medium"
        ? "text-signal-yellow"
        : "text-text-tertiary";

  const priorityBg =
    finding.priority === "high"
      ? "bg-signal-red/10"
      : finding.priority === "medium"
        ? "bg-signal-yellow/10"
        : "bg-bg-elevated";

  const typeLabel = FINDING_TYPE_LABELS[finding.finding_type] || finding.finding_type;

  const handleAnalyze = () => {
    const query = `Deep analysis of ${finding.ticker} — ${finding.headline}`;
    router.push(`/analysis?q=${encodeURIComponent(query)}`);
  };

  return (
    <div
      className="rounded-xl border border-border-primary bg-bg-surface p-4 hover:border-zinc-600 transition-colors"
      style={{ animation: "fade-in 0.3s ease-out" }}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[14px] font-mono font-bold text-text-primary">
            {finding.ticker}
          </span>
          <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wider ${priorityBg} ${priorityColor}`}>
            {finding.priority}
          </span>
          <span className="text-[9px] font-medium px-1.5 py-0.5 rounded uppercase tracking-wider bg-bg-elevated text-text-quaternary">
            {typeLabel}
          </span>
        </div>
        <button
          onClick={handleAnalyze}
          className="text-[11px] text-accent hover:text-blue-400 transition-colors font-medium whitespace-nowrap"
        >
          Analyze →
        </button>
      </div>
      <p className="text-[13px] text-text-primary mb-1">{finding.headline}</p>
      {finding.detail && (
        <p className="text-xs text-text-tertiary">{finding.detail}</p>
      )}
    </div>
  );
}

function IconRefresh({ spinning }: { spinning: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={spinning ? { animation: "spin-slow 1s linear infinite" } : undefined}
    >
      <path d="M10 2V5H7" />
      <path d="M10 5C9.3 3.2 7.5 2 5.5 2C3 2 1 4 1 6.5" />
      <path d="M2 10V7H5" />
      <path d="M2 7C2.7 8.8 4.5 10 6.5 10C9 10 11 8 11 5.5" />
    </svg>
  );
}

export function ScanFindings() {
  const [data, setData] = useState<ScanData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({
    low: true, // Hide low-priority by default
  });

  const loadFindings = async (): Promise<ScanData | null> => {
    try {
      const d = (await api.scanLatest()) as ScanData;
      setData(d);
      return d;
    } catch {
      return null;
    }
  };

  const triggerScan = async (isCancelled?: () => boolean) => {
    setScanning(true);
    try {
      await api.scanTrigger();
      let ticks = 0;
      const maxTicks = 45;
      while (ticks < maxTicks) {
        if (isCancelled?.()) return;
        await new Promise((resolve) => setTimeout(resolve, 4000));
        if (isCancelled?.()) return;
        try {
          const status = (await api.scanStatus()) as { status: string };
          if (status.status !== "running") break;
        } catch {
          break;
        }
        ticks++;
      }
      if (!isCancelled?.()) await loadFindings();
    } catch {
      // ignore
    } finally {
      if (!isCancelled?.()) setScanning(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const isCancelled = () => cancelled;

    (async () => {
      const d = await loadFindings();
      if (cancelled) return;
      setLoading(false);

      if (!d || d.stale || d.findings.length === 0) {
        await triggerScan(isCancelled);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
        <div className="flex items-center gap-2 text-xs text-text-quaternary">
          <div
            className="w-2 h-2 rounded-full border-[1.5px] border-accent border-t-transparent"
            style={{ animation: "spin-slow 0.8s linear infinite" }}
          />
          Loading scan findings...
        </div>
      </div>
    );
  }

  const hasFindings = data && data.findings.length > 0;
  const high = data?.by_priority?.high || [];
  const medium = data?.by_priority?.medium || [];
  const low = data?.by_priority?.low || [];

  return (
    <div className="mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h2 className="text-[13px] font-medium text-text-primary">Overnight Scan</h2>
          {data?.completed_at && (
            <span className="text-[11px] text-text-quaternary">
              · {formatWhen(data.completed_at)}
            </span>
          )}
          {scanning && (
            <span className="text-[11px] text-accent flex items-center gap-1.5">
              <div
                className="w-2 h-2 rounded-full border-[1.5px] border-accent border-t-transparent"
                style={{ animation: "spin-slow 0.8s linear infinite" }}
              />
              scanning...
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {hasFindings && (
            <button
              onClick={async () => {
                try {
                  await api.downloadPdf(api.exportScanLatestUrl(), `alpha-engine-scan-${Date.now()}.pdf`);
                } catch {}
              }}
              className="px-2 py-1 rounded-lg text-[11px] text-text-tertiary hover:text-text-secondary hover:bg-white/[0.04] transition-colors"
            >
              Export
            </button>
          )}
          <button
            onClick={() => { triggerScan(); }}
            disabled={scanning}
            className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] text-text-tertiary hover:text-text-secondary hover:bg-white/[0.04] transition-colors disabled:opacity-40"
          >
            <IconRefresh spinning={scanning} />
            {scanning ? "Scanning" : "Refresh"}
          </button>
        </div>
      </div>

      {/* Empty state */}
      {!hasFindings && !scanning && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
          <p className="text-[13px] text-text-secondary mb-1">No findings yet</p>
          <p className="text-xs text-text-tertiary">
            The scanner will check your watchlist and default universe for anomalies. Click Refresh to run now.
          </p>
        </div>
      )}

      {/* Empty state while scanning */}
      {!hasFindings && scanning && (
        <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
          <p className="text-[13px] text-text-secondary">Scanning universe for anomalies...</p>
          <p className="text-xs text-text-tertiary mt-1">
            Checking RSI, volume, MA crossovers, large moves, and macro shifts.
          </p>
        </div>
      )}

      {/* Findings grouped by priority */}
      {hasFindings && (
        <div className="space-y-4">
          {high.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-medium text-signal-red uppercase tracking-wider">
                  High Priority
                </span>
                <span className="text-[10px] text-text-quaternary">({high.length})</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {high.map((f) => (
                  <FindingCard key={f.id} finding={f} />
                ))}
              </div>
            </div>
          )}

          {medium.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-medium text-signal-yellow uppercase tracking-wider">
                  Signals
                </span>
                <span className="text-[10px] text-text-quaternary">({medium.length})</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {medium.map((f) => (
                  <FindingCard key={f.id} finding={f} />
                ))}
              </div>
            </div>
          )}

          {low.length > 0 && (
            <div>
              <button
                onClick={() => setCollapsed((c) => ({ ...c, low: !c.low }))}
                className="flex items-center gap-2 mb-2 hover:opacity-80 transition-opacity"
              >
                <span className="text-[10px] font-medium text-text-tertiary uppercase tracking-wider">
                  Low Priority
                </span>
                <span className="text-[10px] text-text-quaternary">
                  ({low.length}) {collapsed.low ? "show" : "hide"}
                </span>
              </button>
              {!collapsed.low && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {low.map((f) => (
                    <FindingCard key={f.id} finding={f} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
