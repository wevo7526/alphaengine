import type { ReactNode } from "react";

/**
 * StatPanel — Bloomberg-style stat cell with a mini-viz on the right.
 *
 *   LABEL                              [mini-viz cell]
 *   28.4  pts
 *   sub copy describing the metric
 *
 * Use it inside a grid for stat strips:
 *
 *   <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border-primary/40
 *                   border border-border-primary/40 rounded-md overflow-hidden">
 *     <StatPanel ... />
 *     <StatPanel ... />
 *   </div>
 */
export type StatTone = "default" | "green" | "red" | "yellow";

export type StatPanelProps = {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  tone?: StatTone;
  mini?: ReactNode;
  className?: string;
};

const valueToneClass: Record<StatTone, string> = {
  default: "text-text-primary",
  green: "text-signal-green",
  red: "text-signal-red",
  yellow: "text-signal-yellow",
};

export function StatPanel({
  label,
  value,
  unit,
  sub,
  tone = "default",
  mini,
  className = "",
}: StatPanelProps) {
  return (
    <div
      className={[
        "bg-bg-surface px-5 py-5 flex items-center justify-between gap-4",
        className,
      ].join(" ")}
    >
      <div className="min-w-0">
        <p className="text-[9px] font-mono tracking-[0.18em] text-text-quaternary mb-2">
          {label}
        </p>
        <div className="flex items-baseline gap-2 mb-1.5">
          <span
            className={`text-[28px] font-semibold tracking-tight leading-none counter-tick tabular-nums ${valueToneClass[tone]}`}
          >
            {value}
          </span>
          {unit && (
            <span className="text-[11px] font-mono text-text-tertiary">
              {unit}
            </span>
          )}
        </div>
        {sub && (
          <p className="text-[11px] text-text-tertiary truncate">{sub}</p>
        )}
      </div>
      {mini && <div className="shrink-0 w-20 h-12">{mini}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Mini-vizzes for the right cell. Each takes the full ~80x48 box.
// ─────────────────────────────────────────────────────────────────────────

export type SparklineKind = "flat" | "up" | "down" | "wave";

export function MiniSparkline({
  kind = "wave",
  color,
}: {
  kind?: SparklineKind;
  color?: string;
}) {
  const points =
    kind === "up"
      ? [38, 34, 30, 32, 26, 24, 20, 16, 12, 8]
      : kind === "down"
      ? [10, 14, 18, 16, 22, 26, 28, 32, 36, 40]
      : kind === "flat"
      ? [22, 24, 20, 26, 22, 28, 22, 26, 20, 22]
      : [30, 24, 28, 22, 18, 22, 16, 12, 18, 14];

  const stroke =
    color ??
    (kind === "down" ? "#ef4444" : kind === "up" ? "#10b981" : "#3b82f6");

  const d = points
    .map((y, i) => `${i === 0 ? "M" : "L"} ${i * 9} ${y}`)
    .join(" ");

  return (
    <svg viewBox="0 0 81 48" className="w-full h-full overflow-visible">
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="sparkline-path"
      />
      <circle
        cx={9 * (points.length - 1)}
        cy={points[points.length - 1]}
        r="2.5"
        fill={stroke}
      />
    </svg>
  );
}

export function MiniBars({
  heights = [60, 90, 45, 100, 75, 95],
  color = "rgb(var(--accent) / 0.7)",
}: {
  heights?: number[];
  color?: string;
}) {
  return (
    <div className="w-full h-full flex items-end justify-between gap-1">
      {heights.map((h, i) => (
        <div
          key={i}
          className="flex-1 bg-accent/70 rounded-sm pulse-bar"
          style={{
            height: `${h}%`,
            animationDelay: `${i * 0.15}s`,
            background: color,
          }}
        />
      ))}
    </div>
  );
}

export function MiniDots({
  count = 5,
  color = "rgb(16 185 129 / 0.8)",
}: {
  count?: number;
  color?: string;
}) {
  return (
    <div
      className="w-full h-full grid gap-1 items-center"
      style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="aspect-square rounded-full counter-tick"
          style={{
            background: color,
            animationDelay: `${i * 0.3}s`,
          }}
        />
      ))}
    </div>
  );
}
