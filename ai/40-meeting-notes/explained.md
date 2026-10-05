# Meeting notes — explained

---

## 1. Two things to notice out loud

**It fits.** 60 minutes at 150 words a minute is 9,000 words, about **12k tokens** — 9% of a 128k
window. Chunking is not forced. Saying that explicitly is worth marks, because most candidates
reach for map-reduce reflexively and pay a coherence cost for nothing.

**The product is not the summary.** It is **attributed, verifiable action items**. The summary is
the part nobody disputes. The action items are what people act on, argue about, and are held to.
So the design optimises attribution and verifiability, and every failure mode below attacks one
of those two.

---

## 2. Single-pass, and when to give it up

Decisions get revisited. A commitment made in minute eight gets withdrawn in minute fifty. Those
are relationships **between** parts of the meeting, and a per-chunk pass cannot see them.
`solution.py §1` models the loss growing with the number of boundaries.

So: single-pass while it fits, which covers a 60-minute meeting comfortably and a 3-hour one
marginally. Beyond that, map-reduce — but do it knowingly, and mitigate by carrying a running
summary of decisions into each chunk rather than reducing independent summaries at the end.

---

## 3. Diarisation is load-bearing, and everything inherits it

A misattributed action item is **worse than a missing one**. It is a task assigned to someone who
never agreed to it, and they discover it in a summary email sent to their manager.

`solution.py §2`: at 25% speaker error, 194 of 800 action items land on the wrong person. Nothing
downstream can repair that — the text is correct, the attribution is not, and there is no signal
that anything went wrong.

This is why audio setup is a **clarifying question** rather than an implementation detail. Per
-participant streams from a video platform diarise almost perfectly. One omnidirectional mic in a
room with overlapping speech does not, and it caps the whole product.

Where confidence is low, the honest output is an **unattributed** item flagged for review, not a
guess.

---

## 4. The model believes meetings have action items

This is the second-largest risk and it is specific. Models have a strong prior that a meeting
produces actions, so for a status update where nothing was decided they will produce some anyway.

`solution.py §3`: with a schema requiring a non-empty list, four items are invented across two
meetings that genuinely had none. With the list allowed to be empty, zero.

**A required list field is an instruction to invent.** Two fixes, and use both:

- Let the answer be **explicitly empty**, and make "no action items" a first-class, expected
  output rather than a failure.
- Require a **quote and timestamp** per item. An invented item has nothing to quote, so the
  constraint makes fabrication structurally harder rather than merely discouraged.

---

## 5. The layers, each named by the failure it prevents

**Diarisation + speaker attribution** — *prevents:* "someone said they'd do it", which makes an
action item unusable.

**Transcript as the durable artefact, summaries derived** — *prevents:* being unable to
re-summarise when the prompt improves. `solution.py §5`: transcription is £180/day and
summarisation £10/day, so re-running history costs 5% of the original.

**Single-pass while it fits; map-reduce only beyond** — *prevents:* losing revisited decisions to
a chunk boundary.

**Structured output** — decisions, action items with owner and due date, open questions —
*prevents:* an unactionable wall of prose.

**Entity resolution against the directory** — *prevents:* an item assigned to "Dave" when there
are four.

**Quote and timestamp every decision** — *prevents:* disputes with no evidence, and makes
invention harder.

**Async queue** — *prevents:* building a latency problem that does not exist. 500/day is trivially
batchable.

---

## 6. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Diarisation** | On overlapping speech and poor audio. Everything inherits it. |
| 2 | **Invented action items** | The model's prior, amplified by a required schema field. |
| 3 | **Entity resolution** | Four Daves, and the wrong one gets a task. |
| 4 | **Disputes** | Without quotes and timestamps there is nothing to show. |
| 5 | **Retention** | A transcript of every internal meeting is a discovery liability. |

---

## The follow-ups, answered

**1. Does a 60-minute transcript need chunking?**

No — it is about 12k tokens against a 128k window, 9% of it. And I would not chunk it even if I
could, because single-pass buys global coherence: decisions get revisited and commitments get
withdrawn across a meeting, and a per-chunk pass cannot see relationships that span chunks. I
would reach for map-reduce at around three hours, and even then carry a running decisions list
into each chunk rather than reducing independent summaries.

**2. Two people talk over each other. What breaks?**

