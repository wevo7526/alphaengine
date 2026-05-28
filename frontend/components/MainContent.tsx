"use client";

import { usePathname } from "next/navigation";

export function MainContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Marketing landing + auth + onboarding pages render full-screen
  // (Sidebar is hidden via its own pathname check). All other routes
  // get the sidebar margin.
  const isFullScreen =
    pathname === "/" ||
    pathname.startsWith("/sign-in") ||
    pathname.startsWith("/sign-up") ||
    pathname.startsWith("/sso-callback") ||
    pathname.startsWith("/onboarding");

  if (isFullScreen) {
    // Wrap in a full-width flex child so children fill horizontal space.
    // Without this, the body's `flex` container collapses the page to its
    // content width and everything looks crammed to the left.
    return <main className="flex-1 w-full min-w-0">{children}</main>;
  }

  return (
    <main className="flex-1 ml-52 flex flex-col min-h-screen">{children}</main>
  );
}
