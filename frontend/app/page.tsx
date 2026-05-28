"use client";

import Link from "next/link";
import { useUser } from "@clerk/nextjs";

export default function LandingPage() {
  const { isSignedIn } = useUser();

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary flex flex-col">
      {/* Top nav */}
      <header className="border-b border-border-primary/60 bg-bg-primary/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <Link href="/" className="text-[15px] font-semibold tracking-tight">
            alpha<span className="text-accent">engine</span>
          </Link>
          <nav className="hidden md:flex items-center gap-6 text-[13px] text-text-tertiary">
            <a href="#platform" className="hover:text-text-primary transition-colors">Platform</a>
            <a href="#math" className="hover:text-text-primary transition-colors">Math</a>
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

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-6 pt-20 pb-24 md:pt-32 md:pb-32 w-full">
        <div className="max-w-3xl">
          <p className="text-[11px] uppercase tracking-[0.18em] text-text-quaternary mb-5">
            For long/short equity & macro PMs
          </p>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.05] mb-6">
            AI agents for hedge fund research.
          </h1>
          <p className="text-[16px] md:text-[18px] text-text-secondary leading-relaxed mb-10 max-w-2xl">
            An auditable, math-grounded research desk that turns a freeform query
            into a 10-name trade slate with cointegrated pairs, factor
            decomposition, and live receipts — then grades itself in public.
          </p>
          <div className="flex items-center gap-3">
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

      {/* Problem section */}
      <section className="border-y border-border-primary/60 bg-bg-surface/40">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-24">
          <div className="grid md:grid-cols-2 gap-12 items-start">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-text-quaternary mb-4">
                The problem
              </p>
              <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight mb-5">
                Wall Street research still runs on PDFs and gut feel.
              </h2>
              <p className="text-[15px] text-text-tertiary leading-relaxed">
                Sell-side notes lag the move. Bloomberg shows you data but
                doesn&apos;t reason about it. Every AI tool you&apos;ve tried
                makes up numbers, recommends consensus mega-caps, or has no risk
                framework. PMs end up doing the same manual screen, the same
                manual valuation, and the same manual stress test every Monday.
              </p>
            </div>
            <div className="md:pt-8">
              <p className="text-[44px] md:text-[56px] font-semibold text-text-primary leading-none mb-3">
                ~12 hrs
              </p>
              <p className="text-[14px] text-text-tertiary leading-relaxed">
                The average PM spends 12+ hours/week assembling research that
                exists in fragments across Bloomberg, FactSet, sell-side decks,
                10-Ks, and 13F filings. Alpha Engine produces a defensible
                10-name slate in under 10 minutes — and every number traces back
                to the SEC accession, FRED series, or fund 13F you can pull
                yourself.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Platform — five engines */}
      <section id="platform" className="max-w-6xl mx-auto px-6 py-24 md:py-28 w-full">
        <div className="max-w-2xl mb-14">
          <p className="text-[11px] uppercase tracking-[0.18em] text-text-quaternary mb-4">
            The platform
          </p>
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight">
            Five engines. One desk.
          </h2>
        </div>

        <div className="grid md:grid-cols-2 gap-px bg-border-primary/60 rounded-xl overflow-hidden border border-border-primary/60">
          {ENGINES.map((engine) => (
            <article
              key={engine.number}
              className="bg-bg-surface p-7 md:p-8 flex flex-col"
            >
              <p className="text-[11px] font-mono text-text-quaternary mb-4">{engine.number}</p>
              <h3 className="text-[17px] font-semibold text-text-primary mb-2">
                {engine.title}
              </h3>
              <p className="text-[13px] text-text-secondary leading-relaxed mb-4">
                {engine.body}
              </p>
              <div className="mt-auto flex flex-wrap gap-1.5">
                {engine.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-[10px] font-mono text-text-quaternary bg-bg-elevated/70 border border-border-primary/40 px-2 py-0.5 rounded"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* Math callout */}
      <section id="math" className="border-y border-border-primary/60 bg-bg-surface/40">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-24">
          <div className="max-w-3xl">
            <p className="text-[11px] uppercase tracking-[0.18em] text-text-quaternary mb-4">
              The math
            </p>
            <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight mb-6">
              Institutional-grade, not LLM-generated.
            </h2>
            <p className="text-[15px] text-text-tertiary leading-relaxed mb-8">
              Black-Litterman optimization. EWMA covariance with Ledoit-Wolf
              shrinkage. Cornish-Fisher VaR with bootstrap confidence
              intervals. Engle-Granger cointegration with Ornstein-Uhlenbeck
              half-life. Joint OLS key-rate durations. Information Coefficient
              scoring on every signal. Hidden Markov regime classification. The
              math is textbook — the agents orchestrate it.
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {MATH_BADGES.map((b) => (
                <div
                  key={b.label}
                  className="rounded-xl border border-border-primary bg-bg-surface px-3 py-3"
                >
                  <p className="text-[10px] uppercase tracking-wider text-text-quaternary mb-1">
                    {b.label}
                  </p>
                  <p className="text-[13px] text-text-primary font-mono">{b.value}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Trust pillars */}
      <section id="trust" className="max-w-6xl mx-auto px-6 py-24 md:py-28 w-full">
        <div className="max-w-2xl mb-14">
          <p className="text-[11px] uppercase tracking-[0.18em] text-text-quaternary mb-4">
            Why a PM can trust it
          </p>
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight leading-tight">
            Defensible by construction.
          </h2>
        </div>

        <div className="grid sm:grid-cols-2 gap-px bg-border-primary/60 rounded-xl overflow-hidden border border-border-primary/60">
          {TRUST_PILLARS.map((p) => (
            <div key={p.title} className="bg-bg-surface p-7 md:p-8">
              <h3 className="text-[15px] font-semibold text-text-primary mb-2">
                {p.title}
              </h3>
              <p className="text-[13px] text-text-tertiary leading-relaxed">
                {p.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Closing CTA */}
      <section className="border-t border-border-primary/60 bg-bg-surface/40">
        <div className="max-w-6xl mx-auto px-6 py-24 md:py-32 text-center">
          <h2 className="text-3xl md:text-4xl font-semibold tracking-tight leading-tight mb-5">
            Bring your research desk into the future.
          </h2>
          <p className="text-[15px] text-text-tertiary max-w-xl mx-auto mb-8 leading-relaxed">
            Built for L/S equity and macro PMs who want defensible research,
            not generative prose.
          </p>
          <div className="flex items-center justify-center gap-3">
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
      <footer className="border-t border-border-primary/60 mt-auto">
        <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-[12px] text-text-quaternary">
          <div className="flex items-center gap-4">
            <span className="font-semibold text-text-secondary">
              alpha<span className="text-accent">engine</span>
            </span>
            <span>© {new Date().getFullYear()}</span>
          </div>
          <div className="flex items-center gap-5">
            <a href="#platform" className="hover:text-text-secondary transition-colors">Platform</a>
            <a href="#math" className="hover:text-text-secondary transition-colors">Math</a>
            <a href="#trust" className="hover:text-text-secondary transition-colors">Trust</a>
            <Link href="/sign-in" className="hover:text-text-secondary transition-colors">Sign in</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

const ENGINES: { number: string; title: string; body: string; tags: string[] }[] = [
  {
    number: "01",
    title: "Research Desk",
    body:
      "Five agents — Interpreter, Research Analyst, Risk Manager, Portfolio Strategist, CIO — produce a structured intelligence memo from a freeform query in under 10 minutes. Every numerical claim is grounded in a tool call you can audit.",
    tags: ["LangGraph", "Claude Sonnet", "29 tools"],
  },
  {
    number: "02",
    title: "Hidden-Gem Discovery",
    body:
      "Five live screens that structurally break the mega-cap monoculture: insider cluster buys, smart-money 13F initiations, post-earnings drift on under-covered names, 52-week-low with insider buying, and sector-adjacent picks-and-shovels.",
    tags: ["SEC EDGAR", "Form 4", "13F"],
  },
  {
    number: "03",
    title: "Risk + Attribution",
    body:
      "EWMA-Ledoit-Wolf covariance, Cornish-Fisher VaR with bootstrap CI, drawdown circuit breaker, marginal VaR gate. Long/short construction with dollar-neutral, beta-neutral, gross-leverage constraints. Brinson attribution against any benchmark.",
    tags: ["Black-Litterman", "Cornish-Fisher", "Jacobs-Levy"],
  },
  {
    number: "04",
    title: "Conversational Threads",
    body:
      "Drill down without starting over. Follow-ups inherit the prior memo's tickers, themes, and decision. The Interpreter classifies your query into seven action types — drilldown, validation, risk check, time-horizon shift — and routes accordingly.",
    tags: ["Thread persistence", "Query routing"],
  },
  {
    number: "05",
    title: "Track Record",
    body:
      "The system grades itself in public. Every signal scored at 1-day, 5-day, 20-day horizons against realized prices. Information Coefficient by conviction bucket. Alpha decay curve. Hit rate over time. Empty states warn when sample sizes are not yet statistically meaningful.",
    tags: ["IC", "ICIR", "Brinson"],
  },
];

const MATH_BADGES: { label: string; value: string }[] = [
  { label: "Cointegration", value: "Engle-Granger ADF" },
  { label: "Hedge ratio", value: "Total Least Squares" },
  { label: "Half-life", value: "Ornstein-Uhlenbeck AR(1)" },
  { label: "Covariance", value: "EWMA + Ledoit-Wolf" },
  { label: "VaR", value: "Parametric + CF + Bootstrap" },
  { label: "Regime", value: "Hidden Markov + rule fallback" },
  { label: "Curve", value: "11-tenor CMT + cubic spline" },
  { label: "Skill", value: "Spearman IC, Newey-West α" },
];

const TRUST_PILLARS: { title: string; body: string }[] = [
  {
    title: "Live receipts on every number.",
    body:
      "Each memo carries a lineage block: every SEC accession, FRED series ID, fund CIK, market quote, and screen output that contributed to it. A PM auditing a number months later can pull the source.",
  },
  {
    title: "The system grades itself.",
    body:
      "Every trade idea scored at 1d/5d/20d horizons. IC, hit-rate by conviction, alpha-decay curves surfaced on the Track Record page. If the model is poorly calibrated, the page tells you. No hiding behind smooth narratives.",
  },
  {
    title: "Risk has kill authority.",
    body:
      "Position cap, sector cap, marginal VaR, drawdown circuit breaker, liquidity gate — all enforced before a trade clears. No advisory warnings that get ignored: trades that breach a gate get blocked.",
  },
  {
    title: "Structural defense against monoculture.",
    body:
      "On any slate of 8+ ideas, no more than 30% can be mega-cap and at least 30% must come from a dynamic discovery screen. The system regenerates rather than ship a Mag7 slate.",
  },
];
