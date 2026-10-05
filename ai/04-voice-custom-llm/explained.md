# Voice: custom-LLM provider — explained

**Your code:** `digital-twin/server/voiceLlm.ts`, `voiceToken.ts`, `voiceContext.ts`

| Anchor | What's there |
|---|---|
| `voiceLlm.ts:4-6` | `mapMessages` — "the incoming system message is [discarded]" |
| `voiceLlm.ts:59-71` | `normalizeTurn`, `isRefiredTurn` — duplicate-turn suppression |
| `voiceLlm.ts:79-93` | *"Every chunk must be a valid OpenAI `chat.completion.chunk` — Vapi parses the stream"* |
| `voiceToken.ts:20-23` | `mintVoiceToken` — signs with `purpose`, TTL-bounded |
| `voiceToken.ts:26-32` | `verifyVoiceToken` — returns `null` unless `decoded.purpose === PURPOSE` |
| `voiceToken.ts:12` | the conversation id carried in the token, so voice turns persist server-side |

---

## The inversion — and why it's the interesting part

The default way to use a voice platform: put your prompt in *their* dashboard, let them call
*their* LLM, you receive a transcript.

What you did instead: **registered your own server as their model provider.** Every turn
arrives at your endpoint. You discard the system message they send, rebuild persona +
guardrails + retrieved context yourself, and stream back a response shaped exactly like an
OpenAI streaming completion so their platform can parse it.

**Why this is the right call, in one line each:**

1. **Grounding** — per-turn retrieval against *this* persona's corpus is impossible if the
   prompt lives in someone else's config.
2. **Tenancy** — the prompt must be scoped to the caller's tenant. Vendor config has no
   concept of your tenants.
3. **Versioning and testing** — persona and guardrails are code, so they're reviewed,
   diffed and unit-tested. Dashboard config is none of those.
4. **Consistency** — chat, voice and video then share one composition path, so the twin
   can't answer differently depending on the surface.

---

## You are impersonating the OpenAI streaming API

`voiceLlm.ts:79-93` is explicit: every chunk must be a valid `chat.completion.chunk`. The
first chunk establishes the assistant role (as OpenAI's streams do), subsequent chunks carry
content deltas.

**The failure mode this created, and it's a great story:** a malformed envelope makes the
platform **silently discard every reply while returning HTTP 200**. Nothing errors. The twin
just never speaks. That's the worst class of bug — success status, zero output — and it's why
the chunk shape has its own tests.

---

## The security boundary: a purpose-scoped token

```
mintVoiceToken(claims)  → jwt.sign({ ...claims, purpose: PURPOSE }, secret, { expiresIn: TTL })
verifyVoiceToken(token) → jwt.verify(...); if (decoded.purpose !== PURPOSE) return null
```

Two properties, and both matter:

1. **Purpose-scoped.** The normal auth middleware doesn't accept this purpose, so the token is
   useless against every other route. It authorises exactly one endpoint.
2. **Short-lived.** TTL-bounded, so even the one thing it can do expires.

**The principle: least privilege applied to a third party.** A credential handed to an
external vendor should be assumed leakable — their logs, their support tooling, a
misconfigured proxy. So the design question isn't "how do we keep it secret", it's **"what's
the blast radius when it isn't?"** A session token grants your whole API. This grants one
endpoint for a bounded window.

That reframing — from secrecy to blast radius — is the senior part of this answer.

---

## Real-time turn-taking: six failure classes

Text is request/response. Voice is a continuous stream with no clean boundaries, and each of
these is a distinct bug you hit:

1. **Malformed stream envelope** — platform discards every reply, returns HTTP 200.
2. **Endpointing re-fire** — the platform decides the user finished twice, so you answer the
   same question twice. `isRefiredTurn` (`:71`) compares normalised turns to suppress it.
3. **STT upgrade broke turn finalisation** — transcription was *correct* but the
   end-of-turn signal changed, so the twin listened forever.
4. **Barge-in cancelling itself** — the guard that stops the twin when the user interrupts
   fired on the **avatar's own TTS echo**, so it cut off its own reply.
5. **Mid-sentence pause** splitting one question into two turns.
6. **Cold start** — a ~10s post-deploy warm-up killed the first call every time.

None are algorithmically hard. They're invisible until you're on a live call, and each needed
its own regression test. **That's the honest answer to "what was hardest?"**

---

## The follow-ups, answered

**"Why not configure the prompt in Vapi?"**
Then persona, guardrails and retrieval live outside your system — unversioned, untestable,
un-tenant-scoped, and you can't inject per-turn retrieved context. Owning the model endpoint
keeps all four in your codebase.

**"Why a separate token type?"**
Blast radius, not secrecy. Assume anything given to a vendor leaks; a purpose-scoped
short-lived token means the leak buys one endpoint for minutes instead of your whole API.

**"A call longer than the TTL?"**
The token authorises call *establishment*. Long calls need either a TTL sized to maximum call
duration or a refresh path. **Check `TTL_SECONDS` before the interview** — know which yours is.

**"How would you detect a replay?"**
Today: it simply fails everywhere else because of the purpose check. What's missing is
*detection* — log verification failures by reason and alert on a spike in purpose mismatches.
Honest gap, and volunteering it is better than being asked.

**"What did inserting your server cost in latency?"**
One extra network hop plus your retrieval time, inside a per-turn budget. Mitigated by
streaming: emit the first chunk as soon as the model produces it rather than waiting for a
complete response. That's why the chunked envelope matters for *latency*, not just protocol
compliance.

**"What's the latency budget?"**
Sub-second round trip to feel natural, and it's **serial**: STT → retrieval → LLM first token
→ TTS first audio. Every stage must stream, because waiting for any stage to complete blows
the budget on its own.

---

## One-line summary

> "We own the model endpoint, so persona and grounding stay in our code and stay
> tenant-scoped — and the vendor only ever holds a voice-only, short-lived credential."

## The trap answer to avoid

Saying "we used Vapi for voice." That throws away the whole point. The interesting thing is
that you **inverted** the relationship: they run the call loop, you are the brain, and the
credential they hold can't do anything else.
