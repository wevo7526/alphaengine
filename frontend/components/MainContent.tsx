"use client";

import { usePathname } from "next/navigation";
import { EvalBanner } from "@/components/EvalBanner";

export function MainContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Full-screen (no desk sidebar): marketing, auth, onboarding, the public
  // demo + legal pages, and the standalone portal.
  const isFullScreen =
    pathname === "/" ||
    pathname.startsWith("/docs") ||
    pathname.startsWith("/demo") ||
    pathname.startsWith("/terms") ||
    pathname.startsWith("/privacy") ||
    pathname.startsWith("/portal") ||
    pathname.startsWith("/sign-in") ||
    pathname.startsWith("/sign-up") ||
    pathname.startsWith("/sso-callback") ||
    pathname.startsWith("/onboarding");

  if (isFullScreen) {
    return <main className="flex-1 w-full min-w-0">{children}</main>;
  }

  // The demo desk (the existing app) carries the eval banner at all times.
  // The label is UX; the data-plane boundary is enforced at the gateway/seam.
  return (
    <main className="flex-1 ml-52 flex flex-col min-h-screen">
      <EvalBanner />
      {children}
    </main>
  );
}
