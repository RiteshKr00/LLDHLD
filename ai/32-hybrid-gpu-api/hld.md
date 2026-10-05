# The hybrid platform at scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| GPU fixed cost | £1,460/month | paid whether used or not |
| Ops | ~£1,800/month | the line that gets omitted |
| Break-even | ~3.6B tokens/month/card | including ops |
| Utilisation needed to beat the API | >50% sustained | demanding for interactive-only |
| Card capacity at 70% | ~4.4B tokens/month | 7B model, continuous batching |
| Example fleet | 5 cards + API | 41% saving on a £22k/month bill |

## 2. Topology

**The gateway.** One OpenAI-compatible surface. Call sites send a **task name**, never a model
name. This is the whole reason placement can change without a deploy — and being able to move a
task *back* is what makes the first move safe.

**Self-hosted pool.** vLLM behind a load balancer, continuous batching on, one model per pool.
Separate pools per model rather than swapping weights — a swap is minutes of downtime and the
scheduling gets much harder.

**API path.** Kept live permanently, even for fully migrated tasks. It is the overflow valve,
the failover, and the quality reference you evaluate against.

**Batch queue.** Behind the same pool, strictly lower priority, preemptible. This is what turns
a 40%-utilised fleet into an 80%-utilised one, and it is where the economics actually come from.

## 3. The routing decision, in order

1. Does this task need frontier quality? → API, regardless of volume.
2. Is there a free slot in the task's home pool? → self-hosted.
3. Is the pool saturated or unhealthy? → API overflow, and raise a **cost** alert, not a page.
4. Is this batch work? → queue it, preemptible, behind interactive.

Note that step 2 is about **capacity**, not about the task's assigned home. Routing on
utilisation rather than on a static map is what stops you paying for idle cards.

## 4. Scheduling: keeping batch from eating interactive

Interactive holds a reserved share of slots and strict admission priority. Batch sequences are
preemptible mid-request and resume rather than blocking. Alert on **interactive queue depth**,
never on GPU utilisation — utilisation looks excellent right up to the moment interactive
latency collapses, because batch is extremely good at hiding this exact failure.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Utilisation below the model | Add batch work; consolidate tasks; or shut it down and go back |
| 2 | Ops burden | Budget it explicitly, or do not start |
| 3 | Quality drift on a moved task | Per-task parity eval, re-run on every model or config change |
| 4 | Spike capacity | API overflow, sized for peak not average |
| 5 | Model upgrades | The API improves for free; yours improves when someone does the work |

## 6. Migrating a task in-house — the sequence

1. Run the parity eval offline. If it fails, stop here.
2. Shadow: send the task to both, compare, serve the API's answer.
3. Canary a percentage, watch the task's own quality metric and p99.
4. Ramp, keeping API overflow live.
5. Instrument actual £/1k on both paths and compare against the projection.

Step 5 is the one that gets skipped, and it is the only one that tells you whether the project
worked.

## 7. Observability

Per-task **actual** £/1k on both paths, side by side — the projection is not a metric. GPU
utilisation and interactive queue depth, separately. Overflow rate to the API, with cost
attribution. Per-task quality score against the API baseline, re-run on a schedule rather than
only at migration. Preemption rate for batch. And a monthly reconciliation of the bill against
the model, because the gap between them is the actual finding.
