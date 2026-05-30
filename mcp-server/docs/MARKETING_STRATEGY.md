# AlphaEngine — Master Marketing Strategy

> The single source of truth for positioning, go-to-market, launch, and pricing.
> Companion: `MASTER_PLAN.md` (the build) and `SIGNAL_ENVELOPE.md` (the contract).

---

## 1. Positioning

**Anchor (everything ladders to this): "The signal layer between your data and your algo."**

AlphaEngine is infrastructure, not a research app. Every systematic trader rebuilds
the same plumbing — wrangle data, compute signals, check for overfitting, gate for
risk, generate ideas, format for execution — and most do the validation badly or
not at all. AlphaEngine does it once, correctly, for everyone, on data that never
leaves the trader's control.

> **Your data in. Validated, cited, risk-checked, algo-ready signals out. Nothing stored.**

**Lead with two things only:** *it plugs into your algo*, and *it tells you when
it's noise.* The stateless / no-data story is the **trust close**, not the headline.

**Positioning statement (internal north star):**
> For **solo quants and small trading shops** who **already have data and agent
> workflows but no validated, end-to-end idea pipeline**, AlphaEngine is **a
> stateless signal-infrastructure layer** that **turns their own data into cited,
> overfitting-checked, algo-ready signals** — unlike **stitching together free
> libraries in a notebook**, which gives math but no provenance, no overfitting
> guardrails, no agent reasoning, and nothing an execution layer can consume directly.

**The "afternoon test" (why this is defensible):** a competent quant can rebuild any
single tool (an OLS factor regression, a parametric VaR) in an afternoon with an LLM.
So no single tool is the product. What survives the afternoon test is the **bundle**:
deterministic math + probabilistic agent reasoning + citations on every figure +
overfitting honesty + a secure, stateless delivery + a machine-readable signal an algo
can consume. That assembled, validated pipeline is the moat.

---

## 2. Audience

**Beachhead:** smaller entities and solo traders willing to pay. Not pods/institutions yet.

| | **Solo / systematic trader (primary)** | **Small fund / emerging manager (secondary)** |
|---|---|---|
| Wants | Cheap, self-serve, wire it into my bot | Desk-grade rigor without desk-grade cost; infra behind my stack |
| Path | MCP + direct API; desk UI as a bonus | API/MCP as infra; desk UI for analysts |
| Buys on | "It plugs into my algo and tells me when it's noise" | "Stateless, traceable, we never touch our data" |

**Profile:** a self-directed systematic trader who can code their own signals but has
no rigorous, repeatable pipeline that's honest about overfitting and feeds their algo
directly. Lives on fintwit, r/algotrading, quant Discords, and has started wiring
Claude/agents into their workflow.

**Where they are:** X/Twitter quant corner ("fintwit"); r/algotrading, r/quant;
QuantConnect-adjacent communities; quant Discords/Slacks; Hacker News; **MCP
directories and the Claude/Anthropic ecosystem** (a distribution surface unique to
being MCP-native).

---

## 3. Messaging

- **Core:** *"Your data in. A cited, overfitting-checked, algo-ready signal out. Nothing stored."*
- **Supporting + proof:**
  - *"We tell you when it's noise."* → deflated Sharpe, PBO, purged CV. **Proof:** a real idea the system flagged as `likely_noise`.
  - *"Every number is traceable."* → full provenance on the signal. **Proof:** a sanitized cited slate / envelope.
  - *"Your data never leaves your control."* → stateless, BYO-data, nothing sourced or stored. **Proof:** the two-plane architecture + no-data telemetry.
  - *"It plugs into what you already run."* → MCP-native + a direct API + a Python SDK. **Proof:** a 20-line example script.

---

## 4. The marketing site: reposition from "engine + memo" to "infrastructure + signal"

The current page is well-built (institutional restraint, strong source-ledger and
verified motifs) but sells an *engine* and a *human memo*. Reposition without redesigning.

