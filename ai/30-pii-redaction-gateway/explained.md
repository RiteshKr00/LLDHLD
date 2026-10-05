# PII redaction gateway — explained

**Your version of this:** on the voice/video persona product you are the **Vapi custom-LLM
provider**, so every turn already passes through your code before it reaches a model — that is
the only place a redaction stage can physically live, and you already run **fail-closed tenant
scoping** at exactly that point. The **FastAPI HR platform** is the corpus problem in its
purest form: an HR document store indexed into Mongo Atlas vector search is the densest PII
you will ever retrieve from, and Casbin is the proof you already enforce policy *outside* the
thing being governed. The **clinical-report generator** is the counter-example that makes the
whole design work — it is local-first, so the sensitive path has somewhere to go. And the
grounding layer you own there is where you learned the offsets lesson below: you re-locate a
span in the source text rather than trusting a reported position.

---

## 1. The numbers force the design

| | |
|---|---|
| LLM calls | **600k/day** ≈ 7 QPS average, ~70 peak |
| What gets scanned | the **assembled** prompt, ~6,000 chars, not the user's 200-char question |
| Sync budget for the whole gateway | **≤ 50 ms p95** |
| Deterministic pass, ~24 recognisers + checksums | **~3 ms** |
| LLM extractor | **600 ms p50, ~1.4 s p99**, 1.5 s timeout |
| Ambiguous prompts needing escalation | **~4%** measured, alert above **5%** |
| Entities per call | ~4 → **2.4M vault entries/day** at a 24h TTL |

**What that forces, in one sentence:** an LLM detector on every call costs **600 ms and
~£2,700/month** to protect a path whose entire budget is 50 ms, so the primary detector must be
deterministic and the model must be a rare escalation — and because 4% × 600 ms still ruins
your p99, that escalation cannot be something the request *waits* for.

---

## 2. The first layer is not a detector. It is the egress boundary

*Prevents:* the second-best-engineered path around your gateway.

If a team can `import openai` and reach `api.openai.com`, your redaction stage is a code-review
convention with a Prometheus counter attached. The guarantee comes from the network:

- provider domains are reachable **only** from the gateway's egress proxy; everything else gets
  a connection refused, not a warning
- provider credentials exist **only** in the gateway's secret scope — no key, no call
- a CI test asserts no module outside the gateway package imports a provider SDK

Say this before you say the word "regex". Every candidate designs a detector; the ones who have
actually had to sign a data-processing agreement design the boundary first. A detector you can
walk around is a detector that reports zero leaks forever.

---

## 3. Redact the assembled prompt, not the user's message

*Prevents:* the leak through your own retrieval.

The user typed *"what's the notice period for this employee?"* — no PII. The prompt you send
contains four retrieved HR chunks with names, salaries and a personal email; the last six turns
of conversation; and a tool result from the dealership CRM with a customer's phone number. The
user's message is the smallest and cleanest part of the payload.

So the stage sits **after prompt assembly and immediately before the provider adapter
serialises** — the last point at which the bytes are still yours. This is also the argument for
prompt assembly being **one pure, tested function**: it gives you exactly one place to hook,
rather than five string concatenations spread across a codebase.

---

## 4. Deterministic detection first, checksums second

*Prevents:* paying model latency and model cost on every request — and then, separately, a huge
false-positive class that bare regex hands you for free.

The recogniser set is compiled patterns plus context words: email, phone, PAN, Aadhaar, card,
IFSC, GSTIN, passport, DOB, VIN and registration plates on the dealership side, MRN and
subject-ids on the clinical side. Cheap: ~3 ms over a 6,000-char prompt.

The failure that bites next is precision, not recall. `\b[2-9]\d{11}\b` matches an Aadhaar
number, and it also matches order ids, invoice numbers and internal references. On a day's
traffic that is roughly **two false positives for every true one**. The fix is not a threshold,
it is arithmetic: **Aadhaar carries a Verhoeff check digit, cards carry Luhn, PAN and GSTIN have
structural rules, IFSC has a bank-code table.** `solution.py` measures it — precision goes from
**33% to ~83% with recall unchanged at 100%**, which is the only kind of precision fix worth
having in a system tuned for recall.

---

## 5. The escalation is a routing decision, not a wait

*Prevents:* the tail latency that the "only escalate the ambiguous ones" answer quietly creates.

Free-text names, addresses and unenumerated formats have no pattern and no checksum. Those need
a model. But look at what inline escalation does to the distribution (`solution.py` computes it
over 20,000 requests):

| Design | p50 | p95 | p99 | Extractor spend |
|---|---|---|---|---|
| A — extractor on every call | ~600 ms | ~1,100 ms | ~1,400 ms | ~£2,700/mo |
| B — deterministic + **inline** escalation on 4% | ~3 ms | ~4 ms | **~770 ms** | ~£108/mo |
| B′ — same design, a tenant whose corpus is free text (30%) | ~3 ms | **~850 ms** | ~1,160 ms | ~£810/mo |
| C — deterministic + escalation **routes**, async sample | ~3 ms | ~4 ms | **~4 ms** | ~£54/mo |