Diarisation, and then everything downstream. Overlapping speech is where speaker separation is
weakest, and the failure is silent — you get fluent text attributed to the wrong person. The
mitigations are mostly upstream: per-participant audio streams if the platform provides them,
which removes the problem almost entirely. Where you cannot, propagate the diarisation
**confidence** through to the output and render low-confidence attributions as unassigned with
the quote shown, so a human can resolve it in two seconds. What the user must never see is a
confident wrong name.

**3. The meeting had no action items. What does your system produce?**

An empty list, and it says so. This is the case worth designing for explicitly, because the
model's prior is strongly against it. A required non-empty field in the output schema is an
instruction to invent — in the simulation it produces two fabricated items for each such
meeting. Make the empty answer first-class, require a quote and timestamp per item so there is
nothing to cite for an invented one, and monitor the **distribution** of items per meeting: a
system that never returns zero is fabricating.

**4. "Dave will send the numbers." Which Dave?**

Restrict to meeting attendees first, which resolves most cases, because the person who said
"I'll do it" was in the room. If several attendees match, disambiguate on topic against the
directory — a finance number goes to the finance Dave. If it is still ambiguous, produce an
**unassigned** action item flagged for the organiser to resolve in one click. Never guess: a task
on the wrong Dave's list is worse than a task on nobody's, because the right Dave does not know
it exists and the wrong Dave ignores it.

**5. Someone disputes a decision the summary recorded.**

Show them the quote and the timestamp, and link to that point in the recording. This is why
quote-and-timestamp is a design requirement rather than a nice-to-have — the value of the
artefact depends on it being checkable. If a decision cannot be quoted, it should not appear as a
decision; the honest rendering is an open question. In practice this also changes behaviour in
meetings, because people phrase commitments more clearly once they know they will be quoted.

**6. Your prompt improves next month. What happens to last month's meetings?**

Re-run them, which is why the transcript is the durable artefact and the summary is derived.
Transcription is the expensive, irreversible step at £180/day; summarisation is £10/day, so
re-processing a month of history costs about 5% of what it cost to capture. Version every summary
with the prompt and model that produced it, keep the previous version, and re-generate on demand
rather than in a big-bang backfill. If you store only summaries you have thrown away the ability
to improve.

**7. What does 500 a day cost, and how do you schedule it?**

Roughly £190/day, dominated by transcription. It is an async queue — nobody is waiting, so
schedule it off-peak and use batch pricing where the provider offers it. Prioritise by meeting
end time so the 9am standup is summarised before lunch rather than behind an overnight backlog.
Make each stage independently retryable, and keep transcription and summarisation as separate
jobs, since a summarisation failure should never force re-transcription.

**8. How do you evaluate a summary, given there is no single right answer?**

Split it into parts that are checkable and parts that are not. **Action items** are checkable:
precision and recall against a human-labelled set, plus attribution accuracy, plus the invented
rate on meetings that genuinely had none — that last one is the metric that catches the failure
mode nobody looks for. **Decisions** are checkable through their quotes: does the cited quote
support the stated decision? **Prose quality** is not objectively checkable, so use pairwise human
preference on a sample, and do not pretend a single rubric score means much. Ban the aggregate
"summary quality" number; it hides everything.

**9. The one metric for the business?**

**Action-item precision** — of the items produced, what fraction were real, correctly attributed
and accepted by the owner without correction. It is the closest measure of the actual product,
it directly captures the two failure modes that matter, and it degrades visibly when diarisation
or the extraction prompt regresses. Recall matters too, but a system that misses an item is
merely incomplete, whereas one that invents or misattributes is actively harmful — and precision
is the number that tracks harm.

---

## One-line summary

A 60-minute transcript fits in context, so single-pass over map-reduce buys global coherence for
free — and since the product is attributed, verifiable action items rather than prose, the design
is diarisation quality as the foundation, entity resolution against attendees, an output schema
that permits an empty list, a quote and timestamp on every item, and the transcript kept as the
durable artefact so summaries can be regenerated when the prompt improves.

---

## The trap answer to avoid

Focusing on summarisation quality — prompt wording, tone, length. That is the part nobody
disputes. The value and the risk are both in the action items: inventing them for a meeting that
had none, and attributing them to the wrong person. The second trap is reflexive chunking: it
fits, and map-reduce would cost coherence on exactly the cross-meeting relationships — a decision
revisited at the end — that make a summary worth reading.
