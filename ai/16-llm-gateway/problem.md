# Design scenario 2: build an LLM gateway

## The prompt

> "Every team calls the model providers directly. Build the gateway that sits in front, without
> making anything slower."

*This is "build LiteLLM yourself". You use one, so expect to be asked how it works.*

---

## Clarifying questions to ask FIRST

1. **How many providers, and will that grow?** *(One provider means you're building indirection for nothing.)*
2. **Is it in the request path, or only async?** *(Sync means a hard latency budget on the gateway itself.)*
3. **Do you need streaming?** *(This is the constraint that breaks naive designs.)*
4. **Per-tenant keys, or one company key?** *(Decides whether rate limiting is per-key or per-tenant.)*
5. **Who owns the cost?** *(Decides whether attribution is core or an add-on.)*

---

## The follow-up bank

1. What's the latency budget for the gateway itself?
2. How do you count tokens on a streaming response without buffering it?
3. Ten gateway instances, one provider quota. How do you rate-limit?
4. Where do retries live — client, gateway, or worker?
5. The gateway is now a single point of failure. Justify that.
6. How do you add a provider without touching call sites?
7. How do you test it without hitting a provider?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