B is the answer most people give and it is defensible, but it fails a 50 ms p99 and it degrades
without a deploy: escalation rate is a property of *tenant data*, so B′ is one onboarding away.

C is better and it is only available because you asked clarifying question 2. **Ambiguity means
this prompt does not go to the third party** — it goes to the in-VPC or local model, which needs
no redaction. Nobody waits for anything. The extractor still runs, on a ~2% asynchronous sample,
and its job is different: finding the entity types your recogniser list is missing, which is
failure #2 below. Escalations become new deterministic rules, and each promoted rule moves a
class from "caught by a model sometimes" to "caught every time at zero latency".

Without a local model, C is unavailable and you are choosing between B's p99 and refusing the
request. Say which one you would pick and why — it is a product decision, not a technical one.

---

## 6. Never ask the model for character offsets

*Prevents:* a hallucinated span silently corrupting the prompt **and leaving the PII in place**.

Ask the extractor for `{"text": "...", "type": "..."}`. Nothing else. Then **re-find the span in
code** with an exact string search on the text you are about to send.

The obvious reason is that models hallucinate positions. The better reason, the one that sounds
like experience, is that **the offsets are relative to a string you no longer have**. The
extractor saw a 400-char chunk; you are redacting a 6,000-char assembled prompt with a template
prefix, a system message and three other chunks in front of it. Every offset is wrong by the
length of everything you added afterwards, and the model was not lying — it never saw that
string. `solution.py` shows the result: applying chunk-relative offsets to the assembled prompt
shreds the instruction line and **both the name and the email survive intact**.

Two consequences worth stating:

- if the returned substring **cannot be found**, you did not detect anything. Count it as
  `unlocatable` and **fail closed** on that destination. Silently dropping it is the failure
  mode, because the model has told you something is there and you have chosen not to act
- re-finding means you redact **every** occurrence of that string, not just the reported one,
  which is free extra recall

---

## 7. Reversible tokenisation, and the edge nobody tests

*Prevents:* an unusable answer when the response must refer to the entity.

*"Draft a reply to the customer"* is worthless if the model does not know who the customer is.
So placeholders carry type and identity: `[PERSON_1]`, `[EMAIL_1]`, stable within a request so
coreference survives, backed by a vault entry keyed by `HMAC(tenant_key, value)` so the same
value collapses to the same token without the key itself being the plaintext.

The edge case: rehydration happens on a **stream**, and `[EMAIL_1]` arrives as `[EMA` then
`IL_1] and copied…`. A naive per-chunk regex matches neither half, so the user reads the literal
placeholder — a bug that is invisible in every non-streaming test, which is the same shape as
the buffering bug in the gateway topic. The fix is a **carry buffer**: hold back from the last
unclosed `[`, capped at the longest placeholder length so time-to-first-token stays bounded.

And the vault is the uncomfortable part of this design, so volunteer it: you have just built a
store that maps tokens to raw PII. Short TTL, encrypted with a per-tenant key, separate access
policy from everything else, and it belongs in the data inventory on day one.

---

## 8. Treatment is a table in code; the model may only push stricter

*Prevents:* prompt-driven policy drift, and an unknown entity type defaulting to "allow".

| Entity | Third-party API | In-VPC model | Local model |
|---|---|---|---|
| email, phone | tokenise | tokenise | pass |
| person name | tokenise | pass | pass |
| address | mask to city | pass | pass |
| PAN, Aadhaar, card | **block** | tokenise | pass |
| health condition, MRN | **block** | tokenise | pass |
| internal employee id | hash, stable | pass | pass |
| *anything unrecognised* | **block** | tokenise | pass |

Two rules make it hold. **Unknown type blocks** — the default must be the safe cell, or every
gap in your recogniser list is a silent allow. And **the model may only escalate**: if the
extractor labels something a medical record number, the table decides the treatment and the
model can push it stricter, never looser. Otherwise "treat this as public" is one prompt
injection away from being policy.

---

## 9. Recall over precision, deliberately — and fail closed

*Prevents:* the unrecoverable failure.

Price the two errors and the threshold sets itself. A **false negative** is a disclosure to a
third-party processor: notifiable, unretractable, and it is in their logs now. A **false
positive** is a slightly duller answer. There is no threshold at which those are worth trading
symmetrically, so tune for recall and then spend your engineering effort reducing over-redaction
*without touching recall* — checksums, context windows, and an allow-list for your own product
nouns that keep tripping the name recogniser.

Fail closed follows from the same asymmetry: if the detector errors or times out, **the
third-party call does not happen**. Note that this is the opposite of the gateway topic's advice
to fail *open* on rate limiting, and be ready to say why: a missed rate limit costs money, a
missed redaction costs a disclosure. Knowing which way to fail, and why, is the answer — the
slogan is not.

