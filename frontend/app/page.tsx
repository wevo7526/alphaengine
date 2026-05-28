"use client";

import Link from "next/link";
import { useUser } from "@clerk/nextjs";

export default function LandingPage() {
  const { isSignedIn } = useUser();

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary flex flex-col relative overflow-hidden">
      {/* Ambient gradient orbs — subtle, dark-mode-friendly */}
      <div className="pointer-events-none absolute inset-0 z-0" aria-hidden="true">
        <div className="absolute -top-32 -left-32 w-[36rem] h-[36rem] rounded-full bg-accent/[0.06] blur-3xl" />
        <div className="absolute top-1/3 -right-40 w-[40rem] h-[40rem] rounded-full bg-signal-green/[0.04] blur-3xl" />
      </div>

      {/* Top nav */}
      <header className="border-b border-border-primary/60 bg-bg-primary/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <Link href="/" className="text-[15px] font-semibold tracking-tight">
            alpha<span className="text-accent">engine</span>
          </Link>
          <nav className="hidden md:flex items-center gap-7 text-[13px] text-text-tertiary">
            <a href="#how" className="hover:text-text-primary transition-colors">How it works</a>
            <a href="#product" className="hover:text-text-primary transition-colors">Product</a>
            <a href="#trust" className="hover:text-text-primary transition-colors">Trust</a>
          </nav>
          <div className="flex items-center gap-2">
            {isSignedIn ? (
              <Link
                href="/dashboard"
                className="px-3 py-1.5 rounded-lg bg-white text-bg-primary text-[12px] font-medium hover:bg-zinc-200 transition-colors"
              >
                Go to dashboard
              </Link>
            ) : (
              <>
                <Link
                  href="/sign-in"
                  className="text-[13px] text-text-secondary hover:text-text-primary transition-colors px-3 py-1.5"
                >
                  Sign in
                </Link>
                <Link
                  href="/sign-up"
                  className="px-3 py-1.5 rounded-lg bg-white text-bg-primary text-[12px] font-medium hover:bg-zinc-200 transition-colors"
                >
                  Request access
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      {/* HERO — text left, product mockup right */}
      <section className="relative z-10 max-w-6xl mx-auto px-6 pt-16 pb-20 md:pt-24 md:pb-28 w-full">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          {/* Copy */}
          <div>
            <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-5">
              For L/S equity & macro PMs
            </p>
            <h1 className="text-4xl md:text-5xl lg:text-[58px] font-semibold tracking-tight leading-[1.04] mb-6">
              The AI research desk
              <br />
              for hedge funds.
            </h1>
            <p className="text-[16px] md:text-[17px] text-text-secondary leading-relaxed mb-9 max-w-lg">
              Bring research, risk, and discovery together in one workflow. Get
              a 10-name trade slate with cointegrated pairs, factor decomposition,
              and full source lineage in under 10 minutes.
            </p>
            <div className="flex items-center gap-3 flex-wrap">
              {isSignedIn ? (
                <Link
                  href="/dashboard"
                  className="px-5 py-2.5 rounded-xl bg-white text-bg-primary text-[14px] font-medium hover:bg-zinc-200 transition-colors"
                >
                  Go to dashboard
                </Link>
              ) : (
                <>
                  <Link
                    href="/sign-up"
                    className="px-5 py-2.5 rounded-xl bg-white text-bg-primary text-[14px] font-medium hover:bg-zinc-200 transition-colors"
                  >
                    Request access
                  </Link>
                  <Link
                    href="/sign-in"
                    className="px-5 py-2.5 rounded-xl border border-border-primary text-text-secondary hover:text-text-primary hover:border-zinc-600 text-[14px] font-medium transition-colors"
                  >
                    Sign in
                  </Link>
                </>
              )}
              <div className="flex items-center gap-2 text-[11px] text-text-quaternary ml-2">
                <span className="w-1.5 h-1.5 rounded-full bg-signal-green animate-pulse" />
                Live agents in production
              </div>
            </div>
          </div>

          {/* Product mockup — a memo preview */}
          <HeroMemoMock />
        </div>
      </section>

      {/* HOW IT WORKS — agent pipeline visual */}
      <section id="how" className="relative z-10 border-y border-border-primary/60 bg-bg-surface/40">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-24">
          <div className="max-w-2xl mb-12">
            <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-4">
              How it works
            </p>
            <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight">
              Five agents work together. You get a memo in minutes.
            </h2>
            <p className="text-[15px] text-text-tertiary leading-relaxed mt-4 max-w-xl">
              Each agent is purpose-built for one part of the workflow. Risk is
              woven into the pipeline, so every idea clears its gate before it
              reaches you.
            </p>
          </div>

          <PipelineDiagram />
        </div>
      </section>

      {/* MATH + AGENTS HARMONY */}
      <section id="harmony" className="relative z-10 max-w-6xl mx-auto px-6 py-24 md:py-28 w-full">
        <div className="max-w-2xl mb-12">
          <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-4">
            Math meets agents
          </p>
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight">
            Probabilistic reasoning, grounded in deterministic math.
          </h2>
          <p className="text-[15px] text-text-tertiary leading-relaxed mt-4 max-w-xl">
            Agents are great at reading filings, framing theses, and weighing
            context. Math is great at cointegration, regression, and risk gates.
            Alpha Engine pairs the two, so every reasoning step is backed by a
            number you can defend.
          </p>
        </div>

        <HarmonyDiagram />
      </section>

      {/* PRODUCT SURFACES — four visual cards */}
      <section id="product" className="relative z-10 max-w-6xl mx-auto px-6 py-24 md:py-28 w-full">
        <div className="max-w-2xl mb-14">
          <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-4">
            The product
          </p>
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight">
            What you actually use it for.
          </h2>
        </div>

        <div className="grid md:grid-cols-2 gap-5">
          <ProductCard
            tag="01 Discovery"
            title="Surface names beyond the obvious."
            body="Five live screens highlight insider clusters, smart-money 13F initiations, post-earnings drift, 52-week-low setups with insider buying, and picks-and-shovels for the themes you care about. Each candidate arrives with structured evidence ready to cite."
            visual={<DiscoveryMock />}
          />
          <ProductCard
            tag="02 Track Record"
            title="See exactly how your calls perform."
            body="Every signal you generate is scored at 1d / 5d / 20d against realized prices. Watch your Information Coefficient by conviction bucket, your alpha decay curve, and your hit rate over time. Your track record stays visible to you, always."
            visual={<TrackRecordMock />}
          />
          <ProductCard
            tag="03 Risk + Stress"
            title="Risk controls built into every trade."
            body="Position cap, sector cap, marginal VaR, drawdown circuit breaker, liquidity guard. Each limit is enforced before a trade clears, so the slate you receive is already pressure-tested. Dial in macro shocks and watch projected P&L per position update in real time."
            visual={<RiskMock />}
          />
          <ProductCard
            tag="04 Follow-up Threads"
            title="Keep researching, without starting over."
            body="One click continues your research thread. Follow-ups inherit prior tickers, themes, and the last decision, so you can drill in, validate, or stress test with a sentence. The Interpreter classifies your follow-up and routes accordingly."
            visual={<ThreadsMock />}
          />
        </div>
      </section>

      {/* TRUST */}
      <section id="trust" className="relative z-10 border-y border-border-primary/60 bg-bg-surface/40">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-24">
          <div className="grid md:grid-cols-3 gap-10 items-start">
            <div className="md:col-span-1">
              <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-4">
                Why a PM can trust it
              </p>
              <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight mb-4">
                Every claim, fully traceable.
              </h2>
              <p className="text-[14px] text-text-tertiary leading-relaxed">
                Each memo carries a complete lineage of every SEC accession,
                FRED series, fund CIK, and market quote that shaped it. Open
                any source, verify any number, any time.
              </p>
            </div>
            <div className="md:col-span-2">
              <LineageMock />
            </div>
          </div>
        </div>
      </section>

      {/* Closing CTA */}
      <section className="relative z-10">
        <div className="max-w-6xl mx-auto px-6 py-24 md:py-28 text-center">
          <h2 className="text-3xl md:text-4xl font-semibold tracking-tight leading-tight mb-5">
            Ready to build your next memo?
          </h2>
          <p className="text-[15px] text-text-tertiary max-w-xl mx-auto mb-8 leading-relaxed">
            Sign up takes a minute. Your first memo runs in under ten.
          </p>
          <div className="flex items-center justify-center gap-3 flex-wrap">
            {isSignedIn ? (
              <Link
                href="/dashboard"
                className="px-5 py-2.5 rounded-xl bg-white text-bg-primary text-[14px] font-medium hover:bg-zinc-200 transition-colors"
              >
                Go to dashboard
              </Link>
            ) : (
              <>
                <Link
                  href="/sign-up"
                  className="px-5 py-2.5 rounded-xl bg-white text-bg-primary text-[14px] font-medium hover:bg-zinc-200 transition-colors"
                >
                  Request access
                </Link>
                <Link
                  href="/sign-in"
                  className="px-5 py-2.5 rounded-xl border border-border-primary text-text-secondary hover:text-text-primary hover:border-zinc-600 text-[14px] font-medium transition-colors"
                >
                  Sign in
                </Link>
              </>
            )}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-border-primary/60">
        <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-[12px] text-text-quaternary">
          <div className="flex items-center gap-4">
            <span className="font-semibold text-text-secondary">
              alpha<span className="text-accent">engine</span>
            </span>
            <span>© {new Date().getFullYear()}</span>
          </div>
          <div className="flex items-center gap-5">
            <a href="#how" className="hover:text-text-secondary transition-colors">How it works</a>
            <a href="#product" className="hover:text-text-secondary transition-colors">Product</a>
            <a href="#trust" className="hover:text-text-secondary transition-colors">Trust</a>
            <Link href="/sign-in" className="hover:text-text-secondary transition-colors">Sign in</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Visual mocks — each renders a small product preview for the landing
// ─────────────────────────────────────────────────────────────────────

function HeroMemoMock() {
  return (
    <div className="relative">
      {/* Floating glow behind the card */}
      <div className="absolute -inset-4 bg-gradient-to-br from-accent/10 via-transparent to-signal-green/10 rounded-3xl blur-2xl" />
      <div className="relative rounded-2xl border border-border-primary bg-bg-surface shadow-2xl shadow-black/40 overflow-hidden">
        {/* Mock browser/window chrome */}
        <div className="flex items-center gap-1.5 px-4 py-2.5 border-b border-border-primary bg-bg-primary/40">
          <span className="w-2.5 h-2.5 rounded-full bg-signal-red/60" />
          <span className="w-2.5 h-2.5 rounded-full bg-signal-yellow/60" />
          <span className="w-2.5 h-2.5 rounded-full bg-signal-green/60" />
          <span className="ml-3 text-[11px] font-mono text-text-quaternary">
            alpha-engine · Intelligence Memo
          </span>
        </div>

        <div className="p-5">
          {/* Decision badge + title */}
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-text-quaternary mb-1">
                Industrials L/S
              </p>
              <h3 className="text-[15px] font-semibold text-text-primary leading-snug">
                Power-grid build-out is mispriced
              </h3>
            </div>
            <div className="shrink-0 inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-signal-green/40 bg-signal-green/10">
              <span className="w-1.5 h-1.5 rounded-full bg-signal-green" />
              <span className="text-[10px] font-medium text-signal-green tracking-wide">GO · 82</span>
            </div>
          </div>

          <p className="text-[12px] text-text-tertiary leading-relaxed mb-4">
            Hyperscaler PPAs + transmission backlog favor electrical / cooling
            names over consensus semis. 10 ideas, ≥30% small-cap, two pairs
            cointegrated at p&lt;0.02.
          </p>

          {/* Trade idea rows */}
          <div className="space-y-1.5">
            {[
              { ticker: "VRT", dir: "LONG", conv: 84, tag: "small_cap", color: "signal-green" },
              { ticker: "ETN", dir: "LONG", conv: 78, tag: "quality", color: "signal-green" },
              { ticker: "COHR", dir: "LONG", conv: 73, tag: "special", color: "signal-green" },
              { ticker: "VST/CEG", dir: "PAIR", conv: 71, tag: "cointegrated", color: "accent" },
              { ticker: "GE", dir: "SHORT", conv: 62, tag: "hedge", color: "signal-red" },
            ].map((idea) => (
              <div
                key={idea.ticker}
                className="flex items-center justify-between text-[11px] py-1.5 px-2 rounded-md bg-bg-primary/40 border border-border-primary/40"
              >
                <div className="flex items-center gap-2.5 flex-1 min-w-0">
                  <span className="font-mono font-semibold text-text-primary w-16">
                    {idea.ticker}
                  </span>
                  <span
                    className={`text-[9px] font-semibold px-1.5 py-0.5 rounded ${
                      idea.dir === "LONG"
                        ? "bg-signal-green/15 text-signal-green"
                        : idea.dir === "SHORT"
                        ? "bg-signal-red/15 text-signal-red"
                        : "bg-accent/15 text-accent"
                    }`}
                  >
                    {idea.dir}
                  </span>
                  <span className="text-[10px] text-text-quaternary truncate">{idea.tag}</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <div className="w-16 h-1 rounded-full bg-bg-elevated overflow-hidden">
                    <div
                      className={`h-full bg-${idea.color} rounded-full`}
                      style={{ width: `${idea.conv}%` }}
                    />
                  </div>
                  <span className="font-mono text-text-secondary w-6 text-right">
                    {idea.conv}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Footer line */}
          <div className="mt-4 pt-3 border-t border-border-primary/60 flex items-center justify-between text-[10px] text-text-quaternary">
            <div className="flex items-center gap-3">
              <span>22 tool calls · 14 sources cited</span>
            </div>
            <span className="font-mono">9m 42s</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function PipelineDiagram() {
  const nodes = [
    { label: "Query", sub: "Freeform PM question" },
    { label: "Interpreter", sub: "Parse · classify · plan" },
    { label: "Research", sub: "29 tools · live data" },
    { label: "Risk", sub: "Regime · correlation · gates" },
    { label: "Strategist", sub: "10 ideas · pairs · hedges" },
    { label: "CIO", sub: "Memo · decision · receipts" },
  ];
  return (
    <div className="relative">
      {/* Desktop horizontal flow */}
      <div className="hidden md:grid grid-cols-6 gap-2 items-stretch">
        {nodes.map((n, i) => {
          const isFirst = i === 0;
          const isLast = i === nodes.length - 1;
          return (
            <div key={n.label} className="relative">
              <div
                className={`h-full rounded-xl border p-4 ${
                  isFirst
                    ? "border-border-primary/60 bg-bg-primary/40"
                    : isLast
                    ? "border-accent/40 bg-accent/[0.08]"
                    : "border-border-primary bg-bg-surface"
                }`}
              >
                <p className="text-[9px] font-mono text-text-quaternary mb-1">
                  {String(i).padStart(2, "0")}
                </p>
                <p
                  className={`text-[13px] font-semibold mb-1 ${
                    isLast ? "text-accent" : "text-text-primary"
                  }`}
                >
                  {n.label}
                </p>
                <p className="text-[10px] text-text-quaternary leading-snug">{n.sub}</p>
              </div>
              {!isLast && (
                <div className="absolute top-1/2 -right-1 -translate-y-1/2 z-10 pointer-events-none">
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path
                      d="M2 5h6m0 0L5 2m3 3L5 8"
                      stroke="currentColor"
                      strokeWidth="1.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="text-text-quaternary"
                    />
                  </svg>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Mobile vertical flow */}
      <div className="md:hidden space-y-2">
        {nodes.map((n, i) => {
          const isLast = i === nodes.length - 1;
          return (
            <div
              key={n.label}
              className={`rounded-xl border p-3 flex items-center gap-3 ${
                isLast ? "border-accent/40 bg-accent/[0.08]" : "border-border-primary bg-bg-surface"
              }`}
            >
              <span className="text-[10px] font-mono text-text-quaternary w-6">
                {String(i).padStart(2, "0")}
              </span>
              <div className="flex-1">
                <p className={`text-[13px] font-semibold ${isLast ? "text-accent" : "text-text-primary"}`}>
                  {n.label}
                </p>
                <p className="text-[10px] text-text-quaternary">{n.sub}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Beneath flow: micro-pills showing what each agent calls */}
      <div className="mt-7 flex flex-wrap items-center gap-2 text-[10px] font-mono text-text-quaternary">
        <span className="text-text-tertiary mr-1">Tools wired in:</span>
        {[
          "SEC EDGAR",
          "FRED",
          "13F",
          "Form 4",
          "Insider clusters",
          "Earnings calendar",
          "Black-Litterman",
          "EWMA covariance",
          "Cornish-Fisher VaR",
          "HMM regime",
        ].map((p) => (
          <span
            key={p}
            className="px-2 py-0.5 rounded border border-border-primary/40 bg-bg-elevated/40"
          >
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}

function ProductCard({
  tag,
  title,
  body,
  visual,
}: {
  tag: string;
  title: string;
  body: string;
  visual: React.ReactNode;
}) {
  return (
    <article className="rounded-2xl border border-border-primary bg-bg-surface overflow-hidden flex flex-col">
      <div className="px-6 pt-6 pb-4">
        <p className="text-[10px] font-mono text-text-quaternary tracking-wider mb-3">{tag}</p>
        <h3 className="text-[17px] font-semibold text-text-primary mb-2">{title}</h3>
        <p className="text-[13px] text-text-tertiary leading-relaxed">{body}</p>
      </div>
      <div className="px-6 pb-6 pt-2 mt-auto">
        <div className="rounded-xl border border-border-primary bg-bg-primary/60 p-4">
          {visual}
        </div>
      </div>
    </article>
  );
}

function DiscoveryMock() {
  return (
    <div className="space-y-1.5">
      {[
        { ticker: "RXRX", reason: "4 insider buys · CFO", score: 92, badge: "INSIDER" },
        { ticker: "TLN", reason: "Pershing new init · 2.1%", score: 81, badge: "13F" },
        { ticker: "VKTX", reason: "+38% surprise · 6 analysts", score: 76, badge: "PEAD" },
        { ticker: "FIVE", reason: "2.1% above 52w low + 3 buys", score: 64, badge: "52W-LO" },
      ].map((r) => (
        <div
          key={r.ticker}
          className="flex items-center justify-between text-[11px] py-1.5 px-2 rounded-md bg-bg-surface border border-border-primary/40"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-mono font-semibold text-text-primary w-12">{r.ticker}</span>
            <span className="text-[9px] font-mono text-accent bg-accent/10 px-1.5 py-0.5 rounded border border-accent/20">
              {r.badge}
            </span>
            <span className="text-[10px] text-text-quaternary truncate">{r.reason}</span>
          </div>
          <span className="font-mono text-text-secondary text-[11px]">{r.score}</span>
        </div>
      ))}
    </div>
  );
}

function TrackRecordMock() {
  // Tiny IC-by-conviction bar chart, hand-drawn
  const buckets = [
    { label: "<50", value: 48 },
    { label: "50-74", value: 58 },
    { label: "75+", value: 71 },
  ];
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] text-text-quaternary uppercase tracking-wider">
          Hit rate 5d
        </span>
        <span className="text-[10px] font-mono text-signal-green">IC 0.08</span>
      </div>
      <div className="flex items-end gap-3 h-20">
        {buckets.map((b) => (
          <div key={b.label} className="flex-1 flex flex-col items-center gap-1.5">
            <div className="w-full h-16 flex items-end">
              <div
                className={`w-full rounded-t ${
                  b.value >= 55 ? "bg-signal-green" : "bg-text-quaternary/50"
                }`}
                style={{ height: `${b.value}%` }}
              />
            </div>
            <span className="text-[9px] font-mono text-text-quaternary">{b.label}</span>
            <span className="text-[10px] font-mono text-text-secondary">{b.value}%</span>
          </div>
        ))}
      </div>
      <div className="mt-3 pt-3 border-t border-border-primary/60 flex items-center justify-between text-[10px]">
        <span className="text-text-quaternary">142 signals scored</span>
        <span className="font-mono text-signal-green">+ monotonic</span>
      </div>
    </div>
  );
}

function RiskMock() {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-quaternary uppercase tracking-wider">
          Pre-trade gate · MSFT 5%
        </span>
        <span className="inline-flex items-center gap-1.5 text-[10px] text-signal-red bg-signal-red/10 border border-signal-red/30 px-2 py-0.5 rounded">
          <span className="w-1.5 h-1.5 rounded-full bg-signal-red" />
          BLOCKED
        </span>
      </div>
      <div className="space-y-1.5 text-[11px]">
        {[
          { label: "Position cap", val: "✓ 5.0% ≤ 5.0%", ok: true },
          { label: "Sector cap (Tech)", val: "✗ 32% > 30%", ok: false },
          { label: "Marginal VaR", val: "✗ +3.4% > 3.0%", ok: false },
          { label: "Liquidity (ADV)", val: "✓ 2.1% < 10%", ok: true },
        ].map((r) => (
          <div key={r.label} className="flex items-center justify-between">
            <span className="text-text-tertiary">{r.label}</span>
            <span className={`font-mono ${r.ok ? "text-signal-green" : "text-signal-red"}`}>
              {r.val}
            </span>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-text-quaternary leading-snug pt-2 border-t border-border-primary/60">
        Trade rejected by Risk Manager. Auto-adjusted to 3.5% would clear gate.
      </p>
    </div>
  );
}

function ThreadsMock() {
  return (
    <div className="space-y-1.5">
      {[
        { user: "Q", text: "Best L/S in regional banks?", k: "fresh" },
        { user: "Q", text: "Drill into MTB, what is the capital position?", k: "drilldown" },
        { user: "Q", text: "Stress this slate at +100bp 10y", k: "risk_check" },
        { user: "Q", text: "Challenge the FITB bull thesis", k: "validation" },
      ].map((m, i) => (
        <div
          key={i}
          className="flex items-start gap-2 text-[11px] py-1.5 px-2 rounded-md bg-bg-surface border border-border-primary/40"
        >
          <span className="font-mono text-text-quaternary text-[9px] mt-0.5">#{i + 1}</span>
          <div className="flex-1 min-w-0">
            <p className="text-text-secondary truncate">{m.text}</p>
          </div>
          <span className="text-[9px] font-mono text-accent bg-accent/10 px-1.5 py-0.5 rounded shrink-0">
            {m.k}
          </span>
        </div>
      ))}
      <p className="text-[10px] text-text-quaternary text-center pt-1">
        Each follow-up inherits prior context.
      </p>
    </div>
  );
}

function HarmonyDiagram() {
  const agents = [
    { label: "Query Interpreter", note: "parses + plans" },
    { label: "Research Analyst", note: "29 tools, live data" },
    { label: "Risk Manager", note: "regime + correlation" },
    { label: "Portfolio Strategist", note: "10 ideas + pairs" },
    { label: "CIO Synthesizer", note: "memo + decision" },
  ];
  const math = [
    { label: "Engle-Granger ADF", note: "cointegration p-value" },
    { label: "EWMA + Ledoit-Wolf", note: "covariance + shrinkage" },
    { label: "Cornish-Fisher VaR", note: "fat-tail adjusted" },
    { label: "Black-Litterman", note: "portfolio construction" },
    { label: "Hidden Markov Model", note: "regime detection" },
  ];
  return (
    <div>
      <div className="grid md:grid-cols-[1fr_auto_1fr] gap-5 md:gap-6 items-stretch">
        {/* Left: Agents (Probabilistic) */}
        <div className="relative">
          <div className="absolute -inset-2 bg-accent/[0.06] rounded-2xl blur-2xl pointer-events-none" />
          <div className="relative rounded-2xl border border-border-primary bg-bg-surface p-6 h-full">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                <p className="text-[10px] uppercase tracking-wider text-accent font-medium">
                  Probabilistic
                </p>
              </div>
              <span className="text-[10px] font-mono text-text-quaternary">Agents</span>
            </div>
            <h3 className="text-[17px] font-semibold text-text-primary mb-1">
              Agents reason.
            </h3>
            <p className="text-[12px] text-text-tertiary leading-relaxed mb-4">
              Five purpose-built agents read your question, gather context, and
              shape the thesis.
            </p>
            <div className="space-y-1.5">
              {agents.map((a) => (
                <div
                  key={a.label}
                  className="flex items-center justify-between text-[11px] py-1.5 px-2.5 rounded-md bg-bg-primary/50 border border-border-primary/40"
                >
                  <span className="text-text-secondary font-medium">{a.label}</span>
                  <span className="text-text-quaternary text-[10px]">{a.note}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Middle: + */}
        <div className="hidden md:flex items-center justify-center">
          <div className="relative">
            <div className="absolute inset-0 rounded-full bg-gradient-to-br from-accent/30 to-signal-green/20 blur-lg" />
            <div className="relative w-14 h-14 rounded-full border border-accent/40 bg-bg-surface flex items-center justify-center shadow-xl shadow-black/40">
              <span className="text-3xl text-accent font-light leading-none -mt-1">+</span>
            </div>
          </div>
        </div>

        {/* Right: Math (Deterministic) */}
        <div className="relative">
          <div className="absolute -inset-2 bg-signal-green/[0.05] rounded-2xl blur-2xl pointer-events-none" />
          <div className="relative rounded-2xl border border-border-primary bg-bg-surface p-6 h-full">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-signal-green" />
                <p className="text-[10px] uppercase tracking-wider text-signal-green font-medium">
                  Deterministic
                </p>
              </div>
              <span className="text-[10px] font-mono text-text-quaternary">Math</span>
            </div>
            <h3 className="text-[17px] font-semibold text-text-primary mb-1">
              Math grounds.
            </h3>
            <p className="text-[12px] text-text-tertiary leading-relaxed mb-4">
              A built-in quant library produces exact, reproducible answers
              the agents can cite.
            </p>
            <div className="space-y-1.5">
              {math.map((m) => (
                <div
                  key={m.label}
                  className="flex items-center justify-between text-[11px] py-1.5 px-2.5 rounded-md bg-bg-primary/50 border border-border-primary/40"
                >
                  <span className="text-text-secondary font-mono">{m.label}</span>
                  <span className="text-text-quaternary text-[10px]">{m.note}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Output strip — sample verified claim */}
      <div className="mt-6 rounded-2xl border border-border-primary bg-gradient-to-br from-bg-surface to-bg-primary/40 p-5 flex items-start gap-3">
        <span className="inline-flex items-center gap-1.5 text-[10px] font-mono text-signal-green bg-signal-green/10 border border-signal-green/30 px-2 py-1 rounded shrink-0 mt-0.5">
          <span className="w-1 h-1 rounded-full bg-signal-green" />
          VERIFIED
        </span>
        <p className="text-[12px] md:text-[13px] text-text-secondary leading-relaxed">
          <span className="font-mono text-text-primary">VRT and CEG cointegrate</span>{" "}
          at <span className="font-mono text-text-primary">p = 0.018</span>, with a{" "}
          <span className="font-mono text-text-primary">14-day half-life</span>,
          computed via Engle-Granger ADF on the log-price spread. Hedge ratio
          fit by Total Least Squares on 6 months of daily history. Result is
          reproducible from{" "}
          <span className="font-mono text-accent">/api/quant/pairs</span>.
        </p>
      </div>
    </div>
  );
}

function LineageMock() {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-surface overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border-primary bg-bg-primary/40 flex items-center justify-between">
        <span className="text-[11px] font-mono text-text-tertiary">Source lineage</span>
        <span className="text-[10px] font-mono text-text-quaternary">22 sources</span>
      </div>
      <div className="divide-y divide-border-primary/60">
        {[
          { type: "SEC Form 4", id: "0001067983-25-000412", note: "VRT · 4 insider buys" },
          { type: "FRED", id: "DGS10", note: "10y yield · 4.42%" },
          { type: "SEC 13F", id: "CIK 0001336528", note: "Pershing Sq · new init TLN 2.1%" },
          { type: "Market", id: "COHR@yfinance", note: "current_price 87.21 · live" },
          { type: "Screen", id: "VST@insider_clusters", note: "5 unique buyers · CEO" },
        ].map((s) => (
          <div
            key={s.id}
            className="flex items-center gap-3 px-4 py-2.5 hover:bg-bg-elevated/40 transition-colors"
          >
            <span className="text-[10px] font-mono text-accent bg-accent/10 px-1.5 py-0.5 rounded border border-accent/20 w-20 text-center shrink-0">
              {s.type}
            </span>
            <span className="text-[11px] font-mono text-text-secondary truncate flex-1">
              {s.id}
            </span>
            <span className="text-[10px] text-text-quaternary truncate hidden sm:block">
              {s.note}
            </span>
            <span className="text-[10px] text-text-quaternary shrink-0">↗</span>
          </div>
        ))}
      </div>
    </div>
  );
}
