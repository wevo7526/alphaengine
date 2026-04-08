"use client";

export default function PortfolioPage() {
  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
        Portfolio
      </h1>
      <p className="text-sm text-text-tertiary mb-8">
        Positions, P&amp;L, and risk metrics. Connected in Phase 3 with broker integration.
      </p>

      <div className="rounded-xl border border-border-primary bg-bg-surface p-8 text-center">
        <p className="text-sm text-text-tertiary">
          No positions yet. Run an analysis from Home and execute a trade to begin tracking.
        </p>
      </div>
    </div>
  );
}
