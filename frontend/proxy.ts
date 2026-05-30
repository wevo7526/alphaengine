import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Only the portal (paying/trial) and the onboarding wizard require a Clerk
// session. Everything else is open: marketing, docs, plans, legal, AND the
// demo desk (which runs anonymously via a per-browser demo session, capped at
// 2 model runs/day server-side). Keep in sync with SessionGuard's gating.
const GATED_PREFIXES = ["/portal", "/onboarding"];
const CLERK_COOKIES = ["__session", "__clerk_db_jwt", "__client_uat"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Static assets / API / Next internals always pass.
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // Open routes (incl. the demo desk) pass without a session.
  const gated = GATED_PREFIXES.some((p) => pathname.startsWith(p));
  if (!gated) {
    return NextResponse.next();
  }

  // Portal / onboarding require a Clerk session -> send to portal sign-up.
  const hasSession = CLERK_COOKIES.some((name) => request.cookies.has(name));
  if (!hasSession) {
    const signUpUrl = new URL("/sign-up", request.url);
    signUpUrl.searchParams.set("surface", "portal");
    signUpUrl.searchParams.set("redirect_url", pathname);
    return NextResponse.redirect(signUpUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
  ],
};
