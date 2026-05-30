"use client";

import Link from "next/link";
import { useState } from "react";
import { sampleEnvelopeJson } from "@/lib/sampleEnvelope";

/**
 * Public docs - the activation path and the credibility surface for the algo
 * persona (MARKETING_STRATEGY.md §5). Enterprise-grade: a sticky TOC, real
 * section hierarchy, prose around every code block, parameter tables, and the
 * live SignalEnvelope from lib/sampleEnvelope (same object the hero renders).
 *
 * Status: the gateway (api.py / server.py) lands in build steps T6–T8; the
 * endpoints below are the pinned contract and are labeled "preview" until the
 * service deploys. Hostnames are placeholders.
 */

const TOC = [
  { id: "overview", label: "Overview" },
  { id: "two-planes", label: "The two planes" },
  { id: "auth", label: "Authentication" },
  { id: "quickstart", label: "Quickstart - your first call" },
  { id: "envelope", label: "The SignalEnvelope" },
  { id: "tools", label: "Deterministic tools" },
  { id: "agent-job", label: "Agent slate (async)" },
  { id: "errors", label: "Errors" },
  { id: "versioning", label: "Versioning & determinism" },
];

export default function DocsPage() {
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <DocsNav />
      <div className="max-w-[1180px] mx-auto px-6 lg:grid lg:grid-cols-[200px_1fr] lg:gap-14">
        <Toc />
        <main className="py-16 min-w-0 max-w-[760px]">
          <Header />
          <Overview />
          <TwoPlanes />
          <Auth />
          <Quickstart />
          <EnvelopeSection />
          <ToolsSection />
          <AgentJobSection />
          <ErrorsSection />
          <VersioningSection />
          <Disclaimer />
        </main>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// CHROME
// ────────────────────────────────────────────────────────────────────────
function DocsNav() {
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-50">
      <div className="max-w-[1180px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-brand">engine</span>
          <span className="ml-2 text-[11px] font-mono tracking-[0.18em] text-text-quaternary">/ DOCS</span>
        </Link>
        <div className="flex items-center gap-3">
          <span className="hidden sm:inline-flex items-center gap-1.5 text-[10px] font-mono tracking-[0.16em] text-text-quaternary border border-border-primary rounded-sm px-2 py-1">
            <span className="w-1.5 h-1.5 rounded-full bg-accent/70" /> PREVIEW
          </span>
          <Link href="/" className="text-[12px] font-medium tracking-wide text-text-tertiary hover:text-text-primary transition-colors">
            ← BACK
          </Link>
          <Link
            href="/sign-up"
            className="px-3.5 py-1.5 rounded-sm bg-white text-bg-primary text-[12px] font-semibold tracking-tight hover:bg-zinc-200 transition-colors"
          >
            Start free trial
          </Link>
        </div>
      </div>
    </header>
  );
}

