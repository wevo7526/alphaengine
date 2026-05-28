"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { api } from "@/lib/api";

type AuthState = "checking" | "authenticated" | "unauthenticated";

/**
 * Minimal session guard.
 *
 * - On auth routes (/sign-in, /sign-up): always render children, no checks.
 * - Off auth routes: wait for Clerk to load, redirect to /sign-in if not signed in.
 * - Optimistic — we trust Clerk's isSignedIn and render immediately when true.
 *   The backend will 401 individual API calls if the token is genuinely bad;
 *   we don't block the UI on a blocking /api/auth/me gate (that was the loop).
 */
export function SessionGuard({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const redirectedRef = useRef(false);

  // Public routes (no auth required, no redirect): marketing landing + auth pages.
  const isPublicRoute =
    pathname === "/" ||
    pathname.startsWith("/sign-in") ||
    pathname.startsWith("/sign-up");

  useEffect(() => {
    // Public routes (landing, sign-in, sign-up) never redirect
    if (isPublicRoute) return;

    // Wait for Clerk
    if (!isLoaded) return;

    // Only redirect once per unmount cycle.
    // Unauthenticated users bounce to the marketing landing (not /sign-in)
    // so the public site is always the "home base" — visitors choose to
    // sign in from the nav when they're ready.
    if (!isSignedIn && !redirectedRef.current) {
      redirectedRef.current = true;
      router.replace("/");
    }
  }, [isLoaded, isSignedIn, isPublicRoute, pathname, router]);

  // Public routes render their own content (auth-aware, but no gate)
  if (isPublicRoute) return <>{children}</>;

  // Waiting for Clerk SDK to load
  if (!isLoaded) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <div className="flex flex-col items-center gap-3">
          <div
            className="w-4 h-4 rounded-full border-[1.5px] border-accent border-t-transparent"
            style={{ animation: "spin-slow 0.8s linear infinite" }}
          />
          <p className="text-[11px] text-text-tertiary">Loading...</p>
        </div>
      </div>
    );
  }

  // Not signed in — show placeholder while redirect to landing fires
  if (!isSignedIn) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <p className="text-[11px] text-text-tertiary">Redirecting...</p>
      </div>
    );
  }

  // Signed in — render app. Individual API calls will 401 if token bad.
  return <>{children}</>;
}
