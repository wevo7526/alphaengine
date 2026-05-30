"use client";

import Link from "next/link";
import { useState } from "react";
import { useUser } from "@clerk/nextjs";

/**
 * Paying-user portal (skeleton). Two pillars per the landed spec:
 *   1. Dev Console + Sandbox  — connection, run a tool, schema, recent calls,
 *      usage/latency/status, keys. Table stakes for trusting us in the critical path.
 *   2. Rigor Cockpit          — the "conscience of your research": edge/noise
 *      rate, the cumulative TRIAL LEDGER (the hero), gate analytics, regime
 *      mirror, reproducibility. Calibration + Integrity Report are fast-follows.
 *
 * HARD INVARIANTS (surfaced in the UI): derived rigor stats only. Never raw
 * payloads, market data, positions, or returns. Instrument symbols hashed/
 * omitted in stored metadata. See mcp-server/docs/USER_STATES.md + ACCESS_TIERS.
 *
 * Live data lands once the gateway is deployed (NEXT_PUBLIC_GATEWAY_URL); panels
 * show representative placeholders until then.
 */

type Tab = "console" | "cockpit" | "account";

export default function PortalPage() {
  const { user } = useUser();
  const [tab, setTab] = useState<Tab>("console");
  const first = user?.firstName || user?.fullName?.split(" ")[0];

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <PortalNav tab={tab} setTab={setTab} />
      <div className="max-w-[1100px] mx-auto px-6 py-10">
        <div className="rounded-sm border border-border-primary bg-bg-surface/40 px-5 py-3 mb-8 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-[10px] font-mono tracking-[0.16em] text-text-primary">YOUR DATA · YOUR KEYS · NOTHING STORED</span>
          <span className="text-[11px] text-text-quaternary">
            We retain derived rigor stats only (verdicts, deflated Sharpe, gates, regime, trial counts). Never your payloads, market data, positions, or returns.
          </span>
        </div>

        <h1 className="font-display text-[28px] sm:text-[34px] font-semibold tracking-[-0.01em] mb-6">
          Welcome{first ? `, ${first}` : ""}.
        </h1>

        {tab === "console" && <Console />}
        {tab === "cockpit" && <Cockpit />}
        {tab === "account" && <Account />}
      </div>
    </div>
  );
}

function PortalNav({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  const tabs: [Tab, string][] = [["console", "Dev Console"], ["cockpit", "Rigor Cockpit"], ["account", "Account"]];
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-40">
      <div className="max-w-[1100px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-brand">engine</span>
          <span className="ml-2 text-[11px] font-mono tracking-[0.18em] text-text-quaternary">/ PORTAL</span>
        </Link>
        <nav className="flex items-center gap-1 text-[12px]">
          {tabs.map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`px-3 py-1.5 rounded-sm transition-colors ${tab === id ? "bg-bg-elevated text-text-primary" : "text-text-tertiary hover:text-text-primary"}`}
            >
              {label}
            </button>
          ))}
          <Link href="/docs" className="px-3 py-1.5 text-text-tertiary hover:text-text-primary transition-colors">Docs</Link>
        </nav>
      </div>
    </header>
  );
}

