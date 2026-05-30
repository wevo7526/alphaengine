"use client";

/**
 * Persistent eval banner for every demo / educational surface (public /demo and
 * the demo desk). The label is UX; the real boundary is the gateway/seam. See
 * mcp-server/docs/USER_STATES.md and ACCESS_TIERS.md. Non-negotiable per the
 * split brief: demo surfaces always carry this.
 */
export function EvalBanner() {
  return (
    <div className="w-full bg-bg-elevated/60 border-b border-border-primary/70">
      <div className="max-w-[1280px] mx-auto px-6 py-2 flex items-center gap-3 text-[10.5px] font-mono tracking-[0.14em] text-text-tertiary">
        <span className="text-text-primary">DEMO</span>
        <span className="text-text-quaternary">
          For testing and educational purposes only. Sample data. Not investment advice.
        </span>
      </div>
    </div>
  );
}
