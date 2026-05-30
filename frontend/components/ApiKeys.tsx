"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ApiKeyMasked } from "@/lib/api";

/**
 * API key manager for the portal. Keys are generated server-side; the full
 * plaintext is shown EXACTLY ONCE in a reveal modal (copy there), then only the
 * masked form is available. Regenerate revokes-and-reissues; revoke disables.
 */
export function ApiKeys() {
  const [keys, setKeys] = useState<ApiKeyMasked[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reveal, setReveal] = useState<{ key: string; name: string | null } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.myKeys();
      setKeys(r.keys);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load keys");
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createKey();
      setReveal({ key: created.key, name: created.name });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create key");
    }
    setBusy(false);
  };

  const regenerate = async (id: string) => {
    if (!window.confirm("Regenerate this key? The current key stops working immediately.")) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.regenerateKey(id);
      setReveal({ key: created.key, name: created.name });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not regenerate key");
    }
    setBusy(false);
  };

  const revoke = async (id: string) => {
    if (!window.confirm("Revoke this key? Any client using it will start getting 401s.")) return;
    setBusy(true);
    setError(null);
    try {
      await api.revokeKey(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not revoke key");
    }
    setBusy(false);
  };

  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
      <div className="px-4 py-2 border-b border-border-primary/60 flex items-center justify-between">
        <span className="text-[9px] font-mono uppercase tracking-wider text-text-quaternary">API KEYS</span>
        <button
          onClick={generate}
          disabled={busy}
          className="px-2.5 py-1 rounded-sm bg-white text-bg-primary text-[11px] font-semibold hover:bg-zinc-200 disabled:opacity-60 transition-colors"
        >
          {busy ? "…" : "Generate key"}
        </button>
      </div>
      <div className="p-4">
        {loading ? (
          <p className="text-[11px] text-text-quaternary">Loading…</p>
        ) : keys.length === 0 ? (
          <p className="text-[11px] text-text-quaternary">No keys yet. Generate one to connect over REST or MCP.</p>
        ) : (
          <div className="divide-y divide-border-primary/40">
            {keys.map((k) => (
              <div key={k.id} className="flex items-center gap-3 py-2 text-[11px]">
                <span className="font-mono text-text-secondary flex-1 truncate">{k.masked}</span>
                <span className="text-text-quaternary hidden sm:block">{k.last_used_at ? "used" : "unused"}</span>
                <button onClick={() => regenerate(k.id)} disabled={busy} className="text-text-tertiary hover:text-text-primary transition-colors">Regenerate</button>
                <button onClick={() => revoke(k.id)} disabled={busy} className="text-text-tertiary hover:text-signal-red transition-colors">Revoke</button>
              </div>
            ))}
          </div>
        )}
        {error && <p className="mt-3 text-[11px] text-signal-red">{error}</p>}
        <p className="mt-3 text-[10px] text-text-quaternary leading-relaxed">
          One key works across REST + MCP. We store only a hash; the full key is shown once on creation.
        </p>
      </div>

      {reveal && <RevealModal value={reveal.key} onClose={() => setReveal(null)} />}
    </div>
  );
}

function RevealModal({ value, onClose }: { value: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked — user can select manually */
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-[520px] rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
        <div className="px-5 py-3 border-b border-border-primary flex items-center justify-between">
          <span className="text-[10px] font-mono tracking-[0.18em] text-text-primary">YOUR NEW API KEY</span>
          <button onClick={onClose} className="text-text-quaternary hover:text-text-primary text-[14px]">✕</button>
        </div>
        <div className="p-5">
          <div className="rounded-sm border border-accent/40 bg-accent/[0.05] px-3 py-2.5 mb-4">
            <p className="text-[11px] text-accent leading-relaxed">
              Copy this now. For your security it is shown <span className="font-semibold">only once</span> and cannot be retrieved again. If you lose it, regenerate.
            </p>
          </div>
          <div className="flex items-stretch gap-2">
            <code className="flex-1 min-w-0 font-mono text-[12px] text-text-primary bg-bg-primary/60 border border-border-primary/60 rounded-sm px-3 py-2.5 break-all">
              {value}
            </code>
            <button onClick={copy} className="shrink-0 px-3 rounded-sm bg-white text-bg-primary text-[12px] font-semibold hover:bg-zinc-200 transition-colors">
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className="mt-5 flex justify-end">
            <button onClick={onClose} className="px-4 py-2 rounded-sm border border-border-primary text-text-secondary text-[12px] font-semibold hover:text-text-primary hover:border-zinc-700 transition-colors">
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