**Section fixes:**
- **Hero:** "The signal layer between your data and your algo." Sub: stateless engine on your own data; computes the math, checks for overfitting, returns cited, risk-gated, algo-ready signals — over MCP for your agent or a direct API for your bot; nothing sourced, nothing stored.
- **Hero tearsheet (highest-leverage single change):** keep the human memo, but **add a split showing the same result as a `SignalEnvelope` JSON.** Caption: *"Human-readable for your desk. Machine-readable for your algo. Same result, same receipts."* This one visual communicates the whole thesis.
- **Add a "05 / OUTPUT" showcase card:** "Signals your algo can consume" — the envelope (instruments, levels, overfitting verdict, provenance), over MCP or REST.
- **Add a "How it works" section:** the two-plane pipeline on one screen.
- **TopNav:** `PRODUCT · HOW IT WORKS · DOCS · TRUST · PRICING`. (A docs link is a credibility signal for infra buyers.)
- **SourceLedger copy:** extend the "validator refuses to ship a figure it can't trace" promise to *also* refuse an **idea it can't validate** (rigor, not just provenance).
- **Two-door CTA:** primary "Read the docs / Connect the MCP" (algo persona); secondary "Open the desk / Try the live demo" (human persona).
- **Public docs page:** one real request → envelope (REST + MCP).
- **Pricing placeholder:** "In beta — join the beta." (Absence reads as "not real.")
- **Keep verbatim** — the strongest line on the page: *"NO DATA, BY DESIGN. Your data goes in. The math comes out. Nothing stays."*

