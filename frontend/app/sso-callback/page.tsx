"use client";

import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";

/**
 * OAuth landing page.
 *
 * After Google bounces the user back from its consent screen, Clerk lands
 * the browser here. The `AuthenticateWithRedirectCallback` component
 * completes the session activation (token exchange, session creation)
 * and then redirects to the `redirectUrlComplete` that was set on the
 * original `signIn.authenticateWithRedirect` / `signUp.authenticateWithRedirect`
 * call (see components/GoogleButton.tsx):
 *
 *   sign-in flow → /dashboard
 *   sign-up flow → /onboarding
 *
 * The SessionGuard then takes over and re-routes new users to /onboarding
 * if they reached /dashboard without completing the wizard, and vice versa.
 */
export default function SSOCallbackPage() {
  return (
    <div className="fixed inset-0 flex items-center justify-center bg-bg-primary">
      <div className="flex flex-col items-center gap-3">
        <div
          className="w-5 h-5 rounded-full border-[1.5px] border-accent border-t-transparent"
          style={{ animation: "spin-slow 0.8s linear infinite" }}
        />
        <p className="text-[12px] text-text-tertiary">Signing you in…</p>
      </div>
      <AuthenticateWithRedirectCallback />
    </div>
  );
}
