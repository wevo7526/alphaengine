"use client";

import Link from "next/link";
import { useState } from "react";
import { useUser } from "@clerk/nextjs";
import { sampleMemo } from "@/lib/sampleEnvelope";

/**
 * Marketing landing. Anchor: "The signal layer between your data and your algo."
 * Two front doors over one engine; demo (eval) vs portal (paid) funnel.
 * See mcp-server/docs/MARKETING_STRATEGY.md, ACCESS_TIERS.md, USER_STATES.md.
 *
 * Copy rule: zero em dashes anywhere on this page.
 * CTA ladder: hero "Try the demo" -> /demo, "Read the docs" -> /docs;
 * "Explore the demo desk" -> demo login; "Start building" -> portal trial.
 */
export default function LandingPage() {
  const { isSignedIn } = useUser();
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary flex flex-col relative overflow-hidden">
      <TopNav isSignedIn={!!isSignedIn} />
      <Hero isSignedIn={!!isSignedIn} />
      <TaglineStrip />
      <TheModel />
      <HowItWorks />
      <ProductShowcase />
      <Pipeline />
      <SourceLedger />
      <ClosingCTA isSignedIn={!!isSignedIn} />
      <Footer />
    </div>
  );
}

// ── shared CTA targets ───────────────────────────────────────────────────
const PORTAL_SIGNUP = "/sign-up?surface=portal";
const DEMO_LOGIN = "/sign-in?surface=demo";

// ────────────────────────────────────────────────────────────────────────
// TOP NAV
// ────────────────────────────────────────────────────────────────────────
function TopNav({ isSignedIn }: { isSignedIn: boolean }) {
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-50">
      <div className="max-w-[1280px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-brand">engine</span>
        </Link>
        <nav className="hidden md:flex items-center gap-7 text-[12px] font-medium tracking-wide text-text-tertiary">
          <Link href="/docs" className="hover:text-text-primary transition-colors">DOCS</Link>
          <Link href="/plans" className="hover:text-text-primary transition-colors">PLANS</Link>
        </nav>
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="hidden sm:inline-block px-3 py-1.5 rounded-sm border border-border-primary text-[12px] font-semibold tracking-tight text-text-secondary hover:text-text-primary hover:border-zinc-700 transition-colors"
          >
            Demo Desk
          </Link>
          <Link
            href={isSignedIn ? "/portal" : PORTAL_SIGNUP}
            className="px-3.5 py-1.5 rounded-sm bg-white text-bg-primary text-[12px] font-semibold tracking-tight hover:bg-zinc-200 transition-colors"
          >
            Portal
          </Link>
        </div>
      </div>
    </header>
  );
}

// ────────────────────────────────────────────────────────────────────────
// HERO
// ────────────────────────────────────────────────────────────────────────
function Hero({ isSignedIn }: { isSignedIn: boolean }) {
  return (
    <section className="relative isolate min-h-[80vh] flex flex-col justify-center overflow-hidden border-b border-border-primary/60">
      <div className="absolute inset-0 grid-bg opacity-[0.10]" aria-hidden="true" />
      <div className="relative z-10 max-w-[1280px] mx-auto px-6 w-full py-24">
        <div className="grid lg:grid-cols-[1.02fr_1fr] gap-14 items-center">
          <div className="max-w-xl">
            <h1 className="font-display text-[36px] sm:text-[46px] lg:text-[52px] font-semibold tracking-[-0.01em] leading-[1.07] mb-8 mt-2">
              The signal layer between
              <br />
              your data and your algo.
            </h1>

            <p className="text-[16px] text-text-secondary leading-relaxed mb-10 max-w-md">
              A stateless engine you run on your own licensed data. It computes the
              math, checks for overfitting, and returns cited, risk-gated,
              algo-ready signals. Over MCP for your agent or a direct API for your
              bot. Nothing sourced. Nothing stored.
            </p>

            <div className="flex items-center gap-4 flex-wrap mb-5">
              <Link
                href="/dashboard"
                className="px-5 py-2.5 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors"
              >
                Demo Desk
              </Link>
              <Link
                href={isSignedIn ? "/portal" : PORTAL_SIGNUP}
                className="px-5 py-2.5 rounded-sm border border-border-primary text-text-secondary text-[13px] font-semibold hover:text-text-primary hover:border-zinc-700 transition-colors"
              >
                Portal
              </Link>
            </div>
            <p className="text-[12px] text-text-quaternary">
              The Demo Desk runs on sample data for testing and education.{" "}
              <Link href="/plans" className="text-text-tertiary hover:text-text-primary underline underline-offset-4 decoration-border-primary transition-colors">
                See plans
              </Link>
            </p>
          </div>

          <SplitArtifact />
        </div>
      </div>
    </section>
  );
}

