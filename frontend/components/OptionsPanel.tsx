"use client";

interface OptionsData {
  ticker: string;
  current_price: number;
  expiration: string;
  put_call_ratio: number;
  implied_move_pct: number;
  straddle_price: number;
  atm_strike: number;
  atm_iv: number;
  iv_skew: number;
  max_pain: number;
  greeks: { delta: number; gamma: number; theta: number; vega: number };
  unusual_activity: {
    type: string;
    strike: number;
    volume: number;
    open_interest: number;
    vol_oi_ratio: number;
    iv: number;
  }[];
  total_call_volume: number;
  total_put_volume: number;
  pc_ratio_signal: string;
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div>
      <p className="text-[10px] text-text-quaternary uppercase tracking-wider">
        {label}
      </p>
      <p className={`text-sm font-mono font-medium ${color ?? "text-text-primary"}`}>
        {value}
      </p>
    </div>
  );
}

export function OptionsPanel({
  ticker,
  data,
}: {
  ticker: string;
  data: OptionsData;
}) {
  const pcColor =
    data.pc_ratio_signal === "bearish"
      ? "text-signal-red"
      : data.pc_ratio_signal === "bullish"
        ? "text-signal-green"
        : "text-text-primary";

  return (
    <div
      className="rounded-xl border border-border-primary bg-bg-surface p-4"
      style={{ animation: "fade-in 0.4s ease-out" }}
    >
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[13px] font-mono font-semibold text-text-primary">
          {ticker} Options
        </h4>
        <span className="text-[10px] text-text-quaternary">
          exp {data.expiration}
        </span>
      </div>

      {/* Key metrics grid */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <Stat label="P/C Ratio" value={data.put_call_ratio != null ? data.put_call_ratio.toFixed(2) : "—"} color={pcColor} />
        <Stat label="Implied Move" value={data.implied_move_pct != null ? `${data.implied_move_pct}%` : "—"} />
        <Stat label="ATM IV" value={data.atm_iv != null ? `${data.atm_iv}%` : "—"} />
        <Stat label="IV Skew" value={data.iv_skew != null ? `${data.iv_skew > 0 ? "+" : ""}${data.iv_skew}%` : "—"} color={data.iv_skew != null && data.iv_skew > 5 ? "text-signal-red" : "text-text-primary"} />
      </div>

      <div className="grid grid-cols-4 gap-3 mb-3">
        <Stat label="Max Pain" value={data.max_pain != null ? `$${data.max_pain}` : "—"} />
        <Stat label="Straddle" value={data.straddle_price != null ? `$${data.straddle_price}` : "—"} />
        <Stat label="Call Vol" value={data.total_call_volume != null ? data.total_call_volume.toLocaleString() : "—"} />
        <Stat label="Put Vol" value={data.total_put_volume != null ? data.total_put_volume.toLocaleString() : "—"} />
      </div>

      {/* ATM Greeks */}
      {data.greeks && Object.keys(data.greeks).length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1.5">
            ATM Greeks {data.atm_strike != null ? `($${data.atm_strike} strike)` : ""}
          </p>
          <div className="grid grid-cols-4 gap-3">
            <Stat label="Delta" value={data.greeks.delta != null ? data.greeks.delta.toFixed(3) : "—"} />
            <Stat label="Gamma" value={data.greeks.gamma != null ? data.greeks.gamma.toFixed(5) : "—"} />
            <Stat label="Theta" value={data.greeks.theta != null ? data.greeks.theta.toFixed(3) : "—"} color="text-signal-red" />
            <Stat label="Vega" value={data.greeks.vega != null ? data.greeks.vega.toFixed(3) : "—"} />
          </div>
        </div>
      )}

      {/* Unusual activity */}
      {data.unusual_activity.length > 0 && (
        <div>
          <p className="text-[10px] text-text-quaternary uppercase tracking-wider mb-1.5">
            Unusual Activity
          </p>
          <div className="space-y-1">
            {data.unusual_activity.map((u, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-lg bg-bg-primary px-2.5 py-1.5 text-[11px]"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`font-mono font-bold ${u.type === "call" ? "text-signal-green" : "text-signal-red"}`}
                  >
                    {u.type.toUpperCase()}
                  </span>
                  <span className="font-mono text-text-primary">${u.strike}</span>
                </div>
                <div className="flex items-center gap-3 text-text-tertiary">
                  <span>vol {u.volume.toLocaleString()}</span>
                  <span>OI {u.open_interest.toLocaleString()}</span>
                  <span className="font-mono font-bold text-signal-yellow">
                    {u.vol_oi_ratio}x
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
