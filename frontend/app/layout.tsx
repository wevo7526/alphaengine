import type { Metadata } from "next";
import { Geist, Geist_Mono, Source_Serif_4 } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { MainContent } from "@/components/MainContent";
import { Providers } from "@/components/Providers";
import { SessionGuard } from "@/components/SessionGuard";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Editorial serif for display headlines (marketing surfaces). Gives the
// landing a grounded, research-note feel without disturbing the in-app
// terminal UI, which stays on Geist sans/mono. Exposed as --font-serif and
// surfaced through the `font-display` Tailwind utility (see globals.css).
const sourceSerif = Source_Serif_4({
  variable: "--font-serif",
  subsets: ["latin"],
  weight: ["400", "600"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "AlphaEngine — The signal layer between your data and your algo",
  description:
    "A stateless engine you run on your own licensed data. It computes the math, checks for overfitting, and returns cited, risk-gated, algo-ready signals — over MCP for your agent or a direct API for your bot. Nothing sourced, nothing stored.",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
    shortcut: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider
      publishableKey={
        process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ||
        "pk_test_dW5iaWFzZWQtbWFjYXctODkuY2xlcmsuYWNjb3VudHMuZGV2JA"
      }
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      afterSignOutUrl="/"
      appearance={{
        variables: {
          colorPrimary: "#3b82f6",
          colorBackground: "#18181b",
          colorText: "#fafafa",
          colorTextSecondary: "#a1a1aa",
          colorInputBackground: "#09090b",
          colorInputText: "#fafafa",
          colorNeutral: "#fafafa",
          colorDanger: "#ef4444",
          borderRadius: "0.75rem",
          fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
          fontSize: "14px",
        },
        // Note: we no longer render Clerk's <SignIn>/<SignUp> components.
        // Auth uses our custom AuthPanel + GoogleButton (hook-based OAuth).
        // The only Clerk component still in the app is <UserButton>, so the
        // appearance below covers UserButton popover styling + auth fallback
        // pages (e.g. /sso-callback) just in case Clerk ever renders chrome.
        elements: {
          rootBox: { width: "100%" },
          card: {
            backgroundColor: "#18181b",
            border: "1px solid #27272a",
            boxShadow: "0 25px 50px -12px rgba(0,0,0,0.5)",
            borderRadius: "1rem",
            padding: "2rem 1.75rem",
          },
          // Header
          headerTitle: { color: "#fafafa", fontSize: "20px", fontWeight: 600 },
          headerSubtitle: { color: "#a1a1aa", fontSize: "13px" },
          // Primary CTA
          formButtonPrimary: {
            backgroundColor: "#3b82f6",
            color: "#ffffff",
            borderRadius: "0.75rem",
            fontWeight: 600,
            fontSize: "14px",
            height: "42px",
            boxShadow: "0 0 0 1px rgba(59,130,246,0.4)",
            transition: "background-color 120ms ease",
            "&:hover": { backgroundColor: "#2563eb" },
            "&:focus": { boxShadow: "0 0 0 3px rgba(59,130,246,0.35)" },
          },
          // Inputs
          formFieldInput: {
            backgroundColor: "#09090b",
            border: "1px solid #27272a",
            color: "#fafafa",
            borderRadius: "0.75rem",
            height: "42px",
            fontSize: "14px",
            "&:focus": {
              borderColor: "#3b82f6",
              boxShadow: "0 0 0 3px rgba(59,130,246,0.18)",
            },
            "&::placeholder": { color: "#52525b" },
          },
          formFieldLabel: { color: "#d4d4d8", fontSize: "13px", fontWeight: 500 },
          formFieldHintText: { color: "#71717a", fontSize: "12px" },
          formFieldErrorText: { color: "#ef4444", fontSize: "12px", fontWeight: 500 },
          formFieldSuccessText: { color: "#10b981", fontSize: "12px" },
          formFieldInputShowPasswordButton: {
            color: "#a1a1aa",
            "&:hover": { color: "#fafafa" },
          },
          formResendCodeLink: { color: "#3b82f6", fontWeight: 500 },
          // Alerts
          alert: {
            backgroundColor: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "#fca5a5",
            borderRadius: "0.5rem",
          },
          alertText: { color: "#fca5a5", fontSize: "13px" },
          // Identity preview (the "you're signed in as..." card)
          identityPreview: {
            backgroundColor: "#09090b",
            border: "1px solid #27272a",
            borderRadius: "0.75rem",
          },
          identityPreviewText: { color: "#fafafa", fontSize: "13px" },
          identityPreviewEditButton: {
            color: "#3b82f6",
            "&:hover": { color: "#60a5fa" },
          },
          // Divider between social + form
          dividerLine: { backgroundColor: "#27272a" },
          dividerText: { color: "#71717a", fontSize: "11px" },
          // Social buttons
          socialButtonsBlockButton: {
            backgroundColor: "#09090b",
            border: "1px solid #27272a",
            color: "#fafafa",
            borderRadius: "0.75rem",
            height: "42px",
            transition: "background-color 120ms ease, border-color 120ms ease",
            "&:hover": {
              backgroundColor: "#18181b",
              borderColor: "#3f3f46",
            },
          },
          socialButtonsBlockButtonText: { color: "#fafafa", fontSize: "13px", fontWeight: 500 },
          socialButtonsProviderIcon: { color: "#fafafa" },
          // OTP code field
          otpCodeFieldInput: {
            backgroundColor: "#09090b",
            border: "1px solid #27272a",
            color: "#fafafa",
            fontSize: "16px",
            fontWeight: 600,
            "&:focus": {
              borderColor: "#3b82f6",
              boxShadow: "0 0 0 3px rgba(59,130,246,0.18)",
            },
          },
          // Back / navigation
          headerBackLink: {
            color: "#a1a1aa",
            "&:hover": { color: "#fafafa" },
          },
          headerBackIcon: { color: "#a1a1aa" },
          // Footer (we hide Clerk branding via globals.css; the
          // "Don't have an account? Sign up" link stays visible and styled here)
          footer: {
            backgroundColor: "transparent",
            borderTop: "1px solid #27272a",
            paddingTop: "1rem",
          },
          footerAction: { backgroundColor: "transparent" },
          footerActionText: { color: "#a1a1aa", fontSize: "13px" },
          footerActionLink: {
            color: "#3b82f6",
            fontWeight: 500,
            "&:hover": { color: "#60a5fa" },
          },
          // Profile menu (when signed in elsewhere)
          userButtonPopoverCard: {
            backgroundColor: "#18181b",
            border: "1px solid #27272a",
          },
          userButtonPopoverActionButton: {
            color: "#fafafa",
            "&:hover": { backgroundColor: "#27272a" },
          },
          userButtonPopoverActionButtonText: { color: "#fafafa" },
          userButtonPopoverFooter: { display: "none" },
        },
      }}
    >
      <html
        lang="en"
        className={`${geistSans.variable} ${geistMono.variable} ${sourceSerif.variable} h-full antialiased`}
      >
        <body className="h-full flex">
          <Providers>
            <SessionGuard>
              <Sidebar />
              <MainContent>{children}</MainContent>
            </SessionGuard>
          </Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
