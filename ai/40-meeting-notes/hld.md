# Meeting notes at 500 a day

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Per meeting | ~9,000 words ≈ 12k tokens | 9% of a 128k window |
| Volume | 500/day, 500 audio-hours | post-hoc, batchable |
| Transcription | ~£180/day | expensive, irreversible |
| Summarisation | ~£10/day | 18x cheaper, repeatable |
| Re-running history | ~5% of original cost | because the transcript was kept |

## 2. The pipeline

1. **Ingest audio**, per-participant streams where the platform offers them.
2. **Diarise + transcribe**, emitting speaker labels, timestamps and per-segment confidence.
3. **Persist the transcript.** This is the durable artefact; everything after is derived.
4. **Single-pass extraction** into a schema: summary, decisions, action items, open questions.
5. **Entity resolution** of names against the directory, attendees first.
6. **Verification**: every decision and action item carries a quote and timestamp.
7. **Publish**, with unresolved attributions flagged for the organiser.

Step 3 before step 4 is the load-bearing ordering. Everything after step 3 is disposable and
re-runnable.

## 3. Scheduling

An async queue. Nobody waits, so 500/day is trivially batchable — off-peak, batch pricing where
the provider offers it, prioritised by meeting end time so the morning standup does not sit behind
an overnight backlog.

Transcription and summarisation are **separate jobs**. A summarisation failure must never force
re-transcription, and a prompt change re-runs only the second.

## 4. The output schema

```
summary          prose
decisions        [ { text, quote, timestamp, speaker } ]
action_items     [ { text, owner | null, due | null, quote, timestamp } ]
open_questions   [ { text, quote, timestamp } ]
```

Two deliberate properties. Every list may be **empty** — a required non-empty field is an
instruction to invent. And `owner` may be **null**, so an unresolved attribution has somewhere to
go that is not a guess.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Diarisation on overlap | Per-participant streams; propagate confidence; render low-confidence as unassigned |
| 2 | Invented action items | Allow empty lists; require a quote; monitor items-per-meeting distribution |
| 3 | Entity resolution | Attendees first, then topic, then flag for the organiser |
| 4 | Disputes | Quote and timestamp, linked to the recording |
| 5 | Retention liability | Explicit policy, per-meeting opt-out, automatic expiry |

## 6. Observability

**Action-item precision** — real, correctly attributed, accepted without correction. The headline
number. Alongside it: attribution accuracy separately from extraction accuracy, because they fail
for different reasons and have different fixes. **Invented rate** on meetings that had no
actions, which requires deliberately labelling some such meetings. Diarisation confidence
distribution. The **distribution of items per meeting** — a system that never outputs zero is
fabricating. Queue depth and age. Cost per meeting, split transcription versus summarisation.

## 7. Retention

Worth raising unprompted. A searchable transcript of every internal meeting is a discovery
liability as much as an asset. Default retention measured in months rather than forever,
per-meeting opt-out honoured before transcription rather than after, and access scoped to
attendees by default. This is a question the business should answer, and the engineer who does
not ask it has made the decision by omission.
