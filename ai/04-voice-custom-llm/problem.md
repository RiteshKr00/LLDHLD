# Topic 4: real-time voice — inverting the vendor

## The prompt

> "Your twin holds a live voice conversation. You said you registered your own server as the
> voice platform's custom-LLM provider. Why would you do that instead of just configuring the
> prompt in the platform? And what's the security story for the credential you hand them?"

---

## Clarifying questions worth asking back

1. "Do you want the turn-taking mechanics or the security boundary?" — both are deep.
2. "Are we talking latency budget or correctness?"

---

## The follow-up bank

1. Why not just configure the prompt in Vapi?
2. Why a separate token type rather than a normal session token?
3. Short-lived — what about a call longer than the TTL?
4. How would you know if someone replayed the token?
5. You inserted your own server into a real-time loop. What did that cost?
6. What are the failure modes of real-time turn-taking?
7. What's the latency budget, and where does it go?
8. Scale it to 50k concurrent calls.

Answers in `explained.md`; scaling in `hld.md`.
