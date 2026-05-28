"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import Link from "next/link";
import { api } from "@/lib/api";
import { BrandConstellation } from "@/components/BrandConstellation";

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
  { value: "SPY", label: "S&P 500 (SPY)", desc: "Default for US equity strategies." },
  { value: "QQQ", label: "Nasdaq 100 (QQQ)", desc: "Tech-tilted growth benchmark." },
  { value: "IWM", label: "Russell 2000 (IWM)", desc: "Small-cap focus." },
  { value: "ACWI", label: "MSCI ACWI", desc: "Global equity benchmark." },
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

  // Pre-populate name + email from Clerk on first mount
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

  const next = () => {
    const i = STEPS.indexOf(step);
    if (i < STEPS.length - 1) setStep(STEPS[i + 1]);
  };
  const back = () => {
    const i = STEPS.indexOf(step);
    if (i > 0) setStep(STEPS[i - 1]);
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
      router.replace("/dashboard");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not save your profile.";
      setError(msg);
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen w-full grid lg:grid-cols-[1.05fr_1fr] bg-bg-primary text-text-primary">
      {/* LEFT — brand panel reused */}
      <aside className="relative hidden lg:flex flex-col justify-between p-12 overflow-hidden border-r border-border-primary bg-gradient-to-br from-bg-primary via-bg-primary to-[#0a0e1a]">
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          <div className="absolute -top-40 -left-40 w-[42rem] h-[42rem] rounded-full bg-accent/[0.10] blur-[120px]" />
          <div className="absolute bottom-0 -right-40 w-[36rem] h-[36rem] rounded-full bg-signal-green/[0.06] blur-[120px]" />
        </div>
        <BrandConstellation />
        <Link
          href="/"
          className="relative z-10 inline-block self-start text-[17px] font-semibold tracking-tight hover:opacity-90 transition-opacity"
        >
          alpha<span className="text-accent">engine</span>
        </Link>
        <div className="relative z-10 max-w-md fade-up-1">
          <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-5">
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
          {/* Progress bar */}
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

          {/* Step content */}
          <div className="flex-1">
            {step === "role" && (
              <StepFrame
                eyebrow="About you"
                title={`Welcome${user?.firstName ? `, ${user.firstName}` : ""}.`}
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
                      className={`rounded-xl border px-4 py-3 text-left transition-all ${
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
                    className="w-full pl-8 pr-4 h-12 bg-bg-surface border border-border-primary rounded-xl text-[14px] font-mono text-text-primary focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 transition-colors"
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
                subtitle="This shapes the Strategist's defaults — long-only avoids shorts, market-neutral pairs everything, macro reaches into rates/FX/commodities."
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
                      className={`rounded-xl border p-3 text-left transition-all ${
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
              <StepFrame
                eyebrow="All set"
                title="You're ready to go."
                subtitle="Your first memo runs in under ten minutes. Head to the dashboard or jump straight into a new analysis."
              >
                <div className="rounded-2xl border border-border-primary bg-bg-surface p-6 space-y-3 mb-6">
                  <SummaryRow label="Role" value={ROLES.find((r) => r.value === role)?.label || "—"} />
                  <SummaryRow label="Portfolio size" value={formatUSD(portfolioSize)} />
                  <SummaryRow
                    label="Mandate"
                    value={MANDATES.find((m) => m.value === mandate)?.label || "—"}
                  />
                  <SummaryRow
                    label="Benchmark"
                    value={BENCHMARKS.find((b) => b.value === benchmark)?.label || "—"}
                  />
                </div>
                <p className="text-[12px] text-text-quaternary text-center">
                  You can update any of this in Settings later.
                </p>
              </StepFrame>
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
                onClick={next}
                disabled={!role}
                className="px-5 py-2.5 rounded-xl bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue →
              </button>
            )}
            {step === "portfolio" && (
              <button
                onClick={next}
                disabled={portfolioSize <= 0}
                className="px-5 py-2.5 rounded-xl bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue →
              </button>
            )}
            {step === "mandate" && (
              <button
                onClick={next}
                className="px-5 py-2.5 rounded-xl bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-100 transition-colors"
              >
                Review →
              </button>
            )}
            {step === "done" && (
              <button
                onClick={handleFinish}
                disabled={submitting}
                className="ml-auto px-5 py-2.5 rounded-xl bg-accent text-white text-[13px] font-semibold hover:bg-accent/90 disabled:opacity-60 transition-colors"
              >
                {submitting ? "Saving…" : "Go to dashboard"}
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
    <div key={title}>
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
      className={`w-full text-left rounded-xl border p-4 transition-all ${
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

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-[13px] py-1.5 border-b border-border-primary/40 last:border-b-0">
      <span className="text-text-tertiary">{label}</span>
      <span className="text-text-primary font-medium">{value}</span>
    </div>
  );
}

function formatUSD(n: number): string {
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}
