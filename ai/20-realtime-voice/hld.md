# Voice at 50k — the deployment shape

> `04-voice-custom-llm/hld.md` covers the same scaling levers from the topic side. This is the
> physical layout, the fairness model, and the runbook.

## 1. Numbers first

| Quantity | Value | Where it comes from |
|---|---|---|
| Concurrent calls | 50,000 | the ask |
| LLM turns/sec | 6,250 | 50k ÷ 8s turn cadence |
| Sessions per box | ~400 | socket-bound, not CPU-bound |
| Boxes for sessions | ~157 | 50k × 1.25 headroom ÷ 400 |
| Boxes if you scale on CPU | ~100 | and 10,000 callers get nothing |
| Turn budget | 1,000 ms | serial, no overlap |
| Streamed p50 / p99 | 690 / 1,620 ms | the tail is over budget |

## 2. Topology — where each piece physically runs

**Edge, per region.** Telephony termination, STT, TTS and the session server. RTT is a fixed
geographic tax; nothing else recovers it. Three regions is usually the first sensible shape.

**Regional, near the edge.** The custom-LLM webhook, the persona brief cache, and the
retrieval index replica. Retrieval must not cross a region boundary — that alone can be 200 ms.

**Global, off the critical path.** Metering, the decision and transcript log, the eval
pipeline, billing. None of it may hold up audio. Write asynchronously and accept loss on
crash; a missing metering row is a rounding error, a delayed one is a dropped call.

## 3. The scaling levers, in order of leverage

1. **Stream into TTS.** −700 ms at p50. Nothing else comes close.
2. **Scale on sessions.** Turns a silent under-provision into a correct one.
3. **Per-tenant caps.** Converts a total outage into a bounded one.
4. **Regional edge.** −150 to 200 ms, but it is a deployment project, not a config change.
5. **Warm pools + connection draining.** Removes the deploy-shaped outage.
6. **Faster model on the voice path.** −100 to 200 ms, free quality-wise at spoken length.
7. **Speculative retrieval** on the partial transcript. Overlaps the one stage that refuses
   to fit, at the cost of some wasted lookups.

## 4. Per-tenant fairness

**Floor plus burst.** Every tenant has a guaranteed concurrency floor. Capacity above the sum
of floors is lent opportunistically and reclaimed first when a tenant needs its floor back.
This is the only model that survives a launch: strict equal shares waste capacity all day, and
pure first-come hands the system to whoever spikes first.

Enforce at **admission**, not mid-call. Rejecting a call at setup is a product decision the
caller can act on. Dropping one at 90 seconds is an outage.

Pair the concurrency cap with a **per-tenant spend breaker**. The tenant saturating its
concurrency is usually the same one about to blow its budget, and you want both limits to trip
before finance finds out.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Vendor concurrency quota | Second vendor behind an abstraction; cap admission meanwhile |
| 2 | Cost | Per-tenant breaker; cheaper model on the voice path |
| 3 | p99 turn latency | Break the tail down by region, vendor, model version, tenant |
| 4 | Cold starts / deploys | Warm pools, health gates, connection draining, off-peak |
| 5 | Retrieval latency | Speculative prefetch, cache, or drop it from the first turn |

Three of these five get worse as you add servers. Say that out loud.

## 6. Degradation ladder

Modality and admission, not quality — the chat ladder does not apply.

1. Shorten the answer (prompt-level cap on spoken length)
2. Drop retrieval, answer from the persona brief
3. Drop the avatar (frees the tightest-attach vendor)
4. **Fall back to text**, and say so in the UI
5. Refuse at call setup, with a reason

Rung 5 is the important one. For chat, refusing service is the worst outcome. For voice,
refusing *before* the call starts is far better than dropping it halfway through.

## 7. Observability

**p99 time-to-first-audio**, sliced by region / vendor / model version / tenant — the slice is
the point, an aggregate p99 tells you nothing actionable. Turn-completion rate. Barge-in
false-positive rate. Re-fire rate. Dropped-call rate **by cause**, separating vendor rejection
from your own admission control from genuine crashes. **Cost per minute per tenant**, per
vendor. STT confidence distribution — a drop means audio quality or accent coverage, not a
code bug, and it is the one metric that catches a whole class of "the AI got worse" reports
that have nothing to do with the model.