function Toc() {
  return (
    <aside className="hidden lg:block">
      <nav className="sticky top-[72px] py-16 text-[12.5px]">
        <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-4">ON THIS PAGE</p>
        <ul className="space-y-2.5 border-l border-border-primary/60">
          {TOC.map((t) => (
            <li key={t.id}>
              <a
                href={`#${t.id}`}
                className="block -ml-px pl-4 border-l border-transparent text-text-tertiary hover:text-text-primary hover:border-accent transition-colors leading-snug"
              >
                {t.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}

function Header() {
  return (
    <div className="mb-16">
      <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
        <span className="text-text-tertiary">///</span> DOCUMENTATION
      </p>
      <h1 className="font-display text-[36px] sm:text-[44px] font-semibold tracking-[-0.01em] leading-[1.06] mb-6">
        Your data in. A validated signal out.
      </h1>
      <p className="text-[16px] text-text-secondary leading-relaxed">
        AlphaEngine is a stateless signal layer you call with your own licensed
        data. It runs the quant math, checks the result for overfitting, gates it
        for risk, and returns a single, versioned <Code>SignalEnvelope</Code> - over
        a REST API for your execution bot or over MCP for your agent. You supply
        the data in the request; we compute and discard it. Nothing is stored.
      </p>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// OVERVIEW
// ────────────────────────────────────────────────────────────────────────
function Overview() {
  return (
    <Section id="overview" eyebrow="01" title="Overview">
      <Prose>
        Every call follows the same contract: you POST a payload of your data, the
        engine computes over it, and you receive a <Code>SignalEnvelope</Code> - the
        single artifact every endpoint returns. An execution bot reads the
        machine fields and ignores the prose; a human desk renders the same object
        as a memo. One shape, two readers.
      </Prose>
      <Prose>
        There is nothing to learn beyond the envelope and the handful of inputs
        each tool expects. The interface is model-agnostic - call it from any
        agent, any language, or plain <Code>curl</Code>. Our own reasoning desk
        runs on Claude, but you don&apos;t have to.
      </Prose>
      <Callout label="NO DATA, BY DESIGN">
        You supply the data in the call. We never source it and we never store it.
        Telemetry records request shapes and latency only - never your values.
      </Callout>
    </Section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// TWO PLANES
// ────────────────────────────────────────────────────────────────────────
function TwoPlanes() {
  return (
    <Section id="two-planes" eyebrow="02" title="The two planes">
      <Prose>
        The same engine answers in two modes. Which one you call depends on
        whether you want a number for an algo or a thesis for a human - and how
        long you&apos;re willing to wait.
      </Prose>
      <div className="grid sm:grid-cols-2 gap-4 my-7">
        <PlaneCard
          tag="DETERMINISTIC"
          title="The algo's path"
          lines={[
            "Pure math, version-pinned, sub-second.",
            "Synchronous: POST data, get the envelope back in one response.",
            "No LLM in the path. Same input → same output, always.",
          ]}
          chip="SYNC · REST or MCP"
        />
        <PlaneCard
          tag="PROBABILISTIC"
          title="The human's path"
          lines={[
            "A desk of agents reasons over the same math and narrates a thesis.",
            "Asynchronous job: submit, stream progress, receive the envelope.",
            "Tens of seconds to minutes. Reasons about numbers - never computes one your algo consumes.",
          ]}
          chip="ASYNC JOB · SSE"
        />
      </div>
      <Prose>
        Both planes emit the identical <Code>SignalEnvelope</Code>. The only
        difference a consumer sees is the <Code>determinism</Code> field
        (<Code>&quot;exact&quot;</Code> vs <Code>&quot;agent&quot;</Code>) and
        whether <Code>thesis</Code> is populated.
      </Prose>
    </Section>
  );
}

function PlaneCard({ tag, title, lines, chip }: { tag: string; title: string; lines: string[]; chip: string }) {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface px-5 py-5">
      <p className="text-[10px] font-mono tracking-[0.2em] text-text-quaternary mb-2">{tag}</p>
      <h3 className="text-[15px] font-semibold text-text-primary mb-3">{title}</h3>
      <ul className="space-y-2 mb-4">
        {lines.map((l, i) => (
          <li key={i} className="text-[12.5px] text-text-tertiary leading-relaxed flex gap-2">
            <span className="text-text-quaternary mt-px">·</span>
            <span>{l}</span>
          </li>
        ))}
      </ul>
      <span className="text-[9px] font-mono tracking-[0.14em] text-text-tertiary border border-border-primary/70 rounded-sm px-2 py-0.5">
        {chip}
      </span>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// AUTH
// ────────────────────────────────────────────────────────────────────────
function Auth() {
  return (
    <Section id="auth" eyebrow="03" title="Authentication">
      <Prose>
        Every request carries a per-client key in the <Code>Authorization</Code>{" "}
        header. The same key works across REST and MCP. Keep it server-side; it
        identifies your account for metering and quota.
      </Prose>
      <CodeBlock label="HEADER" lines={[["", "Authorization: Bearer $ALPHAENGINE_KEY"]]} />
      <Prose>
        Want to try before you have a key? The sandbox accepts a public,
        rate-limited key against sample data so you can see a real envelope
        without signing up. Production keys are issued from your dashboard.
      </Prose>
      <ParamTable
        rows={[
          ["ALPHAENGINE_KEY", "string", "Your account key. Sent as a bearer token on every REST and MCP call."],
          ["sandbox key", "string", "Public, rate-limited, sample-data only. For evaluation; not for production traffic."],
        ]}
      />
    </Section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// QUICKSTART
// ────────────────────────────────────────────────────────────────────────
function Quickstart() {
  const [plane, setPlane] = useState<"rest" | "mcp">("rest");
  return (
    <Section id="quickstart" eyebrow="04" title="Quickstart - your first call">
      <Prose>
        The fastest path to a signal is the deterministic plane: send a price
        series, get back a validated envelope synchronously. Pick your surface -
        REST for a bot, MCP for an agent. Both return the same thing.
      </Prose>

      <Tabs
        tabs={[
          { id: "rest", label: "REST · ALGO" },
          { id: "mcp", label: "MCP · DESK" },
        ]}
        active={plane}
        onChange={(id) => setPlane(id as "rest" | "mcp")}
      />

      {plane === "rest" ? (
        <div className="mt-6 space-y-5">
          <Prose>
            <Step n={1} /> Send your data. This posts two aligned close-price
            series to the cointegration tool. Your data is read for the duration
            of the request and then discarded.
          </Prose>
          <CodeBlock
            label="POST /v1/tools/compute_spread_signal"
            lines={[
              ["", "curl -sS https://api.alphaengine.dev/v1/tools/compute_spread_signal \\"],
              ["", '  -H "Authorization: Bearer $ALPHAENGINE_KEY" \\'],
              ["", '  -H "Content-Type: application/json" \\'],
              ["", "  -d '{"],
              ["", '    "a_closes": [12.1, 12.0, 12.3, 12.4],'],
              ["", '    "b_closes": [25.9, 26.0, 26.2, 26.1],'],
              ["", '    "symbol_a": "ASLE", "symbol_b": "WNC"'],
              ["", "  }'"],
            ]}
          />
          <Prose>
            <Step n={2} /> Read the response. You get a <Code>SignalEnvelope</Code> with{" "}
            <Code>determinism: &quot;exact&quot;</Code> and every <Code>thesis: null</Code> -
            there&apos;s no language model in this path, so an algo can pin the
            engine version and reproduce the result exactly. The full shape is{" "}
            <a href="#envelope" className="text-accent hover:underline">documented below</a>.
          </Prose>
        </div>
      ) : (
        <div className="mt-6 space-y-5">
          <Prose>
            <Step n={1} /> Add the server to your MCP client. Any MCP-capable agent
            can discover the tools at connect time - no SDK required.
          </Prose>
          <CodeBlock
            label="~/.config/mcp/servers.json"
            lines={[
              ["", "{"],
              ["", '  "mcpServers": {'],
              ["", '    "alphaengine": {'],
              ["", '      "url": "https://mcp.alphaengine.dev",'],
              ["", '      "headers": {'],
              ["", '        "Authorization": "Bearer ${ALPHAENGINE_KEY}"'],
              ["", "      }"],
              ["", "    }"],
              ["", "  }"],
              ["", "}"],
            ]}
          />
          <Prose>
            <Step n={2} /> Ask your agent to run a tool or start a slate. For a
            deterministic tool the result returns immediately; for the agent desk
            it starts a job your client streams to completion. Either way the
            output is the same <Code>SignalEnvelope</Code>.
          </Prose>
        </div>
      )}
    </Section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// ENVELOPE
// ────────────────────────────────────────────────────────────────────────
function EnvelopeSection() {
  const [open, setOpen] = useState(false);
  const trimmed = sampleEnvelopeJson.split("\n").slice(0, 26).join("\n");
  return (
    <Section id="envelope" eyebrow="05" title="The SignalEnvelope">
      <Prose>
        The envelope is the one artifact every endpoint returns and the only
        contract you build against. The top level carries the version and
        provenance of the run; <Code>signals[]</Code> carries the ideas. An
        execution layer typically reads four things per signal -{" "}
        <Code>instruments</Code>, <Code>levels</Code>,{" "}
        <Code>validation.verdict</Code>, and <Code>risk.gate</Code> - and ignores
        everything else.
      </Prose>

      <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mt-8 mb-3">TOP LEVEL</p>
      <ParamTable
        rows={[
          ["schema_version", "string", "Semver of the envelope. Pin it; a major bump means a breaking change."],
          ["engine_version", "string", "Which quant_core produced this. Lets an algo reproduce or refuse a result."],
          ["request_id", "string", "Echoed back for tracing and idempotency."],
          ["generated_at", "ISO-8601", "UTC timestamp of the response."],
          ["determinism", '"exact" | "agent"', "Which plane produced this. Algos consume exact; desks render agent."],
          ["signals[]", "Signal[]", "The ideas. See the per-signal fields below."],
          ["warnings[]", "string[]", "Caps hit, short windows, fallbacks used - surfaced, never silent."],
        ]}
      />

      <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mt-8 mb-3">PER SIGNAL</p>
      <ParamTable
        rows={[
          ["instruments[]", "Instrument[]", "Symbol, side (long/short), optional weight and hedge_ratio."],
          ["thesis", "string | null", "The agent-plane narrative. Always null on the deterministic plane."],
          ["levels", "{entry,stop,target}", "Suggested price levels."],
          ["sizing", "{suggested_weight,…}", "Portfolio weight, VaR contribution, regime multiplier."],
          ["validation", "Validation", "The overfitting check - deflated_sharpe, pbo, psr, and the verdict."],
          ["risk", "Risk", "VaR/CVaR, factor betas, stress, and the gate (pass/warn/block)."],
          ["context", "{regime,…}", "Macro regime and its posterior."],
          ["provenance[]", "Provenance[]", "Field → tool → inputs_hash → formula. Every figure is traceable."],
        ]}
      />

      <Callout label="THE ONE STRUCTURAL RULE" tone="accent">
        A signal with <Code>validation.verdict: &quot;edge&quot;</Code> is rejected
        unless a rigor figure (<Code>deflated_sharpe</Code>, <Code>pbo</Code>, or{" "}
        <Code>psr</Code>) is populated. The envelope structurally refuses to ship
        an idea it hasn&apos;t checked for overfitting.
      </Callout>

      <Prose>
        Here is a real response. Note the second signal: the system flagged its{" "}
        <span className="text-text-secondary">own</span> pair idea as{" "}
        <span className="text-signal-green">likely_noise</span> and the gate{" "}
        <span className="text-text-secondary">block</span>ed it. Shipping the
        negative verdict instead of hiding it is the point.
      </Prose>
      <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
        <div className="px-4 py-2 border-b border-border-primary flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
          <span>200 OK · application/json</span>
          <span className="text-text-tertiary">schema_version 1.0.0</span>
        </div>
        <pre className="px-4 py-3 text-[10.5px] leading-[1.65] font-mono overflow-x-auto whitespace-pre text-text-tertiary">
          {open ? sampleEnvelopeJson : trimmed + "\n  …"}
        </pre>
        <button
          onClick={() => setOpen((v) => !v)}
          className="w-full px-4 py-2 border-t border-border-primary/60 text-[10px] font-mono tracking-[0.16em] text-text-tertiary hover:text-text-primary hover:bg-bg-elevated/40 transition-colors text-left"
        >
          {open ? "− COLLAPSE" : "+ SHOW FULL ENVELOPE"}
        </button>
      </div>
    </Section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// TOOLS
// ────────────────────────────────────────────────────────────────────────
function ToolsSection() {
  const tools = [
    ["find_cointegrated_pairs", "Signals", "Screen a universe of price series for cointegrated pairs (Engle-Granger ADF, half-life, stability)."],
    ["compute_spread_signal", "Signals", "Full pair analysis for two series: hedge ratio, cointegration, z-score, trade signal."],
    ["deflated_sharpe", "Validation", "Sharpe corrected for the number of trials and non-normal returns. The noise test."],
    ["pbo_cscv", "Validation", "Probability of backtest overfitting via combinatorially symmetric cross-validation."],
    ["compute_var_cvar", "Risk", "Parametric + Cornish-Fisher + historical VaR and Expected Shortfall on a return stream."],
    ["decompose_factors", "Risk", "Factor betas, alpha, R², and a multicollinearity diagnostic from supplied factor returns."],
  ];
  return (
    <Section id="tools" eyebrow="06" title="Deterministic tools">
      <Prose>
        Six tools make up the beta deterministic cut. Each is a pure function over
        the data you supply, callable synchronously on either surface. Inputs are
        validated hard - too few observations or a malformed body returns a typed
        error, never a quietly wrong number.
      </Prose>
      <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden divide-y divide-border-primary/40 my-6">
        {tools.map(([name, layer, desc]) => (
          <div key={name} className="px-4 py-3.5">
            <div className="flex items-center gap-3 mb-1">
              <code className="text-[12px] font-mono text-text-primary">{name}</code>
              <span className="text-[9px] font-mono tracking-[0.14em] text-text-quaternary border border-border-primary/70 rounded-sm px-1.5 py-0.5">
                {layer}
              </span>
            </div>
            <p className="text-[12.5px] text-text-tertiary leading-relaxed">{desc}</p>
          </div>
        ))}
      </div>
      <Prose>
        Construction tools (Black-Litterman, HRP) and context tools (regime,
        yield-curve) are on the roadmap but out of scope for the beta.
      </Prose>
    </Section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// AGENT JOB
// ────────────────────────────────────────────────────────────────────────
function AgentJobSection() {
  return (
    <Section id="agent-job" eyebrow="07" title="Agent slate (asynchronous)">
      <Prose>
        The agent desk reasons over the same math to produce a full, cited slate.
        Because a run takes tens of seconds to minutes, it&apos;s a job, not a
        blocking request: submit, then poll or stream until the terminal envelope
        is ready.
      </Prose>
      <ol className="space-y-3 my-6">
        <Lifecycle n={1} code="POST /v1/jobs" text="Submit your data and a query. Returns a job_id immediately." />
        <Lifecycle n={2} code="GET /v1/jobs/{id}/stream" text="Stream progress over SSE as each desk agent runs." />
        <Lifecycle n={3} code="GET /v1/jobs/{id}" text="Fetch the terminal SignalEnvelope when status is done." />
      </ol>
      <Prose>
        The deterministic plane is idempotent - safe to retry. The agent plane is
        not (it reasons with a language model); an optional input-hash key lets a
        duplicate submit return the in-flight job instead of starting a second
        run. Your data lives only for the duration of the job and is discarded
        with it.
      </Prose>
    </Section>
  );
}

function Lifecycle({ n, code, text }: { n: number; code: string; text: string }) {
  return (
    <li className="flex gap-4">
      <span className="shrink-0 w-6 h-6 rounded-sm border border-border-primary flex items-center justify-center text-[11px] font-mono text-text-tertiary">
        {n}
      </span>
      <div>
        <code className="text-[12px] font-mono text-text-secondary">{code}</code>
        <p className="text-[12.5px] text-text-tertiary leading-relaxed mt-0.5">{text}</p>
      </div>
    </li>
  );
}

// ────────────────────────────────────────────────────────────────────────
// ERRORS
// ────────────────────────────────────────────────────────────────────────
function ErrorsSection() {
  const codes = [
    ["INPUT_TOO_LARGE", "413", "Payload exceeds the inline size cap."],
    ["INSUFFICIENT_OBSERVATIONS", "422", "Too few data points for a stable estimate."],
    ["SCHEMA_INVALID", "422", "The request body failed validation."],
    ["AUTH_MISSING", "401", "No key supplied."],
    ["AUTH_INVALID", "401", "Key not recognized."],
    ["QUOTA_EXCEEDED", "429", "Call/job quota for this key is spent."],
    ["JOB_NOT_FOUND", "404", "No job with that id."],
    ["JOB_FAILED", "500", "The agent run errored out."],
  ];
  return (
    <Section id="errors" eyebrow="08" title="Errors">
      <Prose>
        Errors are typed codes you branch on, never prose. Every error echoes your{" "}
        <Code>request_id</Code> and carries an HTTP status.
      </Prose>
      <CodeBlock
        label="ERROR SHAPE"
        lines={[
          ["", "{"],
          ["", '  "error": {'],
          ["", '    "code": "INSUFFICIENT_OBSERVATIONS",'],
          ["", '    "message": "compute_var_cvar needs >= 20 returns, got 12",'],
          ["", '    "request_id": "req_8f3a1c0e"'],
          ["", "  }"],
          ["", "}"],
        ]}
      />
      <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden divide-y divide-border-primary/40 mt-6">
        {codes.map(([code, status, desc]) => (
          <div key={code} className="grid grid-cols-[minmax(0,230px)_40px_1fr] gap-3 px-4 py-2.5 text-[11.5px] items-center">
            <code className="font-mono text-text-secondary">{code}</code>
            <span className="font-mono text-text-quaternary">{status}</span>
            <span className="text-text-quaternary">{desc}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// VERSIONING
// ────────────────────────────────────────────────────────────────────────
function VersioningSection() {
  return (
    <Section id="versioning" eyebrow="09" title="Versioning & determinism">
      <Prose>
        The envelope is semver&apos;d from the first beta. Additive fields are a
        minor bump; a removal or a semantic change is a major bump with a 90-day
        deprecation window. Pin <Code>schema_version</Code> and you won&apos;t be
        surprised.
      </Prose>
      <Prose>
        On the deterministic plane, every numeric dependency is pinned exactly and
        guarded by golden-output tests, and <Code>engine_version</Code> is stamped
        on every response. A change that would move a regression tail - and
        therefore a signal - fails our CI before it ships, and shows up to you as
        a new <Code>engine_version</Code> you can choose to pin to or refuse.
      </Prose>
    </Section>
  );
}

function Disclaimer() {
  return (
    <section className="border-t border-border-primary/60 pt-8 mt-16">
      <p className="text-[11px] text-text-quaternary leading-relaxed">
        AlphaEngine is computational tooling, not investment advice. Outputs are
        the result of statistical and language models run on data you supply, and
        are not a recommendation to buy or sell any security. You are responsible
        for your own trading decisions.
      </p>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// PRIMITIVES
// ────────────────────────────────────────────────────────────────────────
function Section({ id, eyebrow, title, children }: { id: string; eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 mb-20">
      <div className="flex items-baseline gap-3 mb-6 pb-3 border-b border-border-primary/60">
        <span className="text-[11px] font-mono tracking-[0.2em] text-text-quaternary">{eyebrow}</span>
        <h2 className="font-display text-[24px] sm:text-[28px] font-semibold tracking-[-0.01em]">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Prose({ children }: { children: React.ReactNode }) {
  return <p className="text-[14.5px] text-text-secondary leading-[1.75] mb-4">{children}</p>;
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="font-mono text-[0.88em] text-text-secondary bg-bg-elevated/60 border border-border-primary/60 rounded px-1.5 py-0.5">
      {children}
    </code>
  );
}

function Step({ n }: { n: number }) {
  return (
    <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-accent/15 border border-accent/30 text-accent text-[10px] font-mono font-semibold mr-2 align-middle">
      {n}
    </span>
  );
}

function Callout({ label, children, tone = "neutral" }: { label: string; children: React.ReactNode; tone?: "neutral" | "accent" }) {
  return (
    <div
      className={`my-7 rounded-sm border px-5 py-4 ${
        tone === "accent" ? "border-accent/40 bg-accent/[0.05]" : "border-border-primary bg-bg-surface/50"
      }`}
    >
      <p className={`text-[10px] font-mono tracking-[0.2em] mb-2 ${tone === "accent" ? "text-accent" : "text-text-primary"}`}>
        {label}
      </p>
      <p className="text-[13px] text-text-tertiary leading-relaxed">{children}</p>
    </div>
  );
}

function ParamTable({ rows }: { rows: [string, string, string][] }) {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden divide-y divide-border-primary/40">
      {rows.map(([name, type, desc]) => (
        <div key={name} className="grid sm:grid-cols-[minmax(0,180px)_1fr] gap-1 sm:gap-5 px-4 py-3">
          <div className="min-w-0">
            <code className="text-[12px] font-mono text-text-primary break-words">{name}</code>
            <p className="text-[10.5px] font-mono text-text-quaternary mt-0.5">{type}</p>
          </div>
          <p className="text-[12.5px] text-text-tertiary leading-relaxed">{desc}</p>
        </div>
      ))}
    </div>
  );
}

function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="inline-flex rounded-sm border border-border-primary overflow-hidden text-[10px] font-mono tracking-[0.14em]">
      {tabs.map((t, i) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-4 py-2 transition-colors ${i > 0 ? "border-l border-border-primary" : ""} ${
            active === t.id ? "bg-bg-elevated text-text-primary" : "text-text-quaternary hover:text-text-secondary"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function CodeBlock({ label, lines }: { label: string; lines: [string, string][] }) {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden my-4">
      <div className="px-4 py-2 border-b border-border-primary flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>{label}</span>
        <span className="text-text-tertiary">your data → envelope</span>
      </div>
      <pre className="px-4 py-3 text-[11.5px] leading-[1.7] font-mono overflow-x-auto whitespace-pre">
        {lines.map(([kind, text], i) => (
          <div key={i} className={kind === "c" ? "text-text-quaternary" : "text-text-tertiary"}>
            {text || " "}
          </div>
        ))}
      </pre>
    </div>
  );
}
