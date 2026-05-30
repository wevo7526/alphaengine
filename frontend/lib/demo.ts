"use client";

/**
 * Anonymous Demo Desk identity. The Demo Desk is open to anyone with no Google
 * login; a stable per-browser id (localStorage + cookie) isolates each
 * visitor's workspace (portfolio, memos, etc.). The id is sent as X-Demo-Id;
 * the backend scopes all state to demo:<id> and caps model runs at 2/day.
 * No account, no PII.
 */
const KEY = "ae_demo_id";

export function getDemoId(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = window.localStorage.getItem(KEY);
    if (!id) {
      id = "d_" + Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
      window.localStorage.setItem(KEY, id);
    }
    // Mirror to a cookie so the session survives and can be read server-side later.
    document.cookie = `${KEY}=${id}; path=/; max-age=31536000; SameSite=Lax`;
    return id;
  } catch {
    return "";
  }
}
