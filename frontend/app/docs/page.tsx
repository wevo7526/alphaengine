"use client";

import Link from "next/link";
import { useState } from "react";
import { sampleEnvelopeJson } from "@/lib/sampleEnvelope";

/**
 * Public docs page — the activation path. "Your first call": one real request
 * to either plane returns one SignalEnvelope. This is the credibility asset for
 * the algo persona (MARKETING_STRATEGY.md §5). Renders the pinned envelope from
 * lib/sampleEnvelope so the docs and the hero tearsheet show the same object.
 *
 * Status: the gateway (api.py / server.py) lands in build steps T6–T8. Until
 * then this documents the pinned contract; the endpoint URLs are placeholders.
 */
export default function DocsPage() {
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <DocsNav />
      <div className="max-w-[920px] mx-auto px-6 py-16">
        <Header />
        <NoData />
        <FirstCall />
        <EnvelopeSection />
        <ErrorsSection />
        <Disclaimer />
      </div>
    </div>
  );
}

function DocsNav() {
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-50">
      <div className="max-w-[1280px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-brand">engine</span>
          <span className="ml-2 text-[11px] font-mono tracking-[0.18em] text-text-quaternary">/ DOCS</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link href="/" className="text-[12px] font-medium tracking-wide text-text-tertiary hover:text-text-primary transition-colors">
            ← BACK
          </Link>
          <Link
            href="/sign-up"
            className="px-3.5 py-1.5 rounded-sm bg-white text-bg-primary text-[12px] font-semibold tracking-tight hover:bg-zinc-200 transition-colors"
          >
            Join the beta
          </Link>
        </div>
      </div>
    </header>
  );
}

function Header() {
  return (
    <div className="mb-14">
      <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
        <span className="text-text-tertiary">///</span> QUICKSTART
      </p>
      <h1 className="font-display text-[34px] sm:text-[42px] font-semibold tracking-[-0.01em] leading-[1.08] mb-5">
        Your first call.
      </h1>
      <p className="text-[15px] text-text-secondary leading-relaxed max-w-xl">
        Send your data; get back one <Code>SignalEnvelope</Code>. The deterministic
        plane answers synchronously over REST for your bot. The agent plane runs as
        a job you stream over MCP for your desk. Both emit the same versioned shape.
        Nothing you send is stored.
      </p>
    </div>
  );
}

function NoData() {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface/40 px-5 py-4 mb-14 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
      <span className="text-[10px] font-mono tracking-[0.18em] text-text-primary shrink-0">NO DATA, BY DESIGN</span>
      <span className="text-[12px] text-text-tertiary leading-relaxed">
        You supply the data in the call. We never source it, and we never store it.
        Telemetry records shapes and latency only — never your values.
      </span>
    </div>
  );
}

function FirstCall() {
  const [plane, setPlane] = useState<"rest" | "mcp">("rest");
  return (
    <section className="mb-16">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[20px] font-semibold tracking-tight">Make the call</h2>
        <div className="inline-flex rounded-sm border border-border-primary overflow-hidden text-[10px] font-mono tracking-[0.14em]">
          <button
            onClick={() => setPlane("rest")}
            className={`px-3 py-1 transition-colors ${
              plane === "rest" ? "bg-bg-elevated text-text-primary" : "text-text-quaternary hover:text-text-secondary"
            }`}
          >
            REST · ALGO
          </button>
          <button
            onClick={() => setPlane("mcp")}
            className={`px-3 py-1 border-l border-border-primary transition-colors ${
              plane === "mcp" ? "bg-bg-elevated text-text-primary" : "text-text-quaternary hover:text-text-secondary"
            }`}
          >
            MCP · DESK
          </button>
        </div>
      </div>

      {plane === "rest" ? (
        <>
          <p className="text-[13px] text-text-tertiary leading-relaxed mb-4">
            Synchronous. POST your price series; the deterministic core returns an
            envelope with <Code>determinism: &quot;exact&quot;</Code> and every <Code>thesis: null</Code>.
            No LLM in the path — your algo can pin the engine and reproduce it.
          </p>
          <CodeBlock
            label="POST /v1/signals/pairs"
            lines={[
              ["c", "# your data in — your license, never stored"],
              ["", "curl -sS https://api.alphaengine.dev/v1/signals/pairs \\"],
              ["", '  -H "Authorization: Bearer $ALPHAENGINE_KEY" \\'],
              ["", '  -H "Content-Type: application/json" \\'],
              ["", "  -d @- <<'JSON'"],
              ["", "  {"],
              ["", '    "prices": {'],
              ["", '      "ASLE": [12.1, 12.0, 12.3, 12.4, ...],'],
              ["", '      "WNC":  [25.9, 26.0, 26.2, 26.1, ...]'],
              ["", "    },"],
              ["", '    "n_trials": 240'],
              ["", "  }"],
              ["", "JSON"],
            ]}
          />
        </>
      ) : (
        <>
          <p className="text-[13px] text-text-tertiary leading-relaxed mb-4">
            Add the MCP server to your agent client. The desk runs as a job —
            submit, stream progress, receive the terminal envelope with
            <Code> determinism: &quot;agent&quot;</Code> and a narrated thesis.
          </p>
          <CodeBlock
            label="~/.config/mcp/servers.json"
            lines={[
              ["", "{"],
              ["", '  "mcpServers": {'],
              ["", '    "alphaengine": {'],
              ["", '      "url": "https://mcp.alphaengine.dev",'],
              ["", '      "headers": { "Authorization": "Bearer ${ALPHAENGINE_KEY}" }'],
              ["", "    }"],
              ["", "  }"],
              ["", "}"],
            ]}
          />
          <p className="text-[12px] text-text-quaternary leading-relaxed mt-3">
            Then ask your agent to run the desk on your data — it calls{" "}
            <Code>run_signal_slate</Code>, streams the agents, and hands back the
            same envelope shown below.
          </p>
        </>
      )}
    </section>
  );
}

