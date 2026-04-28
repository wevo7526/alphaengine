function getApiBase(): string {
  // Build-time env var takes priority
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }
  // Runtime detection for Railway production — derive backend URL from frontend host
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host.includes("railway.app") || host.includes("alphaengine")) {
      // In production, backend URL must be set via NEXT_PUBLIC_BACKEND_URL at build time.
      // Fall through to localhost only in dev — this will surface the misconfiguration
      // in the browser console rather than silently pointing to a stale URL.
      console.warn("NEXT_PUBLIC_BACKEND_URL not set in production — API calls will fail");
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

const DEFAULT_TIMEOUT_MS = 45000;

async function request<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const base = getApiBase();
  const authHeaders = await getAuthHeaders();
  const controller = new AbortController();
  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: { ...authHeaders, ...init?.headers },
      signal: init?.signal ?? controller.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `API ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error(`Request timed out after ${timeoutMs}ms: ${path}`);
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

export const api = {
  health: () => request("/api/health"),
  systemInfo: () => request("/api/system/info"),
  authMe: () => request<{ user_id: string; authenticated: boolean }>("/api/auth/me"),

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

  flushPositions: (scope: "open" | "closed" | "all" = "open") =>
    request<{ deleted: number; scope: string }>(
      `/api/portfolio/flush?scope=${scope}`,
      { method: "POST" }
    ),

  // Portfolio positions + live P&L
  positions: () => request("/api/portfolio/positions"),
  attribution: () => request("/api/portfolio/attribution"),

  // Scorecard (Desk 6)
  scorecardSummary: () => request("/api/scorecard/summary"),
  scorecardSignals: (limit = 50) => request(`/api/scorecard/signals?limit=${limit}`),
  scorecardRun: () => request("/api/scorecard/run", { method: "POST" }),

  // Risk gate preview
  riskCheck: (ticker: string, direction: string, size_pct: number) =>
    request("/api/portfolio/risk-check", {
      method: "POST",
      body: JSON.stringify({ ticker, direction, size_pct }),
    }),

  // PDF Export — returns URLs; actual download needs auth headers handled manually
  exportMemoUrl: (memoId: string) => `${getApiBase()}/api/export/memo/${memoId}`,
  exportPortfolioUrl: () => `${getApiBase()}/api/export/portfolio`,
  exportScorecardUrl: () => `${getApiBase()}/api/export/scorecard`,
  exportMorningUrl: () => `${getApiBase()}/api/export/morning`,
  exportRangeUrl: (start: string, end: string) =>
    `${getApiBase()}/api/export/range?start=${start}&end=${end}`,

  /**
   * Trigger a PDF download with auth headers attached.
   * Fetches the PDF blob, then creates a download link.
   */
  downloadPdf: async (url: string, filename: string) => {
    const headers = await getAuthHeaders();
    // Don't send Content-Type on GET
    delete (headers as Record<string, string>)["Content-Type"];
    const res = await fetch(url, { headers });
    if (!res.ok) {
      throw new Error(`Export failed: ${res.status}`);
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  },

  // Quant infrastructure
  portfolioRisk: () => request("/api/quant/portfolio-risk"),
  regime: () => request("/api/quant/regime"),
  factors: (tickers: string[], model: "single" | "ff5_mom" = "single") =>
    request(`/api/quant/factors?tickers=${tickers.join(",")}&model=${model}`),
  stress: () => request("/api/quant/stress"),
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

  // Watchlist
  watchlist: () => request("/api/watchlist"),
  addToWatchlist: (tickers: string[], notes = "") =>
    request("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ tickers, notes }),
    }),
  removeFromWatchlist: (ticker: string) =>
    request(`/api/watchlist/${ticker}`, { method: "DELETE" }),
};
