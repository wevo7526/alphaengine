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
 *     - signed-in required (else bounce to /)
 *     - renders the wizard IMMEDIATELY — does NOT block on the profile
 *       lookup; if the lookup later reveals the user is already onboarded
 *       we redirect to /dashboard in the background. This avoids the
 *       multi-second "Checking your profile…" full-screen that users
 *       were sitting through on first sign-up.
 *   PROTECTED:           every other route
 *     - signed-in required (else bounce to /)
 *     - if signed-in but not onboarded, bounce to /onboarding
 *     - while the profile check is in flight, show a small branded
 *       loader (not a long-running blank screen)
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
        // Treat any failure as "not onboarded" so the user gets the wizard
        // rather than being stuck on a spinner if the API is briefly slow.
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

  // Waiting for Clerk SDK to load — small branded spinner, not full-screen
  if (!isLoaded) {
    return <BrandedLoader caption="Loading" />;
  }

  // Not signed in — bounce in progress
  if (!isSignedIn) {
    return <BrandedLoader caption="Redirecting" />;
  }

  // Onboarding route: render the wizard immediately. The redirect-if-onboarded
  // check fires in the useEffect above and will navigate away if needed.
  // This is the key fix — never block the onboarding UI on the profile API call.
  if (isOnboardingRoute) {
    return <>{children}</>;
  }

  // Protected routes: gate on onboarding completeness
  if (!onboardingChecked) {
    return <BrandedLoader caption="Loading workspace" />;
  }
  if (!isOnboarded) {
    // Redirect already fired in useEffect; show a small loader while it lands
    return <BrandedLoader caption="Setting things up" />;
  }
  return <>{children}</>;
}

/**
 * Compact branded loader. Centered on the viewport with the wordmark above
 * a small spinner and one-line caption. Replaces the previous bare
 * "Checking your profile…" text that left users staring at a blank screen.
 */
function BrandedLoader({ caption }: { caption: string }) {
  return (
    <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
      <div className="flex flex-col items-center gap-4">
        <span className="text-[14px] font-semibold tracking-tight text-text-primary">
          alpha<span className="text-accent">engine</span>
        </span>
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-full border-[1.5px] border-accent border-t-transparent"
            style={{ animation: "spin-slow 0.8s linear infinite" }}
          />
          <p className="text-[11px] text-text-tertiary">{caption}…</p>
        </div>
      </div>
    </div>
  );
}
