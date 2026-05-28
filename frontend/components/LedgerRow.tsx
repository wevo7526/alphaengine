"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { StatusPill, type StatusTone } from "./StatusPill";

/**
 * LedgerRow — the kind-pill + mono-id + meta row pattern from the
 * marketing SourceLedger. Reused in memo list, source ledger inside
 * memos, recent analyses, trade journal closed-trades.
 *
 *   [ FILING ]  0001067983-25-000412         Insider transaction
 *   [ MACRO  ]  10Y · 4.42%                  Treasury yield, intraday
 */
export type LedgerRowProps = {
  kind: string;
  kindTone?: StatusTone;
  id: ReactNode;
  meta?: ReactNode;
  href?: string;
  onClick?: () => void;
  className?: string;
};

export function LedgerRow({
  kind,
  kindTone = "blue",
  id,
  meta,
  href,
  onClick,
  className = "",
}: LedgerRowProps) {
  const inner = (
    <div
      className={[
        "grid grid-cols-[110px_1fr_auto] items-center gap-4 px-4 py-2.5",
        "hover:bg-bg-elevated/40 transition-colors",
        href || onClick ? "cursor-pointer" : "",
        className,
      ].join(" ")}
    >
      <StatusPill label={kind} tone={kindTone} className="justify-self-start" />
      <span className="text-[12px] font-mono text-text-secondary truncate">
        {id}
      </span>
      {meta && (
        <span className="text-[10px] text-text-quaternary truncate hidden md:block">
          {meta}
        </span>
      )}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="block">
        {inner}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button onClick={onClick} className="block w-full text-left">
        {inner}
      </button>
    );
  }
  return inner;
}