// The proof artifact: one result, two formats (memo vs envelope JSON).
function SplitArtifact() {
  const [view, setView] = useState<"memo" | "json">("memo");
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">ONE RESULT · TWO FORMATS</span>
        <div className="inline-flex rounded-sm border border-border-primary overflow-hidden text-[10px] font-mono tracking-[0.14em]">
          <button onClick={() => setView("memo")} className={`px-3 py-1 transition-colors ${view === "memo" ? "bg-bg-elevated text-text-primary" : "text-text-quaternary hover:text-text-secondary"}`}>MEMO</button>
          <button onClick={() => setView("json")} className={`px-3 py-1 border-l border-border-primary transition-colors ${view === "json" ? "bg-bg-elevated text-text-primary" : "text-text-quaternary hover:text-text-secondary"}`}>JSON</button>
        </div>
      </div>
      {view === "memo" ? <MemoTearsheet /> : <EnvelopeTearsheet />}
      <p className="mt-3 text-[11px] text-text-quaternary leading-relaxed">
        Human-readable for your desk. Machine-readable for your algo.{" "}
        <span className="text-text-tertiary">Same result, same receipts.</span>
      </p>
      <p className="mt-1 text-[10px] text-text-quaternary/80">Illustrative sample. Not investment advice.</p>
    </div>
  );
}

function MemoTearsheet() {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden text-text-secondary">
      <div className="px-4 py-2.5 border-b border-border-primary flex items-center justify-between">
        <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">INTELLIGENCE MEMO</span>
        <span className="text-[10px] font-mono tracking-[0.18em] px-2 py-0.5 border border-border-primary rounded-sm text-text-primary">{sampleMemo.decision}</span>
      </div>
      <div className="px-4 pt-3.5 pb-3 border-b border-border-primary/60">
        <p className="font-display text-[15px] text-text-primary leading-snug">{sampleMemo.title}</p>
      </div>
      <div className="grid grid-cols-4 divide-x divide-border-primary/60 border-b border-border-primary/60">
        {[["CONVICTION", String(sampleMemo.conviction)], ["REGIME", sampleMemo.regime], ["RISK", sampleMemo.risk], ["NAMES", String(sampleMemo.rows.length)]].map(([k, v]) => (
          <div key={k} className="px-3 py-2.5">
            <p className="text-[8px] font-mono tracking-[0.18em] text-text-quaternary mb-1">{k}</p>
            <p className="text-[11px] font-mono text-text-primary truncate">{v}</p>
          </div>
        ))}
      </div>
      <div className="px-4 py-2 border-b border-border-primary/60">
        <div className="grid grid-cols-[1.2fr_0.8fr_0.6fr_1fr_1fr_1fr] gap-2 text-[8px] font-mono tracking-[0.14em] text-text-quaternary pb-1.5 mb-1 border-b border-border-primary/40">
          <span>TICKER</span><span>DIR</span><span>CONV</span><span>ENTRY</span><span>STOP</span><span>TARGET</span>
        </div>
        {sampleMemo.rows.map((r) => (
          <div key={r.t} className="grid grid-cols-[1.2fr_0.8fr_0.6fr_1fr_1fr_1fr] gap-2 text-[11px] font-mono py-1 tabular-nums">
            <span className="text-text-primary">{r.t}</span><span className="text-text-tertiary">{r.d}</span><span className="text-text-secondary">{r.c}</span><span className="text-text-tertiary">{r.e}</span><span className="text-text-tertiary">{r.s}</span><span className="text-text-tertiary">{r.p}</span>
          </div>
        ))}
      </div>
      <div className="px-4 py-2.5 flex items-center gap-3 bg-bg-elevated/40">
        <span className="text-[10px] font-mono tracking-[0.16em] text-text-primary">✓ VERIFIED</span>
        <span className="text-[10px] font-mono tracking-[0.16em] text-text-quaternary">{sampleMemo.sources} sources</span>
        <span className="ml-auto text-[10px] font-mono tracking-[0.16em] text-text-quaternary">deflated&nbsp;SR&nbsp;{sampleMemo.deflated_sharpe}</span>
      </div>
    </div>
  );
}

