# Access tiers — demo sandbox vs the paying MCP portal

> Maps the delineation in full: the free/eval **demo** (show the power, no
> signup) vs the paid **portal** (BYO-data MCP/REST behind a key). Informs T9
> (keys + sandbox), T12 (Clerk provisioning + dashboard), and the frontend
> demo route. Status: design — revisit after the infra todos land.

---

## The core distinction (one rule drives everything)

> **The demo fetches sample data for you. The portal never fetches anything.**

That single rule keeps the no-data invariant intact while still letting a
stranger experience the product:

- **Demo** is the *only* place fetching is allowed, and only for
  **unauthenticated, sample-data** runs. yfinance-backed sample data is
  non-commercial → demo/eval only, never on a paying path (locked decision #8).
- **Portal** (anything authenticated / paying) runs in **provided-mode only** —
  the seam (T5) makes the fetch layer unreachable. The customer brings their
  licensed data; we compute and discard it.

So "free vs paid" is not just a quota — it's a different **data plane**. This is
why a paying customer can trust the trust posture: their tier *structurally
cannot* source or store data, and that's enforced, not promised.

---

## Three tiers

| | **Demo (sandbox)** | **Free trial** | **Paid** |
|---|---|---|---|
| Signup | None | Yes (Clerk) | Yes (Clerk org) |
| Auth | None / public shared key | Per-user trial key | Per-client key(s) |
| Data mode | **Sample data we fetch** (eval) | **Provided-mode** (BYO) | **Provided-mode** (BYO) |
| Fetch layer | Reachable (sample only) | Unreachable | Unreachable |
| Surfaces | Desk UI on sample data + public sandbox API | Full MCP + REST + desk | Full MCP + REST + desk |
| Quota | Hard global rate limit | Generous trial quota, time-boxed | Metered seats + calls |
| Labeling | "EVAL — sample data" everywhere | "Trial" badge | — |
| Stores data? | No (sample is canned/ephemeral) | No | No |
| Purpose | Prove the power, zero friction | Activate on *their* data | Production |

The CTA ladder: **Demo (no signup)** → **Start free trial (signup → key)** →
**Paid seat**. Activation metric = time-to-first-signal on the trial.

---

## Two surfaces, mapped to tiers

### 1. The Desk UI (the product as it exists today)
- The gated Next.js app (`/dashboard`, `/analysis`, …). This is the human
  surface — the agent desk, memos, portfolio.
- **Demo slice:** a public, no-signup `/demo` route that runs the desk on a
  **canned sample dataset** (eval-labeled), so a stranger sees a real slate
  without an account. Read-only; no persistence; clearly marked sample data.
- **Trial/Paid:** the full gated app on the user's own context.

### 2. The MCP/REST Portal (the infrastructure product)
- The gateway: deterministic REST (`api.py`) + MCP (`server.py`).
- **Demo slice:** a public, rate-limited **sandbox key** that only accepts the
  deterministic tools against **sample payloads** (or the caller's own small
  payload, provided-mode) so the documented curl works without signup.
- **Trial/Paid:** per-client keys, provided-mode only, metered. The dashboard
  shows the connection snippet (MCP URL + key), usage, latency, quality — all
  from stateless metrics.

The desk UI and the portal are **two doors to the same engine**, not two
products (see README). A user can wire the API into their bot *and* open the
desk; the trial/paid entitlement covers both.

---

## How a request is routed (the gateway decision)

```
inbound request
  ├─ has a valid per-client key?
  │     yes → PORTAL: force provided-mode (seam on), meter the call, enforce quota
  │     no  → is it the public sandbox key (or no key on a sandbox route)?
  │              yes → DEMO: sample-data allowed, hard global rate-limit, eval-labeled
  │              no  → AUTH_MISSING / AUTH_INVALID
```

Key properties:
- **A paid key can never reach the fetch layer.** Provided-mode is forced for
  any authenticated request; the seam raises FetchForbidden otherwise.
- **The sandbox can never touch a customer's data** — it only ever sees sample
  data or the caller's own demo payload, and it's unauthenticated, so there is
  no customer to leak.
- **One key space, shared by REST + MCP** (build spec T9): the same key
  authenticates both doors.

---

## What this requires (build mapping)

- **T9** — key auth shared by REST + MCP, plus the **public sandbox key** with a
  hard global rate limit. The router above lives here.
- **T10** — metering/quota per key (portal only); the sandbox is rate-limited,
  not metered per-account.
- **T12** — Clerk → key provisioning: on signup, mint a trial key (Clerk
  org→key); the dashboard renders the connection snippet + stateless usage. The
  trial→paid upgrade flips the entitlement, not the data plane (both are
  provided-mode).
- **Frontend** — a public `/demo` route (desk on sample data, eval-labeled) and
  the docs sandbox (already previewed). The marketing CTAs become "Start free
  trial" (→ signup → key) with the demo reachable with no signup.
- **Sample datasets** — ship a small, redistributable canned dataset for the
  demo so it never depends on a live fetch at request time (and so the desk demo
  is deterministic for screenshots/launch).

---

## Open decisions (for the revisit)

- **Trial shape:** time-boxed (e.g. 14 days) vs quota-boxed (e.g. N jobs / N
  calls) vs both. Recommend quota-boxed (aligns with the metered billable unit).
- **Sandbox scope:** deterministic tools only, or also one agent-slate run on
  sample data? Agent runs cost real LLM tokens — recommend deterministic-only in
  the API sandbox, and the *agent* demo lives in the `/demo` desk route with a
  canned, pre-computed slate (no live LLM spend per visitor).
- **Sample dataset sourcing:** which tickers/period, refreshed how often, and
  the redistribution check on the canned data.
- **Pricing numbers** for the paid tier (still an open CEO input).
