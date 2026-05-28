import type { ReactNode } from "react";

/**
 * TerminalPanel — the canonical bordered card.
 *
 *   ┌─────────────────────────────────────────────┐
 *   │ /// LABEL                       [status]    │
 *   ├─────────────────────────────────────────────┤
 *   │  body                                       │
 *   └─────────────────────────────────────────────┘
 *
 * Replaces every `rounded-xl border bg-bg-surface` panel across the
 * authenticated app. Use compound subcomponents for header + body, or
 * pass `label` + `status` props for the common case.
 */
export type TerminalPanelProps = {
  label?: ReactNode;
  status?: ReactNode;
  density?: "comfortable" | "compact";
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
};

export function TerminalPanel({
  label,
  status,
  density = "comfortable",
  className = "",
  bodyClassName = "",
  children,
}: TerminalPanelProps) {
  const bodyPad = density === "compact" ? "p-4" : "p-5";
  return (
    <section
      className={[
        "rounded-md border border-border-primary bg-bg-surface overflow-hidden",
        className,
      ].join(" ")}
    >
      {(label || status) && (
        <header className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border-primary/60">
          {label && (
            <span className="text-[10px] font-mono tracking-[0.18em] text-text-quaternary">
              <span className="text-accent">///</span> {label}
            </span>
          )}
          {status && (
            <span className="text-[10px] font-mono tracking-wider text-text-quaternary">
              {status}
            </span>
          )}
        </header>
      )}
      <div className={[bodyPad, bodyClassName].join(" ")}>{children}</div>
    </section>
  );
}

/**
 * TerminalDivider — full-width separator inside a TerminalPanel.
 */
export function TerminalDivider({ className = "" }: { className?: string }) {
  return (
    <hr
      className={[
        "border-0 border-t border-border-primary/60 -mx-5 my-4",
        className,
      ].join(" ")}
    />
  );
}
