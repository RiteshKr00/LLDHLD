# AI-04 — real-time voice

## META
- difficulty: hard
- time: 18 min
- tags: voice, streaming, jwt, least-privilege, latency, turn-taking
- source: `04-voice-custom-llm/`

## PROMPT

> "Your twin holds a live voice conversation, and you registered your own server as the voice
> platform's custom-LLM provider. Why not just configure the prompt in the platform? And what's
> the security story for the credential you hand them?"

## CLARIFY

- **"Turn-taking mechanics or the security boundary?"**
  → *"Both. Start wherever."*
- **"Latency budget or correctness?"**
  → *"Correctness first, then latency."*

## STEP 1 — Scope & stakes

### CHECKPOINTS
- Three surfaces (chat, voice, video) over one grounded core
- Voice is the hard one: **hard real-time budget**, ~sub-second to feel natural
- The stake: the twin speaking as a real person means a fabricated answer is a reputational event

## STEP 2 — Mechanism — the inversion

### CHECKPOINTS
- Registered **our server as their model provider**; every turn arrives at our endpoint
- We **discard their system message** and rebuild persona + guardrails + retrieved context
- Stream back a **byte-valid OpenAI `chat.completion.chunk`** — their platform parses it
- Four reasons for owning it: per-turn **grounding**, **tenant scope**, **versioning/testing**, **cross-surface consistency**
- Can point at `voiceLlm.ts:79-93` and `voiceToken.ts:20-32`

## STEP 3 — The security boundary

### CHECKPOINTS
- Token is **purpose-scoped**: a `purpose` claim, and `verifyVoiceToken` returns `null` on mismatch
- Normal auth middleware **rejects that purpose** → useless anywhere else
- **Short-lived**, TTL-bounded
- Reframes correctly: **not secrecy, blast radius** — assume a vendor credential leaks
- Names the principle: **least privilege applied to a third party**

## STEP 4 — Failure modes

### CHECKPOINTS
Names real classes, not generic ones:
- malformed envelope → platform **discards every reply while returning HTTP 200** (success status, zero output)
- **endpointing re-fire** → answers twice; `isRefiredTurn` suppresses via normalised comparison
- STT upgrade transcribed correctly but broke turn finalisation → listened forever
- **barge-in guard firing on the avatar's own TTS echo** → cut off its own reply
- mid-sentence pause splitting one question into two turns
- ~10s cold start killing the first call after every deploy
- Each captured as a regression test or named manual case
- Honest on detection: purpose-mismatch **logging/alerting is missing**

## STEP 5 — Scale to 50k concurrent

### CHECKPOINTS
- Recognises the budget is **serial**: STT → retrieval → LLM first token → TTS first audio → network
- **Stream into TTS** — partial tokens, don't wait for a complete response (biggest perceived win)
- **Autoscale on concurrent sessions, not CPU** — a voice server looks idle while saturated
- Regional edge to cut RTT
- Warm pools (their own cold-start bug becomes continuous outage at scale)
- **Graceful degradation = fall back to text**, not degraded audio
- Names the real ceiling: **cost across five providers**, needing per-tenant concurrency caps
- Bottleneck order: provider concurrency quotas → cost → p99 tail → cold starts → retrieval latency

## STEP 6 — Honesty

### CHECKPOINTS
- Volunteers: internal product on a **pilot** — scale answers are reasoning, not measurements
- TTL is a fixed constant, not derived from real call durations
- No replay **detection**, only prevention
- Separates credit: Vapi runs STT/TTS/call loop; *you* own the brain and the credential design

## TRAP

"We used Vapi for voice." That discards the entire point. The interesting thing is that you
**inverted** it — they run the loop, you are the brain, and the credential they hold can do
exactly one thing for a few minutes.
