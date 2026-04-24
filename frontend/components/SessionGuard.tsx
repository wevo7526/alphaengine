"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { api } from "@/lib/api";

type AuthState = "checking" | "authenticated" | "unauthenticated";

/**
 * Wraps protected pages. Ensures Clerk session is loaded AND backend
 * recognizes the user (via /api/auth/me) before rendering children.
 *
 * Shows a minimal loading state during auth check — distinguishable from
 * data loading which happens inside children.
 */
export function SessionGuard({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const [authState, setAuthState] = useState<AuthState>("checking");

  // Auth pages bypass the guard
  const isAuthRoute = pathname.startsWith("/sign-in") || pathname.startsWith("/sign-up");

  useEffect(() => {
    if (isAuthRoute) {
      setAuthState("authenticated");
      return;
    }
    if (!isLoaded) return;

    if (!isSignedIn) {
      setAuthState("unauthenticated");
      router.replace("/sign-in");
      return;
    }

    // Clerk says signed in — verify backend agrees
    let cancelled = false;
    (async () => {
      try {
        await api.authMe();
        if (!cancelled) setAuthState("authenticated");
      } catch {
        // Backend rejected the token — likely Clerk config mismatch
        if (!cancelled) {
          setAuthState("unauthenticated");
          router.replace("/sign-in");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, isAuthRoute, router]);

  if (isAuthRoute) return <>{children}</>;

  if (authState === "checking") {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <div className="flex flex-col items-center gap-3">
          <div
            className="w-4 h-4 rounded-full border-[1.5px] border-accent border-t-transparent"
            style={{ animation: "spin-slow 0.8s linear infinite" }}
          />
          <p className="text-[11px] text-text-tertiary">Checking session...</p>
        </div>
      </div>
    );
  }

  if (authState === "unauthenticated") {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <p className="text-[11px] text-text-tertiary">Redirecting to sign-in...</p>
      </div>
    );
  }

  return <>{children}</>;
}
