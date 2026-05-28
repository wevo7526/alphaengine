import type { ReactNode } from "react";

export type StatusTone = "green" | "red" | "yellow" | "blue" | "neutral";

/**
 * StatusPill — bordered terminal-style status badge with a colored dot.
 *
 *   ● PROFILE READY     ● LIVE     ● BLOCKED
 *
 * Replaces ad-hoc status badges across the platform.
 */
export type StatusPillProps = {
  label: ReactNode;
  tone?: StatusTone;
  pulse?: boolean;
  mono?: boolean;
  className?: string;
};

const dotByTone: Record<StatusTone, string> = {
  green: "bg-signal-green",
  red: "bg-signal-red",
  yellow: "bg-signal-yellow",
  blue: "bg-accent",
  neutral: "bg-text-quaternary",
};

const textByTone: Record<StatusTone, string> = {
  green: "text-signal-green",
  red: "text-signal-red",
  yellow: "text-signal-yellow",
  blue: "text-accent",
  neutral: "text-text-tertiary",
};

export function StatusPill({
  label,
  tone = "neutral",
  pulse = false,
  mono = true,
  className = "",
}: StatusPillProps) {
  return (
    <span
      className={[
        "inline-flex items-center gap-2 px-2.5 py-1 rounded border border-border-primary bg-bg-surface",
        "text-[10px] tracking-[0.18em]",
        mono ? "font-mono uppercase" : "uppercase",
        textByTone[tone],
        className,
      ].join(" ")}
    >
      <span className="relative inline-flex">
        <span className={`w-1.5 h-1.5 rounded-full ${dotByTone[tone]}`} />
        {pulse && (
          <span
            className={`absolute inset-0 w-1.5 h-1.5 rounded-full ${dotByTone[tone]} opacity-60`}
            style={{ animation: "core-breathe 2s ease-in-out infinite" }}
          />
        )}
      </span>
      <span>{label}</span>
    </span>
  );
}
