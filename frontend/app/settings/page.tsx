"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useUser } from "@clerk/nextjs";
import { api } from "@/lib/api";
import { TerminalHeader } from "@/components/TerminalHeader";
import { RiskGatesEditor } from "@/components/RiskGatesEditor";

interface SystemInfo {
  app: { version: string; env: string; commit: string | null };
  database: { ok: boolean; dialect?: string };
  data_sources: { name: string; configured: boolean; note: string }[];
  auth: { provider: string; issuer_configured: boolean };
  risk_parameters: { label: string; value: string; description: string }[];
}

type Role = "pm" | "analyst" | "allocator" | "other";
type Mandate = "long_only" | "long_short" | "market_neutral" | "macro" | "multi_strat";
type Benchmark = "SPY" | "QQQ" | "IWM" | "ACWI";

interface Profile {
  full_name: string | null;
  email: string | null;
  role: string | null;
  portfolio_size_usd: number | null;
  benchmark: string;
  mandate: string;
  onboarded_at: string | null;
}

const ROLES: { value: Role; label: string }[] = [
  { value: "pm", label: "Portfolio Manager" },
  { value: "analyst", label: "Analyst" },
  { value: "allocator", label: "Allocator" },
  { value: "other", label: "Other" },
];
const MANDATES: { value: Mandate; label: string; desc: string }[] = [
  { value: "long_only", label: "Long Only", desc: "Outright positions only." },
  { value: "long_short", label: "Long / Short", desc: "Both sides, directional + pairs." },
  { value: "market_neutral", label: "Market Neutral", desc: "Beta / dollar neutral." },
  { value: "macro", label: "Macro", desc: "Cross-asset themes." },
  { value: "multi_strat", label: "Multi-Strategy", desc: "Mix of styles." },
];
const BENCHMARKS: { value: Benchmark; label: string }[] = [
  { value: "SPY", label: "S&P 500" },
  { value: "QQQ", label: "Nasdaq 100" },
  { value: "IWM", label: "Russell 2000" },
  { value: "ACWI", label: "MSCI ACWI" },
];