function EnvelopeTearsheet() {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border-primary flex items-center justify-between">
        <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">SIGNAL ENVELOPE</span>
        <span className="text-[10px] font-mono tracking-[0.18em] text-text-tertiary">application/json</span>
      </div>
      <pre className="px-4 py-3 text-[10.5px] leading-[1.55] font-mono overflow-x-auto text-text-tertiary">
        <Ln>{"{"}</Ln>
        <Ln i={1}><K>"schema_version"</K>: <S>"1.0.0"</S>,</Ln>
        <Ln i={1}><K>"engine_version"</K>: <S>"quant_core@1.0.0"</S>,</Ln>
        <Ln i={1}><K>"determinism"</K>: <S>"agent"</S>,</Ln>
        <Ln i={1}><K>"signals"</K>: [{"{"}</Ln>
        <Ln i={2}><K>"instruments"</K>: [{"{"} <K>"symbol"</K>: <S>"ASLE"</S>, <K>"side"</K>: <S>"long"</S> {"}"}],</Ln>
        <Ln i={2}><K>"levels"</K>: {"{"} <K>"entry"</K>: <N>12.40</N>, <K>"stop"</K>: <N>10.90</N>, <K>"target"</K>: <N>17.20</N> {"}"},</Ln>
        <Ln i={2}><K>"validation"</K>: {"{"}</Ln>
        <Ln i={3}><K>"deflated_sharpe"</K>: <N>0.91</N>, <K>"pbo"</K>: <N>0.18</N>,</Ln>
        <Ln i={3}><K>"verdict"</K>: <V>"edge"</V></Ln>
        <Ln i={2}>{"}"},</Ln>
        <Ln i={2}><K>"risk"</K>: {"{"} <K>"var"</K>: <N>0.021</N>, <K>"gate"</K>: <V>"pass"</V> {"}"}</Ln>
        <Ln i={1}>{"}"}]</Ln>
        <Ln>{"}"}</Ln>
      </pre>
      <div className="px-4 py-2.5 flex items-center gap-3 bg-bg-elevated/40 border-t border-border-primary/60">
        <span className="text-[10px] font-mono tracking-[0.16em] text-signal-green">verdict: edge</span>
        <span className="text-[10px] font-mono tracking-[0.16em] text-text-quaternary">gate: pass</span>
        <Link href="/docs" className="ml-auto text-[10px] font-mono tracking-[0.16em] text-text-tertiary hover:text-text-primary transition-colors">full envelope →</Link>
      </div>
    </div>
  );
}

function Ln({ i = 0, children }: { i?: number; children: React.ReactNode }) {
  return <div style={{ paddingLeft: `${i * 1.1}rem` }}>{children}</div>;
}
function K({ children }: { children: React.ReactNode }) { return <span className="text-text-secondary">{children}</span>; }
function S({ children }: { children: React.ReactNode }) { return <span className="text-text-tertiary">{children}</span>; }
function N({ children }: { children: React.ReactNode }) { return <span className="text-text-primary tabular-nums">{children}</span>; }
function V({ children }: { children: React.ReactNode }) { return <span className="text-signal-green">{children}</span>; }

