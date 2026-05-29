"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useUser } from "@clerk/nextjs";
import { api } from "@/lib/api";
import {
  IconHome,
  IconBriefcase,
  IconSettings,
} from "./icons";

// Dynamic import to avoid SSG crash when ClerkProvider isn't available
import dynamic from "next/dynamic";
const ClerkUserButton = dynamic(
  () => import("@clerk/nextjs").then((mod) => ({ default: mod.UserButton })),
  { ssr: false }
);

// Inline icons kept lightweight — strokeWidth 1.5, 16px viewBox, no fill.
// Matches the terminal aesthetic better than heavier filled icons.
function IconChart(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2 12L6 8L9 10L14 4" />
      <path d="M14 4V7M14 4H11" />
    </svg>
  );
}

function IconShield(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M8 2L3 4.5V8C3 11 5 13.5 8 14.5C11 13.5 13 11 13 8V4.5L8 2Z" />
    </svg>
  );
}

function IconTarget(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="8" cy="8" r="6" />
      <circle cx="8" cy="8" r="3" />
      <circle cx="8" cy="8" r="0.5" fill="currentColor" />
    </svg>
  );
}

function IconCompare(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 4H7M3 8H7M3 12H7" />
      <path d="M9 4H13M9 8H13M9 12H13" />
      <path d="M1 2V14M8 2V14M15 2V14" />
    </svg>
  );
}

function IconStack(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2 5l6-3 6 3-6 3-6-3z" />
      <path d="M2 9l6 3 6-3" />
      <path d="M2 12l6 3 6-3" />
    </svg>
  );
}

type NavItem = {
  href: string;
  label: string;
  icon: (p: React.SVGProps<SVGSVGElement>) => React.JSX.Element;
};

// Grouped navigation so the sidebar tells a story instead of being a flat
// list. Section labels use the same `/// LABEL` motif as TerminalPanel /
// TerminalHeader so the sidebar feels native to the design system.
const SECTIONS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "WORKSPACE",
    items: [
      { href: "/dashboard", label: "Home", icon: IconHome },
      { href: "/analysis", label: "Analysis", icon: IconChart },
      { href: "/memos", label: "Analyses", icon: IconStack },
    ],
  },
  {
    label: "BOOK",
    items: [
      { href: "/portfolio", label: "Portfolio", icon: IconBriefcase },
      { href: "/risk", label: "Risk", icon: IconShield },
      { href: "/track-record", label: "Track Record", icon: IconTarget },
    ],
  },
  {
    label: "TOOLS",
    items: [{ href: "/compare", label: "Compare", icon: IconCompare }],
  },
];

// Role + mandate labels for the footer chips. Keep short so two chips
// fit comfortably on the same row inside the 208px sidebar.
const ROLE_LABEL: Record<string, string> = {
  pm: "PM",
  analyst: "Analyst",
  allocator: "Allocator",
  other: "Other",
};

const MANDATE_LABEL: Record<string, string> = {
  long_only: "Long Only",
  long_short: "L/S",
  market_neutral: "Mkt Neutral",
  macro: "Macro",
  multi_strat: "Multi",
};

