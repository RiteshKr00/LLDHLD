# Fast revision — the night before / morning of

60–90 minutes. **Out loud.** Reading this silently does not work.

## Round 1 — One-liners (10 min)

For each resume bullet, say the 30-second answer from memory. Stumble → mark it, come back.
Don't fix it now, just note it.

## Round 2 — The "why not X" gauntlet (15 min)

Only contrarian follow-ups. ≤3 sentences each, then move on.

- Why not more workers on one queue?
- Why not caching instead of indexing?
- Why not DB-per-tenant?
- Why not one prompt instead of two?
- Why not LLM-as-judge for the eval gate?
- Why not configure the prompt in Vapi?
- Why not threads instead of multiprocessing?
- Why not reranking on the policy assistant?
- Why not microservices?
- Why not fine-tune instead of RAG?

Remember the four beats: concede → constraint → trade accepted → what would change your mind.

## Round 3 — Whiteboard the two flagships (20 min)

From blank paper. Label **every** box, store and failure point.

1. **Dealership Analytics** — request path, the Celery split, the LLM path through LiteLLM, the Databricks/Spark KPI job, S3 ingest.
2. **Digital Twin** — three surfaces, the Vapi custom-LLM inversion, the tenant scope funnel, RAG namespaces, the usage ledger.

If you can't draw it, you can't defend it.

## Round 4 — Scaling reflex (15 min)

Recite the ten steps of the rubric from memory. Then answer *"scale it to 1M"* for one
system in five minutes flat, out loud, with numbers.

## Round 5 — Metrics cross-exam (10 min)

For each of `45%` · `85%` · `25,000+` · `37+` · `17 probes` · `185/185` · `0.002` — state
**what it measured / how / what it didn't**. Any you can't complete, downgrade the claim in
your head to a safe phrasing *now*, before the interview.

## The cheat triggers — memorise these seven

| Trigger | Means |
|---|---|
| **Bulkhead** | isolated capacity per workload → your Celery queue split |
| **Fail closed** | deny by default → your tenant resolver returns no rows, not all rows |
| **Grounding** | retrieve then constrain; deterministic check *before* LLM check |
| **Batch API** | trade latency for cost/throughput on staleness-tolerant work |
| **Little's Law** | concurrency ≈ arrival rate × service time → how you size pools |
| **Semantic cache** | the #1 lever when anyone says "scale RAG" or "cut LLM cost" |
| **Noise floor** | establish variance *before* comparing, or you're reading noise |

## Six facts to look up before you walk in

- `numCandidates` reasoning on Atlas vector search — why 10× `top_k`
- ResumeFlow's chunk size and overlap
- `TTL_SECONDS` in `voiceToken.ts`
- The Casbin model shape — subject / object / action, model vs policy
- Direction of the read:write ratio on the reporting tables
- Whether the Dealership repo is recoverable

## The last thing to read

> Every metric: **what it measured, how, and what it didn't.**
> Every team system: **say your boundary first.**
> Every "why not X": **concede, constrain, trade, and what would change your mind.**
