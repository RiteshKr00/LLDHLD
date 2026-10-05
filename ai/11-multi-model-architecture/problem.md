# Topic 11: architecting a multi-model LLM system that doesn't fail at scale

## The prompt (as an interviewer would give it)

> "You're building a platform that serves several LLM-powered features — chat, summarisation,
> extraction, voice — across multiple models and providers. Architect it so it doesn't fall
> over at scale. What breaks, and what do you put in place before it does?"

Deliberately open. **Your job is to make it concrete** — scope it, put numbers on it, then
build up layer by layer naming the failure each layer prevents.

---

## Clarifying questions to ask FIRST
_Each one changes the architecture. Ask before designing._

1. **How many distinct features / task types?** *(Decides whether you need a router at all.)*
2. **Self-hosted, API providers, or both?** *(Self-hosted = you own capacity planning; API = you own quota management.)*
3. **Latency SLO per feature?** *(Voice sub-second vs a nightly summary are different systems.)*
4. **Is there a cost ceiling, and is it per tenant?** *(Decides whether budget enforcement is core or later.)*
5. **Who is the tenant — internal teams or external customers?** *(Decides quota isolation and blast radius.)*
6. **Are outputs user-facing or machine-consumed?** *(Machine-consumed needs hard output contracts.)*
7. **What happens if a feature is unavailable for 10 minutes?** *(Decides fallback vs fail.)*

Stating your assumptions out loud when they don't answer is itself scored.

---

## The follow-up bank

1. A provider starts returning 429s at 30% of requests. What happens to your system?
2. Your main provider has a 40-minute outage. Walk me through it.
3. The model you depend on gets deprecated with 30 days' notice.
4. p99 latency doubles but p50 is unchanged. What do you do?
5. One tenant's usage triples your monthly bill overnight.
6. How do you swap a model without shipping a quality regression?
7. How do you keep structured output working across models that behave differently?
8. Why not just use one big model for everything?
9. Where does the retry live — client, gateway, or worker?
10. How do you test any of this?

Answers: `explained.md`. The scaled design: `hld.md`.