// ── primitives ──
function Panel({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
      <div className="px-4 py-2 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>{title}</span>
        {note && <span className="text-text-tertiary">{note}</span>}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
function Pre({ children }: { children: React.ReactNode }) {
  return <pre className="text-[11px] leading-[1.6] font-mono text-text-tertiary overflow-x-auto whitespace-pre">{children}</pre>;
}
function Stub({ label }: { label: string }) {
  return <span className="text-[9px] font-mono tracking-[0.14em] text-text-quaternary border border-border-primary/70 rounded-sm px-1.5 py-0.5">{label}</span>;
}

// ────────────────────────────────────────────────────────────────────────
// PILLAR 1 — DEV CONSOLE + SANDBOX
// ────────────────────────────────────────────────────────────────────────
function Console() {
  return (
    <div className="space-y-6">
      <Sandbox />
      <div className="grid lg:grid-cols-2 gap-6">
        <Panel title="MCP · for your agent">
          <Pre>{`{
  "mcpServers": {
    "alphaengine": {
      "url": "https://<your-gateway>/mcp/",
      "headers": { "Authorization": "Bearer $ALPHAENGINE_KEY" }
    }
  }
}`}</Pre>
        </Panel>
        <Panel title="REST · for your bot">
          <Pre>{`curl https://<your-gateway>/v1/tools/compute_var_cvar \\
  -H "Authorization: Bearer $ALPHAENGINE_KEY" \\
  -d '{ "portfolio_returns": [ ... ] }'`}</Pre>
        </Panel>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Panel title="USAGE" note="stateless">
          <div className="grid grid-cols-3 gap-px bg-border-primary/40 border border-border-primary/40 rounded-sm overflow-hidden text-center">
            {[["CALLS", "0"], ["JOBS", "0"], ["p95 ms", "--"]].map(([k, v]) => (
              <div key={k} className="bg-bg-surface px-2 py-3">
                <p className="text-[8px] font-mono tracking-[0.18em] text-text-quaternary mb-1">{k}</p>
                <p className="text-[15px] font-mono text-text-primary">{v}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-text-tertiary">Counts + latency only, from /v1/status. We never log your payload values.</p>
        </Panel>
        <Panel title="RECENT CALLS" note="no values">
          <div className="divide-y divide-border-primary/40 text-[11px] font-mono">
            {[
              ["compute_var_cvar", "42ms", "200", "req_8f3a1c0e"],
              ["deflated_sharpe", "11ms", "200", "req_2b9d4f10"],
              ["compute_spread_signal", "—", "422", "req_71b9ac3d"],
            ].map(([tool, ms, code, rid]) => (
              <div key={rid} className="grid grid-cols-[1.4fr_0.6fr_0.5fr_1.2fr] gap-2 py-1.5">
                <span className="text-text-secondary truncate">{tool}</span>
                <span className="text-text-tertiary">{ms}</span>
                <span className={code === "200" ? "text-signal-green" : "text-text-tertiary"}>{code}</span>
                <span className="text-text-quaternary truncate">{rid}</span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-text-quaternary">Tool, duration, status, request_id. Never the payload.</p>
        </Panel>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Panel title="KEYS" note="beta">
          <div className="font-mono text-[12px] text-text-secondary bg-bg-primary/60 border border-border-primary/60 rounded-sm px-3 py-2.5 flex items-center justify-between">
            <span>ae_live_••••••••••••••••</span>
            <span className="text-[10px] tracking-[0.16em] text-text-quaternary">PROVISIONING</span>
          </div>
          <p className="mt-3 text-[11px] text-text-tertiary">Provision / rotate / revoke land with the gateway deploy. One key works across REST + MCP.</p>
        </Panel>
        <SchemaExplorer />
      </div>
    </div>
  );
}

function Sandbox() {
  const TOOLS = ["compute_var_cvar", "deflated_sharpe", "pbo_cscv", "compute_spread_signal", "find_cointegrated_pairs", "decompose_factors"];
  const [tool, setTool] = useState(TOOLS[0]);
  const [body, setBody] = useState('{\n  "portfolio_returns": [0.004, -0.011, 0.006, 0.013, -0.002, 0.009, -0.014, 0.007, 0.003, 0.011, -0.006, 0.002, 0.008, -0.009, 0.005, 0.001, 0.010, -0.004, 0.006, -0.003, 0.007, 0.012, -0.008, 0.004, 0.009, -0.005, 0.003, 0.006]\n}');
  const [out, setOut] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setOut("");
    const base = process.env.NEXT_PUBLIC_GATEWAY_URL;
    if (!base) {
      setOut("// Set NEXT_PUBLIC_GATEWAY_URL (the deployed gateway) to run live.\n// Until then this is a UI preview. The call shape is:\n// POST " + base + "/v1/tools/" + tool);
      setBusy(false);
      return;
    }
    try {
      const res = await fetch(`${base}/v1/tools/${tool}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      setOut(JSON.stringify(await res.json(), null, 2));
    } catch (e) {
      setOut("// request failed: " + (e instanceof Error ? e.message : String(e)));
    }
    setBusy(false);
  };

  return (
    <Panel title="SANDBOX" note="your key, real envelopes">
      <div className="flex items-center gap-2 mb-3">
        <select value={tool} onChange={(e) => setTool(e.target.value)} className="bg-bg-primary/60 border border-border-primary/60 rounded-sm px-2 py-1.5 text-[12px] font-mono text-text-secondary">
          {TOOLS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button onClick={run} disabled={busy} className="px-3 py-1.5 rounded-sm bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-200 disabled:opacity-60 transition-colors">
          {busy ? "Running…" : "Run"}
        </button>
      </div>
      <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6}
        className="w-full bg-bg-primary/60 border border-border-primary/60 rounded-sm px-3 py-2 text-[11px] font-mono text-text-secondary mb-3" />
      {out && <Pre>{out}</Pre>}
    </Panel>
  );
}

function SchemaExplorer() {
  const tools = [
    ["compute_var_cvar", "portfolio_returns[], confidence?"],
    ["deflated_sharpe", "returns[], n_trials"],
    ["pbo_cscv", "pnl_matrix[][], n_splits?"],
    ["compute_spread_signal", "a_closes[], b_closes[]"],
    ["find_cointegrated_pairs", "prices{}"],
    ["decompose_factors", "portfolio_returns[], factor_returns{}"],
  ];
  return (
    <Panel title="SCHEMA EXPLORER" note="6 tools">
      <div className="divide-y divide-border-primary/40">
        {tools.map(([t, inp]) => (
          <div key={t} className="py-1.5">
            <code className="text-[11px] font-mono text-text-primary">{t}</code>
            <span className="text-[10px] font-mono text-text-quaternary ml-2">{inp}</span>
          </div>
        ))}
      </div>
      <Link href="/docs#tools" className="mt-3 inline-block text-[11px] text-accent hover:underline">Full reference →</Link>
    </Panel>
  );
}

// ────────────────────────────────────────────────────────────────────────
// PILLAR 2 — RIGOR COCKPIT (the conscience of your research process)
// ────────────────────────────────────────────────────────────────────────
function Cockpit() {
  return (
    <div className="space-y-6">
      <p className="text-[13px] text-text-tertiary leading-relaxed max-w-2xl">
        The longitudinal mirror of your research process, built from verdict
        metadata alone. None of it needs your data. Symbols are hashed in stored
        stats by default, so even the rigor view never reveals what you trade.
      </p>

      <div className="grid lg:grid-cols-2 gap-6">
        <Panel title="EDGE / NOISE RATE" note="trailing 90d">
          <div className="flex items-end gap-4">
            {[["edge", "31%", "text-signal-green"], ["inconclusive", "44%", "text-text-secondary"], ["likely_noise", "25%", "text-text-tertiary"]].map(([k, v, c]) => (
              <div key={k}>
                <p className={`text-[22px] font-semibold ${c}`}>{v}</p>
                <p className="text-[10px] font-mono text-text-quaternary">{k}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-text-quaternary">Your own false-discovery tendency, made visible. Your backtester roots for you; this doesn&apos;t.</p>
        </Panel>

        <Panel title="CUMULATIVE TRIAL LEDGER" note="the one in-house tools miss">
          <div className="grid grid-cols-2 gap-3 text-center mb-2">
            <div className="bg-bg-primary/50 border border-border-primary/50 rounded-sm py-3">
              <p className="text-[8px] font-mono tracking-[0.18em] text-text-quaternary mb-1">TRIALS THIS QTR</p>
              <p className="text-[20px] font-mono text-text-primary">1,284</p>
            </div>
            <div className="bg-bg-primary/50 border border-border-primary/50 rounded-sm py-3">
              <p className="text-[8px] font-mono tracking-[0.18em] text-text-quaternary mb-1">FAMILY-WISE PBO</p>
              <p className="text-[20px] font-mono text-text-primary">0.41</p>
            </div>
          </div>
          <p className="text-[11px] text-text-tertiary leading-relaxed">
            Adjusted for everything you&apos;ve run through us, your best Sharpe this
            quarter is <span className="text-text-secondary">~41% likely to be luck</span>.
            No in-house tool keeps this ledger, because none sees your whole research program.
          </p>
        </Panel>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Panel title="GATE ANALYTICS" note="risk discipline">
          <div className="space-y-1.5 text-[11px] font-mono">
            {[["pass", "58%", "text-signal-green"], ["warn", "27%", "text-text-secondary"], ["block", "15%", "text-text-tertiary"]].map(([k, v, c]) => (
              <div key={k} className="flex items-center justify-between"><span className="text-text-quaternary">{k}</span><span className={c}>{v}</span></div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-text-quaternary">Top blockers: sector limit, marginal VaR.</p>
        </Panel>

        <Panel title="REGIME MIRROR" note="where your edge clusters">
          <div className="space-y-1.5 text-[11px] font-mono">
            {[["risk_on", "edge 38%"], ["late_cycle", "edge 29%"], ["transition", "edge 9%"], ["risk_off", "edge 17%"]].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between"><span className="text-text-quaternary">{k}</span><span className="text-text-secondary">{v}</span></div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-text-quaternary">Your hit-rate craters in transition regimes.</p>
        </Panel>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <Panel title="REPRODUCIBILITY">
          <p className="text-[12px] font-mono text-text-secondary mb-1">engine_version</p>
          <p className="text-[14px] font-mono text-text-primary">quant_core@1.0.0</p>
          <p className="mt-3 text-[11px] text-text-quaternary">Pin it; prove a signal reproduces on a given engine.</p>
        </Panel>
        <Panel title="ENGINE CALIBRATION"><div className="flex items-center gap-2"><Stub label="FAST-FOLLOW" /></div><p className="mt-3 text-[11px] text-text-quaternary">Do our edge verdicts precede positive returns? Forward returns scored in-call, aggregate stat kept, returns discarded.</p></Panel>
        <Panel title="RESEARCH INTEGRITY REPORT"><div className="flex items-center gap-2"><Stub label="FAST-FOLLOW" /></div><p className="mt-3 text-[11px] text-text-quaternary">A periodic digest you could hand an allocator. Populates after a few weeks of metadata.</p></Panel>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// ACCOUNT
// ────────────────────────────────────────────────────────────────────────
function Account() {
  return (
    <div className="space-y-6 max-w-[680px]">
      <Panel title="PLAN">
        <div className="flex items-baseline gap-2 mb-2">
          <span className="text-[20px] font-semibold text-text-primary">Free trial</span>
          <span className="text-[12px] font-mono text-text-tertiary">10-day · started on sign-up</span>
        </div>
        <p className="text-[12px] text-text-tertiary">Solo $49 / mo · Systematic $149 / mo · White-label (contact). Upgrade keeps your key and history.</p>
        <Link href="/plans" className="mt-3 inline-block text-[11px] text-accent hover:underline">View plans →</Link>
      </Panel>
      <Panel title="BILLING" note="beta"><p className="text-[12px] text-text-quaternary">Billing + invoices land with paid conversion.</p></Panel>
    </div>
  );
}
