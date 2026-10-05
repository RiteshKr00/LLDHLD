# The prompt and config platform at scale

## 1. Numbers first

| Input | Value |
|---|---|
| Tenants | 500, ~40 with a tuned chat prompt |
| Features | 4 — RAG chat, summarisation, extraction, voice |
| LLM calls/day | 600k → **7 QPS average, 70 peak** |
| Config resolutions | **one bundle per call** — same 7/70 QPS |
| Config changes/year | 4 × ~2/week × 50 weeks = **~400**, currently **0 reviewed** |
| Binding rows | ~900 live, sparse against 500 × 4 × 3 = 6,000 possible |
| Whole corpus | 400 versions/yr × 3 yr × ~4 KB ≈ **5 MB** |
| Spend | $0.004/call → **$2.4k/day, $72k/month**, input at **$2 per 1M** |
| Rollback target | **30s** pointer flip vs **~12 min** redeploy |

**Little's Law: 70 QPS × ~2s service time = ~140 requests in flight**, each holding a resolved
bundle for its whole lifetime. So a promotion always has **two snapshot generations live at
once**. That is not a race to eliminate — it is the constraint: snapshots are immutable, the
swap is an atomic pointer assignment, and generation N−1 stays reachable for at least one
service time (longer for streaming and for voice sessions).

**What the rest of the numbers force:**

- **5 MB of config against 600k reads/day** — so the corpus ships whole to every pod and
  resolution is an in-memory dictionary walk. A per-request read would put a 100%-blast-radius
  dependency in the path of every LLM call to save nothing.
- **400 unreviewed changes against a fully-reviewed codebase.** The gate is the product; the
  storage is incidental.
- **+500 prompt tokens on chat = $400/day = ~$12k/month.** Cost belongs in the gate, priced in
  the diff, not discovered in the invoice.

## 2. Topology — a control plane and a data plane that never share a request

```
authoring (dashboard / PR / API)
        │  change request, never a write
        ▼
  promotion service ── eval gate (topic 08) ── token budget ── contract check
        │  the ONLY writer
        ▼
  version store (write-once, content-addressed)  ──► binding table
        │                                                │
        └───────────── snapshot builder (~5 MB) ◄────────┘
                              │  pub/sub push, 10s poll fallback
        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
   app pod: in-memory resolver              app pod: in-memory resolver
        │  bundle id + winning rule on every request
        ▼
   LLM call ──► traces / logs / eval records ──► guardrails ──► auto-revert
```

The dashed line in an interview: **the control plane can be entirely down and serving is
unaffected.** Pods hold the last snapshot in memory and on local disk. What you lose is the
ability to *change* config, which is the correct thing to lose.

## 3. Scaling levers

| Pressure | Lever |
|---|---|
| More pods (fan-out on publish) | pub/sub push, not polling; 10s poll only as a repair path |
| More tenants with overrides | bindings stay sparse rows; never materialise 500 × 4 × 3 |
| Corpus growth past memory | ship only bundles reachable from live bindings + the last N |
| Gate wall-clock | tiered eval — smoke on the change request, full tier on promote |
| Canary throughput | bucket by conversation hash, so widening needs no coordination |

## 4. Multi-tenant fairness

Fairness here is not throughput, it is **who can overwrite whom**. Three rules:

- A **global promote must never silently supersede a tenant override** — precedence rank, not
  insertion order. This is the failure `solution.py` measures.
- A **tenant override must not fork forever.** Track *override drift* (versions behind global)
  and expire overrides deliberately; the 40 tuned prompts are 40 pieces of debt.
- **Per-tenant canaries for tenant-scoped changes.** A global bundle canaries by traffic share;
  a change to one tenant's override canaries within that tenant, or the sample is one account.

## 5. What breaks, in order

1. **Precedence confusion** — the only failure on the happy path. No error, no alert, and it
   compounds with every override. Fixed by a total order plus the resolved bundle id on every
   request; everything else here is undebuggable without that id.
2. **A pod stuck on a stale snapshot** — a missed push and a broken poll. Silent, and it makes
   canary numbers a blend. Detected by *distinct bundle ids per (feature, env)*.
3. **The gate becomes a bottleneck** — a six-minute wait on a one-line copy fix, so people route
   around it. A bypassed gate is worse than no gate because it looks like coverage.
4. **Version sprawl** — 400 bundles a year plus per-tenant forks; snapshot size and human
   comprehension both degrade before anything errors.
5. **Canary contamination** — bucketing per request rather than per conversation.
6. **Audit gaps at rollback** — the promote is recorded, the 2am revert is not.

## 6. Degradation — and it differs per feature

| Failure | Behaviour |
|---|---|
| Control plane down | serving continues on the last snapshot; **promotion pauses** |
| Snapshot fetch fails on a **new** pod | **fail closed** — do not start serving with empty config |
| Snapshot fetch fails on a **running** pod | **fail open** — keep the old snapshot, alarm on age |
| Eval provider down | promotion **blocks**; break-glass pages and expires in 4h |
| Chat | tolerates a stale prompt for hours |
| Extraction | must not — a stale bundle means schema drift, so it pins the bundle in the deploy artifact and refuses a snapshot older than its consumer contract |
| Voice | resolve once at call start and hold for the session; never hot-swap mid-call |

The new-pod/running-pod split is the interesting one: the same failure gets opposite answers
because a running pod has a known-good config and a new one has nothing.

## 7. Observability

Per feature, per environment, per tenant cohort: promotion rate, gate pass/block rate with
reasons, canary arm divergence, rollback count and rollback wall-clock, prompt token count per
bundle as a time series.

**Leading indicators — these move before anything shows up as an error:**

- **% of requests carrying a resolved bundle id** — anything under 100% is the exact fraction of
  the next incident you will not be able to explain
- **distinct bundle ids serving one (feature, env)** — 1 normally, 2 briefly during a flip; a
  persistent 3 is a stuck pod
- **snapshot age p99 per pod** — rises before the stuck pod is noticed
- **break-glass uses per month** — should trend to zero; a rising count means the gate is too slow
- **override drift** — tenant overrides drifting behind global predicts the next "why is this
  tenant different" ticket
- **prompt token count per bundle** — cost regressions are silent and permanent
