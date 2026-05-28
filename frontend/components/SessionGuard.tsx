"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { api } from "@/lib/api";

/**
 * Session + onboarding guard.
 *
 * Route classes:
 *   PUBLIC (no checks):  /, /sign-in, /sign-up, /sso-callback
 *   ONBOARDING:          /onboarding
 *     - signed-in only
 *     - if already onboarded, redirect to /dashboard
 *   PROTECTED:           every other route
 *     - signed-in required, otherwise bounce to /
 *     - if signed-in but not onboarded, bounce to /onboarding
 *
 * Onboarding state is cached after the first successful fetch so
 * subsequent navigations don't re-hit the API.
 */
export function SessionGuard({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const redirectedRef = useRef(false);
  const [onboardingChecked, setOnboardingChecked] = useState(false);
  const [isOnboarded, setIsOnboarded] = useState<boolean | null>(null);

  const isPublicRoute =
    pathname === "/" ||
    pathname.startsWith("/sign-in") ||
    pathname.startsWith("/sign-up") ||
    pathname.startsWith("/sso-callback");
  const isOnboardingRoute = pathname.startsWith("/onboarding");

  // Fetch onboarding state once after sign-in.
  useEffect(() => {
    if (!isLoaded || !isSignedIn) {
      setOnboardingChecked(false);
      setIsOnboarded(null);
      return;
    }
    if (onboardingChecked) return;

    let cancelled = false;
    api
      .myProfile()
      .then((d) => {
        if (cancelled) return;
        setIsOnboarded(Boolean(d?.onboarded));
        setOnboardingChecked(true);
      })
      .catch(() => {
        // Default to unonboarded on any error so the user gets the wizard
        if (cancelled) return;
        setIsOnboarded(false);
        setOnboardingChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, onboardingChecked]);

  useEffect(() => {
    // Public routes never redirect
    if (isPublicRoute) return;
    if (!isLoaded) return;

    // Unsigned-in users on protected routes bounce to landing
    if (!isSignedIn) {
      if (!redirectedRef.current) {
        redirectedRef.current = true;
        router.replace("/");
      }
      return;
    }

    // Wait for onboarding check to settle before any onboarding routing
    if (!onboardingChecked) return;

    // Onboarded users hitting /onboarding go to dashboard
    if (isOnboardingRoute && isOnboarded) {
      router.replace("/dashboard");
      return;
    }

    // Unonboarded users on any other protected route bounce to /onboarding
    if (!isOnboardingRoute && !isOnboarded) {
      router.replace("/onboarding");
      return;
    }
  }, [
    isLoaded,
    isSignedIn,
    isPublicRoute,
    isOnboardingRoute,
    onboardingChecked,
    isOnboarded,
    pathname,
    router,
  ]);

  // Public routes render their own content
  if (isPublicRoute) return <>{children}</>;

  // Waiting for Clerk SDK
  if (!isLoaded) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <div className="flex flex-col items-center gap-3">
          <div
            className="w-4 h-4 rounded-full border-[1.5px] border-accent border-t-transparent"
            style={{ animation: "spin-slow 0.8s linear infinite" }}
          />
          <p className="text-[11px] text-text-tertiary">Loading…</p>
        </div>
      </div>
    );
  }

  // Not signed in (bounce in progress)
  if (!isSignedIn) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <p className="text-[11px] text-text-tertiary">Redirecting…</p>
      </div>
    );
  }

  // Onboarding-route flow: render once we know whether to redirect or not
  if (isOnboardingRoute) {
    if (!onboardingChecked) {
      return (
        <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
          <p className="text-[11px] text-text-tertiary">Checking your profile…</p>
        </div>
      );
    }
    return <>{children}</>;
  }

  // Protected routes: gate on onboarding completeness
  if (!onboardingChecked) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <p className="text-[11px] text-text-tertiary">Loading your workspace…</p>
      </div>
    );
  }
  if (!isOnboarded) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <p className="text-[11px] text-text-tertiary">Setting up your account…</p>
      </div>
    );
  }
  return <>{children}</>;
}
