# Multi-region serving under data residency — explained

---

## 1. The numbers force the design

Three regions times the full stack. Not three copies of the API — three copies of the *vector
store, cache, telemetry pipeline, eval harness and golden set*.

- **3x infrastructure**, most of it running well under capacity, because you cannot pool.
- **3x the eval surface.** Provider model versions differ by region, so a single suite
  validates one region and assumes the other two.
- **0x the failover** for regulated tenants. The standard availability answer is unavailable.

That last line is the one to lead with, because it is the one candidates get wrong.

---

## 2. Say this before anything else: every failure here is a best practice

Failover to a healthy region. One shared semantic cache. Centralised observability. One eval
suite in CI. Every one of those is the **correct** engineering answer in a single-region
system, and every one is a compliance breach here.

That reframing matters, because it tells you where the bugs will be. They will not be in the
code someone wrote carelessly. They will be in the code someone wrote *well*, against the
wrong assumption, usually months before residency became a requirement.

`solution.py §1` prices the first one: a textbook HA router, doing exactly what it was designed
to do when the EU provider goes down, produces **6,810 cross-border requests** out of 20,000.
Nothing malfunctioned.

---

## 3. The layers, each named by the failure it prevents

**Region as a hard boundary, routed at the edge on tenant residency** — *prevents:* the
accidental cross-border call. The decision has to happen before the request enters a regional
stack, because once it is inside, everything downstream is local by construction and looks
fine.

**Per-region vector store and per-region cache** — *prevents:* embeddings crossing. An
embedding is derived from personal data and is invertible enough that regulators treat it as
personal data. A shared cache is worse still: it holds the completion, keyed by the prompt.

**Region-local provider endpoints, pinned** — *prevents:* a global endpoint silently serving
from wherever has capacity. `api.provider.com` is not a region. Pin it, and assert the pin.

**Logs and traces stay in-region; only aggregate metrics cross** — *prevents:* exfiltration
via observability, which is the leak that actually happens. Counts, latencies and error rates
can cross a border. Span attributes carrying prompts cannot.

**No cross-region failover for regulated tenants; degrade in-region instead** — *prevents:*
the availability reflex from becoming the breach. `solution.py §1`: the residency-aware router
serves 13,190 and degrades 6,810 **in place**, at zero cross-border requests.

**Per-region eval runs, gated per region** — *prevents:* assuming model parity.
`solution.py §3`: the global average passes at 79.2 while `eu-west` sits at 77.8, under the
gate. Averaging three regions is how you ship a regression to one of them.

**A residency test in CI** — *prevents:* all of the above from silently regressing. This is
the only control on the list that survives staff turnover.

---

## 4. What actually counts as personal data

This is the part that separates a real answer from a diagram.

| Artefact | Leaks in a naive 3-region build? | Why it counts |
|---|---|---|
| Prompt | No | Everyone protects this one |
| Completion | No | Also obvious |
| **Embedding** | **Yes** | Derived from the text, and invertible enough to matter |
| **Cache entry** | **Yes** | Holds the completion, keyed by the prompt |
| **Trace / log** | **Yes** | Prompt and completion ride along as span attributes |
| **Eval sample** | **Yes** | A snapshot of real customer text, copied into a golden set |

`solution.py §2` runs this: the naive build routes the prompt **correctly** and still leaks
four artefacts. Each one is a sensible default that shipped before residency was a requirement.

The eval sample is the sneakiest, because the golden set is usually built by hand from real
production traffic, committed to a repo, and then replicated wherever CI runs.

---

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **The failover design** | Your instinct is to fail over. For regulated tenants that instinct is the breach. |
| 2 | **Telemetry** | Configured by a different team, and traces do not look like customer data until you read the span attributes. |
| 3 | **Model parity** | Same model ID, different rollout state per region. Nobody is told. |
| 4 | **Cost** | 3x the stack, each running at a third of the utilisation you sized for. |
| 5 | **The golden set** | Real customer text, copied into a repo, replicated to wherever CI runs. |

---

## The follow-ups, answered

**1. Your EU region loses its LLM provider. What happens to EU traffic?**

For regulated tenants: it degrades **in region**, and you decide in advance what that means.
The ladder, best first — serve from the in-region semantic cache; fall back to a second
in-region provider if you have one; fall back to a smaller in-region self-hosted model; queue
with an honest wait; refuse with a clear message. What you must not do is fail over to
`us-east`, because a compliance breach is not an availability improvement. For unregulated
tenants, fail over normally. That difference is exactly why residency is a **per-tenant
attribute** rather than a global mode.

**2. Are embeddings personal data?**