// ────────────────────────────────────────────────────────────────────────
// TAGLINE STRIP — kept verbatim (strongest line on the page).
// ────────────────────────────────────────────────────────────────────────
function TaglineStrip() {
  return (
    <section className="relative border-y border-border-primary/60 bg-bg-surface/20">
      <div className="max-w-[920px] mx-auto px-6 py-20 text-center">
        <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-6">
          <span className="text-text-tertiary">///</span> NO DATA, BY DESIGN
        </p>
        <p className="font-display text-[26px] sm:text-[32px] font-semibold tracking-[-0.01em] leading-[1.2] text-text-primary">
          Your data goes in. The math comes out. Nothing stays.
          <br className="hidden sm:block" />
          <span className="text-text-tertiary">
            {" "}We never source, store, or redistribute market data. Your data runs through the engine in the moment and is discarded. No data to leak, no licensing to untangle, no vendor lock between you and your numbers.
          </span>
        </p>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// THE MODEL — new graphic (data -> engine -> signal, nothing kept) + tagline.
// ────────────────────────────────────────────────────────────────────────
function TheModel() {
  return (
    <section className="border-b border-border-primary/60">
      <div className="max-w-[1280px] mx-auto px-6 py-20">
        <div className="text-center mb-14 max-w-2xl mx-auto">
          <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-4">
            <span className="text-text-tertiary">///</span> THE MODEL
          </p>
          <h2 className="font-display text-[26px] sm:text-[34px] font-semibold tracking-[-0.01em] leading-[1.15] mb-4">
            Plug it in. Know when it&apos;s noise.
          </h2>
          <p className="text-[15px] text-text-tertiary max-w-lg mx-auto leading-relaxed">
            A computation layer, not a data vendor. Your data passes through, the
            math comes back, and nothing is kept.
          </p>
        </div>

        {/* Flow graphic: data -> engine (concrete micro-outputs) -> a signal */}
        <div className="max-w-[980px] mx-auto rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
          <div className="grid md:grid-cols-[0.85fr_1.3fr_0.85fr]">
            {/* YOUR DATA */}
            <div className="px-6 py-7 border-b md:border-b-0 md:border-r border-border-primary/50">
              <p className="text-[10px] font-mono tracking-[0.2em] text-text-quaternary mb-4">YOUR DATA</p>
              <div className="space-y-1.5">
                {["ASLE · prices", "fundamentals", "filings"].map((x) => (
                  <div key={x} className="font-mono text-[11px] text-text-tertiary bg-bg-primary/50 border border-border-primary/50 rounded-sm px-2.5 py-1.5">{x}</div>
                ))}
              </div>
              <p className="mt-4 text-[10px] text-text-quaternary">on your license</p>
            </div>
            {/* THE ENGINE */}
            <div className="px-6 py-7 bg-bg-elevated/30 border-b md:border-b-0 md:border-r border-border-primary/50">
              <p className="text-[10px] font-mono tracking-[0.2em] text-text-secondary mb-4">THE ENGINE</p>
              <div className="space-y-3">
                {[["compute", "spread z  -1.27"], ["validate", "deflated SR 0.91 · pbo 0.18"], ["risk-gate", "VaR 2.1% · pass"]].map(([k, v]) => (
                  <div key={k} className="flex items-center gap-3">
                    <span className="w-1 h-1 rounded-full bg-accent/70 shrink-0" />
                    <span className="text-[11px] text-text-tertiary w-16 shrink-0">{k}</span>
                    <span className="font-mono text-[11px] text-text-secondary tabular-nums">{v}</span>
                  </div>
                ))}
              </div>
            </div>
            {/* A SIGNAL */}
            <div className="px-6 py-7">
              <p className="text-[10px] font-mono tracking-[0.2em] text-text-primary mb-4">A SIGNAL</p>
              <div className="rounded-sm border border-border-primary bg-bg-primary/50 px-3 py-2.5 space-y-1.5">
                {[["verdict", "edge", "text-signal-green"], ["gate", "pass", "text-signal-green"], ["format", "envelope", "text-text-secondary"]].map(([k, v, c]) => (
                  <div key={k} className="flex items-center justify-between text-[11px] font-mono">
                    <span className="text-text-quaternary">{k}</span>
                    <span className={c}>{v}</span>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-[10px] text-text-quaternary">cited · risk-gated · algo-ready</p>
            </div>
          </div>
          <div className="px-5 py-2.5 border-t border-border-primary/60 bg-bg-elevated/30 flex flex-wrap items-center gap-x-5 gap-y-1 text-[10px] font-mono tracking-[0.14em] text-text-quaternary">
            <span><span className="text-text-secondary">deterministic</span> · version-pinned</span>
            <span><span className="text-text-secondary">deflated</span> · adjusted for trials</span>
            <span><span className="text-text-secondary">traceable</span> · figure to formula</span>
            <span className="ml-auto text-text-tertiary">nothing retained</span>
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// HOW IT WORKS — clearer hierarchy, one vertical spine.
// ────────────────────────────────────────────────────────────────────────
function HowItWorks() {
  return (
    <section id="how-it-works" className="border-b border-border-primary/60 bg-bg-surface/20">
      <div className="max-w-[1280px] mx-auto px-6 py-24">
        <div className="text-center mb-16 max-w-2xl mx-auto">
          <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
            <span className="text-text-tertiary">///</span> HOW IT WORKS
          </p>
          <h2 className="font-display text-[30px] sm:text-[40px] font-semibold tracking-[-0.01em] leading-[1.08] mb-5">
            One engine. Two planes. One signal.
          </h2>
          <p className="text-[15px] text-text-tertiary max-w-lg mx-auto leading-relaxed">
            Your data goes into one core engine. An execution bot reads the
            deterministic plane. A human reads the agent plane. Both return the
            same versioned envelope, and the language model never computes a
            number your algo trades on.
          </p>
        </div>

        <div className="max-w-[940px] mx-auto">
          <PipeNode badge="YOUR DATA" text="Prices, fundamentals, filings, supplied in the call, on your license." tone="muted" />
          <PipeArrow />
          <div className="rounded-sm border border-border-primary bg-bg-surface px-6 py-5 text-center">
            <p className="text-[11px] font-mono tracking-[0.22em] text-text-secondary mb-1">ONE CORE ENGINE</p>
            <p className="text-[12px] text-text-tertiary">deterministic quant core + agent desk, nothing stored</p>
          </div>
          <PipeArrow split />
          <div className="grid md:grid-cols-2 gap-5">
            <PlaneCard tag="DETERMINISTIC PLANE" dot="bg-text-quaternary" title="The algo's path"
              body="Pure math, version-pinned, sub-second. POST your data, get the envelope synchronously. No language model in the path."
              chips={["SYNC REST / MCP", "exact", "golden-tested"]} />
            <PlaneCard tag="PROBABILISTIC PLANE" dot="bg-text-tertiary" title="The human's path"
              body="A desk of agents reasons over the same math, narrates a thesis, and signs off. Submit a job, stream it, read the memo."
              chips={["ASYNC JOB · SSE", "reasons", "cited"]} />
          </div>
          <PipeArrow merge />
          <PipeNode badge="SIGNAL ENVELOPE" text="One versioned shape from both planes: instruments, levels, overfitting verdict, risk gate, provenance." tone="primary" />
        </div>
      </div>
    </section>
  );
}

function PipeNode({ badge, text, tone }: { badge: string; text: string; tone: "muted" | "primary" }) {
  return (
    <div className={`rounded-sm border px-6 py-4 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 ${tone === "primary" ? "border-border-primary bg-bg-elevated/50" : "border-border-primary/70 bg-bg-surface/40"}`}>
      <span className={`text-[10px] font-mono tracking-[0.18em] shrink-0 ${tone === "primary" ? "text-text-primary" : "text-text-quaternary"}`}>{badge}</span>
      <span className="text-[12px] text-text-tertiary leading-relaxed">{text}</span>
    </div>
  );
}
function PipeArrow({ split, merge }: { split?: boolean; merge?: boolean }) {
  return (
    <div className="flex items-center justify-center py-3 text-text-quaternary">
      <span className="font-mono text-[12px]">{split ? "↓   ↓" : merge ? "↘   ↙" : "↓"}</span>
    </div>
  );
}
function PlaneCard({ tag, dot, title, body, chips }: { tag: string; dot: string; title: string; body: string; chips: string[] }) {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface px-6 py-6">
      <div className="flex items-center gap-2.5 mb-3">
        <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
        <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary">{tag}</p>
      </div>
      <h3 className="text-[16px] font-semibold text-text-primary mb-2">{title}</h3>
      <p className="text-[13px] text-text-tertiary leading-relaxed mb-4">{body}</p>
      <div className="flex flex-wrap gap-1.5">
        {chips.map((c) => (
          <span key={c} className="text-[9px] font-mono tracking-[0.12em] text-text-tertiary border border-border-primary/70 rounded-sm px-2 py-0.5">{c}</span>
        ))}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// PRODUCT SHOWCASE
// ────────────────────────────────────────────────────────────────────────
function ProductShowcase() {
  return (
    <section id="product" className="border-b border-border-primary/60">
      <div className="max-w-[1280px] mx-auto px-6 py-24">
        <div className="text-center mb-20 max-w-2xl mx-auto">
          <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
            <span className="text-text-tertiary">///</span> THE ENGINE
          </p>
          <h2 className="font-display text-[30px] sm:text-[38px] font-semibold tracking-[-0.01em] leading-[1.1] mb-5">
            The math, exposed as tools.
          </h2>
          <p className="text-[15px] text-text-tertiary max-w-lg mx-auto leading-relaxed">
            Call the computation directly from your bot, or let the desk of agents
            run it for you. Either way the data is yours, the math is pinned, and
            the result is a signal your algo can consume.
          </p>
        </div>
        <div className="max-w-[1040px] mx-auto space-y-6">
          <ShowcaseCard tag="01 / PAIRS" title="Cointegrated pairs from your prices."
            sub="Pass in a set of price series. Get back the cointegrated pairs with test statistic and p-value, the half-life of mean reversion, the hedge ratio, and the live spread z-score. Engle-Granger done right, on your data."
            visual={<DiscoveryViz />} />
          <ShowcaseCard tag="02 / RIGOR" title="Know when it&apos;s edge, and when it&apos;s noise."
            sub="Every backtest reports a deflated Sharpe, corrected for how many ideas were tried and for non-normal returns, plus probability of backtest overfitting and purged, embargoed cross-validation. We tell you when a result is probably noise."
            visual={<TrackRecordViz />} />
          <ShowcaseCard tag="03 / RISK" title="Risk and stress on your book."
            sub="VaR and CVaR (parametric, historical, Cornish-Fisher, bootstrapped), Ledoit-Wolf covariance, factor decomposition, and macro-shock stress, computed on the positions and returns you supply. No black box, every figure traceable."
            visual={<RiskViz />} />
          <ShowcaseCard tag="04 / AGENTS" title="A desk of agents over the same engine."
            sub="Research, risk, and portfolio agents with a CIO that signs off run the same math and turn it into a sourced, risk-checked memo. The desk runs on Claude: Opus 4.8 for the reasoning, lighter models for the grunt work."
            visual={<ThreadViz />} />
          <ShowcaseCard tag="05 / OUTPUT" title="Signals your algo can consume."
            sub="Both planes emit one versioned SignalEnvelope: instruments and sides, entry, stop and target, sizing, the overfitting verdict, the risk gate, and provenance on every figure. Pin the schema, read it over MCP or REST, route it into execution."
            visual={<EnvelopeViz />} />
        </div>
      </div>
    </section>
  );
}

function ShowcaseCard({ tag, title, sub, visual }: { tag: string; title: string; sub: string; visual: React.ReactNode }) {
  return (
    <article className="group relative rounded-sm border border-border-primary bg-bg-surface overflow-hidden hover:border-zinc-700 transition-colors">
      <div className="grid lg:grid-cols-[1.05fr_1fr] gap-10 p-8 lg:p-12 relative items-center">
        <div className="max-w-md">
          <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-5">{tag}</p>
          <h3 className="text-[24px] font-semibold tracking-tight text-text-primary mb-3 leading-tight">{title}</h3>
          <p className="text-[14px] text-text-tertiary leading-relaxed">{sub}</p>
        </div>
        <div className="w-full">{visual}</div>
      </div>
    </article>
  );
}

function DiscoveryViz() {
  const rows = [
    { ticker: "RXRX", reason: "Insider cluster", score: 92, color: "signal-green" },
    { ticker: "TLN", reason: "Fund initiation", score: 81, color: "accent" },
    { ticker: "VKTX", reason: "Post-earnings drift", score: 76, color: "signal-green" },
    { ticker: "FIVE", reason: "52w low + insider buy", score: 64, color: "accent" },
  ];
  return (
    <div className="rounded-sm border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>SCREEN OUTPUT</span><span className="text-text-tertiary">● LIVE</span>
      </div>
      <div className="divide-y divide-border-primary/40">
        {rows.map((r) => (
          <div key={r.ticker} className="flex items-center gap-3 px-3 py-2.5 text-[11px]">
            <span className="font-mono font-semibold text-text-primary w-14">{r.ticker}</span>
            <span className="text-text-tertiary flex-1 truncate">{r.reason}</span>
            <span className="font-mono text-text-secondary tabular-nums w-7 text-right">{r.score}</span>
            <span className={`w-1 h-4 rounded-sm bg-${r.color}/80`} />
          </div>
        ))}
      </div>
    </div>
  );
}
function TrackRecordViz() {
  const points = [50, 47, 51, 48, 52, 49, 54, 51, 56, 58, 55, 60, 64, 62, 68, 71];
  const d = points.map((y, i) => `${i === 0 ? "M" : "L"} ${i * 18} ${72 - y * 0.6}`).join(" ");
  return (
    <div className="rounded-sm border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>SIGNAL IC · TRAILING 90D</span><span className="text-text-tertiary">+0.08</span>
      </div>
      <div className="p-3">
        <svg viewBox="0 0 280 80" className="w-full h-20 overflow-visible">
          <defs><linearGradient id="ic-fill" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stopColor="#a1a1aa" stopOpacity="0.25" /><stop offset="100%" stopColor="#a1a1aa" stopOpacity="0" /></linearGradient></defs>
          <path d={`${d} L ${(points.length - 1) * 18} 80 L 0 80 Z`} fill="url(#ic-fill)" />
          <path d={d} fill="none" stroke="#a1a1aa" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="sparkline-path" />
          <line x1="0" y1="48" x2="280" y2="48" stroke="rgba(250,250,250,0.06)" strokeDasharray="2 3" />
        </svg>
        <div className="mt-2 grid grid-cols-3 gap-2 text-[10px] font-mono text-text-tertiary">
          <span>DEF. SHARPE <span className="text-text-secondary ml-1">0.62</span></span>
          <span>PBO <span className="text-text-secondary ml-1">18%</span></span>
          <span>BRIER <span className="text-text-secondary ml-1">0.21</span></span>
        </div>
      </div>
    </div>
  );
}
function RiskViz() {
  const gates = [
    { label: "Position", ok: true, val: "5.0% ≤ 5.0%" },
    { label: "Sector", ok: false, val: "32% > 30%" },
    { label: "Marg VaR", ok: false, val: "3.4% > 3.0%" },
    { label: "Liquidity", ok: true, val: "2.1% < 10%" },
  ];
  return (
    <div className="rounded-sm border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider">
        <span className="text-text-quaternary">PRE-TRADE GATE</span><span className="text-text-tertiary">BLOCKED</span>
      </div>
      <div className="divide-y divide-border-primary/40">
        {gates.map((g) => (
          <div key={g.label} className="flex items-center justify-between px-3 py-2 text-[11px] font-mono">
            <span className="text-text-tertiary">{g.label}</span>
            <span className="text-text-tertiary">{g.ok ? "✓" : "✗"} {g.val}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
function ThreadViz() {
  const items = [
    { tag: "FRESH", text: "Best L/S in regional banks?" },
    { tag: "DRILLDOWN", text: "Capital position on MTB?" },
    { tag: "RISK CHECK", text: "Stress at +100bp on the 10Y" },
    { tag: "VALIDATION", text: "Challenge the FITB bull case" },
  ];
  return (
    <div className="rounded-sm border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>THREAD · 4 MESSAGES</span><span className="text-text-tertiary">● ACTIVE</span>
      </div>
      <div className="divide-y divide-border-primary/40">
        {items.map((m, i) => (
          <div key={i} className="flex items-center gap-3 px-3 py-2 text-[11px]">
            <span className="font-mono text-text-quaternary w-4">{i + 1}</span>
            <span className="font-mono text-[9px] tracking-wider w-20 text-text-tertiary">{m.tag}</span>
            <span className="text-text-secondary truncate flex-1">{m.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
function EnvelopeViz() {
  const fields = [
    { k: "instruments", v: "ASLE · long", tone: "text-text-secondary" },
    { k: "levels", v: "12.40 / 10.90 / 17.20", tone: "text-text-secondary" },
    { k: "validation.verdict", v: "edge", tone: "text-signal-green" },
    { k: "risk.gate", v: "pass", tone: "text-signal-green" },
    { k: "provenance", v: "3 receipts", tone: "text-text-tertiary" },
  ];
  return (
    <div className="rounded-sm border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>SIGNAL ENVELOPE · v1</span><span className="text-text-tertiary">MCP · REST</span>
      </div>
      <div className="divide-y divide-border-primary/40">
        {fields.map((f) => (
          <div key={f.k} className="flex items-center justify-between px-3 py-2 text-[11px] font-mono">
            <span className="text-text-quaternary">{f.k}</span>
            <span className={`${f.tone} tabular-nums`}>{f.v}</span>
          </div>
        ))}
      </div>
      <div className="px-3 py-2 border-t border-border-primary/60 flex items-center gap-2 bg-bg-elevated/40 text-[9px] font-mono tracking-[0.14em] text-text-quaternary">
        <span>schema_version 1.0.0</span><span className="ml-auto">engine_version pinned</span>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// PIPELINE — why your algo can trust it (recomposed, numbered spine).
// ────────────────────────────────────────────────────────────────────────
function Pipeline() {
  const steps = [
    { n: "01", k: "COMPUTE", d: "The deterministic engine runs the math and binds every figure to a source." },
    { n: "02", k: "NARRATE", d: "The language model only arranges pre-computed facts. It never originates a number your algo consumes." },
    { n: "03", k: "VALIDATE", d: "A validator rejects any claim it cannot trace back to a receipt, and any edge it has not checked for overfitting." },
  ];
  return (
    <section id="intelligence" className="relative border-b border-border-primary/60 overflow-hidden">
      <div className="max-w-[1280px] mx-auto px-6 py-24 relative">
        <div className="text-center mb-16 max-w-2xl mx-auto">
          <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
            <span className="text-text-tertiary">///</span> WHY YOUR ALGO CAN TRUST IT
          </p>
          <h2 className="font-display text-[28px] sm:text-[38px] font-semibold tracking-[-0.01em] leading-[1.1] mb-5">
            The model never touches the number your algo trades on.
          </h2>
          <p className="text-[15px] text-text-tertiary max-w-lg mx-auto leading-relaxed">
            The deterministic plane computes every figure and binds it to a source.
            The agent plane only arranges those facts into a thesis. Agents propose,
            math disposes, you decide.
          </p>
        </div>

        <div className="max-w-[820px] mx-auto">
          {steps.map((s, i) => (
            <div key={s.n} className="relative pl-14 pb-8 last:pb-0">
              {i < steps.length - 1 && <span className="absolute left-[18px] top-9 bottom-0 w-px bg-border-primary/60" aria-hidden="true" />}
              <span className="absolute left-0 top-0 w-9 h-9 rounded-sm border border-border-primary bg-bg-surface flex items-center justify-center font-mono text-[12px] text-text-secondary">{s.n}</span>
              <p className="text-[11px] font-mono tracking-[0.22em] text-text-secondary mb-1.5 pt-1.5">{s.k}</p>
              <p className="text-[14px] text-text-tertiary leading-relaxed">{s.d}</p>
            </div>
          ))}
          <div className="mt-2 ml-14 inline-flex items-center gap-3 rounded-sm border border-border-primary bg-bg-elevated/40 px-4 py-2.5">
            <span className="font-mono text-[11px] tracking-[0.18em] text-text-primary">✓ VERIFIED</span>
            <span className="font-mono text-[10px] tracking-[0.18em] text-text-quaternary">claim · source · math</span>
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// SOURCE LEDGER — rigor + provenance.
// ────────────────────────────────────────────────────────────────────────
function SourceLedger() {
  const sources = [
    { kind: "FILING", id: "0001067983-25-000412", note: "Insider transaction" },
    { kind: "MACRO", id: "10Y · 4.42%", note: "Treasury yield, intraday" },
    { kind: "FUND HOLDING", id: "CIK · 0001336528", note: "Position initiation" },
    { kind: "QUOTE", id: "COHR · 87.21", note: "Live market price" },
    { kind: "EARNINGS", id: "VKTX · 4Q surprise", note: "Beat consensus +38%" },
  ];
  return (
    <section id="trust" className="relative border-b border-border-primary/60 bg-bg-surface/30">
      <div className="max-w-[1280px] mx-auto px-6 py-24">
        <div className="text-center mb-20 max-w-2xl mx-auto">
          <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
            <span className="text-text-tertiary">///</span> SOURCE LEDGER
          </p>
          <h2 className="font-display text-[30px] sm:text-[38px] font-semibold tracking-[-0.01em] leading-[1.1] mb-5">
            It refuses to ship what it can&apos;t stand behind.
          </h2>
          <p className="text-[15px] text-text-tertiary max-w-lg mx-auto leading-relaxed">
            Every number binds to a receipt: the named formula that produced it and
            the data you supplied. The validator won&apos;t ship a figure it can&apos;t
            trace, and it won&apos;t stamp an idea <span className="text-text-secondary">edge</span> it
            hasn&apos;t checked for overfitting. Provenance and rigor, both by default.
            Your audit trail, computed and handed back. We keep none of it.
          </p>
        </div>
        <div className="max-w-[760px] mx-auto rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-border-primary flex items-center justify-between">
            <span className="text-[10px] font-mono tracking-wider text-text-tertiary">SOURCE LEDGER</span>
            <span className="text-[10px] font-mono text-text-quaternary">22 ENTRIES</span>
          </div>
          <div className="divide-y divide-border-primary/60">
            {sources.map((s) => (
              <div key={s.id} className="grid grid-cols-[110px_1fr_auto] items-center gap-4 px-4 py-3 hover:bg-bg-elevated/40 transition-colors">
                <span className="text-[10px] font-mono tracking-wider text-text-tertiary bg-accent/10 border border-accent/20 px-2 py-0.5 rounded text-center">{s.kind}</span>
                <span className="text-[12px] font-mono text-text-secondary truncate">{s.id}</span>
                <span className="text-[10px] text-text-quaternary truncate hidden md:block">{s.note}</span>
              </div>
            ))}
          </div>
          <div className="px-4 py-2.5 border-t border-border-primary flex items-center justify-between text-[10px] font-mono text-text-quaternary">
            <span>+ 17 MORE</span><span className="text-text-tertiary">● ALL VERIFIED</span>
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// CLOSING CTA + model-agnostic note.
// ────────────────────────────────────────────────────────────────────────
function ClosingCTA({ isSignedIn }: { isSignedIn: boolean }) {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 grid-bg opacity-[0.08]" aria-hidden="true" />
      <div className="max-w-[920px] mx-auto px-6 py-24 text-center relative">
        <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-6">
          <span className="text-text-tertiary">///</span> POINT IT AT YOUR DATA
        </p>
        <h2 className="font-display text-[34px] sm:text-[46px] font-semibold tracking-[-0.01em] leading-[1.08] mb-7">
          Your data in.
          <br />
          A validated signal out.
        </h2>
        <p className="text-[15px] text-text-tertiary max-w-md mx-auto mb-10 leading-relaxed">
          Open the Demo Desk on sample data, or connect the Portal and wire the
          engine into your own bot over REST or your agent over MCP. Your data
          stays yours. We run the math and hand it back.
        </p>
        <div className="flex items-center justify-center gap-4 flex-wrap mb-10">
          <Link href="/dashboard" className="inline-block px-6 py-3 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors">
            Demo Desk
          </Link>
          <Link href={isSignedIn ? "/portal" : PORTAL_SIGNUP} className="inline-block px-6 py-3 rounded-sm border border-border-primary text-text-secondary text-[13px] font-semibold hover:text-text-primary hover:border-zinc-700 transition-colors">
            Portal
          </Link>
        </div>
        <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary leading-relaxed max-w-lg mx-auto">
          MODEL-AGNOSTIC INTERFACE. CALL IT FROM ANY AGENT OR BOT OVER MCP OR REST.
          OUR DESK RUNS ON CLAUDE.
        </p>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// FOOTER — adds Terms / Privacy.
// ────────────────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer className="border-t border-border-primary/60 mt-auto">
      <div className="max-w-[1280px] mx-auto px-6 py-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-[11px] font-mono tracking-wider text-text-quaternary">
        <div className="flex items-center gap-5">
          <span className="font-semibold text-text-secondary">alpha<span className="text-brand">engine</span></span>
          <span>© {new Date().getFullYear()}</span>
        </div>
        <div className="flex items-center gap-5 flex-wrap">
          <Link href="/docs" className="hover:text-text-secondary transition-colors">DOCS</Link>
          <Link href="/plans" className="hover:text-text-secondary transition-colors">PLANS</Link>
          <Link href="/terms" className="hover:text-text-secondary transition-colors">TERMS</Link>
          <Link href="/privacy" className="hover:text-text-secondary transition-colors">PRIVACY</Link>
          <Link href="/sign-in" className="hover:text-text-secondary transition-colors">SIGN IN</Link>
        </div>
      </div>
    </footer>
  );
}
