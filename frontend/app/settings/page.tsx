"use client";

export default function SettingsPage() {
  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-xl font-semibold tracking-tight text-text-primary mb-1">
        Settings
      </h1>
      <p className="text-sm text-text-tertiary mb-8">
        API configuration, agent weights, and risk parameters.
      </p>

      <div className="space-y-6">
        <section>
          <h2 className="text-[13px] font-medium text-text-primary mb-3">
            Agent Weights
          </h2>
          <div className="rounded-xl border border-border-primary bg-bg-surface divide-y divide-border-primary">
            {[
              { label: "Macro Regime", weight: 0.15 },
              { label: "Fundamentals", weight: 0.3 },
              { label: "Sentiment", weight: 0.2 },
              { label: "Options Flow", weight: 0.15 },
              { label: "Quant Strategy", weight: 0.2 },
            ].map((a) => (
              <div key={a.label} className="flex items-center justify-between px-4 py-3">
                <span className="text-[13px] text-text-secondary">{a.label}</span>
                <span className="text-xs font-mono text-text-tertiary">
                  {(a.weight * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-[13px] font-medium text-text-primary mb-3">
            Risk Parameters
          </h2>
          <div className="rounded-xl border border-border-primary bg-bg-surface divide-y divide-border-primary">
            {[
              { label: "Max position size", value: "5%" },
              { label: "Sizing method", value: "Half-Kelly" },
              { label: "BUY/SELL threshold", value: "75 conviction" },
              { label: "WATCH threshold", value: "50 conviction" },
            ].map((p) => (
              <div key={p.label} className="flex items-center justify-between px-4 py-3">
                <span className="text-[13px] text-text-secondary">{p.label}</span>
                <span className="text-xs font-mono text-text-tertiary">{p.value}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
