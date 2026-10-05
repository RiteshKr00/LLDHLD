# Design scenario 6: real-time voice at 50k concurrent

## The prompt

> "Your persona assistant holds live voice conversations. Take it to 50,000 concurrent calls."

*The interviewer is checking one thing before anything else: whether you reach for the chat
playbook. Every scaling instinct you have — queue it, batch it, retry it, autoscale on CPU —
is wrong here, and each one fails in its own way. Voice cannot queue.*

> Topic 4 covers the custom-LLM inversion and the credential boundary. This card is the
> scale problem only: `04-voice-custom-llm/` for how the integration works.

---

## Clarifying questions to ask FIRST

1. **50k concurrent *calls*, or 50k calls an hour?** *(A factor of roughly twenty between
   them. Concurrent is a capacity problem; per-hour is a throughput problem with a queue,
   which is a different and much easier system.)*
2. **What is the latency target, and is it a target or a contract?** *(Sub-second round trip
   is the natural-conversation threshold. Whether you have 800 ms or 1500 ms decides whether
   retrieval can stay in the turn at all.)*
3. **Which parts do we own and which are vendors?** *(STT, TTS, avatar and the telephony
   platform are usually all bought. Their concurrency quotas, not your compute, are the real
   ceiling — and you cannot autoscale someone else's quota.)*
4. **What is the acceptable degraded mode?** *(Fall back to text, a shorter answer, a
   cheaper model, or refuse the call? Decides the whole backpressure design. There has to be
   an answer, because at some point you will be over capacity.)*
5. **Is the traffic spiky or steady, and is it one tenant or many?** *(A single tenant's
   product launch is the scenario that actually happens, and it is what per-tenant
   concurrency caps exist to survive.)*
6. **What is the cost ceiling per minute?** *(Five metered vendors per call. At this volume
   cost stops being a finance concern and becomes an architectural constraint — it is
   usually what breaks second, right after vendor quotas.)*

---

## The follow-up bank

1. Your autoscaler sees 12% CPU and scales in. Calls start dropping. Explain.
2. Retrieval takes 300 ms at p99. Does it stay in the turn? Defend either answer.
3. The TTS vendor caps you at 20,000 concurrent streams. You need 50,000. Now what?
4. Why can you not solve a load spike with a queue, when that works everywhere else?
5. You deploy at peak. What happens to the calls in flight, and what should happen?
6. One tenant launches a campaign and consumes 80% of your capacity. Design the fix.
7. p99 time-to-first-audio doubles but the average is flat. Where do you look first?
8. Cost per minute rises 40% with no traffic change. Walk me through the investigation.
9. Contrast the degradation ladder here with the one for a chat assistant. Why do they differ?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