export default function SettingsPage() {
  const { user } = useUser();
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [showSystem, setShowSystem] = useState(false);

  // Editable form state — kept separate from `profile` so user can revert
  const [role, setRole] = useState<Role>("pm");
  const [portfolioSize, setPortfolioSize] = useState<number>(1_000_000);
  const [mandate, setMandate] = useState<Mandate>("long_short");
  const [benchmark, setBenchmark] = useState<Benchmark>("SPY");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.systemInfo().catch(() => null),
      api.myProfile().catch(() => null),
    ]).then(([i, p]) => {
      if (cancelled) return;
      if (i) setInfo(i as SystemInfo);
      const profileData = (p as { profile: Profile | null } | null)?.profile ?? null;
      if (profileData) {
        setProfile(profileData);
        if (profileData.role && (ROLES.map((r) => r.value) as string[]).includes(profileData.role)) {
          setRole(profileData.role as Role);
        }
        if (profileData.portfolio_size_usd && profileData.portfolio_size_usd > 0) {
          setPortfolioSize(profileData.portfolio_size_usd);
        }
        if (profileData.mandate && (MANDATES.map((m) => m.value) as string[]).includes(profileData.mandate)) {
          setMandate(profileData.mandate as Mandate);
        }
        if (profileData.benchmark && (BENCHMARKS.map((b) => b.value) as string[]).includes(profileData.benchmark)) {
          setBenchmark(profileData.benchmark as Benchmark);
        }
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaveMessage(null);
    setApiError(null);
    try {
      await api.updateMyProfile({
        role,
        portfolio_size_usd: portfolioSize,
        mandate,
        benchmark,
      });
      setSaveMessage("Profile saved.");
      // Clear success message after 2s
      setTimeout(() => setSaveMessage(null), 2500);
    } catch (e: unknown) {
      setApiError(e instanceof Error ? e.message : "Could not save profile.");
    } finally {
      setSaving(false);
    }
  };

  const isDirty =
    !!profile &&
    (role !== profile.role ||
      portfolioSize !== profile.portfolio_size_usd ||
      mandate !== profile.mandate ||
      benchmark !== profile.benchmark);

  const dbOk = info?.database.ok ?? false;
  const env = info?.app.env ?? "unknown";

  return (
    <div className="p-8 max-w-3xl mx-auto">
      {apiError && (
        <div className="mb-6 flex items-start justify-between rounded-md border border-signal-red/25 bg-signal-red/[0.06] p-3">
          <div>
            <p className="text-xs font-medium text-signal-red">Notice</p>
            <p className="text-[11px] text-text-tertiary mt-0.5">{apiError}</p>
          </div>
          <button
            onClick={() => setApiError(null)}
            className="text-text-quaternary hover:text-text-primary text-xs px-2"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <TerminalHeader
        eyebrow="SETTINGS"
        title="Profile and platform"
        sub="Your profile drives risk sizing, benchmark, and Strategist defaults. Risk gates below are per-user overrides applied across every quant module."
        className="mb-8"
      />

      {/* ───────────────────────── Profile / account ────────────────── */}
      <div className="rounded-md border border-border-primary bg-bg-surface p-5 mb-6">
        <h2 className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-4">
          <span className="text-accent">///</span> ACCOUNT
        </h2>
        <div className="flex items-center gap-3">
          {user?.imageUrl ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={user.imageUrl}
              alt={user.fullName ?? ""}
              className="w-10 h-10 rounded-full object-cover"
            />
          ) : (
            <span className="w-10 h-10 rounded-full bg-accent/20 grid place-items-center text-[13px] font-semibold text-accent">
              {(user?.firstName ?? "?").charAt(0).toUpperCase()}
            </span>
          )}
          <div>
            <p className="text-[14px] font-medium text-text-primary">
              {user?.fullName || "—"}
            </p>
            <p className="text-[12px] text-text-tertiary">
              {user?.primaryEmailAddress?.emailAddress || "—"}
            </p>
          </div>
        </div>
      </div>

      {/* ───────────────────────── Profile editor ───────────────────── */}
      <div className="rounded-md border border-border-primary bg-bg-surface p-5 mb-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-2">
              <span className="text-accent">///</span> PROFILE
            </h2>
            <p className="text-[12px] text-text-tertiary">
              Changes drive Strategist defaults and position sizing math.
            </p>
          </div>
          {profile?.onboarded_at && (
            <span className="text-[10px] font-mono text-text-quaternary">
              ONBOARDED {new Date(profile.onboarded_at).toLocaleDateString()}
            </span>
          )}
        </div>

        {loading ? (
          <p className="text-[12px] text-text-quaternary py-4">Loading profile…</p>
        ) : (
          <div className="space-y-6">
            {/* Role */}
            <FieldRow label="Role" hint="Drives default views.">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {ROLES.map((r) => (
                  <button
                    key={r.value}
                    onClick={() => setRole(r.value)}
                    className={`rounded-md border px-3 py-2 text-[12px] font-medium transition-all ${
                      role === r.value
                        ? "border-accent bg-accent/[0.08] text-accent"
                        : "border-border-primary bg-bg-primary text-text-secondary hover:border-zinc-600"
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </FieldRow>

            {/* Portfolio size */}
            <FieldRow
              label="Portfolio size"
              hint="USD basis used to convert position percentages into dollar exposure."
            >
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[12px] text-text-tertiary">
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
                  className="w-full pl-7 pr-3 h-10 bg-bg-primary border border-border-primary rounded-md text-[13px] font-mono text-text-primary focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 transition-colors"
                />
              </div>
              <p className="mt-1 text-[10px] text-text-quaternary">
                Currently {formatUSD(portfolioSize)}
              </p>
            </FieldRow>

            {/* Mandate */}
            <FieldRow label="Mandate" hint="Shapes long-only vs long-short vs market-neutral defaults.">
              <div className="space-y-1.5">
                {MANDATES.map((m) => (
                  <button
                    key={m.value}
                    onClick={() => setMandate(m.value)}
                    className={`w-full text-left rounded-md border px-3 py-2.5 transition-all ${
                      mandate === m.value
                        ? "border-accent bg-accent/[0.08]"
                        : "border-border-primary bg-bg-primary hover:border-zinc-600"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <p
                          className={`text-[13px] font-semibold mb-0 ${
                            mandate === m.value ? "text-accent" : "text-text-primary"
                          }`}
                        >
                          {m.label}
                        </p>
                        <p className="text-[11px] text-text-tertiary">{m.desc}</p>
                      </div>
                      <div
                        className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors ${
                          mandate === m.value ? "border-accent bg-accent" : "border-border-primary"
                        }`}
                      >
                        {mandate === m.value && (
                          <svg width="8" height="8" viewBox="0 0 10 10" fill="none">
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
                ))}
              </div>
            </FieldRow>

            {/* Benchmark */}
            <FieldRow label="Benchmark" hint="Default ticker for relative performance + attribution.">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {BENCHMARKS.map((b) => (
                  <button
                    key={b.value}
                    onClick={() => setBenchmark(b.value)}
                    className={`rounded-md border px-3 py-2 text-[12px] font-medium transition-all ${
                      benchmark === b.value
                        ? "border-accent bg-accent/[0.08] text-accent"
                        : "border-border-primary bg-bg-primary text-text-secondary hover:border-zinc-600"
                    }`}
                  >
                    {b.label}
                  </button>
                ))}
              </div>
            </FieldRow>

            <div className="flex items-center justify-end gap-3 pt-2 border-t border-border-primary">
              {saveMessage && (
                <span className="text-[11px] text-signal-green">{saveMessage}</span>
              )}
              <button
                onClick={handleSave}
                disabled={saving || !isDirty}
                className="px-4 py-2 rounded-md bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {saving ? "Saving…" : isDirty ? "Save changes" : "Saved"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ───────────────────────── Risk gates (editable) ────────────── */}
      <div className="rounded-md border border-border-primary bg-bg-surface p-5 mb-6">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary">
            <span className="text-accent">///</span> RISK GATES
          </h2>
          <Link
            href="/risk"
            className="text-[10px] font-mono tracking-wider text-text-tertiary hover:text-text-primary transition-colors"
          >
            LIVE DASHBOARD →
          </Link>
        </div>
        <p className="text-[12px] text-text-tertiary mb-4">
          Per-user overrides for pre-trade risk checks, sizing limits, and the optimizer.
        </p>
        <RiskGatesEditor />
      </div>

      {/* ───────────────────────── System info (collapsible) ────────── */}
      <div className="rounded-md border border-border-primary bg-bg-surface overflow-hidden">
        <button
          onClick={() => setShowSystem((v) => !v)}
          className="w-full flex items-center justify-between px-5 py-4 hover:bg-bg-elevated/40 transition-colors"
        >
          <div className="text-left">
            <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-1">
              <span className="text-accent">///</span> SYSTEM
            </p>
            <p className="text-[12px] text-text-tertiary">
              Environment, data sources, risk parameters.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                dbOk
                  ? "border-signal-green/30 bg-signal-green/[0.08] text-signal-green"
                  : "border-signal-red/30 bg-signal-red/[0.08] text-signal-red"
              }`}
            >
              {dbOk ? "DB OK" : "DB ?"}
            </span>
            <span className="text-text-quaternary text-[13px]">
              {showSystem ? "−" : "+"}
            </span>
          </div>
        </button>

        {showSystem && (
          <div className="border-t border-border-primary p-5 space-y-5">
            <div>
              <p className="text-[10px] font-mono tracking-wider text-text-quaternary mb-2">
                STATUS
              </p>
              <div className="space-y-1.5 text-[12px]">
                <div className="flex justify-between">
                  <span className="text-text-tertiary">Environment</span>
                  <span className="font-mono text-text-secondary capitalize">{env}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-tertiary">Database</span>
                  <span className="font-mono text-text-secondary">
                    {info?.database.dialect || "—"}
                  </span>
                </div>
                {info?.app.commit && (
                  <div className="flex justify-between">
                    <span className="text-text-tertiary">Build</span>
                    <span className="font-mono text-text-secondary">{info.app.commit}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-text-tertiary">Auth</span>
                  <span className="font-mono text-text-secondary">
                    {info?.auth.provider || "Clerk"}{" "}
                    {info?.auth.issuer_configured ? "" : "(not configured)"}
                  </span>
                </div>
              </div>
            </div>

            {info?.data_sources && info.data_sources.length > 0 && (
              <div>
                <p className="text-[10px] font-mono tracking-wider text-text-quaternary mb-2">
                  DATA SOURCES
                </p>
                <div className="space-y-1.5 text-[12px]">
                  {info.data_sources.map((s) => (
                    <div key={s.name} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            s.configured ? "bg-signal-green" : "bg-signal-yellow"
                          }`}
                        />
                        <span className="text-text-tertiary">{s.name}</span>
                      </div>
                      <span className="text-[10px] font-mono text-text-quaternary">
                        {s.configured ? "ACTIVE" : "MISSING KEY"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Read-only risk parameters previously listed here have moved to
                the editable RISK GATES section above. */}
          </div>
        )}
      </div>
    </div>
  );
}

function FieldRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2">
        <p className="text-[12px] font-medium text-text-primary">{label}</p>
        {hint && <p className="text-[11px] text-text-tertiary">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

function formatUSD(n: number): string {
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}