**One more leak to close:** do not log the raw prompt. The observability layer is where
carefully redacted PII gets written back to disk in plaintext, at full fidelity, with a 90-day
retention. Log the **redacted** text, the counts by entity type, the rule ids and the policy
version. That is enough to debug and it is what an auditor actually wants.

---

## 10. Proving it, because "we have a detector" is not evidence

Canary tokens: synthetic PII of every entity type planted in a test tenant's corpus, with an
assertion in CI and a probe in production that it never appears in an outbound payload. A
hash-only outbound record per call — entity counts by type, policy version, destination — so
"no PII reached the provider last quarter" is a query, not an opinion. And the egress test from
section 2, which is the only one that proves the *boundary* rather than the detector.

---

## What breaks first, in order

1. **The escalation rate.** It is the only number in the design that moves without a deploy —
   it is a property of tenant data, not of your code. One tenant with a free-text corpus takes
   it from 4% to 30%, and in design C that does not show up as latency, it shows up as **a third
   of traffic silently routed to the weaker model**. Silent quality loss is why it is first.
2. **Recall on entity types you never enumerated.** Your recogniser list is something you wrote
   in a room. A new jurisdiction brings NHS numbers or IBANs; a new tenant brings an internal
   employee-id format that means nothing to any of your patterns. No error, no alert, just a
   leak — which is what the async extractor sample exists to find.
3. **The reversal path.** The model invents `[PERSON_4]` you never issued; a placeholder splits
   across stream chunks; a vault entry expires before an async job finishes. First user-visible
   bug, and the first one anyone actually reports.
4. **The vault becoming the honeypot.** Retention creep. Someone raises the TTL to debug an
   incident and now you hold a token-to-plaintext map for 30 days, in a store that was never in
   the data inventory.
5. **Over-redaction eroding answer quality**, followed by the team quietly loosening thresholds
   one entity type at a time. That is a governance failure, not a code one, which is why the
   thresholds are versioned config with an owner and a changelog.

---

## The follow-ups, answered

**"What stops a team bypassing the gateway?"**
Not policy — the egress proxy and key custody. Provider domains unroutable from anywhere else,
credentials only in the gateway's scope, plus a CI import test. Anything softer than that is a
convention, and conventions do not survive a deadline.

**"Where exactly does redaction run, and why not earlier?"**
After prompt assembly, before the adapter serialises. Earlier and you miss the retrieved chunks,
the tool outputs and the history — which carry more PII than the user's message ever does.

**"What do you ask the extractor for?"**
Substring and type. Never offsets, never a rewritten prompt, never a treatment decision. You
re-find the span in code, and if you cannot find it, you fail closed on that destination.

**"The answer needs the customer's name back."**
Reversible tokenisation with a vault, rehydrated on the way out with a carry buffer so a
placeholder split across two stream chunks does not surface to the user. Short TTL, per-tenant
HMAC key, and I would say out loud that the vault is now the most sensitive store in the estate.

**"The detector times out."**
Block the third-party call. If there is an in-VPC model, reroute to it and mark the response as
degraded; if there is not, refuse. Degradation here means changing the **destination**, never
skipping the check — a redaction gateway that fails open is decorative.

**"Why not just use a local model to redact properly?"**
Two problems. You cannot verify a redaction produced by the same class of system you are
protecting against — there is no oracle, and a missed entity looks exactly like a clean prompt.
And it is slow: 600 ms against a 50 ms budget. A local model is a fine *destination* for the
sensitive path and a fine *offline* recogniser-discovery tool. It is a poor primary detector.

**"Voice?"**
Voice has an 800 ms time-to-first-audio budget and no retract option once TTS has spoken. So
the voice path gets deterministic-only detection, a narrower allowed scope, and the sensitive
path routes to the in-VPC model. You cannot un-say a leaked phone number.

**"Prove it to an auditor."**
Canary tokens in a test corpus asserted in CI, per-call outbound records with entity counts and
policy version, the egress-boundary test, and honesty about what the evidence covers: it proves
the boundary and the enumerated entity types. It does not prove recall on a type nobody has
thought of yet, and saying so is stronger than pretending otherwise.

---

## One-line summary

> "Enforce it at the egress boundary, not in a code convention; scan the **assembled** prompt
> because the retrieved chunks carry more PII than the user's message; deterministic recognisers
> with checksums as the primary detector because a 50 ms budget rules out a model; ambiguity is
> a **routing** decision to the local model rather than something the request waits for; ask the
> extractor for substrings and re-find the span in code; tokenise reversibly into a short-TTL
> vault; and fail closed, because a false negative is a disclosure and a false positive is a
> duller answer."

## The trap answer to avoid

Asking the LLM to redact the PII. You would be sending the raw PII to the exact system you are
protecting it from, to perform an operation you cannot verify, at twelve times your latency
budget. The nearby variant loses the same way: *"I'd add 'never repeat personal data' to the
system prompt."* A system prompt is advisory input to the thing you are trying to constrain.
Enforcement lives outside the model, in code, at the boundary.
