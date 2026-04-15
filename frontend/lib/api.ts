function getApiBase(): string {
  // Build-time env var takes priority
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }
  // Runtime detection for Railway production
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host.includes("railway.app") || host.includes("alphaengine")) {
      return "https://alpha-backend-production-51df.up.railway.app";
    }
  }
  return "http://localhost:8000";
}

// Get Clerk token for authenticated requests
async function getAuthHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (typeof window !== "undefined") {
    try {
      // @ts-expect-error Clerk exposes this globally
      const clerk = window.Clerk;
      if (clerk?.session) {
        const token = await clerk.session.getToken();
        if (token) {
          headers["Authorization"] = `Bearer ${token}`;
        }
      }
    } catch {
      // No auth available — requests work without it (backward compatible)
    }
  }
  return headers;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getApiBase();
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { ...authHeaders, ...init?.headers },
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

  closeTrade: (tradeId: string, exitPrice: number, notes = "") =>
    request(`/api/portfolio/trade/${tradeId}/close`, {
      method: "POST",
      body: JSON.stringify({ exit_price: exitPrice, notes }),
    }),

  // Quant infrastructure
  portfolioRisk: () => request("/api/quant/portfolio-risk"),
  regime: () => request("/api/quant/regime"),
  factors: (tickers: string[]) =>
    request(`/api/quant/factors?tickers=${tickers.join(",")}`),
  preTradeCheck: (ticker: string, sizePct = 3, action = "BUY") =>
    request(`/api/quant/risk-check/${ticker}?size_pct=${sizePct}&action=${action}`),
  regimeConditionalReturns: (ticker = "SPY") =>
    request(`/api/quant/regime/conditional-returns?ticker=${ticker}`),

  // Backtesting
  runBacktest: (config: { tickers: string[]; period?: string; initial_capital?: number }) =>
    request("/api/backtest/run", { method: "POST", body: JSON.stringify(config) }),
  backtestRuns: () => request("/api/backtest/runs"),
  backtestResults: (runId: string) => request(`/api/backtest/results/${runId}`),

  // Portfolio optimization
  optimize: (config: { tickers: string[]; method?: string; trade_ideas?: unknown[] }) =>
    request("/api/portfolio/optimize", { method: "POST", body: JSON.stringify(config) }),

  evaluateTrades: () => request("/api/portfolio/backtest"),
  agentStatus: () => request("/api/agents/status"),
  latestMemos: (limit = 20) => request(`/api/signals/latest?limit=${limit}`),
  deleteMemo: (id: string) =>
    request(`/api/signals/${id}`, { method: "DELETE" }),
};
