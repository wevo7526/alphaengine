"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import Link from "next/link";
import { api } from "@/lib/api";

type Role = "pm" | "analyst" | "allocator" | "other";
type Mandate = "long_only" | "long_short" | "market_neutral" | "macro" | "multi_strat";
type Benchmark = "SPY" | "QQQ" | "IWM" | "ACWI";

const STEPS = ["role", "portfolio", "mandate", "done"] as const;
type Step = (typeof STEPS)[number];

const ROLES: { value: Role; label: string; desc: string }[] = [
  { value: "pm", label: "Portfolio Manager", desc: "Run a book, take positions." },
  { value: "analyst", label: "Analyst", desc: "Research ideas, support a PM." },
  { value: "allocator", label: "Allocator", desc: "Evaluate managers, allocate capital." },
  { value: "other", label: "Other", desc: "Strategist, family office, retail." },
];

const MANDATES: { value: Mandate; label: string; desc: string }[] = [
  { value: "long_only", label: "Long Only", desc: "Outright positions, no shorts." },
  { value: "long_short", label: "Long / Short", desc: "Both sides, directional and pairs." },
  { value: "market_neutral", label: "Market Neutral", desc: "Beta-neutral, dollar-neutral book." },
  { value: "macro", label: "Macro", desc: "Cross-asset themes, rates, FX, commodities." },
  { value: "multi_strat", label: "Multi-Strategy", desc: "Mix of styles across the book." },
];

const BENCHMARKS: { value: Benchmark; label: string; desc: string }[] = [
  { value: "SPY", label: "S&P 500", desc: "Default US equity." },
  { value: "QQQ", label: "Nasdaq 100", desc: "Tech-tilted growth." },
  { value: "IWM", label: "Russell 2000", desc: "Small-cap focus." },
  { value: "ACWI", label: "MSCI ACWI", desc: "Global equity." },
];

const PORTFOLIO_PRESETS: { label: string; value: number }[] = [
  { label: "$100K", value: 100_000 },
  { label: "$1M", value: 1_000_000 },
  { label: "$10M", value: 10_000_000 },
  { label: "$100M", value: 100_000_000 },
];

