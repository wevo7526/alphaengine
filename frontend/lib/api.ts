function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }
  if (typeof window !== "undefined" && window.location.hostname.includes("railway.app")) {
    return "https://alpha-backend-production-51df.up.railway.app";
  }
  return "http://localhost:8000";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getApiBase(); // Evaluate on every call, not at module load
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/api/health"),

  analyze: (query: string) =>
    request("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),

  analyzeStreamUrl: () => `${getApiBase()}/api/analyze/stream`,

  macroDashboard: () => request("/api/data/macro"),
  macro: () => request("/api/data/macro/snapshot"),
  market: (ticker: string, period = "3mo") =>
    request(`/api/data/market/${ticker}?period=${period}`),
  options: (ticker: string) =>
    request(`/api/data/market/${ticker}/options`),
  filings: (ticker: string, formType = "8-K", limit = 5) =>
    request(`/api/data/filings/${ticker}?form_type=${formType}&limit=${limit}`),
  news: (ticker: string) => request(`/api/data/news/${ticker}`),

  enrich: (tickers: string[], period = "3mo") =>
    request(`/api/quant/enrich?tickers=${tickers.join(",")}&period=${period}`),

  morningReport: () => request("/api/morning-report"),

  takeTrade: (trade: {
    memo_id?: string;
    ticker: string;
    direction: string;
    action?: string;
    entry_price?: number;
    stop_loss?: number;
    take_profit?: number;
    position_size_pct?: number;
    conviction?: number;
    thesis?: string;
  }) =>
    request("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify(trade),
    }),

  listTrades: (status = "all") =>
    request(`/api/portfolio/trades?status=${status}`),

  // Quant infrastructure
  portfolioRisk: () => request("/api/quant/portfolio-risk"),
  regime: () => request("/api/quant/regime"),
  factors: (tickers: string[]) =>
    request(`/api/quant/factors?tickers=${tickers.join(",")}`),

  // Backtesting
  runBacktest: (config: { tickers: string[]; period?: string; initial_capital?: number }) =>
    request("/api/backtest/run", { method: "POST", body: JSON.stringify(config) }),
  backtestRuns: () => request("/api/backtest/runs"),
  backtestResults: (runId: string) => request(`/api/backtest/results/${runId}`),

  // Portfolio optimization
  optimize: (config: { tickers: string[]; method?: string; trade_ideas?: unknown[] }) =>
    request("/api/portfolio/optimize", { method: "POST", body: JSON.stringify(config) }),

  agentStatus: () => request("/api/agents/status"),
  latestMemos: (limit = 20) => request(`/api/signals/latest?limit=${limit}`),
};
