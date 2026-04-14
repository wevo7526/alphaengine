"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface AgentWeight {
  label: string;
  key: string;
  weight: number;
}

const DEFAULT_WEIGHTS: AgentWeight[] = [
  { label: "Query Interpreter", key: "query_interpreter", weight: 1.0 },
  { label: "Research Analyst", key: "research_analyst", weight: 1.0 },
  { label: "Risk Manager", key: "risk_manager", weight: 1.0 },
  { label: "Portfolio Strategist", key: "portfolio_strategist", weight: 1.0 },
  { label: "CIO Synthesizer", key: "cio_synthesizer", weight: 1.0 },
];

const DEFAULT_RISK_PARAMS = [
  { label: "Max position size", key: "max_position", value: "5%", description: "Maximum allocation to a single position" },
  { label: "Max sector concentration", key: "max_sector", value: "30%", description: "Maximum allocation to one sector" },
  { label: "Sizing method", key: "sizing", value: "Half-Kelly", description: "Position sizing algorithm" },
  { label: "BUY/SELL threshold", key: "buy_threshold", value: "75 conviction", description: "Minimum conviction to recommend action" },
  { label: "WATCH threshold", key: "watch_threshold", value: "50 conviction", description: "Minimum conviction for watchlist" },
  { label: "Max drawdown trigger", key: "max_dd", value: "10%", description: "Portfolio drawdown that triggers circuit breaker" },
];

export default function SettingsPage() {
  const [agentStatus, setAgentStatus] = useState<Record<string, string>>({});
  const [backendHealth, setBackendHealth] = useState<Record<string, unknown> | null>(null);
  const [healthError, setHealthError] = useState(false);

  useEffect(() => {
    api.health().then((d: unknown) => setBackendHealth(d as Record<string, unknown>)).catch(() => setHealthError(true));
    api.agentStatus().then((d: unknown) => {
      const data = d as { agents: Record<string, string> };
      setAgentStatus(data.agents);
    }).catch(() => {});
  }, []);

  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
        Settings
      </h1>
      <p className="text-sm text-text-tertiary mb-8">
        System configuration, agent status, and risk parameters.
      </p>

      {/* System Status */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
        <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
          System Status
        </h2>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[13px] text-text-secondary">Backend</span>
            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${healthError ? "bg-signal-red" : backendHealth ? "bg-signal-green" : "bg-signal-yellow"}`} />
              <span className="text-xs text-text-tertiary">
                {healthError ? "Unreachable" : backendHealth ? "Connected" : "Checking..."}
              </span>
            </div>
          </div>
          {backendHealth && (
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-text-secondary">Environment</span>
              <span className="text-xs font-mono text-text-tertiary">{String(backendHealth.env || "unknown")}</span>
            </div>
          )}
        </div>
      </div>

      {/* Agent Status */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
        <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
          Agent Status
        </h2>
        <div className="space-y-2">
          {DEFAULT_WEIGHTS.map((agent) => {
            const status = agentStatus[agent.key] ?? "unknown";
            return (
              <div key={agent.key} className="flex items-center justify-between">
                <span className="text-[13px] text-text-secondary">{agent.label}</span>
                <div className="flex items-center gap-1.5">
                  <div className={`w-1.5 h-1.5 rounded-full ${
                    status === "idle" ? "bg-signal-green" : status === "running" ? "bg-signal-yellow" : "bg-text-quaternary"
                  }`} />
                  <span className="text-xs text-text-tertiary capitalize">{status}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Risk Parameters */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
        <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
          Risk Parameters
        </h2>
        <div className="divide-y divide-border-primary">
          {DEFAULT_RISK_PARAMS.map((param) => (
            <div key={param.key} className="flex items-center justify-between py-3">
              <div>
                <span className="text-[13px] text-text-secondary">{param.label}</span>
                <p className="text-[10px] text-text-quaternary">{param.description}</p>
              </div>
              <span className="text-xs font-mono text-text-primary bg-bg-elevated px-2 py-1 rounded">
                {param.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Data Sources */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
        <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
          Data Sources
        </h2>
        <div className="space-y-2">
          {[
            { name: "FRED (Macro)", status: "active", note: "13 indicators, 1hr cache" },
            { name: "Yahoo Finance", status: "active", note: "Price, fundamentals, options" },
            { name: "NewsAPI", status: "active", note: "100/day limit, 30min cache" },
            { name: "Finnhub", status: "active", note: "60/min, 15min cache" },
            { name: "SEC EDGAR", status: "active", note: "Filings, insider trades" },
            { name: "Alpha Vantage", status: "active", note: "25/day limit, 4hr cache" },
            { name: "Firecrawl", status: "optional", note: "Web validation, requires API key" },
          ].map((source) => (
            <div key={source.name} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className={`w-1.5 h-1.5 rounded-full ${source.status === "active" ? "bg-signal-green" : "bg-signal-yellow"}`} />
                <span className="text-[13px] text-text-secondary">{source.name}</span>
              </div>
              <span className="text-[10px] text-text-quaternary">{source.note}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
