"use client";

import Link from "next/link";
import { useUser } from "@clerk/nextjs";
import { BrandConstellation } from "@/components/BrandConstellation";

export default function LandingPage() {
  const { isSignedIn } = useUser();

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary flex flex-col relative overflow-hidden">
      <TopNav isSignedIn={!!isSignedIn} />
      <Hero isSignedIn={!!isSignedIn} />
      <TickerBand />
      <StatusStrip />
      <ProductShowcase />
      <IntelligenceLayer />
      <SourceLedger />
      <ClosingCTA isSignedIn={!!isSignedIn} />
      <Footer />
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// TOP NAV
// ────────────────────────────────────────────────────────────────────────
function TopNav({ isSignedIn }: { isSignedIn: boolean }) {
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-50">
      <div className="max-w-[1280px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-accent">engine</span>
        </Link>
        <nav className="hidden md:flex items-center gap-8 text-[12px] font-medium tracking-wide text-text-tertiary">
          <a href="#product" className="hover:text-text-primary transition-colors">PRODUCT</a>
          <a href="#intelligence" className="hover:text-text-primary transition-colors">INTELLIGENCE</a>
          <a href="#trust" className="hover:text-text-primary transition-colors">TRUST</a>
        </nav>
        <div className="flex items-center gap-3">
          {isSignedIn ? (
            <Link
              href="/dashboard"
              className="px-3 py-1.5 rounded-md bg-white text-bg-primary text-[12px] font-semibold tracking-tight hover:bg-zinc-200 transition-colors"
            >
              Go to dashboard
            </Link>
          ) : (
            <Link
              href="/sign-up"
              className="px-3 py-1.5 rounded-md bg-white text-bg-primary text-[12px] font-semibold tracking-tight hover:bg-zinc-200 transition-colors"
            >
              Get started
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}

// ────────────────────────────────────────────────────────────────────────
// HERO — large constellation backdrop, terminal-style headline overlay
// ────────────────────────────────────────────────────────────────────────
function Hero({ isSignedIn }: { isSignedIn: boolean }) {
  return (
    <section className="relative isolate min-h-[88vh] flex flex-col justify-center overflow-hidden border-b border-border-primary/60">
      {/* Layered background:
          1. Animated grid (faint, drifting)
          2. Ambient gradient orbs
          3. The constellation animation as the centerpiece visual
          4. Vignette to anchor the copy on the left  */}
      <div className="absolute inset-0 grid-bg opacity-50" aria-hidden="true" />
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div className="absolute -top-48 -left-48 w-[48rem] h-[48rem] rounded-full bg-accent/[0.10] blur-[120px]" />
        <div className="absolute bottom-0 -right-48 w-[42rem] h-[42rem] rounded-full bg-signal-green/[0.06] blur-[120px]" />
      </div>
      <div className="absolute right-0 top-0 bottom-0 w-1/2 lg:w-3/5 opacity-90" aria-hidden="true">
        <BrandConstellation />
      </div>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-bg-primary via-bg-primary/85 to-transparent" aria-hidden="true" />

      <div className="relative z-10 max-w-[1280px] mx-auto px-6 w-full py-20">
        <div className="max-w-xl">
          {/* Terminal-style tag */}
          <div className="inline-flex items-center gap-2 mb-7 text-[10px] font-mono tracking-[0.22em] text-text-quaternary">
            <span className="text-accent">///</span>
            <span>ALPHA ENGINE · v1.0</span>
            <span className="w-1 h-1 rounded-full bg-text-quaternary" />
            <span className="text-signal-green">LIVE</span>
          </div>

          <h1 className="text-[44px] sm:text-[56px] lg:text-[64px] font-semibold tracking-[-0.02em] leading-[1.02] mb-7">
            The AI research desk
            <br />
            for hedge funds.
          </h1>

          <p className="text-[16px] text-text-secondary leading-relaxed mb-9 max-w-md">
            Run a defensible long/short or macro slate in minutes, with full
            source provenance on every claim and risk controls on every trade.
          </p>

          <div className="flex items-center gap-5 flex-wrap">
            {isSignedIn ? (
              <Link
                href="/dashboard"
                className="px-5 py-2.5 rounded-md bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors"
              >
                Go to dashboard
              </Link>
            ) : (
              <Link
                href="/sign-up"
                className="px-5 py-2.5 rounded-md bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors"
              >
                Get started
              </Link>
            )}
            <a
              href="#product"
              className="text-[12px] tracking-wide text-text-secondary hover:text-text-primary transition-colors"
            >
              SEE PRODUCT →
            </a>
          </div>

          {/* Terminal-style command preview, evocative not literal */}
          <div className="mt-12 max-w-md rounded-md border border-border-primary bg-bg-surface/60 backdrop-blur-sm overflow-hidden">
            <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center gap-1.5 text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
              <span className="w-1.5 h-1.5 rounded-full bg-signal-red/60" />
              <span className="w-1.5 h-1.5 rounded-full bg-signal-yellow/60" />
              <span className="w-1.5 h-1.5 rounded-full bg-signal-green/60" />
              <span className="ml-2">ANALYSIS · NEW</span>
              <span className="ml-auto text-[9px]">~10 min</span>
            </div>
            <div className="px-4 py-3 font-mono text-[12px] text-text-secondary leading-relaxed">
              <span className="text-accent">{">"}</span> long/short setup in
              regional banks ahead of FOMC<span className="terminal-cursor text-accent" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// TICKER BAND — full-width scrolling band of mock market moves
// ────────────────────────────────────────────────────────────────────────
function TickerBand() {
  const items = [
    { t: "VRT",  d: +2.31 }, { t: "ETN",  d: +1.08 }, { t: "CCJ",  d: +3.84 },
    { t: "DDOG", d: -0.42 }, { t: "PLTR", d: +0.97 }, { t: "MTB",  d: +1.45 },
    { t: "COHR", d: +4.12 }, { t: "TLN",  d: +2.66 }, { t: "VST",  d: +1.18 },
    { t: "FITB", d: -0.21 }, { t: "RXRX", d: +5.34 }, { t: "VKTX", d: +6.71 },
    { t: "GLD",  d: -0.18 }, { t: "TLT",  d: -0.74 }, { t: "HYG",  d: +0.11 },
    { t: "USO",  d: +1.92 }, { t: "UUP",  d: -0.34 }, { t: "VXX",  d: -2.45 },
    { t: "SMH",  d: +0.86 }, { t: "XLF",  d: +0.42 }, { t: "XLE",  d: +1.27 },
    { t: "QQQ",  d: +0.51 }, { t: "SPY",  d: +0.34 }, { t: "IWM",  d: +1.08 },
  ];
  // Duplicate for seamless loop
  const loop = [...items, ...items];

  return (
    <section className="relative border-b border-border-primary/60 bg-bg-surface/30 overflow-hidden" aria-label="Sample data feed">
      {/* edge fades */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-32 bg-gradient-to-r from-bg-primary to-transparent z-10" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-32 bg-gradient-to-l from-bg-primary to-transparent z-10" />

      <div className="ticker-scroll flex items-center py-3 whitespace-nowrap">
        {loop.map((x, i) => {
          const up = x.d >= 0;
          return (
            <div
              key={i}
              className="inline-flex items-center gap-2 px-5 text-[11px] font-mono"
            >
              <span className="text-text-secondary">{x.t}</span>
              <span className={up ? "text-signal-green" : "text-signal-red"}>
                {up ? "▲" : "▼"} {Math.abs(x.d).toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// STATUS STRIP — Bloomberg-style stat panels with mini sparklines
// ────────────────────────────────────────────────────────────────────────
function StatusStrip() {
  return (
    <section className="border-b border-border-primary/60">
      <div className="max-w-[1280px] mx-auto px-6 py-12">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border-primary/40 border border-border-primary/40 rounded-md overflow-hidden">
          <StatPanel
            label="MEMO TURNAROUND"
            value="~10"
            unit="min"
            sub="From query to final memo"
            mini={<MiniSparkline kind="flat" />}
          />
          <StatPanel
            label="SOURCES PER MEMO"
            value="22"
            unit="avg"
            sub="Every claim is cited"
            mini={<MiniSparkline kind="up" />}
          />
          <StatPanel
            label="RISK GATES"
            value="6"
            unit="active"
            sub="Pre-trade controls"
            mini={<MiniBars />}
          />
          <StatPanel
            label="DISCOVERY SCREENS"
            value="5"
            unit="live"
            sub="Beyond consensus names"
            mini={<MiniDots />}
          />
        </div>
      </div>
    </section>
  );
}

function StatPanel({
  label,
  value,
  unit,
  sub,
  mini,
}: {
  label: string;
  value: string;
  unit?: string;
  sub: string;
  mini?: React.ReactNode;
}) {
  return (
    <div className="bg-bg-surface px-5 py-5 flex items-center justify-between gap-4">
      <div>
        <p className="text-[9px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
          {label}
        </p>
        <div className="flex items-baseline gap-2 mb-1.5">
          <span className="text-[28px] font-semibold tracking-tight text-text-primary leading-none counter-tick">
            {value}
          </span>
          {unit && <span className="text-[11px] font-mono text-text-tertiary">{unit}</span>}
        </div>
        <p className="text-[11px] text-text-tertiary">{sub}</p>
      </div>
      <div className="shrink-0 w-20 h-12">{mini}</div>
    </div>
  );
}

function MiniSparkline({ kind }: { kind: "flat" | "up" | "down" }) {
  // Hand-tuned y values that look organic
  const points = kind === "up"
    ? [38, 34, 30, 32, 26, 24, 20, 16, 12, 8]
    : kind === "down"
    ? [10, 14, 18, 16, 22, 26, 28, 32, 36, 40]
    : [22, 24, 20, 26, 22, 28, 22, 26, 20, 22];
  const d = points
    .map((y, i) => `${i === 0 ? "M" : "L"} ${i * 9} ${y}`)
    .join(" ");
  return (
    <svg viewBox="0 0 81 48" className="w-full h-full overflow-visible">
      <path
        d={d}
        fill="none"
        stroke="#3b82f6"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="sparkline-path"
      />
      <circle cx={9 * (points.length - 1)} cy={points[points.length - 1]} r="2.5" fill="#3b82f6" />
    </svg>
  );
}

function MiniBars() {
  const heights = [60, 90, 45, 100, 75, 95];
  return (
    <div className="w-full h-full flex items-end justify-between gap-1">
      {heights.map((h, i) => (
        <div
          key={i}
          className="flex-1 bg-accent/70 rounded-sm pulse-bar"
          style={{ height: `${h}%`, animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

function MiniDots() {
  // 5 dots aligned to "5 live screens"
  return (
    <div className="w-full h-full grid grid-cols-5 gap-1 items-center">
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="aspect-square rounded-full bg-signal-green/80 counter-tick"
          style={{ animationDelay: `${i * 0.3}s` }}
        />
      ))}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// PRODUCT SHOWCASE — 4 panels in an asymmetric grid, mockup-led
// ────────────────────────────────────────────────────────────────────────
function ProductShowcase() {
  return (
    <section id="product" className="border-b border-border-primary/60">
      <div className="max-w-[1280px] mx-auto px-6 py-24">
        <div className="flex items-end justify-between mb-12">
          <div className="max-w-xl">
            <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-4">
              /// PRODUCT
            </p>
            <h2 className="text-[36px] sm:text-[44px] font-semibold tracking-[-0.02em] leading-[1.05] mb-3">
              What you actually use it for.
            </h2>
          </div>
          <p className="hidden md:block text-[11px] font-mono tracking-wider text-text-quaternary text-right">
            4 SURFACES · LIVE
          </p>
        </div>

        {/* Asymmetric grid: two large, two compact */}
        <div className="grid lg:grid-cols-12 gap-5">
          <ShowcaseCard
            tag="01 / DISCOVERY"
            title="Names beyond the obvious."
            sub="Five live screens highlight insider buying clusters, smart-money initiations, post-earnings drift, fresh 52-week-low setups, and picks-and-shovels for current themes."
            span="lg:col-span-7"
            visual={<DiscoveryViz />}
          />
          <ShowcaseCard
            tag="02 / TRACK RECORD"
            title="See how your calls perform."
            sub="Every signal scored at 1d / 5d / 20d. Information Coefficient by conviction. Alpha decay over time."
            span="lg:col-span-5"
            visual={<TrackRecordViz />}
          />
          <ShowcaseCard
            tag="03 / RISK & STRESS"
            title="Hard controls on every trade."
            sub="Position, sector, marginal VaR, drawdown, and liquidity gates. Dial in macro shocks and watch projected P&L per position update live."
            span="lg:col-span-5"
            visual={<RiskViz />}
          />
          <ShowcaseCard
            tag="04 / FOLLOW-UP THREADS"
            title="Keep researching, without restarting."
            sub="Continue any memo with one click. Drill into a name, validate a thesis, or stress-test a slate in a sentence."
            span="lg:col-span-7"
            visual={<ThreadViz />}
          />
        </div>
      </div>
    </section>
  );
}

function ShowcaseCard({
  tag,
  title,
  sub,
  visual,
  span,
}: {
  tag: string;
  title: string;
  sub: string;
  visual: React.ReactNode;
  span: string;
}) {
  return (
    <article
      className={`group relative ${span} rounded-md border border-border-primary bg-bg-surface overflow-hidden hover:border-zinc-700 transition-colors`}
    >
      <div className="absolute inset-0 bg-gradient-to-br from-accent/[0.03] via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
      <div className="grid lg:grid-cols-[1fr_auto] gap-6 p-6 lg:p-8 relative">
        <div className="max-w-md">
          <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary mb-4">{tag}</p>
          <h3 className="text-[20px] font-semibold tracking-tight text-text-primary mb-2.5 leading-tight">
            {title}
          </h3>
          <p className="text-[13px] text-text-tertiary leading-relaxed">{sub}</p>
        </div>
        <div className="lg:min-w-[300px] lg:max-w-[380px] w-full">{visual}</div>
      </div>
    </article>
  );
}

// ─── Showcase visuals — each evokes a product surface without exposing internals
function DiscoveryViz() {
  const rows = [
    { ticker: "RXRX",  reason: "Insider cluster",          score: 92, color: "signal-green" },
    { ticker: "TLN",   reason: "Fund initiation",          score: 81, color: "accent" },
    { ticker: "VKTX",  reason: "Post-earnings drift",      score: 76, color: "signal-green" },
    { ticker: "FIVE",  reason: "52w low + insider buy",    score: 64, color: "accent" },
  ];
  return (
    <div className="rounded-md border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>SCREEN OUTPUT</span>
        <span className="text-signal-green">● LIVE</span>
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
  // Mock equity curve drawing in over time
  const points = [50, 47, 51, 48, 52, 49, 54, 51, 56, 58, 55, 60, 64, 62, 68, 71];
  const d = points
    .map((y, i) => `${i === 0 ? "M" : "L"} ${i * 18} ${72 - y * 0.6}`)
    .join(" ");
  return (
    <div className="rounded-md border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>SIGNAL IC · TRAILING 90D</span>
        <span className="text-signal-green">+0.08</span>
      </div>
      <div className="p-3">
        <svg viewBox="0 0 280 80" className="w-full h-20 overflow-visible">
          <defs>
            <linearGradient id="ic-fill" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${d} L ${(points.length - 1) * 18} 80 L 0 80 Z`} fill="url(#ic-fill)" />
          <path
            d={d}
            fill="none"
            stroke="#10b981"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="sparkline-path"
          />
          {/* Zero baseline */}
          <line x1="0" y1="48" x2="280" y2="48" stroke="rgba(250,250,250,0.06)" strokeDasharray="2 3" />
        </svg>
        <div className="mt-2 grid grid-cols-3 gap-2 text-[10px] font-mono text-text-tertiary">
          <span>1D <span className="text-text-secondary ml-1">+0.04</span></span>
          <span>5D <span className="text-text-secondary ml-1">+0.08</span></span>
          <span>20D <span className="text-text-secondary ml-1">+0.11</span></span>
        </div>
      </div>
    </div>
  );
}

function RiskViz() {
  const gates = [
    { label: "Position",  ok: true,  val: "5.0% ≤ 5.0%" },
    { label: "Sector",    ok: false, val: "32% > 30%" },
    { label: "Marg VaR",  ok: false, val: "3.4% > 3.0%" },
    { label: "Liquidity", ok: true,  val: "2.1% < 10%" },
  ];
  return (
    <div className="rounded-md border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider">
        <span className="text-text-quaternary">PRE-TRADE GATE</span>
        <span className="text-signal-red">BLOCKED</span>
      </div>
      <div className="divide-y divide-border-primary/40">
        {gates.map((g) => (
          <div key={g.label} className="flex items-center justify-between px-3 py-2 text-[11px] font-mono">
            <span className="text-text-tertiary">{g.label}</span>
            <span className={g.ok ? "text-signal-green" : "text-signal-red"}>
              {g.ok ? "✓" : "✗"} {g.val}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ThreadViz() {
  const items = [
    { tag: "FRESH",      text: "Best L/S in regional banks?",            color: "text-text-quaternary" },
    { tag: "DRILLDOWN",  text: "Capital position on MTB?",               color: "text-accent" },
    { tag: "RISK CHECK", text: "Stress at +100bp on the 10Y",            color: "text-accent" },
    { tag: "VALIDATION", text: "Challenge the FITB bull case",           color: "text-accent" },
  ];
  return (
    <div className="rounded-md border border-border-primary bg-bg-primary/60 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>THREAD · 4 MESSAGES</span>
        <span className="text-signal-green">● ACTIVE</span>
      </div>
      <div className="divide-y divide-border-primary/40">
        {items.map((m, i) => (
          <div key={i} className="flex items-center gap-3 px-3 py-2 text-[11px]">
            <span className="font-mono text-text-quaternary w-4">{i + 1}</span>
            <span className={`font-mono text-[9px] tracking-wider w-20 ${m.color}`}>{m.tag}</span>
            <span className="text-text-secondary truncate flex-1">{m.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// INTELLIGENCE LAYER — abstract pairing (no agent or library names)
// ────────────────────────────────────────────────────────────────────────
function IntelligenceLayer() {
  return (
    <section id="intelligence" className="relative border-b border-border-primary/60 overflow-hidden">
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div className="absolute top-1/3 left-1/4 w-[32rem] h-[32rem] rounded-full bg-accent/[0.06] blur-[120px]" />
        <div className="absolute bottom-0 right-1/4 w-[32rem] h-[32rem] rounded-full bg-signal-green/[0.04] blur-[120px]" />
      </div>

      <div className="max-w-[1280px] mx-auto px-6 py-24 relative">
        <div className="grid lg:grid-cols-[1fr_1.1fr] gap-12 items-center">
          {/* Copy */}
          <div className="max-w-md">
            <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-4">
              /// INTELLIGENCE LAYER
            </p>
            <h2 className="text-[36px] sm:text-[44px] font-semibold tracking-[-0.02em] leading-[1.05] mb-5">
              Reasoning meets math.
            </h2>
            <p className="text-[14px] text-text-tertiary leading-relaxed mb-7">
              Two engines work in tandem. One reads, frames, and reasons through
              the question. The other runs the exact math behind every claim.
              You get the speed of one and the certainty of the other.
            </p>
            <div className="flex flex-wrap items-center gap-3 text-[10px] font-mono tracking-wider">
              <span className="inline-flex items-center gap-2 px-2.5 py-1 rounded border border-border-primary bg-bg-surface text-text-secondary">
                <span className="w-1 h-1 rounded-full bg-accent" />
                PROBABILISTIC
              </span>
              <span className="text-text-quaternary">+</span>
              <span className="inline-flex items-center gap-2 px-2.5 py-1 rounded border border-border-primary bg-bg-surface text-text-secondary">
                <span className="w-1 h-1 rounded-full bg-signal-green" />
                DETERMINISTIC
              </span>
            </div>
          </div>

          {/* Abstract visual */}
          <IntelligenceVisual />
        </div>
      </div>
    </section>
  );
}

function IntelligenceVisual() {
  return (
    <div className="relative aspect-[5/3] rounded-md border border-border-primary bg-bg-surface overflow-hidden">
      <div className="absolute inset-0 grid-bg opacity-30" />
      {/* Two glyphs + connecting flow */}
      <svg viewBox="0 0 500 300" className="w-full h-full relative">
        <defs>
          <radialGradient id="glyph-blue" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.9" />
            <stop offset="60%" stopColor="#3b82f6" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="glyph-green" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#10b981" stopOpacity="0.9" />
            <stop offset="60%" stopColor="#10b981" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Left glyph — probabilistic (cloud of nodes) */}
        <g>
          <circle cx="110" cy="150" r="80" fill="url(#glyph-blue)" />
          <g className="constellation-orbit-1" style={{ transformOrigin: "110px 150px" }}>
            {[
              [110, 90], [170, 120], [165, 180], [115, 210], [55, 180], [50, 120],
            ].map(([cx, cy], i) => (
              <circle key={i} cx={cx} cy={cy} r="3.5" fill="#3b82f6" />
            ))}
          </g>
          <circle cx="110" cy="150" r="8" fill="#3b82f6" className="constellation-core" style={{ transformOrigin: "110px 150px" }} />
        </g>

        {/* Right glyph — deterministic (precise grid) */}
        <g>
          <circle cx="390" cy="150" r="80" fill="url(#glyph-green)" />
          {/* Grid of 3x3 dots */}
          {[-1, 0, 1].flatMap((dx) =>
            [-1, 0, 1].map((dy) => (
              <rect
                key={`${dx},${dy}`}
                x={388 + dx * 24}
                y={148 + dy * 24}
                width="4"
                height="4"
                fill="#10b981"
                className="constellation-node"
                style={{ animationDelay: `${(dx + dy + 2) * 0.25}s` }}
              />
            ))
          )}
          <circle cx="390" cy="150" r="6" fill="#10b981" className="constellation-core" style={{ transformOrigin: "390px 150px" }} />
        </g>

        {/* Connection flow between glyphs */}
        <g>
          <path
            d="M 190 150 Q 250 90 310 150"
            fill="none"
            stroke="rgba(59,130,246,0.4)"
            strokeWidth="1.5"
            className="constellation-line"
            style={{ animationDelay: "0.5s" }}
          />
          <path
            d="M 190 150 Q 250 210 310 150"
            fill="none"
            stroke="rgba(16,185,129,0.4)"
            strokeWidth="1.5"
            className="constellation-line"
            style={{ animationDelay: "1.5s" }}
          />
          {/* Center merge point */}
          <circle cx="250" cy="150" r="3" fill="#fafafa" className="counter-tick" />
        </g>

        {/* Bottom output strip */}
        <rect x="80" y="245" width="340" height="32" rx="4" fill="rgba(16,185,129,0.06)" stroke="rgba(16,185,129,0.25)" />
        <text x="100" y="266" fill="#10b981" fontSize="11" fontFamily="ui-monospace, monospace" letterSpacing="0.05em">
          ✓ VERIFIED
        </text>
        <text x="170" y="266" fill="#a1a1aa" fontSize="11" fontFamily="ui-monospace, monospace">
          claim ⇆ source ⇆ math
        </text>
      </svg>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// SOURCE LEDGER — receipts in a more generic, less-revealing format
// ────────────────────────────────────────────────────────────────────────
function SourceLedger() {
  const sources = [
    { kind: "FILING",      id: "0001067983-25-000412", note: "Insider transaction" },
    { kind: "MACRO",       id: "10Y · 4.42%",          note: "Treasury yield, intraday" },
    { kind: "FUND HOLDING",id: "CIK · 0001336528",     note: "Position initiation" },
    { kind: "QUOTE",       id: "COHR · 87.21",         note: "Live market price" },
    { kind: "EARNINGS",    id: "VKTX · 4Q surprise",   note: "Beat consensus +38%" },
  ];
  return (
    <section id="trust" className="relative border-b border-border-primary/60 bg-bg-surface/30">
      <div className="max-w-[1280px] mx-auto px-6 py-24">
        <div className="grid lg:grid-cols-[1fr_1.4fr] gap-12 items-start">
          <div className="max-w-md">
            <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-4">
              /// SOURCE LEDGER
            </p>
            <h2 className="text-[36px] sm:text-[44px] font-semibold tracking-[-0.02em] leading-[1.05] mb-5">
              Every claim, fully traceable.
            </h2>
            <p className="text-[14px] text-text-tertiary leading-relaxed mb-6">
              Each memo carries a complete ledger of every filing, market quote,
              and data point that shaped it. Open any source. Verify any number.
              Months from now, it still works.
            </p>
            <div className="flex items-center gap-4 text-[11px] text-text-quaternary">
              <span className="font-mono">22 sources avg / memo</span>
              <span>·</span>
              <span className="font-mono">100% citable</span>
            </div>
          </div>

          <div className="rounded-md border border-border-primary bg-bg-surface overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border-primary flex items-center justify-between">
              <span className="text-[10px] font-mono tracking-wider text-text-tertiary">SOURCE LEDGER</span>
              <span className="text-[10px] font-mono text-text-quaternary">22 ENTRIES</span>
            </div>
            <div className="divide-y divide-border-primary/60">
              {sources.map((s) => (
                <div
                  key={s.id}
                  className="grid grid-cols-[110px_1fr_auto] items-center gap-4 px-4 py-2.5 hover:bg-bg-elevated/40 transition-colors"
                >
                  <span className="text-[10px] font-mono tracking-wider text-accent bg-accent/10 border border-accent/20 px-2 py-0.5 rounded text-center">
                    {s.kind}
                  </span>
                  <span className="text-[12px] font-mono text-text-secondary truncate">{s.id}</span>
                  <span className="text-[10px] text-text-quaternary truncate hidden md:block">{s.note}</span>
                </div>
              ))}
            </div>
            <div className="px-4 py-2 border-t border-border-primary flex items-center justify-between text-[10px] font-mono text-text-quaternary">
              <span>+ 17 MORE</span>
              <span className="text-signal-green">● ALL VERIFIED</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// CLOSING CTA
// ────────────────────────────────────────────────────────────────────────
function ClosingCTA({ isSignedIn }: { isSignedIn: boolean }) {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 grid-bg opacity-30" aria-hidden="true" />
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[48rem] h-[24rem] bg-accent/[0.08] blur-[120px] rounded-full" />
      </div>
      <div className="max-w-[1280px] mx-auto px-6 py-28 text-center relative">
        <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-5">
          /// READY WHEN YOU ARE
        </p>
        <h2 className="text-[40px] sm:text-[52px] font-semibold tracking-[-0.02em] leading-[1.05] mb-5">
          Build your next memo
          <br />
          in under ten minutes.
        </h2>
        <p className="text-[14px] text-text-tertiary max-w-md mx-auto mb-9 leading-relaxed">
          Sign up takes a minute. Your first memo runs immediately.
        </p>
        {isSignedIn ? (
          <Link
            href="/dashboard"
            className="inline-block px-6 py-3 rounded-md bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors"
          >
            Go to dashboard
          </Link>
        ) : (
          <Link
            href="/sign-up"
            className="inline-block px-6 py-3 rounded-md bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors"
          >
            Get started
          </Link>
        )}
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────────
// FOOTER
// ────────────────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer className="border-t border-border-primary/60 mt-auto">
      <div className="max-w-[1280px] mx-auto px-6 py-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-[11px] font-mono tracking-wider text-text-quaternary">
        <div className="flex items-center gap-5">
          <span className="font-semibold text-text-secondary">
            alpha<span className="text-accent">engine</span>
          </span>
          <span>© {new Date().getFullYear()}</span>
        </div>
        <div className="flex items-center gap-6">
          <a href="#product" className="hover:text-text-secondary transition-colors">PRODUCT</a>
          <a href="#intelligence" className="hover:text-text-secondary transition-colors">INTELLIGENCE</a>
          <a href="#trust" className="hover:text-text-secondary transition-colors">TRUST</a>
          <Link href="/sign-in" className="hover:text-text-secondary transition-colors">SIGN IN</Link>
        </div>
      </div>
    </footer>
  );
}
