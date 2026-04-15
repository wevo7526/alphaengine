"use client";

import { usePathname } from "next/navigation";

export function MainContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuth =
    pathname.startsWith("/sign-in") || pathname.startsWith("/sign-up");

  if (isAuth) {
    // Auth pages take over the full screen — no sidebar margin
    return <>{children}</>;
  }

  return (
    <main className="flex-1 ml-52 flex flex-col min-h-screen">{children}</main>
  );
}
