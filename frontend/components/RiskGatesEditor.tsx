"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { TerminalPanel } from "@/components/TerminalPanel";
import { StatusPill } from "@/components/StatusPill";

/**
 * RiskGatesEditor — inline editable list of per-user risk gates.
 *
 * Same UX as the standalone /risk-config page: save-on-blur per field,
 * inline error messages, RESET per override, "RESET ALL" header action.
 * Lives in /settings as a section so the user can configure their book
 * without leaving the profile flow.
 */

interface RiskParam {
  field: string;
  label: string;
  desc: string;
  group: string;
  value: number;
  default: number | null;
  source: "user" | "env" | "default";
  scale: "pct" | "raw";
  range_min: number;
  range_max: number;
}

const GROUP_LABELS: Record<string, string> = {
  position_limits: "POSITION LIMITS",
  var_breaker: "VAR & CIRCUIT BREAKER",
  liquidity: "LIQUIDITY",
  optimizer: "OPTIMIZER",
};

const GROUP_ORDER = ["position_limits", "var_breaker", "liquidity", "optimizer"];

function toDisplay(value: number, scale: "pct" | "raw"): string {
  if (scale === "pct") {
    const n = value * 100;
    if (Math.abs(n) < 0.01) return "0";
    const fixed = n.toFixed(3);
    return parseFloat(fixed).toString();
  }
  const fixed = value.toFixed(4);
  return parseFloat(fixed).toString();
}

function fromDisplay(input: string, scale: "pct" | "raw"): number | null {
  const trimmed = input.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return null;
  return scale === "pct" ? n / 100 : n;
}

function unitFor(scale: "pct" | "raw", field: string): string {
  if (scale === "pct") return "%";
  if (field.endsWith("_bps")) return "bp";
  if (field === "var_confidence") return "";
  return "";
}