export default function OnboardingPage() {
  const router = useRouter();
  const { user, isLoaded } = useUser();

  const [step, setStep] = useState<Step>("role");
  const [role, setRole] = useState<Role | null>(null);
  const [portfolioSize, setPortfolioSize] = useState<number>(1_000_000);
  const [mandate, setMandate] = useState<Mandate>("long_short");
  const [benchmark, setBenchmark] = useState<Benchmark>("SPY");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Each step's fade-in key — re-mounts the content so the entrance
  // animation re-plays on every step change.
  const [stepKey, setStepKey] = useState(0);

  // Pre-populate name + email from Clerk on first mount. This also
  // creates the row in user_profiles so per-step saves can update it.
  useEffect(() => {
    if (!isLoaded || !user) return;
    api
      .updateMyProfile({
        full_name: user.fullName || undefined,
        email: user.primaryEmailAddress?.emailAddress || undefined,
      })
      .catch(() => {
        /* non-blocking */
      });
  }, [isLoaded, user]);

  const idx = STEPS.indexOf(step);
  const total = STEPS.length - 1; // exclude "done" from the progress count

  // Per-step save: persists the user's selections after every step so a
  // mid-flow refresh / close doesn't lose progress. Non-blocking — UI
  // moves on immediately, save is fire-and-forget.
  const savePartial = (fields: Parameters<typeof api.updateMyProfile>[0]) => {
    api.updateMyProfile(fields).catch(() => {
      /* non-blocking; complete() at the end is the authoritative write */
    });
  };

  const goTo = (s: Step) => {
    setStep(s);
    setStepKey((k) => k + 1);
  };
  const next = () => {
    const i = STEPS.indexOf(step);
    if (i < STEPS.length - 1) goTo(STEPS[i + 1]);
  };
  const back = () => {
    const i = STEPS.indexOf(step);
    if (i > 0) goTo(STEPS[i - 1]);
  };

  const handleRoleNext = () => {
    if (!role) return;
    savePartial({ role });
    next();
  };
  const handlePortfolioNext = () => {
    if (portfolioSize <= 0) return;
    savePartial({ portfolio_size_usd: portfolioSize });
    next();
  };
  const handleMandateNext = () => {
    savePartial({ mandate, benchmark });
    next();
  };

  const handleFinish = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.completeOnboarding({
        role: role || "other",
        portfolio_size_usd: portfolioSize,
        mandate,
        benchmark,
        full_name: user?.fullName || undefined,
        email: user?.primaryEmailAddress?.emailAddress || undefined,
      });
      // Hard navigation (not router.replace) so SessionGuard re-mounts
      // and re-fetches /api/me/profile. A client-side route change keeps
      // the stale `isOnboarded: false` cache and bounces the user back
      // here in a redirect loop.
      if (typeof window !== "undefined") {
        window.location.href = "/dashboard";
      } else {
        router.replace("/dashboard");
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not save your profile.";
      setError(msg);
      setSubmitting(false);
    }
  };

  const greetingName = user?.firstName || user?.fullName?.split(" ")[0];
  const avatarUrl = user?.imageUrl;

  return (
    <div className="min-h-screen w-full grid lg:grid-cols-[1.05fr_1fr] bg-bg-primary text-text-primary">
      {/* LEFT — brand panel */}
      <aside className="relative hidden lg:flex flex-col justify-between p-12 overflow-hidden border-r border-border-primary bg-bg-surface/30">
        {/* Faint structural grid only — flat institutional, no glow/constellation. */}
        <div className="absolute inset-0 grid-bg opacity-[0.10]" aria-hidden="true" />
        <Link
          href="/"
          className="relative z-10 inline-block self-start text-[17px] font-semibold tracking-tight hover:opacity-90 transition-opacity"
        >
          alpha<span className="text-brand">engine</span>
        </Link>

        {/* Identity card — surfaces who is signing in (avatar + name) */}
        <div className="relative z-10 max-w-md fade-up-1">
          {(avatarUrl || greetingName) && (
            <div className="mb-6 inline-flex items-center gap-3 rounded-full border border-border-primary bg-bg-surface/70 backdrop-blur px-3 py-1.5">
              {avatarUrl ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={avatarUrl}
                  alt={greetingName ?? "you"}
                  className="w-6 h-6 rounded-full object-cover"
                />
              ) : (
                <span className="w-6 h-6 rounded-full bg-accent/20 grid place-items-center text-[10px] font-semibold text-accent">
                  {(greetingName ?? "?").charAt(0).toUpperCase()}
                </span>
              )}
              <span className="text-[12px] text-text-secondary">
                Signed in as <span className="text-text-primary font-medium">{greetingName ?? "you"}</span>
              </span>
            </div>
          )}

          <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-4">
            Setting things up
          </p>
          <h2 className="text-[40px] xl:text-[44px] font-semibold tracking-tight leading-[1.05] mb-5">
            A few quick details, and you&apos;re running.
          </h2>
          <p className="text-[14px] text-text-tertiary leading-relaxed max-w-sm">
            We&apos;ll tailor your dashboard, risk gates, and benchmark to how
            you actually work. You can change any of this later in Settings.
          </p>
        </div>

        <div className="relative z-10 text-[11px] text-text-quaternary">
          © {new Date().getFullYear()} Alpha Engine
        </div>
      </aside>

      {/* RIGHT — wizard */}
      <section className="relative flex flex-col p-6 sm:p-12 overflow-y-auto">
        <div className="w-full max-w-[480px] mx-auto flex-1 flex flex-col">
          {/* Progress bar — hidden on the celebratory done step */}
          {step !== "done" && (
            <div className="mb-10 fade-up-1">
              <div className="flex items-center justify-between text-[11px] text-text-quaternary mb-2 uppercase tracking-wider">
                <span>
                  Step {idx + 1} of {total}
                </span>
                <span>{Math.round(((idx + 1) / total) * 100)}%</span>
              </div>
              <div className="h-1 rounded-full bg-bg-surface overflow-hidden">
                <div
                  className="h-full bg-accent rounded-full transition-all duration-500 ease-out"
                  style={{ width: `${((idx + 1) / total) * 100}%` }}
                />
              </div>
            </div>
          )}

          {/* Step content with fresh entrance animation via stepKey */}
          <div key={stepKey} className="flex-1">
            {step === "role" && (
              <StepFrame
                eyebrow="About you"
                title={`Welcome${greetingName ? `, ${greetingName}` : ""}.`}
                subtitle="Which role best describes how you'll use Alpha Engine?"
              >
                <div className="space-y-2">
                  {ROLES.map((r) => (
                    <SelectCard
                      key={r.value}
                      active={role === r.value}
                      onClick={() => setRole(r.value)}
                      title={r.label}
                      desc={r.desc}
                    />
                  ))}
                </div>
              </StepFrame>
            )}

            {step === "portfolio" && (
              <StepFrame
                eyebrow="Portfolio sizing"
                title="What portfolio should we size against?"
                subtitle="We use this to convert position percentages into dollar exposure. You can change it any time."
              >
                <div className="grid grid-cols-2 gap-2 mb-4">
                  {PORTFOLIO_PRESETS.map((p) => (
                    <button
                      key={p.value}
                      onClick={() => setPortfolioSize(p.value)}
                      className={`rounded-sm border px-4 py-3 text-left transition-all ${
                        portfolioSize === p.value
                          ? "border-accent bg-accent/[0.08]"
                          : "border-border-primary bg-bg-surface hover:border-zinc-600"
                      }`}
                    >
                      <p
                        className={`text-[18px] font-semibold ${
                          portfolioSize === p.value ? "text-accent" : "text-text-primary"
                        }`}
                      >
                        {p.label}
                      </p>
                    </button>
                  ))}
                </div>
                <label className="block text-[11px] uppercase tracking-wider text-text-quaternary mb-2">
                  Or set a custom value
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-[13px] text-text-tertiary">
                    $
                  </span>
                  <input
                    type="number"
                    value={portfolioSize}
                    onChange={(e) =>
                      setPortfolioSize(Math.max(0, Number(e.target.value) || 0))
                    }
                    step={10000}
                    min={0}
                    className="w-full pl-8 pr-4 h-12 bg-bg-surface border border-border-primary rounded-sm text-[14px] font-mono text-text-primary focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 transition-colors"
                  />
                </div>
                <p className="mt-3 text-[11px] text-text-quaternary">
                  Currently sized at{" "}
                  <span className="font-mono text-text-secondary">
                    {formatUSD(portfolioSize)}
                  </span>
                </p>
              </StepFrame>
            )}

            {step === "mandate" && (
              <StepFrame
                eyebrow="Investment mandate"
                title="How do you run money?"
                subtitle="This shapes the Strategist's defaults. Long-only avoids shorts, market-neutral pairs everything, macro reaches into rates, FX, and commodities."
              >
                <div className="space-y-2 mb-8">
                  {MANDATES.map((m) => (
                    <SelectCard
                      key={m.value}
                      active={mandate === m.value}
                      onClick={() => setMandate(m.value)}
                      title={m.label}
                      desc={m.desc}
                    />
                  ))}
                </div>
                <label className="block text-[11px] uppercase tracking-wider text-text-quaternary mb-3">
                  Benchmark
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {BENCHMARKS.map((b) => (
                    <button
                      key={b.value}
                      onClick={() => setBenchmark(b.value)}
                      className={`rounded-sm border p-3 text-left transition-all ${
                        benchmark === b.value
                          ? "border-accent bg-accent/[0.08]"
                          : "border-border-primary bg-bg-surface hover:border-zinc-600"
                      }`}
                    >
                      <p
                        className={`text-[13px] font-semibold mb-0.5 ${
                          benchmark === b.value ? "text-accent" : "text-text-primary"
                        }`}
                      >
                        {b.label}
                      </p>
                      <p className="text-[11px] text-text-tertiary">{b.desc}</p>
                    </button>
                  ))}
                </div>
              </StepFrame>
            )}

            {step === "done" && (
              <DoneReveal
                greetingName={greetingName}
                role={role}
                portfolioSize={portfolioSize}
                mandate={mandate}
                benchmark={benchmark}
              />
            )}
          </div>

          {/* Footer actions */}
          <div className="mt-10 flex items-center justify-between">
            {step !== "role" && step !== "done" ? (
              <button
                onClick={back}
                disabled={submitting}
                className="text-[13px] text-text-tertiary hover:text-text-primary transition-colors disabled:opacity-40"
              >
                ← Back
              </button>
            ) : (
              <span />
            )}

            {step === "role" && (
              <button
                onClick={handleRoleNext}
                disabled={!role}
                className="px-5 py-2.5 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue →
              </button>
            )}
            {step === "portfolio" && (
              <button
                onClick={handlePortfolioNext}
                disabled={portfolioSize <= 0}
                className="px-5 py-2.5 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue →
              </button>
            )}
            {step === "mandate" && (
              <button
                onClick={handleMandateNext}
                className="px-5 py-2.5 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-100 transition-colors"
              >
                Review →
              </button>
            )}
            {step === "done" && (
              <button
                onClick={handleFinish}
                disabled={submitting}
                className="ml-auto px-5 py-2.5 rounded-sm bg-accent text-bg-primary text-[13px] font-semibold hover:bg-accent/90 disabled:opacity-60 transition-colors"
              >
                {submitting ? "Saving…" : "Enter Alpha Engine →"}
              </button>
            )}
          </div>

          {error && (
            <p className="mt-4 text-[12px] text-signal-red text-center" role="alert">
              {error}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function StepFrame({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-7 fade-up-1">
        <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-3">
          {eyebrow}
        </p>
        <h1 className="text-[26px] font-semibold tracking-tight text-text-primary mb-2 leading-tight">
          {title}
        </h1>
        <p className="text-[13px] text-text-tertiary leading-relaxed">{subtitle}</p>
      </div>
      <div className="fade-up-2">{children}</div>
    </div>
  );
}

function SelectCard({
  active,
  onClick,
  title,
  desc,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  desc: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-sm border p-4 transition-all ${
        active
          ? "border-accent bg-accent/[0.08]"
          : "border-border-primary bg-bg-surface hover:border-zinc-600"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <p
            className={`text-[14px] font-semibold mb-0.5 ${
              active ? "text-accent" : "text-text-primary"
            }`}
          >
            {title}
          </p>
          <p className="text-[12px] text-text-tertiary leading-snug">{desc}</p>
        </div>
        <div
          className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors ${
            active ? "border-accent bg-accent" : "border-border-primary"
          }`}
        >
          {active && (
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <path
                d="M2 5 L4 7 L8 3"
                stroke="white"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </div>
      </div>
    </button>
  );
}

/**
 * Celebratory final step. Replaces the previous flat summary card with
 * a brand reveal: large hero copy, identity confirmation, then a tight
 * spec sheet of what they chose and a "what comes next" teaser.
 */
function DoneReveal({
  greetingName,
  role,
  portfolioSize,
  mandate,
  benchmark,
}: {
  greetingName?: string;
  role: Role | null;
  portfolioSize: number;
  mandate: Mandate;
  benchmark: Benchmark;
}) {
  const roleLabel = ROLES.find((r) => r.value === role)?.label || "—";
  const mandateLabel = MANDATES.find((m) => m.value === mandate)?.label || "—";
  const benchmarkLabel = BENCHMARKS.find((b) => b.value === benchmark)?.label || "—";
  return (
    <div>
      <div className="fade-up-1">
        <div className="inline-flex items-center gap-2 mb-5 px-2.5 py-1 rounded-full border border-signal-green/30 bg-signal-green/[0.08] text-signal-green text-[10px] font-mono tracking-[0.18em]">
          <span className="w-1.5 h-1.5 rounded-full bg-signal-green animate-pulse" />
          PROFILE READY
        </div>
        <h1 className="text-[32px] font-semibold tracking-tight text-text-primary mb-2 leading-tight">
          You&apos;re set{greetingName ? `, ${greetingName}` : ""}.
        </h1>
        <p className="text-[14px] text-text-tertiary leading-relaxed mb-7">
          Your dashboard, risk gates, and benchmark are tuned to how you run
          money. You can change any of this any time from Settings.
        </p>
      </div>

      <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden fade-up-2">
        <div className="px-4 py-2.5 border-b border-border-primary bg-bg-primary/40">
          <p className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">
            YOUR PROFILE
          </p>
        </div>
        <div className="divide-y divide-border-primary/40">
          <SummaryRow label="Role" value={roleLabel} />
          <SummaryRow label="Portfolio size" value={formatUSD(portfolioSize)} />
          <SummaryRow label="Mandate" value={mandateLabel} />
          <SummaryRow label="Benchmark" value={benchmarkLabel} />
        </div>
      </div>

      <div className="mt-6 grid grid-cols-3 gap-2 fade-up-3">
        {[
          { tag: "STEP 1", label: "Run an analysis" },
          { tag: "STEP 2", label: "Pick a trade" },
          { tag: "STEP 3", label: "Watch the receipts" },
        ].map((s) => (
          <div
            key={s.tag}
            className="rounded-sm border border-border-primary bg-bg-surface px-3 py-3"
          >
            <p className="text-[9px] font-mono tracking-wider text-text-quaternary mb-1">
              {s.tag}
            </p>
            <p className="text-[12px] text-text-secondary leading-tight">{s.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <span className="text-[12px] text-text-tertiary">{label}</span>
      <span className="text-[13px] text-text-primary font-medium">{value}</span>
    </div>
  );
}

function formatUSD(n: number): string {
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}