function formatPortfolioSize(usd: number | null | undefined): string | null {
  if (!usd || usd <= 0) return null;
  if (usd >= 1_000_000_000) return `$${(usd / 1_000_000_000).toFixed(1)}B`;
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(usd >= 10_000_000 ? 0 : 1)}M`;
  if (usd >= 1_000) return `$${(usd / 1_000).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useUser();
  const [profile, setProfile] = useState<{
    role: string | null;
    portfolio_size_usd: number | null;
    mandate: string;
    benchmark: string;
  } | null>(null);

  // Pull the user profile once for the footer chips. The same call backs
  // SessionGuard, so this is usually a warm-cache fetch. Failures are
  // silent — the sidebar still renders, just without the role/size badges.
  useEffect(() => {
    let cancelled = false;
    api
      .myProfile()
      .then((d) => {
        if (cancelled || !d?.profile) return;
        setProfile({
          role: d.profile.role,
          portfolio_size_usd: d.profile.portfolio_size_usd,
          mandate: d.profile.mandate,
          benchmark: d.profile.benchmark,
        });
      })
      .catch(() => { /* silent — sidebar still works without it */ });
    return () => {
      cancelled = true;
    };
  }, []);

  // Hide sidebar on full-screen routes. MainContent.tsx mirrors this list.
  if (
    pathname === "/" ||
    pathname.startsWith("/sign-in") ||
    pathname.startsWith("/sign-up") ||
    pathname.startsWith("/sso-callback") ||
    pathname.startsWith("/onboarding")
  ) {
    return null;
  }

  const isActive = (href: string) =>
    href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href);

  const isSettings = pathname.startsWith("/settings") || pathname.startsWith("/risk-config");
  const portfolioLabel = formatPortfolioSize(profile?.portfolio_size_usd);
  const roleLabel = profile?.role ? ROLE_LABEL[profile.role] ?? profile.role.toUpperCase() : null;
  const mandateLabel = profile?.mandate ? MANDATE_LABEL[profile.mandate] ?? null : null;
  const firstName = user?.firstName ?? null;

  return (
    <aside className="fixed inset-y-0 left-0 w-52 bg-bg-primary border-r border-border-primary flex flex-col z-50">
      {/* ──────────────────────────── HEADER ─────────────────────────── */}
      <div className="px-4 pt-5 pb-4 border-b border-border-primary/60">
        <Link href="/dashboard" className="block">
          <span className="text-[15px] font-semibold tracking-tight text-text-primary">
            alpha<span className="text-accent">engine</span>
          </span>
        </Link>
      </div>

      {/* ──────────────────────────── NAV ────────────────────────────── */}
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {SECTIONS.map((section) => (
          <div key={section.label}>
            <p className="px-2 mb-1.5 text-[9px] font-mono tracking-[0.22em] text-text-quaternary">
              <span className="text-accent">///</span> {section.label}
            </p>
            <div className="space-y-px">
              {section.items.map((item) => {
                const active = isActive(item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={[
                      "group relative flex items-center gap-2.5 pl-3 pr-3 py-1.5 rounded-md text-[13px] font-medium transition-colors",
                      active
                        ? "bg-bg-elevated/60 text-text-primary"
                        : "text-text-tertiary hover:text-text-secondary hover:bg-bg-surface/60",
                    ].join(" ")}
                  >
                    {/* Left accent bar on the active item — design-system
                        marker that doesn't add visual weight. */}
                    <span
                      aria-hidden
                      className={[
                        "absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full transition-colors",
                        active ? "bg-accent" : "bg-transparent",
                      ].join(" ")}
                    />
                    <Icon
                      className={
                        active ? "text-accent shrink-0" : "text-text-quaternary group-hover:text-text-tertiary shrink-0"
                      }
                    />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* ──────────────────────────── FOOTER ─────────────────────────── */}
      <div className="border-t border-border-primary/60 px-2 pt-3 pb-3 space-y-2">
        {/* User identity card — name, role, mandate, portfolio size.
            Shows the user that the platform "knows" who they are without
            them having to open Settings to remember what they configured.
            All values come from /api/me/profile so editing Settings
            updates this card on next mount. */}
        <Link
          href="/settings"
          className={[
            "block rounded-md border px-3 py-2.5 transition-colors",
            isSettings
              ? "border-accent/40 bg-accent/[0.05]"
              : "border-border-primary bg-bg-surface/60 hover:border-zinc-700 hover:bg-bg-surface",
          ].join(" ")}
        >
          <div className="flex items-center justify-between mb-1.5 min-w-0">
            <span className="text-[12px] font-medium text-text-primary truncate">
              {firstName ?? "Account"}
            </span>
            {portfolioLabel && (
              <span className="text-[10px] font-mono text-text-secondary tabular-nums shrink-0 ml-2">
                {portfolioLabel}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {roleLabel && (
              <span className="text-[9px] font-mono tracking-[0.16em] uppercase text-text-tertiary border border-border-primary rounded px-1.5 py-0.5">
                {roleLabel}
              </span>
            )}
            {mandateLabel && (
              <span className="text-[9px] font-mono tracking-[0.16em] uppercase text-text-tertiary border border-border-primary rounded px-1.5 py-0.5">
                {mandateLabel}
              </span>
            )}
            {!roleLabel && !mandateLabel && (
              <span className="text-[10px] text-text-quaternary">Configure profile →</span>
            )}
          </div>
        </Link>

        {/* Settings row + Clerk avatar trigger. Settings link uses the
            same active treatment as the main nav items above so the user
            never sees "two ways into the same place" looking different. */}
        <div className="flex items-center gap-1.5">
          <Link
            href="/settings"
            className={[
              "group relative flex-1 flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-md text-[12px] font-medium transition-colors",
              isSettings
                ? "bg-bg-elevated/60 text-text-primary"
                : "text-text-tertiary hover:text-text-secondary hover:bg-bg-surface/60",
            ].join(" ")}
          >
            <span
              aria-hidden
              className={[
                "absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full transition-colors",
                isSettings ? "bg-accent" : "bg-transparent",
              ].join(" ")}
            />
            <IconSettings
              className={
                isSettings ? "text-accent shrink-0" : "text-text-quaternary group-hover:text-text-tertiary shrink-0"
              }
            />
            <span>Settings</span>
          </Link>
          <div className="shrink-0 px-1.5 py-1 rounded-md border border-border-primary bg-bg-surface/60 flex items-center justify-center">
            <ClerkUserButton
              appearance={{
                elements: {
                  avatarBox: "w-6 h-6",
                },
              }}
            />
          </div>
        </div>
      </div>
    </aside>
  );
}