function EnvelopeSection() {
  return (
    <section className="mb-16">
      <h2 className="text-[20px] font-semibold tracking-tight mb-2">The response: one SignalEnvelope</h2>
      <p className="text-[13px] text-text-tertiary leading-relaxed mb-4 max-w-xl">
        The single artifact both planes emit. Your algo reads{" "}
        <Code>instruments</Code>, <Code>levels</Code>, <Code>validation.verdict</Code>,
        and <Code>risk.gate</Code> and ignores the prose. Note the second signal: the
        system flagged its <span className="text-text-secondary">own</span> idea{" "}
        <span className="text-signal-green">likely_noise</span> and the gate{" "}
        <span className="text-text-secondary">block</span>ed it. That honesty ships by default.
      </p>
      <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
        <div className="px-4 py-2 border-b border-border-primary flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
          <span>200 OK · application/json</span>
          <span className="text-text-tertiary">schema_version 1.0.0</span>
        </div>
        <pre className="px-4 py-3 text-[10.5px] leading-[1.6] font-mono overflow-x-auto text-text-tertiary whitespace-pre">
          {sampleEnvelopeJson}
        </pre>
      </div>
      <p className="text-[12px] text-text-quaternary leading-relaxed mt-4 max-w-xl">
        <span className="text-text-tertiary">The one structural rule:</span> a signal
        with <Code>verdict: &quot;edge&quot;</Code> is rejected unless <Code>validation</Code> is
        populated. The envelope structurally refuses to ship an idea it hasn&apos;t
        checked for overfitting.
      </p>
    </section>
  );
}

function ErrorsSection() {
  const codes = [
    ["INPUT_TOO_LARGE", "Payload exceeds the inline size cap."],
    ["INSUFFICIENT_OBSERVATIONS", "Too few data points for a stable estimate."],
    ["SCHEMA_INVALID", "The request body failed validation."],
    ["AUTH_MISSING / AUTH_INVALID", "No key, or a key we don't recognize."],
    ["QUOTA_EXCEEDED", "Beta call/job quota for this key is spent."],
    ["JOB_NOT_FOUND / JOB_FAILED", "Agent-job lifecycle errors."],
  ];
  return (
    <section className="mb-16">
      <h2 className="text-[20px] font-semibold tracking-tight mb-2">Errors are machine-parseable</h2>
      <p className="text-[13px] text-text-tertiary leading-relaxed mb-4 max-w-xl">
        Typed codes you branch on, never prose. Every error echoes your{" "}
        <Code>request_id</Code>.
      </p>
      <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden divide-y divide-border-primary/40">
        {codes.map(([code, desc]) => (
          <div key={code} className="grid grid-cols-[minmax(0,260px)_1fr] gap-4 px-4 py-2.5 text-[11px]">
            <span className="font-mono text-text-secondary">{code}</span>
            <span className="text-text-quaternary">{desc}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Disclaimer() {
  return (
    <section className="border-t border-border-primary/60 pt-8">
      <p className="text-[11px] text-text-quaternary leading-relaxed max-w-xl">
        AlphaEngine is computational tooling, not investment advice. Outputs are
        the result of statistical and language models run on data you supply, and
        are not a recommendation to buy or sell any security. You are responsible
        for your own trading decisions.
      </p>
    </section>
  );
}

// ─── primitives
function Code({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[0.92em] text-text-secondary bg-bg-elevated/60 border border-border-primary/60 rounded px-1 py-0.5">
      {children}
    </span>
  );
}

function CodeBlock({ label, lines }: { label: string; lines: [string, string][] }) {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
      <div className="px-4 py-2 border-b border-border-primary flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>{label}</span>
        <span className="text-text-tertiary">your data → envelope</span>
      </div>
      <pre className="px-4 py-3 text-[11px] leading-[1.6] font-mono overflow-x-auto whitespace-pre">
        {lines.map(([kind, text], i) => (
          <div key={i} className={kind === "c" ? "text-text-quaternary" : "text-text-tertiary"}>
            {text || " "}
          </div>
        ))}
      </pre>
    </div>
  );
}
