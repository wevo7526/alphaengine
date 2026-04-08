"use client";

export function ConvictionBar({
  value,
  size = "md",
}: {
  value: number;
  size?: "sm" | "md";
}) {
  const h = size === "sm" ? "h-1" : "h-1.5";
  const color =
    value >= 75
      ? "bg-signal-green"
      : value >= 50
        ? "bg-signal-yellow"
        : "bg-signal-red";

  return (
    <div className="flex items-center gap-2.5">
      <div className={`flex-1 ${h} rounded-full bg-bg-elevated overflow-hidden`}>
        <div
          className={`${h} rounded-full ${color}`}
          style={{ width: `${value}%`, animation: "fill-bar 0.6s ease-out" }}
        />
      </div>
      <span className="text-xs font-mono text-text-tertiary tabular-nums w-6 text-right">
        {value}
      </span>
    </div>
  );
}
