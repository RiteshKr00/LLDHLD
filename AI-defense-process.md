# The defense process — how to answer any "tell me about this"

One repeatable shape for every claim on your resume. Learn the shape, not 15 scripts.

## The five-part dossier

| Part | Length | Purpose |
|---|---|---|
| **1 · 30-second answer** | 3–4 sentences | What you say first. Problem → what you did → why it worked. |
| **2 · Deep dive** | 1–2 min | The mechanism, if they pull the thread. |
| **3 · Five hardest follow-ups** | — | Pre-loaded. Mostly "why not X?" |
| **4 · Honest weakness** | 1–2 sentences | What it doesn't handle. Volunteer it. |
| **5 · Metric justification** | 3 sentences | What / how / what it didn't measure. |

## The 30-second answer template

> "**[The problem in business terms.]** So I **[what you built]**, which **[the mechanism
> in one clause]**. That meant **[the outcome]**."

Bad: *"I used Celery with a dedicated queue for LLM calls."* — mechanism only, no stakes.

Good: *"Gemini calls take several seconds. If they ran on the same workers as ordinary
jobs, an LLM burst would starve everything behind it. I put LLM work on its own queue with
its own workers, so the two workloads have isolated capacity."*

The difference: the second one makes the interviewer understand **why the problem was
hard** before hearing what you did.

## Answering "why not X?" — the four-beat move

This is 70% of follow-ups. Never answer with "because X is bad."

1. **Concede what X is good for.** *"DB-per-tenant gives you isolation by construction."*
2. **Name the constraint that ruled it out.** *"It was a retrofit on a live single-tenant app."*
3. **State the trade you accepted.** *"So isolation is enforced in app code — a missed filter is a leak."*
4. **Say what would change your mind.** *"At regulated scale, or with tenants demanding data residency, I'd move to schema-per-tenant."*

Beat 4 is what separates a senior answer. It shows the decision was *conditional*, not
dogma.

## Volunteering the boundary — do this unprompted

When a system was team-built, or you owned part of it, **say so before they ask.**

> "One of that repo's commits is mine, so I'll describe it as a system I benchmarked, not
> one I built. What's mine is the evaluation harness and the inference backends."

This feels like it costs you. It doesn't — it converts *"how much of this is really
yours?"* from a suspicion into evidence that your other claims are accurate.

The same move for scale:

> "It's an internal product on a pilot deployment, so I've never run it at real scale. My
> answers about 50k concurrent calls are reasoning from the architecture, not measurements."

## Never answer a size question with a size answer

*"How many users?"* → answer honestly, then pivot to the constraint **in the same breath**:

> "Pilot scale. But the hard part wasn't load — it was that a cache key missing the persona
> would serve one tenant's answer to another. That's the bug I went after."

Stakes and constraints signal seniority. User counts signal nothing, and a small honest
number costs you nothing if you never let it be the subject.

## What to do when you don't know

> "I haven't hit that. In our codebase the nearest thing is **[X]**. My instinct would be
> **[reasoning from a principle you do know]**. How do you handle it?"

Reasoning out loud from a model you understand beats guessing an API name. And admitting
one gap after eight solid answers costs nothing — it makes the eight more believable.

## The framework-credit trap

Say **"I chose"** not **"it does"** — and be able to tell the difference.

| Framework did it | You did it |
|---|---|
| Celery retries a failed task | You set `acks_late` and made the task idempotent so retry is safe |
| FastAPI returns 422 on bad input | You defined the Pydantic contract and chose `extra="forbid"` |
| Atlas does ANN search | You chose `numCandidates = 10 × top_k` and know it's the recall/latency dial |
| Vapi runs the voice loop | You inverted it — your server is the model provider |

Claiming the left column is the fastest way to lose credibility with a senior interviewer,
because they know which is which.
