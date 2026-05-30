import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Routes a logged-out visitor must reach. `/` is matched exactly (a
// startsWith("/") would make everything public); the rest by prefix. Keep
// this in sync with the public-route lists in SessionGuard / MainContent /
// Sidebar. Everything not listed here (/dashboard and the app routes) stays
// gated behind a Clerk session.
const PUBLIC_EXACT = ["/"];
const PUBLIC_PREFIXES = ["/docs", "/sign-in", "/sign-up", "/sso-callback"];
const CLERK_COOKIES = ["__session", "__clerk_db_jwt", "__client_uat"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    PUBLIC_EXACT.includes(pathname) ||
    PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))
  ) {
    return NextResponse.next();
  }

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  const hasSession = CLERK_COOKIES.some((name) => request.cookies.has(name));
  if (!hasSession) {
    const signInUrl = new URL("/sign-in", request.url);
    signInUrl.searchParams.set("redirect_url", pathname);
    return NextResponse.redirect(signInUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
  ],
};
