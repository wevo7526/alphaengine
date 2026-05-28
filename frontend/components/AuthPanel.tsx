"use client";

import Link from "next/link";
import { GoogleButton } from "@/components/GoogleButton";
import { BrandConstellation } from "@/components/BrandConstellation";

/**
 * Two-sided auth panel used by both /sign-in and /sign-up.
 *
 * Left (lg+): brand panel with the BrandConstellation as the visual
 *             centerpiece, hero copy overlaid on top, gradient ambient
 *             orbs in the background. Footer line at the bottom.
 * Right     : auth controls — tab switcher, heading, Google button,
 *             switch link, fine print. Entrance animations stagger the
 *             elements so the page feels alive on mount.
 *
 * `mode` drives the active tab and the Clerk flow (signIn vs signUp).
 */
export function AuthPanel({ mode }: { mode: "signin" | "signup" }) {
  return (
    <div className="min-h-screen w-full grid lg:grid-cols-[1.05fr_1fr] bg-bg-primary text-text-primary">
      {/* ─── LEFT: BRAND PANEL ─────────────────────────────────────────── */}
      <aside className="relative hidden lg:flex flex-col justify-between p-12 overflow-hidden border-r border-border-primary bg-gradient-to-br from-bg-primary via-bg-primary to-[#0a0e1a]">
        {/* Ambient gradient orbs (additional depth on top of base gradient) */}
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          <div className="absolute -top-40 -left-40 w-[42rem] h-[42rem] rounded-full bg-accent/[0.10] blur-[120px]" />
          <div className="absolute bottom-0 -right-40 w-[36rem] h-[36rem] rounded-full bg-signal-green/[0.06] blur-[120px]" />
        </div>

        {/* The animated constellation — sits behind copy */}
        <BrandConstellation />

        {/* Top: brand mark */}
        <Link
          href="/"
          className="relative z-10 inline-block self-start text-[17px] font-semibold tracking-tight hover:opacity-90 transition-opacity"
        >
          alpha<span className="text-accent">engine</span>
        </Link>

        {/* Center-ish: hero copy. Sits above the constellation. */}
        <div className="relative z-10 max-w-md fade-up-1">
          <p className="text-[11px] uppercase tracking-[0.2em] text-text-quaternary mb-5">
            For L/S equity &amp; macro PMs
          </p>
          <h2 className="text-[40px] xl:text-[44px] font-semibold tracking-tight leading-[1.05] mb-5">
            The AI research desk for hedge funds.
          </h2>
          <p className="text-[14px] text-text-tertiary leading-relaxed max-w-sm">
            Bring research, risk, and discovery together in one workflow.
            Generate a defensible 10-name trade slate with cointegrated
            pairs, factor decomposition, and full source lineage in under
            10 minutes.
          </p>

          {/* Live indicator */}
          <div className="mt-6 flex items-center gap-2 text-[11px] text-text-tertiary">
            <span className="relative inline-flex">
              <span className="absolute inline-flex h-2 w-2 rounded-full bg-signal-green opacity-75 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-signal-green" />
            </span>
            Live agents in production
          </div>
        </div>

        {/* Footer */}
        <div className="relative z-10 flex items-center justify-between text-[11px] text-text-quaternary">
          <span>© {new Date().getFullYear()} Alpha Engine</span>
          <Link href="/" className="hover:text-text-tertiary transition-colors">
            ← Back to homepage
          </Link>
        </div>
      </aside>

      {/* ─── RIGHT: AUTH CONTROLS ──────────────────────────────────────── */}
      <section className="relative flex flex-col items-center justify-center p-6 sm:p-12">
        {/* Mobile brand mark (left panel is hidden on small screens) */}
        <Link
          href="/"
          className="lg:hidden mb-10 text-[17px] font-semibold tracking-tight hover:opacity-90 transition-opacity"
        >
          alpha<span className="text-accent">engine</span>
        </Link>

        <div className="w-full max-w-[400px]">
          {/* Tab switcher */}
          <div className="grid grid-cols-2 mb-8 rounded-xl border border-border-primary bg-bg-surface p-1 fade-up-1">
            <Link
              href="/sign-in"
              prefetch
              className={`text-center py-2 rounded-lg text-[13px] font-medium transition-all ${
                mode === "signin"
                  ? "bg-bg-primary text-text-primary shadow-sm"
                  : "text-text-tertiary hover:text-text-primary"
              }`}
            >
              Sign in
            </Link>
            <Link
              href="/sign-up"
              prefetch
              className={`text-center py-2 rounded-lg text-[13px] font-medium transition-all ${
                mode === "signup"
                  ? "bg-bg-primary text-text-primary shadow-sm"
                  : "text-text-tertiary hover:text-text-primary"
              }`}
            >
              Sign up
            </Link>
          </div>

          {/* Heading */}
          <div className="mb-7 fade-up-2">
            <h1 className="text-[26px] font-semibold tracking-tight text-text-primary mb-2 leading-tight">
              {mode === "signin" ? "Welcome back." : "Create your account."}
            </h1>
            <p className="text-[13px] text-text-tertiary leading-relaxed">
              {mode === "signin"
                ? "Sign in to continue your research."
                : "Sign up in seconds. Your first memo runs in under ten minutes."}
            </p>
          </div>

          {/* Google button */}
          <div className="fade-up-3">
            <GoogleButton mode={mode} />
          </div>

          {/* Switch link */}
          <p className="mt-7 text-center text-[12px] text-text-tertiary fade-up-4">
            {mode === "signin" ? (
              <>
                New to Alpha Engine?{" "}
                <Link
                  href="/sign-up"
                  prefetch
                  className="text-accent font-medium hover:text-accent/80 transition-colors"
                >
                  Create an account →
                </Link>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <Link
                  href="/sign-in"
                  prefetch
                  className="text-accent font-medium hover:text-accent/80 transition-colors"
                >
                  Sign in →
                </Link>
              </>
            )}
          </p>

          {/* Fine print */}
          <p className="mt-10 text-center text-[11px] text-text-quaternary leading-relaxed fade-up-4">
            By continuing you agree to our terms and privacy policy. We only
            authenticate via your Google account.
          </p>
        </div>
      </section>
    </div>
  );
}
