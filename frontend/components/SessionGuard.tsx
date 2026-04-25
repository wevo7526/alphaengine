"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useUser } from "@clerk/nextjs";

const LOAD_TIMEOUT_MS = 10000;

export function SessionGuard({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const redirectedRef = useRef(false);
  const [timedOut, setTimedOut] = useState(false);

  const isAuthRoute = pathname.startsWith("/sign-in") || pathname.startsWith("/sign-up");

  useEffect(() => {
    if (isAuthRoute) return;
    if (!isLoaded) return;

    if (!isSignedIn && !redirectedRef.current) {
      redirectedRef.current = true;
      router.replace("/sign-in");
    }
  }, [isLoaded, isSignedIn, isAuthRoute, pathname, router]);

  useEffect(() => {
    if (isAuthRoute || isLoaded) return;
    const t = setTimeout(() => setTimedOut(true), LOAD_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [isAuthRoute, isLoaded]);

  if (isAuthRoute) return <>{children}</>;

  if (!isLoaded && timedOut) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary p-6">
        <div className="flex flex-col items-center gap-3 max-w-sm text-center">
          <p className="text-[13px] font-medium text-text-primary">Authentication failed to load</p>
          <p className="text-[11px] text-text-tertiary">
            The sign-in service is not responding. Check your connection, then reload. If this persists, the Clerk publishable key may be missing in the deployment.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-2 px-3 py-1.5 rounded-lg bg-white text-bg-primary text-xs font-medium hover:bg-zinc-200 transition-colors"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }

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

  if (!isSignedIn) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
        <p className="text-[11px] text-text-tertiary">Redirecting to sign-in...</p>
      </div>
    );
  }

  return <>{children}</>;
}
