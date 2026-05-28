"use client";

import { useEffect, useRef, useState } from "react";
import { useSignIn, useSignUp } from "@clerk/nextjs";

/**
 * Minimal type shim: Clerk's @clerk/nextjs ships TypeScript types that
 * surface `SignInFutureResource` / `SignUpFutureResource` via inference
 * which don't expose `authenticateWithRedirect` in their static type,
 * even though the runtime resource has it. We cast to this shim to call
 * the method safely while keeping the rest of the resource typed.
 */
type OAuthRedirectable = {
  authenticateWithRedirect: (params: {
    strategy: string;
    redirectUrl: string;
    redirectUrlComplete: string;
  }) => Promise<unknown>;
};

/**
 * Custom Google OAuth button using Clerk's authenticateWithRedirect.
 *
 * Two key design points:
 *
 *   1. Split into SignInGoogleButton + SignUpGoogleButton so each only
 *      uses the one Clerk hook it actually needs. Calling both useSignIn
 *      and useSignUp in the same component was causing one of them to
 *      stay in an `isLoaded: false` state and never resolve.
 *
 *   2. The signIn / signUp resource is mirrored into a ref so the click
 *      handler reads the latest value, not a stale closure. This fixes
 *      the "Auth service is still loading" error that would persist even
 *      after Clerk had finished initializing.
 *
 * Modes:
 *   "signin" — Clerk signIn flow → /dashboard. Brand-new Google accounts
 *              get auto-created and SessionGuard routes them to /onboarding.
 *   "signup" — Clerk signUp flow → /onboarding.
 */
export function GoogleButton({
  mode,
  label,
}: {
  mode: "signin" | "signup";
  label?: string;
}) {
  if (mode === "signin") {
    return <SignInGoogleButton label={label} />;
  }
  return <SignUpGoogleButton label={label} />;
}

// ─────────────────────────────────────────────────────────────────────

function SignInGoogleButton({ label }: { label?: string }) {
  const { signIn } = useSignIn();
  // Mirror Clerk's signIn resource into a ref so the click handler reads
  // the latest value instead of a stale closure. Type comes from useSignIn.
  const signInRef = useRef<typeof signIn>(signIn);
  useEffect(() => {
    signInRef.current = signIn;
  }, [signIn]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (loading) return;
    setError(null);
    setLoading(true);
    const resource = signInRef.current as unknown as OAuthRedirectable | null;
    if (!resource) {
      setError("Sign in is still initializing. Please try again.");
      setLoading(false);
      return;
    }
    try {
      await resource.authenticateWithRedirect({
        strategy: "oauth_google",
        redirectUrl: "/sso-callback",
        redirectUrlComplete: "/dashboard",
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not start Google sign in.";
      setError(msg);
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

// ─────────────────────────────────────────────────────────────────────

function SignUpGoogleButton({ label }: { label?: string }) {
  const { signUp } = useSignUp();
  const signUpRef = useRef<typeof signUp>(signUp);
  useEffect(() => {
    signUpRef.current = signUp;
  }, [signUp]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (loading) return;
    setError(null);
    setLoading(true);
    const resource = signUpRef.current as unknown as OAuthRedirectable | null;
    if (!resource) {
      setError("Sign up is still initializing. Please try again.");
      setLoading(false);
      return;
    }
    try {
      await resource.authenticateWithRedirect({
        strategy: "oauth_google",
        redirectUrl: "/sso-callback",
        redirectUrlComplete: "/onboarding",
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not start Google sign up.";
      setError(msg);
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

// ─────────────────────────────────────────────────────────────────────

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
        className="group w-full relative flex items-center justify-center gap-3 h-12 px-4 rounded-xl bg-white text-zinc-900 text-[14px] font-semibold hover:bg-zinc-50 active:bg-zinc-100 disabled:opacity-70 disabled:cursor-wait transition-all shadow-[0_1px_2px_rgba(0,0,0,0.4),0_0_0_1px_rgba(255,255,255,0.04)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.06)]"
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
