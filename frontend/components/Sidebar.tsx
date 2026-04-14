"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconHome, IconGlobe, IconBriefcase, IconSettings } from "./icons";

// Reuse IconGlobe for Analysis, add simple SVG for new pages
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

function IconRewind(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M8 3L3 8L8 13" />
      <path d="M13 3L8 8L13 13" />
    </svg>
  );
}

const NAV = [
  { href: "/", label: "Home", icon: IconHome },
  { href: "/analysis", label: "Analysis", icon: IconChart },
  { href: "/portfolio", label: "Portfolio", icon: IconBriefcase },
  { href: "/risk", label: "Risk", icon: IconShield },
];

const BOTTOM = [{ href: "/settings", label: "Settings", icon: IconSettings }];

export function Sidebar() {
  const pathname = usePathname();

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <aside className="fixed inset-y-0 left-0 w-52 bg-bg-primary border-r border-border-primary flex flex-col z-50">
      <div className="px-4 py-5">
        <span className="text-[15px] font-semibold tracking-tight text-text-primary">
          alpha<span className="text-accent">engine</span>
        </span>
      </div>

      <nav className="flex-1 px-2 space-y-0.5">
        {NAV.map((item) => {
          const active = isActive(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={[
                "flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-[13px] font-medium transition-colors",
                active
                  ? "bg-white/[0.07] text-text-primary"
                  : "text-text-tertiary hover:text-text-secondary hover:bg-white/[0.03]",
              ].join(" ")}
            >
              <Icon className={active ? "text-text-primary" : "text-text-quaternary"} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-2 pb-4 space-y-0.5">
        {BOTTOM.map((item) => {
          const active = isActive(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={[
                "flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-[13px] font-medium transition-colors",
                active
                  ? "bg-white/[0.07] text-text-primary"
                  : "text-text-tertiary hover:text-text-secondary hover:bg-white/[0.03]",
              ].join(" ")}
            >
              <Icon className={active ? "text-text-primary" : "text-text-quaternary"} />
              {item.label}
            </Link>
          );
        })}
      </div>
    </aside>
  );
}
