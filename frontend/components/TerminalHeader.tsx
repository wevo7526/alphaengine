import type { ReactNode } from "react";

/**
 * TerminalHeader — the canonical page / section header.
 *
 *   /// EYEBROW                              [meta on the right]
 *   Large headline at -0.02em tracking
 *   Optional one-line sub
 *
 * Use it at the top of every authenticated page (and any in-page
 * section that needs a terminal-style anchor).
 */
export type TerminalHeaderProps = {
  eyebrow: string;
  title: string;
  sub?: ReactNode;
  meta?: ReactNode;
  size?: "md" | "lg";
  className?: string;
};

export function TerminalHeader({
  eyebrow,
  title,
  sub,
  meta,
  size = "md",
  className = "",
}: TerminalHeaderProps) {
  const titleSize =
    size === "lg"
      ? "text-[36px] sm:text-[44px]"
      : "text-[26px] sm:text-[32px]";

  return (
    <header className={`flex items-end justify-between gap-6 flex-wrap ${className}`}>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-3">
          <span className="text-accent">///</span> {eyebrow}
        </p>
        <h1
          className={`${titleSize} font-semibold tracking-[-0.02em] leading-[1.05] text-text-primary break-words`}
        >
          {title}
        </h1>
        {sub && (
          <p className="mt-2 text-[13px] text-text-tertiary leading-relaxed max-w-2xl">
            {sub}
          </p>
        )}
      </div>
      {meta && (
        <div className="shrink-0 text-[11px] font-mono tracking-wider text-text-quaternary text-right">
          {meta}
        </div>
      )}
    </header>
  );
}
