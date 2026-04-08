"use client";

export function CorrelationHeatmap({
  tickers,
  matrix,
}: {
  tickers: string[];
  matrix: number[][];
}) {
  if (!tickers.length || !matrix.length) return null;

  function cellColor(val: number): string {
    if (val >= 0.7) return "bg-signal-red/40";
    if (val >= 0.4) return "bg-signal-yellow/30";
    if (val >= 0) return "bg-signal-green/10";
    if (val >= -0.4) return "bg-accent/10";
    return "bg-accent/30";
  }

  return (
    <div
      className="rounded-xl border border-border-primary bg-bg-surface p-4"
      style={{ animation: "fade-in 0.4s ease-out" }}
    >
      <h4 className="text-[11px] font-medium text-text-quaternary uppercase tracking-wider mb-3">
        Return Correlation Matrix
      </h4>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="w-14" />
              {tickers.map((t) => (
                <th
                  key={t}
                  className="px-1 py-1 text-[10px] font-mono text-text-tertiary text-center"
                >
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tickers.map((rowTicker, i) => (
              <tr key={rowTicker}>
                <td className="pr-2 py-1 text-[10px] font-mono text-text-tertiary text-right">
                  {rowTicker}
                </td>
                {matrix[i].map((val, j) => (
                  <td key={j} className="p-0.5 text-center">
                    <div
                      className={`rounded px-1 py-1 text-[10px] font-mono ${
                        i === j
                          ? "bg-white/[0.04] text-text-quaternary"
                          : `${cellColor(val)} text-text-primary`
                      }`}
                    >
                      {val.toFixed(2)}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-3 mt-3 text-[9px] text-text-quaternary">
        <span>High corr (&gt;0.7) = concentrated risk</span>
        <span>Negative corr = natural hedge</span>
      </div>
    </div>
  );
}
