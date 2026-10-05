# Hallucination control at scale

## 1. The number that frames it
At 600k generations/day, **a 0.1% failure rate is 600 bad outputs a day.** So the design target
is never "zero" — it is **bounded, detected, and recoverable.** Say that first; it reframes the
whole question away from a promise you can't keep.

## 2. Cost of the layers
| Layer | Cost per call | Catches |
|---|---|---|
| Grounding (retrieve first) | retrieval only | invention, preventatively |
| Deterministic validator | ~0 | schema, ungrounded numbers, ranges |
| LLM checker | **a second model call** | semantic and tone problems |

At 600k/day a checker on every generation **doubles your LLM bill**. So:

## 3. Sampling the expensive layer
Run the deterministic layer on **100%** — it's free. Run the LLM checker on:
- **100%** of high-stakes output (client-facing, regulated, irreversible)
- **a sample** of low-stakes output, sized to detect a rate change
- **100%** of anything the validator flagged as borderline

That tiering is the scaled answer, and it's where the cost argument for
deterministic-first becomes decisive rather than merely tidy.

## 4. Measuring whether the layers work
You cannot improve what you don't measure, and this is the gap most systems have:
- **hold out known-bad outputs** and measure each layer's catch rate
- **sample production output** for human review, stratified by feature
- track **escaped-defect rate** — bad output that passed both layers and reached a user
- alert on **validator rejection rate** moving: a spike means the model changed; a *drop* can
  mean the validator broke

## 5. What breaks at scale
1. **The checker becomes the bottleneck** — it's a second serial model call in the path
2. **Cost doubles** if you don't sample
3. **Validator drift** — the rules stop matching the output schema after a prompt change
4. **False positives** — over-rejection means regenerating, which costs more than the original
5. **Nobody looks at the rejections** — a rejection log with no review is just a bin

## 6. Degradation
When the checker is unavailable: **for high-stakes output, block and queue for human review.**
For low-stakes, ship with the deterministic layer only and flag it. Never silently skip the
check — an unlogged skip means you don't know what shipped unverified.
