const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
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

  // Research desk — freeform query
  analyze: (query: string) =>
    request("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),

  // Data endpoints
  macro: () => request("/api/data/macro/snapshot"),
  market: (ticker: string, period = "3mo") =>
    request(`/api/data/market/${ticker}?period=${period}`),
  options: (ticker: string) =>
    request(`/api/data/market/${ticker}/options`),
  filings: (ticker: string, formType = "8-K", limit = 5) =>
    request(`/api/data/filings/${ticker}?form_type=${formType}&limit=${limit}`),
  news: (ticker: string) => request(`/api/data/news/${ticker}`),

  // Quant enrichment
  enrich: (tickers: string[], period = "3mo") =>
    request(`/api/quant/enrich?tickers=${tickers.join(",")}&period=${period}`),

  // Agent status
  agentStatus: () => request("/api/agents/status"),
  latestMemos: (limit = 20) => request(`/api/signals/latest?limit=${limit}`),
};
