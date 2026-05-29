"use client";

import Link from "next/link";
import { GoogleButton } from "@/components/GoogleButton";

/**
 * Two-sided auth panel used by both /sign-in and /sign-up.
 *
 * Institutional treatment (matches the landing reskin): flat, near-
 * monochrome, hard 1px rules, faint structural grid — no glow orbs,
 * gradient, or animated constellation. Blue appears only on the logo
 * wordmark. Display headings inherit the editorial serif (globals.css).
 *
 * `mode` drives the active tab and the Clerk flow (signIn vs signUp).
 */
export function AuthPanel({ mode }: { mode: "signin" | "signup" }) {
  return (
    <div className="min-h-screen w-full grid lg:grid-cols-[1.05fr_1fr] bg-bg-primary text-text-primary">
      {/* ─── LEFT: BRAND PANEL ─────────────────────────────────────────── */}
      <aside className="relative hidden lg:flex flex-col justify-between p-12 overflow-hidden border-r border-border-primary bg-bg-surface/30">
        {/* Faint structural grid only — no glow, no orbs, no animation. */}
        <div className="absolute inset-0 grid-bg opacity-[0.10]" aria-hidden="true" />

        {/* Top: brand mark (the one place blue is allowed). */}
        <Link
          href="/"
          className="relative z-10 inline-block self-start text-[17px] font-semibold tracking-tight hover:opacity-90 transition-opacity"
        >
          alpha<span className="text-accent">engine</span>
        </Link>

        {/* Center: hero copy. */}
        <div className="relative z-10 max-w-md fade-up-1">
          <p className="text-[10px] font-mono uppercase tracking-[0.22em] text-text-quaternary mb-5">
            <span className="text-text-tertiary">///</span> For L/S equity &amp; macro PMs
          </p>
          <h2 className="font-display text-[38px] xl:text-[42px] font-semibold tracking-[-0.01em] leading-[1.08] mb-5">
            AI agents for investment managers.
          </h2>
          <p className="text-[14px] text-text-tertiary leading-relaxed max-w-sm">
            A team of agents handles research, risk, and portfolio
            construction, and a CIO agent signs off. You get a sourced,
            risk-checked memo with trade ideas, in minutes.
          </p>

          {/* Status line — neutral, no colored ping. */}
          <div className="mt-7 flex items-center gap-2 text-[11px] font-mono text-text-tertiary">
            <span className="inline-flex h-1.5 w-1.5 rounded-full bg-text-tertiary" />
            LIVE AGENTS IN PRODUCTION
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
          {/* Tab switcher — flat, bordered, no shadow. */}
          <div className="grid grid-cols-2 mb-8 rounded-sm border border-border-primary bg-bg-surface p-1 fade-up-1">
            <Link
              href="/sign-in"
              prefetch
              className={`text-center py-2 rounded-sm text-[12px] font-mono uppercase tracking-wider transition-colors ${
                mode === "signin"
                  ? "bg-bg-elevated text-text-primary"
                  : "text-text-quaternary hover:text-text-secondary"
              }`}
            >
              Sign in
            </Link>
            <Link
              href="/sign-up"
              prefetch
              className={`text-center py-2 rounded-sm text-[12px] font-mono uppercase tracking-wider transition-colors ${
                mode === "signup"
                  ? "bg-bg-elevated text-text-primary"
                  : "text-text-quaternary hover:text-text-secondary"
              }`}
            >
              Sign up
            </Link>
          </div>

          {/* Heading — serif via the global h1 rule. */}
          <div className="mb-7 fade-up-2">
            <h1 className="text-[28px] font-semibold tracking-[-0.01em] text-text-primary mb-2 leading-tight">
              {mode === "signin" ? "Welcome back." : "Create your account."}
            </h1>
            <p className="text-[13px] text-text-tertiary leading-relaxed">
              {mode === "signin"
                ? "Sign in to continue your research."
                : "Your first memo runs in under ten minutes."}
            </p>
          </div>

          {/* Google button */}
          <div className="fade-up-3">
            <GoogleButton mode={mode} />
          </div>

          {/* Switch link — neutral, underlined (no accent). */}
          <p className="mt-7 text-center text-[12px] text-text-tertiary fade-up-4">
            {mode === "signin" ? (
              <>
                New to Alpha Engine?{" "}
                <Link
                  href="/sign-up"
                  prefetch
                  className="text-text-primary font-medium underline underline-offset-4 decoration-border-primary hover:decoration-text-tertiary transition-colors"
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
                  className="text-text-primary font-medium underline underline-offset-4 decoration-border-primary hover:decoration-text-tertiary transition-colors"
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
