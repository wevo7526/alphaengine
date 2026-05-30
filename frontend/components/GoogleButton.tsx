"use client";

import { useState } from "react";
import { useSignIn, useSignUp } from "@clerk/nextjs";

/**
 * Custom Google OAuth button — Clerk v7 Future API.
 *
 * Clerk v7 re-implemented useSignIn() / useSignUp() to return a
 * signal-backed value:
 *
 *     useSignIn() -> { signIn: SignInFutureResource, errors, fetchStatus }
 *     useSignUp() -> { signUp: SignUpFutureResource, errors, fetchStatus }
 *
 * Notes:
 *   - There is no `isLoaded` flag and no waiting period. The Future
 *     resource is available immediately on mount.
 *   - The legacy `signIn.authenticateWithRedirect(...)` no longer exists.
 *     Use `signIn.sso({ strategy, redirectUrl, redirectCallbackUrl })`.
 *   - Sso() returns `{ error: ClerkError | null }` rather than throwing.
 *   - `redirectUrl` is the FINAL destination after OAuth completes
 *     (legacy `redirectUrlComplete`). `redirectCallbackUrl` is the SSO
 *     landing page Clerk uses to exchange the OAuth code (legacy
 *     `redirectUrl`). Param naming flipped between APIs.
 *
 * Modes:
 *   "signin" -> /dashboard (SessionGuard re-routes to /onboarding if
 *               the user has not finished the wizard).
 *   "signup" -> /onboarding straight away.
 */
export function GoogleButton({
  mode,
  label,
}: {
  mode: "signin" | "signup";
  label?: string;
}) {
  if (mode === "signin") return <SignInGoogleButton label={label} />;
  return <SignUpGoogleButton label={label} />;
}

// ─── Sign In ─────────────────────────────────────────────────────────

function SignInGoogleButton({ label }: { label?: string }) {
  const { signIn } = useSignIn();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (loading) return;
    if (!signIn) {
      setError("Auth service unavailable. Please refresh and try again.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const surface = surfaceFromUrl();
      const result = await signIn.sso({
        strategy: "oauth_google",
        // Portal sign-in lands on the portal; demo / default lands on the desk.
        redirectUrl: absoluteUrl(surface === "portal" ? "/portal" : "/dashboard"),
        redirectCallbackUrl: absoluteUrl("/sso-callback"),
      });
      const errMsg = extractError(result?.error);
      if (errMsg) {
        setError(errMsg);
        setLoading(false);
      }
      // Success: browser is mid-redirect; leave loading=true.
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not start Google sign in.");
      setLoading(false);
    }
  };

  return (
    <ButtonShell
      onClick={handleClick}
      loading={loading}
      error={error}
      label={label ?? "Continue with Google"}
    />
  );
}

// ─── Sign Up ─────────────────────────────────────────────────────────

function SignUpGoogleButton({ label }: { label?: string }) {
  const { signUp } = useSignUp();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (loading) return;
    if (!signUp) {
      setError("Auth service unavailable. Please refresh and try again.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const surface = surfaceFromUrl();
      const result = await signUp.sso({
        strategy: "oauth_google",
        // Carry the surface intent into onboarding so it sets entitlement +
        // the right post-onboarding destination (portal vs demo desk).
        redirectUrl: absoluteUrl(surface ? `/onboarding?surface=${surface}` : "/onboarding"),
        redirectCallbackUrl: absoluteUrl("/sso-callback"),
      });
      const errMsg = extractError(result?.error);
      if (errMsg) {
        setError(errMsg);
        setLoading(false);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not start Google sign up.");
      setLoading(false);
    }
  };

  return (
    <ButtonShell
      onClick={handleClick}
      loading={loading}
      error={error}
      label={label ?? "Sign up with Google"}
    />
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────

function absoluteUrl(path: string): string {
  if (typeof window === "undefined") return path;
  return window.location.origin + path;
}

/** Read the demo|portal surface intent from the current URL (?surface=...). */
function surfaceFromUrl(): "demo" | "portal" | null {
  if (typeof window === "undefined") return null;
  const v = new URLSearchParams(window.location.search).get("surface");
  return v === "portal" || v === "demo" ? v : null;
}

function extractError(err: unknown): string | null {
  if (!err) return null;
  if (typeof err === "string") return err;
  if (typeof err === "object" && err !== null) {
    const e = err as {
      message?: string;
      longMessage?: string;
      errors?: Array<{ message?: string; longMessage?: string }>;
    };
    if (typeof e.longMessage === "string" && e.longMessage) return e.longMessage;
    if (typeof e.message === "string" && e.message) return e.message;
    if (Array.isArray(e.errors) && e.errors.length > 0) {
      const first = e.errors[0];
      return first?.longMessage || first?.message || null;
    }
  }
  return null;
}

function ButtonShell({
  onClick,
  loading,
  error,
  label,
}: {
  onClick: () => void;
  loading: boolean;
  error: string | null;
  label: string;
}) {
  return (
    <div className="w-full">
      <button
        onClick={onClick}
        disabled={loading}
        className="group w-full relative flex items-center justify-center gap-3 h-12 px-4 rounded-sm bg-white text-zinc-900 text-[14px] font-semibold hover:bg-zinc-50 active:bg-zinc-100 disabled:opacity-70 disabled:cursor-wait transition-all shadow-[0_1px_2px_rgba(0,0,0,0.4),0_0_0_1px_rgba(255,255,255,0.04)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.06)]"
      >
        {loading ? (
          <span className="flex items-center gap-2">
            <span
              className="w-4 h-4 rounded-full border-[1.5px] border-zinc-400 border-t-zinc-900"
              style={{ animation: "spin-slow 0.8s linear infinite" }}
            />
            <span>Redirecting…</span>
          </span>
        ) : (
          <>
            <GoogleLogo />
            <span>{label}</span>
          </>
        )}
      </button>
      {error && (
        <p className="mt-3 text-[12px] text-signal-red text-center" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
        fill="#EA4335"
      />
    </svg>
  );
}
