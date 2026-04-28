"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface SystemInfo {
  app: { version: string; env: string; commit: string | null };
  database: { ok: boolean; dialect?: string };
  data_sources: { name: string; configured: boolean; note: string }[];
  auth: { provider: string; issuer_configured: boolean };
  risk_parameters: { label: string; value: string; description: string }[];
}

const AGENT_LABELS: { key: string; label: string }[] = [
  { key: "query_interpreter", label: "Query Interpreter" },
  { key: "research_analyst", label: "Research Analyst" },
  { key: "risk_manager", label: "Risk Manager" },
  { key: "portfolio_strategist", label: "Portfolio Strategist" },
  { key: "cio_synthesizer", label: "CIO Synthesizer" },
];

export default function SettingsPage() {
  const [agentStatus, setAgentStatus] = useState<Record<string, string>>({});
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.systemInfo().then((d: unknown) => {
      if (!cancelled) setInfo(d as SystemInfo);
    }).catch((e) => {
      if (!cancelled) setApiError(e instanceof Error ? e.message : "Failed to load system info");
    });
    api.agentStatus().then((d: unknown) => {
      const data = d as { agents: Record<string, string> };
      if (!cancelled) setAgentStatus(data.agents || {});
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const dbOk = info?.database.ok ?? false;
  const env = info?.app.env ?? "unknown";

  return (
    <div className="p-8 max-w-3xl">
      {apiError && (
        <div className="mb-4 flex items-start justify-between rounded-xl border border-signal-red/25 bg-signal-red/[0.06] p-3">
          <div>
            <p className="text-xs font-medium text-signal-red">System info unreachable</p>
            <p className="text-[11px] text-text-tertiary mt-0.5">{apiError}</p>
          </div>
          <button onClick={() => setApiError(null)} className="text-text-quaternary hover:text-text-primary text-xs px-2" aria-label="Dismiss">×</button>
        </div>
      )}

      <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
        Settings
      </h1>
      <p className="text-sm text-text-tertiary mb-8">
        Live system status, data source health, and risk parameters in effect.
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
              <div className={`w-1.5 h-1.5 rounded-full ${info ? "bg-signal-green" : apiError ? "bg-signal-red" : "bg-signal-yellow"}`} />
              <span className="text-xs text-text-tertiary">{info ? "Connected" : apiError ? "Unreachable" : "Checking..."}</span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[13px] text-text-secondary">Database</span>
            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${dbOk ? "bg-signal-green" : "bg-signal-red"}`} />
              <span className="text-xs font-mono text-text-tertiary">
                {info?.database.dialect || "—"}
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[13px] text-text-secondary">Environment</span>
            <span className="text-xs font-mono text-text-tertiary capitalize">{env}</span>
          </div>
          {info?.app.commit && (
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-text-secondary">Build</span>
              <span className="text-xs font-mono text-text-tertiary">{info.app.commit}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-[13px] text-text-secondary">Auth</span>
            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${info?.auth.issuer_configured ? "bg-signal-green" : "bg-signal-yellow"}`} />
              <span className="text-xs text-text-tertiary">
                {info?.auth.provider || "Clerk"} {info?.auth.issuer_configured ? "" : "(not configured)"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Agent Status */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
        <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
          Agent Status
        </h2>
        <div className="space-y-2">
          {AGENT_LABELS.map((agent) => {
            const status = agentStatus[agent.key] ?? "idle";
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

      {/* Data Sources */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5 mb-6">
        <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
          Data Sources
        </h2>
        <div className="space-y-2">
          {(info?.data_sources ?? []).map((source) => (
            <div key={source.name} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className={`w-1.5 h-1.5 rounded-full ${source.configured ? "bg-signal-green" : "bg-signal-yellow"}`} />
                <span className="text-[13px] text-text-secondary">{source.name}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[10px] text-text-quaternary">{source.note}</span>
                <span className={`text-[10px] font-mono uppercase ${source.configured ? "text-signal-green" : "text-signal-yellow"}`}>
                  {source.configured ? "active" : "missing key"}
                </span>
              </div>
            </div>
          ))}
          {!info && !apiError && (
            <p className="text-xs text-text-quaternary">Loading…</p>
          )}
        </div>
      </div>

      {/* Risk Parameters */}
      <div className="rounded-xl border border-border-primary bg-bg-surface p-5">
        <h2 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
          Risk Parameters
        </h2>
        <div className="divide-y divide-border-primary">
          {(info?.risk_parameters ?? []).map((param) => (
            <div key={param.label} className="flex items-center justify-between py-3">
              <div>
                <span className="text-[13px] text-text-secondary">{param.label}</span>
                <p className="text-[10px] text-text-quaternary">{param.description}</p>
              </div>
              <span className="text-xs font-mono text-text-primary bg-bg-elevated px-2 py-1 rounded">
                {param.value}
              </span>
            </div>
          ))}
          {!info && !apiError && (
            <p className="text-xs text-text-quaternary py-3">Loading…</p>
          )}
        </div>
      </div>
    </div>
  );
}
