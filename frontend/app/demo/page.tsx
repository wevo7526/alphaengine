"use client";

import Link from "next/link";
import { EvalBanner } from "@/components/EvalBanner";
import { sampleMemo, sampleEnvelope } from "@/lib/sampleEnvelope";

/**
 * Public, no-signup demo slate (top of funnel). Shows a real, canned result
 * including the idea the system flagged as likely_noise. Shared and read-only,
 * so there is no per-user state to leak (see USER_STATES.md). Eval-labeled.
 */
export default function DemoPage() {
  const noise = sampleEnvelope.signals.find((s) => s.validation.verdict === "likely_noise");
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <EvalBanner />
      <DemoNav />
      <div className="max-w-[920px] mx-auto px-6 py-14">
        <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
          <span className="text-text-tertiary">///</span> LIVE DEMO · SAMPLE DATA
        </p>
        <h1 className="font-display text-[32px] sm:text-[40px] font-semibold tracking-[-0.01em] leading-[1.08] mb-5">
          A validated slate, the way the engine returns it.
        </h1>
        <p className="text-[15px] text-text-secondary leading-relaxed mb-10 max-w-xl">
          This is a real result on sample data. Note the second idea: the system
          flagged its <span className="text-text-secondary">own</span> pair{" "}
          <span className="text-signal-green">likely_noise</span> and the risk gate{" "}
          <span className="text-text-secondary">blocked</span> it. We ship the negative
          verdict instead of hiding it. To run this on your own data, start a free trial.
        </p>

        {/* Memo card */}
        <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden mb-8">
          <div className="px-4 py-2.5 border-b border-border-primary flex items-center justify-between">
            <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">INTELLIGENCE MEMO</span>
            <span className="text-[10px] font-mono tracking-[0.18em] px-2 py-0.5 border border-border-primary rounded-sm text-text-primary">{sampleMemo.decision}</span>
          </div>
          <div className="px-4 pt-3.5 pb-3 border-b border-border-primary/60">
            <p className="font-display text-[16px] text-text-primary leading-snug">{sampleMemo.title}</p>
          </div>
          <div className="grid grid-cols-4 divide-x divide-border-primary/60 border-b border-border-primary/60">
            {[["CONVICTION", String(sampleMemo.conviction)], ["REGIME", sampleMemo.regime], ["RISK", sampleMemo.risk], ["NAMES", String(sampleMemo.rows.length)]].map(([k, v]) => (
              <div key={k} className="px-3 py-2.5">
                <p className="text-[8px] font-mono tracking-[0.18em] text-text-quaternary mb-1">{k}</p>
                <p className="text-[11px] font-mono text-text-primary truncate">{v}</p>
              </div>
            ))}
          </div>
          <div className="px-4 py-2.5">
            <div className="grid grid-cols-[1fr_0.7fr_0.6fr_1fr_1fr_1fr_1fr] gap-2 text-[8px] font-mono tracking-[0.14em] text-text-quaternary pb-1.5 mb-1 border-b border-border-primary/40">
              <span>TICKER</span><span>DIR</span><span>CONV</span><span>ENTRY</span><span>STOP</span><span>TARGET</span><span>VERDICT</span>
            </div>
            {sampleMemo.rows.map((r) => (
              <div key={r.t} className="grid grid-cols-[1fr_0.7fr_0.6fr_1fr_1fr_1fr_1fr] gap-2 text-[11px] font-mono py-1 tabular-nums">
                <span className="text-text-primary">{r.t}</span>
                <span className="text-text-tertiary">{r.d}</span>
                <span className="text-text-secondary">{r.c}</span>
                <span className="text-text-tertiary">{r.e}</span>
                <span className="text-text-tertiary">{r.s}</span>
                <span className="text-text-tertiary">{r.p}</span>
                <span className={r.verdict === "edge" ? "text-signal-green" : "text-text-quaternary"}>{r.verdict}</span>
              </div>
            ))}
          </div>
          <div className="px-4 py-2.5 flex items-center gap-3 bg-bg-elevated/40 border-t border-border-primary/60">
            <span className="text-[10px] font-mono tracking-[0.16em] text-text-primary">✓ VERIFIED</span>
            <span className="text-[10px] font-mono tracking-[0.16em] text-text-quaternary">{sampleMemo.sources} sources</span>
            <span className="ml-auto text-[10px] font-mono tracking-[0.16em] text-text-quaternary">deflated&nbsp;SR&nbsp;{sampleMemo.deflated_sharpe}</span>
          </div>
        </div>

        {/* The flagged-noise callout */}
        {noise && (
          <div className="rounded-sm border border-border-primary bg-bg-surface/60 px-5 py-4 mb-10">
            <p className="text-[10px] font-mono tracking-[0.2em] text-text-quaternary mb-2">FLAGGED: {noise.instruments.map((i) => i.symbol).join(" / ")} PAIR</p>
            <p className="text-[13px] text-text-tertiary leading-relaxed">
              deflated_sharpe <span className="font-mono text-text-secondary">{noise.validation.deflated_sharpe}</span>,
              pbo <span className="font-mono text-text-secondary">{noise.validation.pbo}</span>,
              verdict <span className="font-mono text-signal-green">{noise.validation.verdict}</span>,
              gate <span className="font-mono text-text-secondary">{noise.risk.gate}</span>. The honesty is the brand.
            </p>
          </div>
        )}

        <div className="flex items-center gap-4 flex-wrap">
          <Link href="/sign-up?surface=portal" className="px-5 py-2.5 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors">Start a free trial on your data</Link>
          <Link href="/docs" className="px-5 py-2.5 rounded-sm border border-border-primary text-text-secondary text-[13px] font-semibold hover:text-text-primary hover:border-zinc-700 transition-colors">Read the docs</Link>
        </div>
        <p className="mt-8 text-[11px] text-text-quaternary leading-relaxed max-w-xl">
          For testing and educational purposes only. Sample data. Computational
          tooling, not investment advice.
        </p>
      </div>
    </div>
  );
}

function DemoNav() {
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-40">
      <div className="max-w-[1280px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-brand">engine</span>
          <span className="ml-2 text-[11px] font-mono tracking-[0.18em] text-text-quaternary">/ DEMO</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link href="/docs" className="text-[12px] font-medium tracking-wide text-text-tertiary hover:text-text-primary transition-colors">DOCS</Link>
          <Link href="/sign-in?surface=demo" className="text-[12px] font-medium tracking-wide text-text-tertiary hover:text-text-primary transition-colors">Explore the desk</Link>
          <Link href="/sign-up?surface=portal" className="px-3.5 py-1.5 rounded-sm bg-white text-bg-primary text-[12px] font-semibold tracking-tight hover:bg-zinc-200 transition-colors">Start building</Link>
        </div>
      </div>
    </header>
  );
}
