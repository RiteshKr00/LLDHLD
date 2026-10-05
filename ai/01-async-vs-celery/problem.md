# Topic 1: async vs Celery — the conflation trap

## The prompt (as an interviewer would give it)

> "Your resume says the AI Insights layer runs on 'an async task layer on its own dedicated
> Celery queue', and elsewhere you list FastAPI. Walk me through the difference between that
> Celery queue and an `async def` endpoint. When a Gemini call takes 4 seconds — what is
> waiting, and where?"

**This is the single most-asked question for your profile**, because your resume names both
and most candidates use "async" to mean both. Getting it wrong here colours everything after.

---

## Why it's a trap

"Async" is used for two unrelated things:

| | `asyncio` / `async def` | Celery |
|---|---|---|
| **Axis** | concurrency *inside one process* | work moved to *other processes* |
| **Who waits** | the event loop, on an `await` | a worker process, on a blocking call |
| **Durability** | none — process dies, work dies | broker persists the task |
| **Retries** | you write them | built in |
| **Response** | same HTTP request | request returns immediately; result later |
| **Solves** | "don't block the thread while waiting on I/O" | "don't do this in the request at all" |

They are not alternatives. **You can, and often should, use both.**

---

## Clarifying questions worth asking back

1. "Do you mean within a single request, or across requests?" — shows you know they're different axes.
2. "Is the caller waiting for the result?" — this is what actually decides queue vs async.
3. "Does the work need to survive a deploy?" — decides Celery vs `BackgroundTasks`.

---

## The follow-up bank

1. Why not just add more workers to one queue?
2. What if the LLM queue itself backs up?
3. A worker dies mid-Gemini-call — what happens?
4. Redis as broker is a single point of failure.
5. How would you size the two pools?
6. When would you use `BackgroundTasks` instead of Celery?
7. You're in an `async def` and must call something blocking. Now what?
8. Why is `async def` sometimes *worse* than plain `def`?

Model answers: `explained.md`.
