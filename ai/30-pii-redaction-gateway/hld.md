# The redaction gateway at scale

## 1. Numbers first

| Input | Value |
|---|---|
| LLM calls | 600k/day → **~7 QPS average, ~70 peak** |
| Bytes scanned per call | the assembled prompt, **~6,000 chars** |
| Deterministic pass | **~3 ms** |
| Little's Law on the stage | 70 × 0.003 s = **0.2 concurrent** |
| Inline extractor at 4% | 70 × 0.04 × 0.6 s = **~1.7 concurrent** |
| Inline extractor at 30% | 70 × 0.30 × 0.6 s = **~12.6 concurrent** |
| Vault writes | ~4 entities/call → **280 writes/s peak, 2.4M entries/day** |
| Vault residency at a 24h TTL | ~2.4M keys, ~200 bytes each → **~500 MB** |

**What those numbers force:** the deterministic stage is not a capacity problem at all — 0.2
concurrent is noise. Everything expensive in this design is the **escalation**, and the
escalation rate is set by *tenant data* rather than by your code. That is the one number to
build controls around, and it is why the design treats ambiguity as a routing decision instead
of a wait.

## 2. The stage runs in-process, never as a remote service

Same argument as the gateway topic — a remote hop costs latency and adds a failure domain to a
component whose job is to protect both — plus one that is specific to this scenario:

> A remote redaction service means the **raw, un-redacted prompt crosses a network boundary to
> a second system**, which now has it in memory, possibly in its access logs, and certainly in
> its trace spans. You have added a place for the data to leak in order to stop the data
> leaking.

So: a library inside the gateway process, or a sidecar in the same pod at worst. The recogniser
pack and the treatment table are config, cached in memory, reloaded on a pub/sub signal and
**versioned**, because every audit answer is "under policy version N".

## 3. The escalation budget is admission control, not a hope

The extractor is finite — GPU seconds or an API quota — and three paths want it: the async
sample of sync traffic, the batch and ingestion path that *does* run it inline, and any
tenant-specific backfill. Give it a shared token bucket in Redis, **per tenant as well as
global**, so one tenant's free-text corpus cannot eat the whole budget. Above the cap the batch
path queues, because it has no latency budget, and the sample is dropped, because it is a
sample. Nothing on the sync path ever waits for it, which is what makes the cap safe to enforce.

Alert on the ambiguity **rate**, not on bucket saturation. A move from 4% to 12% means an
eighth of your traffic is now leaving the third-party path — a corpus change — and you want it
as a graph before you get it as a quality complaint.

## 4. The vault is the most sensitive store you now own

- **Per-tenant encryption key** from the KMS; the token index is an HMAC of the value, so the
  key material is not the plaintext
- **TTL measured in hours**, matched to the longest legitimate reversal window — an async
  extraction job that finishes on Monday is the constraint, not chat
- **Its own access policy and its own audit trail.** Nothing that reads prompts should also be
  able to read the vault
- **In the data inventory on day one**, or you will discover during a subject-access request
  that you built an undocumented PII store

Sizing is not the problem — 500 MB is nothing. Retention creep is the problem, so the TTL is a
reviewed config value, not a constant somebody bumps during an incident.

## 5. Per tenant, because a recogniser set is jurisdictional

Tenants get a **recogniser pack** (India: Aadhaar, PAN, GSTIN, IFSC · UK: NHS number, NI
number, sort code · clinical: MRN, subject id), a per-tenant escalation bucket, a per-tenant
treatment table that may only be *stricter* than the platform default, and their own canary
tokens planted in a test corpus. Aggregate detection metrics hide the tenant whose recogniser
pack is wrong for their data.

## 6. What breaks, in order

1. **Escalation rate**, because it is the only number that moves without a deploy and it moves
   with tenant data. In the routing design it degrades **quality** silently rather than latency
   loudly, which makes it harder to notice, not easier.
2. **Recall on unenumerated entity types.** No error, no alert, no exception — the recogniser
   list is a document you wrote in a room, and the world keeps adding identifier formats.
3. **The reversal path**: an invented placeholder the model was never given, a token split
   across stream chunks, a vault entry that expired before an async job finished. First
   user-visible bug in the whole design.
4. **Vault retention creep**, which converts a transient mapping into a standing liability.
5. **Over-redaction eroding answer quality**, followed by thresholds being loosened quietly.
   A governance failure, not a code one, so the control is a changelog and an owner.
6. **The egress proxy** as a hard dependency — run a pair per AZ, and be clear that its
   failure mode is *no LLM calls at all*, which is the correct failure mode.

## 7. Degradation, and it differs per surface

| Surface | Detector down or over budget |
|---|---|
| RAG chat | route to the in-VPC model, mark the answer degraded, keep streaming |
| Extraction | **fail loudly** — a wrong or blocked extraction is better than a leaked one |
| Voice | deterministic-only detection, narrowed scope, in-VPC destination. There is no retract once TTS has spoken, and the 800 ms time-to-first-audio budget forbids escalation entirely |
| Batch and ingestion | no latency budget, so run the extractor **inline** on ambiguous chunks and take the 600 ms — this is the one path where design B is right |
| Anything with no local model | refuse, and say why |

The line that matters: degradation changes the **destination**, never the check. A redaction
gateway that fails open is decorative.

## 8. Observability

Per tenant and per entity type, never aggregate: detections by type, escalation rate,
unlocatable-span rate, blocked-call rate, rehydration misses, vault write rate and TTL
distribution, canary probe results, policy version in use.

**Leading indicators** — all of these move before anything shows up as an error:

- **escalation rate** rising (a corpus changed, or a pack is wrong for the tenant)
- **detections-per-1k-calls by type** falling for a type that used to fire (a format changed,
  or an upstream field stopped being populated)
- **unlocatable-span rate** rising (the extractor is drifting, and you are now failing closed
  more often than you think)
- **rehydration misses** — placeholders in an output with no vault entry, which is the
  reversal path breaking before a user reports it

Error rate is the lagging indicator here, and the worst-case failure produces **no error at
all**: a clean-looking prompt that left the building with a name in it. That is why the canary
probe exists, and why it runs in production and not only in CI.