export function RiskGatesEditor() {
  const [params, setParams] = useState<RiskParam[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingField, setSavingField] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [toast, setToast] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .myRisk()
      .then((d) => {
        if (cancelled) return;
        const list = (d.parameters as RiskParam[]) ?? [];
        setParams(list);
        setDraft(Object.fromEntries(list.map((p) => [p.field, toDisplay(p.value, p.scale)])));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setApiError(e instanceof Error ? e.message : "Could not load risk gates.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(() => {
    const out: Record<string, RiskParam[]> = {};
    for (const p of params) {
      out[p.group] ??= [];
      out[p.group].push(p);
    }
    return out;
  }, [params]);

  const userOverrideCount = useMemo(
    () => params.filter((p) => p.source === "user").length,
    [params]
  );

  const flashToast = (msg: string) => {
    setToast(msg);
    if (typeof window !== "undefined") {
      window.setTimeout(() => setToast(null), 2500);
    }
  };

  async function saveField(field: string) {
    const p = params.find((x) => x.field === field);
    if (!p) return;
    const raw = draft[field];
    const parsed = fromDisplay(raw ?? "", p.scale);

    const payload: Record<string, number | null> = {};
    if (parsed === null) {
      payload[field] = null;
    } else {
      if (parsed < p.range_min || parsed > p.range_max) {
        const displayMin = toDisplay(p.range_min, p.scale);
        const displayMax = toDisplay(p.range_max, p.scale);
        setErrors((prev) => ({ ...prev, [field]: `Must be between ${displayMin} and ${displayMax}` }));
        return;
      }
      payload[field] = parsed;
    }

    if (parsed === p.value || (parsed === null && p.source === "default")) {
      setErrors((prev) => {
        const { [field]: _drop, ...rest } = prev;
        return rest;
      });
      return;
    }

    setSavingField(field);
    setErrors((prev) => {
      const { [field]: _drop, ...rest } = prev;
      return rest;
    });
    try {
      const updated = (await api.updateMyRisk(payload)) as { parameters: RiskParam[] };
      const next = updated.parameters as RiskParam[];
      setParams(next);
      setDraft(Object.fromEntries(next.map((np) => [np.field, toDisplay(np.value, np.scale)])));
      flashToast(parsed === null ? "Reset to default" : "Saved");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Save failed.";
      try {
        const parsedErr = JSON.parse(msg);
        if (parsedErr?.errors?.length) {
          setErrors((prev) => ({ ...prev, [field]: parsedErr.errors.join(", ") }));
        } else {
          setErrors((prev) => ({ ...prev, [field]: msg }));
        }
      } catch {
        setErrors((prev) => ({ ...prev, [field]: msg }));
      }
    } finally {
      setSavingField(null);
    }
  }

  async function resetAll() {
    if (typeof window !== "undefined") {
      const ok = window.confirm("Reset every risk gate back to the platform default? Your custom overrides will be cleared.");
      if (!ok) return;
    }
    setResetting(true);
    try {
      const updated = (await api.resetMyRisk()) as { parameters: RiskParam[] };
      const next = updated.parameters as RiskParam[];
      setParams(next);
      setDraft(Object.fromEntries(next.map((np) => [np.field, toDisplay(np.value, np.scale)])));
      setErrors({});
      flashToast("All gates reset to default");
    } catch (e: unknown) {
      setApiError(e instanceof Error ? e.message : "Reset failed.");
    } finally {
      setResetting(false);
    }
  }

  function resetSingle(field: string) {
    setDraft((prev) => ({ ...prev, [field]: "" }));
    setTimeout(() => saveField(field), 0);
  }

  if (loading) {
    return <p className="text-[12px] text-text-quaternary font-mono">Loading risk gates…</p>;
  }

  return (
    <div className="space-y-4">
      {apiError && (
        <div className="flex items-start justify-between rounded-md border border-signal-red/25 bg-signal-red/[0.06] p-3">
          <div>
            <p className="text-xs font-medium text-signal-red">Notice</p>
            <p className="text-[11px] text-text-tertiary mt-0.5">{apiError}</p>
          </div>
          <button
            onClick={() => setApiError(null)}
            className="text-text-quaternary hover:text-text-primary text-xs px-2"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-[11px] text-text-tertiary">
          Save-on-blur per field. Leave a field empty and tab out to reset that gate
          back to the platform default.
        </p>
        <div className="flex items-center gap-2 shrink-0">
          <StatusPill
            label={userOverrideCount > 0 ? `${userOverrideCount} CUSTOM` : "ALL DEFAULT"}
            tone={userOverrideCount > 0 ? "blue" : "neutral"}
          />
          <button
            onClick={resetAll}
            disabled={resetting || userOverrideCount === 0}
            className="px-2.5 py-1 rounded-md border border-signal-red/30 bg-signal-red/[0.06] text-signal-red text-[10px] font-mono tracking-wider hover:bg-signal-red/[0.12] transition-colors disabled:opacity-30"
          >
            {resetting ? "RESETTING…" : "RESET ALL"}
          </button>
        </div>
      </div>

      {toast && (
        <div className="rounded-md border border-signal-green/30 bg-signal-green/[0.06] px-3 py-2 text-[12px] text-signal-green">
          {toast}
        </div>
      )}

      <div className="space-y-4">
        {GROUP_ORDER.map((group) => {
          const rows = groups[group];
          if (!rows || rows.length === 0) return null;
          return (
            <TerminalPanel
              key={group}
              label={GROUP_LABELS[group] ?? group.toUpperCase()}
              status={
                <span className="text-text-quaternary">
                  {rows.filter((r) => r.source === "user").length} / {rows.length} CUSTOM
                </span>
              }
              bodyClassName="p-0"
            >
              <div className="divide-y divide-border-primary/40">
                {rows.map((p) => {
                  const isOverride = p.source === "user";
                  const draftValue = draft[p.field] ?? "";
                  const isSaving = savingField === p.field;
                  const error = errors[p.field];
                  return (
                    <div
                      key={p.field}
                      className="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-5 py-4"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <p className="text-[13px] font-medium text-text-primary">
                            {p.label}
                          </p>
                          {p.source === "user" && (
                            <span className="text-[9px] font-mono tracking-[0.18em] text-accent">USER</span>
                          )}
                          {p.source === "env" && (
                            <span className="text-[9px] font-mono tracking-[0.18em] text-signal-yellow">ENV</span>
                          )}
                          {p.source === "default" && (
                            <span className="text-[9px] font-mono tracking-[0.18em] text-text-quaternary">DEFAULT</span>
                          )}
                        </div>
                        <p className="text-[11px] text-text-tertiary leading-relaxed">{p.desc}</p>
                        {error && (
                          <p className="mt-1 text-[11px] font-mono text-signal-red">
                            {error}
                          </p>
                        )}
                        {p.default !== null && (
                          <p className="mt-1 text-[10px] font-mono text-text-quaternary">
                            Platform default: {toDisplay(p.default, p.scale)}{unitFor(p.scale, p.field)}
                            {" · "}Range: {toDisplay(p.range_min, p.scale)}{unitFor(p.scale, p.field)}–{toDisplay(p.range_max, p.scale)}{unitFor(p.scale, p.field)}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <input
                          type="number"
                          value={draftValue}
                          disabled={isSaving}
                          onChange={(e) =>
                            setDraft((prev) => ({ ...prev, [p.field]: e.target.value }))
                          }
                          onBlur={() => saveField(p.field)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.currentTarget.blur();
                            }
                          }}
                          placeholder={toDisplay(p.value, p.scale)}
                          className={[
                            "w-24 px-2.5 py-1.5 rounded-md bg-bg-primary border text-[13px] font-mono tabular-nums text-right text-text-primary outline-none transition-colors",
                            error
                              ? "border-signal-red/60 focus:border-signal-red"
                              : isOverride
                              ? "border-accent/40 focus:border-accent"
                              : "border-border-primary focus:border-zinc-600",
                          ].join(" ")}
                          step={p.scale === "pct" ? 0.1 : p.field.endsWith("_bps") ? 1 : 0.001}
                        />
                        <span className="text-[10px] font-mono text-text-quaternary w-4">
                          {unitFor(p.scale, p.field)}
                        </span>
                      </div>
                      <div className="w-20 text-right">
                        {isOverride ? (
                          <button
                            onClick={() => resetSingle(p.field)}
                            disabled={isSaving}
                            className="text-[10px] font-mono tracking-wider text-text-tertiary hover:text-signal-red transition-colors disabled:opacity-30"
                          >
                            RESET
                          </button>
                        ) : (
                          <span className="text-[10px] font-mono text-text-quaternary">—</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </TerminalPanel>
          );
        })}
      </div>
    </div>
  );
}
