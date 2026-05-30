"use client";

import Link from "next/link";

/**
 * Plans page. Replaces the in-landing pricing section. Two paid tiers with real
 * numbers + a white-label "contact" tier. The trial CTA starts the portal
 * sign-up + onboarding flow and initiates a 10-day free trial
 * (surface=portal&trial=1 -> onboarding sets entitlement=trial + trial_ends_at).
 * Copy rule: zero em dashes.
 */

const TRIAL = "/sign-up?surface=portal&trial=1";

const TIERS = [
  {
    name: "Solo",
    price: "$49",
    cadence: "/ mo",
    for: "Individual trader exploring, or running modest signals.",
    cta: { label: "Start free trial", href: TRIAL, primary: false },
    highlight: false,
  },
  {
    name: "Systematic",
    price: "$149",
    cadence: "/ mo",
    for: "Running it in production, polling into a live algo.",
    cta: { label: "Start free trial", href: TRIAL, primary: true },
    highlight: true,
  },
  {
    name: "White-label",
    price: "Contact",
    cadence: "",
    for: "The whole engine and desk under your own brand.",
    cta: { label: "Contact us", href: "mailto:hello@alphaengine.dev?subject=White-label", primary: false },
    highlight: false,
  },
];

const MATRIX: { label: string; values: [string, string, string] }[] = [
  { label: "Deterministic calls", values: ["5,000 / mo", "50,000 / mo", "Custom"] },
  { label: "Agent slates", values: ["10 / mo", "50 / mo", "Custom"] },
  { label: "Keys", values: ["1", "2 (prod + dev)", "Custom"] },
  { label: "Surfaces", values: ["MCP + REST + SDK + desk", "MCP + REST + SDK + desk", "Same, white-labeled"] },
  { label: "Rate limits", values: ["Standard", "Priority", "Dedicated"] },
  { label: "Support", values: ["Community", "Email", "Dedicated"] },
];

export default function PlansPage() {
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <PlansNav />
      <div className="max-w-[1080px] mx-auto px-6 py-16">
        <div className="text-center mb-14 max-w-2xl mx-auto">
          <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
            <span className="text-text-tertiary">///</span> PLANS
          </p>
          <h1 className="font-display text-[34px] sm:text-[44px] font-semibold tracking-[-0.01em] leading-[1.08] mb-5">
            Start free for 10 days. Grandfathered for life.
          </h1>
          <p className="text-[15px] text-text-tertiary max-w-lg mx-auto leading-relaxed">
            Run it on your own data, no card to start. Every plan speaks the same
            versioned SignalEnvelope over MCP, REST, and the SDK, and includes the
            desk. Early seats lock today&apos;s rate for life.
          </p>
        </div>

        {/* Tier headers */}
        <div className="grid md:grid-cols-3 gap-5 mb-px">
          {TIERS.map((t) => (
            <div key={t.name} className={`rounded-sm border bg-bg-surface px-6 py-7 ${t.highlight ? "border-accent/50" : "border-border-primary"}`}>
              <div className="flex items-center justify-between mb-3">
                <p className="text-[11px] font-mono tracking-[0.2em] text-text-secondary">{t.name.toUpperCase()}</p>
                {t.highlight && <span className="text-[9px] font-mono tracking-[0.14em] text-accent border border-accent/40 rounded-sm px-2 py-0.5">POPULAR</span>}
              </div>
              <div className="flex items-baseline gap-1.5 mb-3">
                <span className="text-[30px] font-semibold tracking-tight text-text-primary leading-none">{t.price}</span>
                {t.cadence && <span className="text-[12px] font-mono text-text-tertiary">{t.cadence}</span>}
              </div>
              <p className="text-[13px] text-text-tertiary leading-relaxed mb-5 min-h-[3rem]">{t.for}</p>
              <Link
                href={t.cta.href}
                className={`block text-center px-4 py-2.5 rounded-sm text-[13px] font-semibold transition-colors ${
                  t.cta.primary
                    ? "bg-white text-bg-primary hover:bg-zinc-200"
                    : "border border-border-primary text-text-secondary hover:text-text-primary hover:border-zinc-700"
                }`}
              >
                {t.cta.label}
              </Link>
            </div>
          ))}
        </div>

        {/* Feature matrix */}
        <div className="mt-10 rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
          <div className="px-5 py-3 border-b border-border-primary grid grid-cols-[1.4fr_1fr_1fr_1fr] gap-4 text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
            <span>What you get</span>
            <span>Solo</span>
            <span>Systematic</span>
            <span>White-label</span>
          </div>
          <div className="divide-y divide-border-primary/40">
            {MATRIX.map((row) => (
              <div key={row.label} className="px-5 py-3 grid grid-cols-[1.4fr_1fr_1fr_1fr] gap-4 text-[12.5px]">
                <span className="text-text-tertiary">{row.label}</span>
                {row.values.map((v, i) => (
                  <span key={i} className="font-mono text-text-secondary">{v}</span>
                ))}
              </div>
            ))}
          </div>
        </div>

        <div className="text-center mt-12">
          <Link href={TRIAL} className="inline-block px-6 py-3 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors">
            Start free trial
          </Link>
          <p className="mt-4 text-[11px] text-text-quaternary">
            10-day trial on your own data. No card to start. Computational tooling, not investment advice.
          </p>
        </div>
      </div>
    </div>
  );
}

function PlansNav() {
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-40">
      <div className="max-w-[1280px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-brand">engine</span>
          <span className="ml-2 text-[11px] font-mono tracking-[0.18em] text-text-quaternary">/ PLANS</span>
        </Link>
        <div className="flex items-center gap-3 text-[12px]">
          <Link href="/docs" className="text-text-tertiary hover:text-text-primary transition-colors">DOCS</Link>
          <Link href="/dashboard" className="text-text-tertiary hover:text-text-primary transition-colors">DESK</Link>
          <Link href="/sign-up?surface=portal" className="px-3.5 py-1.5 rounded-sm bg-white text-bg-primary text-[12px] font-semibold tracking-tight hover:bg-zinc-200 transition-colors">Start building</Link>
        </div>
      </div>
    </header>
  );
}