Yes, and argue it rather than asserting it. An embedding is a deterministic function of the
input text, it preserves enough semantics to support similarity search — that is the entire
point — and inversion attacks recover substantial fragments of the source. Under GDPR the test
is whether an individual is identifiable from the data, directly or indirectly; a vector that
lets you retrieve the original document clears that bar. Design consequence: **per-region
vector stores, and the index is not a cache you can rebuild anywhere.** If you ever re-embed,
the job runs in region too.

**3. A US engineer opens a trace to debug an EU customer's bad answer. Is that a breach?**

If the trace carries the prompt or completion, yes — that is an international transfer, and it
happens over a coffee with no record. Three fixes, in order of how much they cost you:
region-locked telemetry backends so the trace is not reachable from a US console at all;
payload redaction at the collector so traces carry IDs and shapes rather than text; and
break-glass access that is time-boxed, approved and logged, for the cases where someone really
must see the text. Keep aggregate metrics global — you still want one latency dashboard.

**4. The same model ID scores 4 points lower in `eu-west` than `us-east`.**

First, believe it — this is the normal state, not an anomaly. Providers roll versions out by
region and rarely announce it. So: pin the model *version*, not the family, in every region;
gate each region against its own baseline rather than a global average; and treat a version
change as a deploy that must pass the regional suite before it takes traffic. If the EU region
genuinely cannot reach the gate, that is a **product** decision — ship a reduced feature set
in the EU, or do not ship there — and it needs to be made by someone who can own it, not
absorbed silently by an average.

**5. Where does the semantic cache live, and what is its key?**

In region, always, and never shared. The key must include **tenant, region, corpus version and
persona** — not just a hash of the prompt. Two independent reasons: a global cache keyed on
prompt alone will serve one tenant's completion to another, which is a data leak before it is
ever a residency issue; and omitting corpus version means the cache keeps serving pre-reindex
answers forever. Residency makes a bad cache key into a reportable incident rather than a bug.

**6. How do you prove no EU prompt reached a US endpoint last March?**

Design for this up front, because you cannot reconstruct it later. What an auditor will accept:
network-level egress policy denying the EU stack any route to non-EU endpoints, so the claim
rests on infrastructure rather than application logic; a per-request log of the resolved
endpoint, stored in region and retained; the CI residency test with its history, showing the
control was in force on every deploy that month; and the change log for the routing config. The
weak answer is "we reviewed the code" — an auditor wants a control that would have *failed*,
not an assurance that it did not.

**7. A tenant relocates from US to EU. Migrate them.**

It is a data migration with a cutover, not a config flip. Provision in EU; copy the corpus and
**re-embed in region** rather than copying vectors, if the source region's model version
differs; replay or discard the cache — usually discard; move the conversation history; then
flip the routing attribute; then verify the old region holds nothing, and that includes the
cache, the traces within retention, and any golden-set samples drawn from that tenant. Then
delete, with evidence. The step everyone forgets is the last one: the tenant is EU now, but
their data is still sitting in `us-east` telemetry for another 30 days.

**8. What does this cost, honestly?**

Substantially more than 3x, and say so plainly. Three stacks each sized for peak but each
carrying a third of the traffic, so utilisation drops and the per-request cost rises. Three
eval runs per change. Three on-call surfaces. No cross-region pooling, so headroom cannot be
shared. A second provider per region if you want in-region failover at all. The honest framing
for a business: **this is a market-access cost, not an engineering cost** — you are buying the
right to sell in the EU. Price it that way and it is a straightforward decision; price it as
infrastructure and it looks like an engineering failure.

**9. Design the CI test that would have caught the leak.**

Walk the deploy config for every regulated region, and for every client that can carry personal
data — LLM endpoint, vector store, cache, telemetry collector, eval bucket — assert the URL
resolves in that region. `solution.py §4` is that test in a dozen lines, and it catches the
realistic failure: four of five clients regionalised, and the OTel collector still pointing at
a global endpoint because observability is owned by a different team. Two properties matter:
it reads **config, not intent**, and it **fails the build** rather than filing a ticket.
Extend it with an egress test in staging that asserts the EU stack cannot open a connection to
a non-EU host at all.

---

## One-line summary

Residency inverts four things that are correct everywhere else — failover, a shared cache,
central observability and one eval suite — so the design is a hard per-tenant region boundary
with in-region degradation instead of failover, every derived artefact (embeddings, cache,
traces, eval samples) treated as personal data, per-region model pinning and gating, and a CI
test that reads config rather than trusting intent.

---

## The trap answer to avoid

Answering with routing and stopping there — "we route EU tenants to the EU region". That is the
easy 20% and it is the part that will not break. The two real traps underneath it: assuming
**embeddings and logs are exempt** because they are not the prompt, and preserving
**cross-region failover** because high availability is always good. The second is worse,
because it only fires during an incident, when nobody is reading the routing table.
