"""
Gateway access control (T9 + T10) — one dependency shared by REST and MCP.

Auth: a per-client bearer key resolves to an Identity{client_id, tier}. A public
sandbox key resolves to the "sandbox" tier (eval). AUTH_STUB short-circuits to a
local paid identity for development. Metering: fixed-window per-client counters
enforce a ceiling and raise QUOTA_EXCEEDED. We count calls only — never the
payload, never any value (invariant #1).

Env:
  AUTH_STUB=1            bypass auth (local dev / tests). Default on; set 0 in prod.
  MCP_API_KEYS="k:client,k2:client2"   paid keys -> client ids.
  SANDBOX_API_KEY        the public, rate-limited key (default ae_sandbox_public).
  SANDBOX_RATE_LIMIT     calls per SANDBOX_WINDOW_S (default 60 / 60s).
  PAID_DAILY_QUOTA       calls per 24h for a paid client (default 100000).

The routing decision from docs/ACCESS_TIERS.md lives here: a paid/authenticated
identity always runs provided-mode (the seam is engaged by the caller path); the
sandbox is rate-limited and eval-labeled.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from fastapi import Request

from contracts.errors import AuthInvalid, AuthMissing, QuotaExceeded

_DEFAULT_SANDBOX_KEY = "ae_sandbox_public"


@dataclass
class Identity:
    client_id: str
    tier: str  # "paid" | "sandbox" | "local"


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _load_paid_keys() -> dict[str, str]:
    """Parse MCP_API_KEYS='key:client,key2:client2' -> {key: client_id}."""
    out: dict[str, str] = {}
    for part in (os.getenv("MCP_API_KEYS", "") or "").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            k, c = part.split(":", 1)
            out[k.strip()] = c.strip()
        else:
            out[part] = part[:12]
    return out


def resolve_identity(request: Request) -> Identity:
    if _truthy(os.getenv("AUTH_STUB", "1")):
        return Identity("local", "local")

    authz = request.headers.get("authorization", "")
    if not authz.lower().startswith("bearer "):
        raise AuthMissing("missing bearer token in Authorization header")
    key = authz[7:].strip()
    if not key:
        raise AuthMissing("empty bearer token")

    if key == os.getenv("SANDBOX_API_KEY", _DEFAULT_SANDBOX_KEY):
        return Identity("sandbox", "sandbox")

    paid = _load_paid_keys()
    if key in paid:
        return Identity(paid[key], "paid")
    raise AuthInvalid("unrecognized API key")


# ── metering (fixed window, in-memory; never stores payloads) ─────────────

_lock = threading.Lock()
_windows: dict[str, list] = {}  # client_id -> [window_start, count]


def _limit_for(tier: str) -> tuple[int, int]:
    """(max_calls, window_seconds) for a tier."""
    if tier == "sandbox":
        return int(os.getenv("SANDBOX_RATE_LIMIT", "60")), int(os.getenv("SANDBOX_WINDOW_S", "60"))
    if tier == "local":
        return 10**9, 60  # effectively unmetered locally
    return int(os.getenv("PAID_DAILY_QUOTA", "100000")), 86400


def meter(identity: Identity) -> None:
    """Increment the call counter; raise QuotaExceeded over the ceiling."""
    limit, window = _limit_for(identity.tier)
    now = time.time()
    with _lock:
        slot = _windows.get(identity.client_id)
        if slot is None or now - slot[0] >= window:
            slot = [now, 0]
        slot[1] += 1
        _windows[identity.client_id] = slot
        count = slot[1]
    if count > limit:
        raise QuotaExceeded(
            f"call quota exceeded for tier '{identity.tier}' "
            f"({limit} per {window}s)",
            details={"limit": limit, "window_seconds": window, "tier": identity.tier},
        )


def usage_for(client_id: str) -> dict:
    with _lock:
        slot = _windows.get(client_id)
    if not slot:
        return {"client_id": client_id, "calls_in_window": 0}
    return {"client_id": client_id, "calls_in_window": slot[1], "window_started_at": int(slot[0])}


def reset_meter() -> None:
    """Test helper — clear all counters."""
    with _lock:
        _windows.clear()


def require_call(request: Request) -> Identity:
    """FastAPI dependency: authenticate, meter, return the Identity."""
    identity = resolve_identity(request)
    meter(identity)
    return identity
