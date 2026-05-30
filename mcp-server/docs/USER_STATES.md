# User states & isolation — who sees what

> Companion to ACCESS_TIERS.md. That doc maps the data-plane boundary (demo
> fetches sample data; portal never fetches). This doc maps the two axes of
> "who sees what": the entitlement **state** (demo / trial / paid) and per-user
> **isolation** (you only ever see your own work).

## Two independent axes

1. **Entitlement state** — *which surfaces and which data plane you may use.*
   Lives on the identity: Clerk `publicMetadata.entitlement` (the brief's
   mechanism) mirrored by a server-side `user_profiles.entitlement` column
   (source of truth the backend can enforce without a Clerk round-trip).
   Values: `demo | trial | paid`. New sign-ups default to `demo`.

2. **Isolation** — *whose data you can read.* Already enforced: every backend
   read/write filters by `user_id` (memos, profiles, risk profiles, portfolio +
   position snapshots). The prior multi-tenant bug was fixed to make `user_id`
   required. So two authenticated users — demo or paid — never see each other's
   work today. This is verified in `db/repositories.py`.

These are orthogonal: a demo user is isolated from every other user *and*
restricted to the sample-data plane; a paid user is isolated *and* on the
provided-mode plane. Upgrading flips the state, not the identity, and never
exposes another user's data.

## State → surface → data plane

| State | Surfaces | Data plane | Isolation |
|---|---|---|---|
| (none / logged out) | `/`, `/docs`, public `/demo` (shared canned slate) | sample only | n/a — no per-user state |
| `demo` | demo desk (the existing app), eval-labeled | sample data (we fetch, eval) | per `user_id` |
| `trial` | demo desk **+** `/portal/*` (keys, sandbox) | provided-mode (BYO) on the portal | per `user_id` / org |
| `paid` | demo desk **+** `/portal/*` | provided-mode (BYO) on the portal | per `user_id` / org |

The public `/demo` slate is the one place with **no per-user state**: it is a
single canned, read-only result shown to everyone (including the
`likely_noise` idea). Nothing a visitor does there is saved, so there is nothing
to leak between visitors.

## Where each axis is enforced

- **Isolation** — the backend, already. Never add a query that reads across
  users without a `user_id` filter (the standing rule in CLAUDE.md).
- **State / surface gating** — Clerk entitlement gates the **UI** (which routes
  render, which banner shows). This is UX, not security.
- **Data-plane** — the **gateway/seam** is the security boundary (ACCESS_TIERS):
  a portal key forces provided-mode and the fetch layer is unreachable; a demo
  identity has no portal key and can only reach the sample-data path. A React
  guard or banner is never the wall.

## What this requires (folded into the SPLIT todos)

- **Backend:** `user_profiles.entitlement` column (default `demo`), exposed on
  `/api/me/profile`; resolve helper treats missing as `demo`. *(Executable now —
  the per-user state.)*
- **Clerk:** default `publicMetadata.entitlement = demo` on demo sign-up; portal
  sign-up mints `trial`; upgrade → `paid`. A Clerk webhook keeps the backend
  column in sync. *(Needs the Clerk dashboard / webhook — flagged.)*
- **Frontend:** read entitlement, show the eval banner for `demo`, gate
  `/portal/*` to `trial|paid`. *(Marketing/split pass.)*
- **Gateway:** portal key → provided-mode (done, T5+T9); demo identity → sample
  path only.