**Flow:** keep the app gated (correct — it's per-user). Add the **integration
onboarding branch**: first question "How will you use AlphaEngine?" → [wire it into
my algo] / [use the desk] / [both]. The wire-in path → provision key → connection
snippet → "your first call" doc → copy-paste example returning an envelope. **Demo
runs on sample data with no signup** (eval-labeled). Activation metric =
**time-to-first-signal**.

---

## 5. Launch assets (these ARE the marketing — build before launch)

1. **The JSON/memo split tearsheet** — the one visual that sells the thesis.
2. **Public docs page** with a real request → envelope (REST + MCP).
3. **The Python SDK + example script** — "20 lines: your prices in, a validated signal out." The proof, not a claim.
4. **One sanitized real slate where the system flagged its OWN idea as `likely_noise`.** The honesty is the brand; this is the single best asset you can make.

---

## 6. Go-to-market — launch channels (solo founder, lean; architecture-as-marketing)

| Channel | Angle | Why it fits |
|---|---|---|
| Build-in-public on X / fintwit | "We flagged our own idea as noise" + the split tearsheet | Contrarian, shareable; the honesty hook |
| **Show HN** | "Stateless quant signal infra your algo calls — nothing stored" | HN rewards infra + the two-plane/no-data architecture + MCP-native; SDK & docs make it credible |
| **MCP directory listings + Claude-ecosystem post** | "MCP-native quant desk" | Native distribution to the agent-builder crowd |
| r/algotrading + quant Discords | The SDK example: "paste prices, get a validated signal" | Hands-on hook for the algo persona |
| Launch technical writeup | "Why we never store your data, and how the two-plane design lets your algo trust the output" | The architecture *is* the differentiation — explain it |
| Founder-led fund outreach | The trust posture (stateless, traceable, BYO-data) | Funds buy on trust, not features |

**Skip:** paid ads, PR firms, conferences, webinars, podcast. Wrong stage. Every hour
goes to the SDK, the docs, and talking to users.

---

## 7. Funnel & activation

**Demo (no signup, sample data)** = top of funnel → **SDK quickstart / first API
call** = activation ("aha") → **paid beta seat** = conversion. Optimize
**time-to-first-signal** the way a SaaS optimizes time-to-first-value. For the algo
persona, "aha" is a real signal envelope returned from their own call — instrument
and shorten that path relentlessly.

---

## 8. Pricing & price discovery

Goal: land paying beta seats, **discover** price — don't guess it. Cheap, and
**grandfathered for life** as the close.

**Anchor hypotheses (to test, not commit):**

| Segment | Hypothesis | Note |
|---|---|---|
| Solo trader | **$29–$79 / mo** | Impulse-range for a working trader |
| Small shop (1–5) | **$199–$499 / mo** | Per-org, a few seats included |

*(Anchors, not researched numbers — validate against what your audience already pays
for tooling/data.)*

**Discovery method:**
- **Founder interviews (n≈5):** what do they pay for tools today; what would this have to do to be worth $X.
- **Two-price test:** show cohorts two price points; watch conversion, not opinions.
- **Van Westendorp survey** (too cheap / cheap / expensive / too expensive) to bracket the range.
- **Grandfathering** as the beta close — converts fence-sitters, rewards early users.
- **Decide** once you have ~15+ data points.

**Billable unit (aligns with the build):** seats for the desk + metered calls/jobs for
the API, generous beta quotas. Don't hide pricing — a "join the beta" page with a number.

---

## 9. Content calendar (lean, 6 weeks)

| Week | Piece | Channel | Notes |
|---|---|---|---|
| 0 | Repositioned page (hero + split tearsheet + How-it-works + docs) | Owned | Depends on the envelope shape being pinned |
| 0 | SDK + "your first call" doc + example script | Owned | The activation path |
| 1 | "We tell you when it's noise" thread + sanitized slate | X / fintwit | The hook |
| 1 | Founder-interview outreach (target 10, land 5) | Outbound | Pricing + JTBD discovery |
| 2 | Show HN / r/algotrading launch post | Earned | Lead with MCP + no-data + algo-ready |
| 2 | MCP directory listings + README | Earned | Passive inbound |
| 3 | "Plug it into your algo" demo (envelope → toy execution) | X / blog | Proves end-to-end |
| 3 | Two-price test live | Owned | Discovery |
| 4 | Beta-user quote / mini-case (if any) | X / owned | Social proof |
| 4–6 | Iterate price; double down on the channel that converted | All | Kill what didn't work |

---

## 10. Metrics & beta exit criteria

| Metric | Target (6 wk) |
|---|---|
| Paying beta seats | 15–25 |
| Activated users (connected + ran a signal) | ≥60% of signups |
| Founder interviews | 5 |
| Time-to-first-signal | minimize; instrument it |
| Week-4 retention (activated) | ≥40% |
| Price range converged | a defensible $X |

**Beta is "done" when:** N paying seats + a price discovered + activation/retention
thresholds met — not merely when features ship. Track activation and retention over
raw signups; 15 engaged users teach more than 500 tire-kickers.

---

## 11. Risks & mitigations

- **"Quants can build it themselves"** → never sell the calculator; sell the validated, cited, algo-ready *pipeline* and the overfitting honesty (the afternoon test).
- **"Why send you my data?"** → lead with stateless/no-data; let them point their *own* data at it and verify nothing's stored.
- **No social proof yet** → the sanitized "we flagged our own idea as noise" slate IS the proof; manufacture one great artifact.
- **Pricing too low to signal value / too high to convert** → the two-price test + grandfathering resolve it.
- **Investment-advice perception** (outputs look like recommendations to retail) → ship a "computational tooling, not investment advice" disclaimer/ToS; clear counsel before charging.
- **Gating** → keep the app gated; decide explicitly between a public marketing page vs an invite-only waitlist and commit the page to one.

---

## 12. Open CEO inputs

- **Pricing numbers** (before real pricing copy ships).
- **Gating style** — public marketing page vs invite-only beta waitlist.
- **White-label** — day-one messaging vs "contact us" (if pursued).
- **Legal sign-off** — no-data/eval framing + the advice disclaimer, before charging.
