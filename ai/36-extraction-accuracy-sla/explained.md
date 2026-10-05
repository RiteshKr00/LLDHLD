# Extraction against an accuracy SLA — explained

---

## 1. The arithmetic hidden in "99% accuracy"

Say this in the first thirty seconds:

> **20 fields at 99% each is 0.99²⁰ = 82% of documents perfect.**

At 50,000 invoices a month that is **9,104 imperfect documents**. `solution.py §1`.

| Per-field | Documents perfect | Bad docs/month |
|---|---|---|
| 99.00% | 81.8% | 9,104 |
| 99.50% | 90.5% | 4,769 |
| 99.90% | 98.0% | 990 |
| **99.95%** | **99.0%** | 497 |

To reach 99% *per document* you need **99.95% per field**, which no model does unaided. That is
not a quality gap you close with a better model — it is arithmetic.

**Therefore human review is not a fallback. It is the architecture.** Everything else in the
design exists to make the review queue affordable.

---

## 2. Pin the SLA definition before designing anything

The contract says 99%. Before agreeing, establish:

- **Per field or per document?** An eighteen-point difference.
- **Which fields?** A single number pretends a handwritten note and a currency code are equally
  hard. They are not, by twenty points.
- **Measured against what?** A labelled set someone maintains, or the reviewer's judgement — and
  if the latter, what is the reviewer's own error rate?
- **Errors weighted how?** A wrong postcode is a re-send. A wrong bank account is fraud.

Getting this pinned is the deliverable of the first meeting. Designing before it is settled means
building to a number nobody agrees on.

---

## 3. The layers, each named by the failure it prevents

**Confidence-routed human review** — *prevents:* paying for 100% review, or shipping 18% bad
documents. `solution.py §2`: routing catches most errors while touching under half the documents,
at roughly **half the cost** of reviewing everything.

**Per-field confidence, not per-document** — *prevents:* re-reviewing nineteen correct fields
because one was uncertain. `solution.py §3`: **15x** the reviewer time for identical accuracy.
This is the difference between a review queue and a department.

**Deterministic validators** — *prevents:* spending model confidence on things arithmetic can
prove. Subtotal plus tax equals total. Line items sum to subtotal. Due date after invoice date.
Checksums on VAT and IBAN.

**Template detection with cached layout** — *prevents:* paying full extraction cost for the 80%
of volume that comes from recurring senders.

**Cross-field consistency** — *prevents:* individually-plausible, jointly-impossible
extractions. Each field looks fine; the document does not add up.

**Reviewer corrections flow back into the eval set** — *prevents:* a static benchmark that stops
resembling production.

**Per-field accuracy dashboard** — *prevents:* an aggregate hiding one broken field.

---

## 4. The aggregate is the enemy

`solution.py §5`, on a realistic per-field profile:

| Field | Accuracy | Errors/month | Share of all errors |
|---|---|---|---|
| handwritten_note | 78.2% | 10,899 | **48%** |
| line_2_desc | 96.1% | 1,950 | 9% |
| line_1_desc | 96.4% | 1,800 | 8% |
| po_number | 97.2% | 1,400 | 6% |

Aggregate: **97.74%**. Which reads as a near miss you could tune away with a better model.

It is not. **One field is nearly half of every error in the system** — more than the next three
combined — and it is a field that should never have been in the contract. The aggregate does not
merely hide the problem, it actively misdirects the fix.

Note also that `bank_account` sits at 99.95% because it is **validated**, not because it is easy.
The fields that matter most should be the ones you refuse to trust a model on.

---

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **The SLA definition** | Per-field versus per-document is eighteen points. Pin it first. |
| 2 | **Reviewer throughput** | The queue is the capacity constraint, and it is a hiring problem. |
| 3 | **Confidence calibration** | A confidence signal noisier than the error rate flags everything. |
| 4 | **One hard field** | Invisible in the aggregate, half the errors. |
| 5 | **Eval-set staleness** | Senders change formats; the benchmark does not. |

---

## The follow-ups, answered

**1. The contract says 99%. What do you ask before agreeing?**

Per field or per document — because 20 fields at 99% each is 82% of documents perfect, and if the
customer means per document they are asking for 99.95% per field, which is a different product at
a different price. Then: which fields, weighted how, measured against whose labels, and with what
review budget. I would not sign the first version of this SLA, and saying so is not obstruction —
an SLA nobody can meet is worse for both sides than a renegotiated one.

**2. How many documents need review, and how do you decide which?**

Route on **per-field confidence** against a threshold, and let the threshold be a business dial
rather than a constant. In the simulation that touches under half of documents and catches most
errors at about half the cost of reviewing everything. The threshold is set by the SLA and the
review budget together: tighten it and you catch more errors and pay more reviewers; loosen it and
the reverse. That trade should be explicit and revisited, not buried in a config file.

**3. A reviewer sees an uncertain field. Do they re-check the other nineteen?**

No, and this is the most consequential design decision in the whole system. Per-field routing
shows the reviewer the one field in question with the source region highlighted. Per-document
routing costs **15x** the reviewer time for identical accuracy. The only exception is when a
cross-field validator fails, because then the error is in the *relationship* and you cannot know
which of the two fields is wrong — so you show both.

**4. Which fields would you never trust a model on?**

Anything where an error is expensive and a check is cheap. Bank account and sort code — validate
the checksum, and require a match against a supplier record on file. Total — recompute it from
line items rather than reading it. Currency — constrain to an enumeration. VAT numbers — checksum.
The general rule: **if arithmetic or a lookup can prove it, do not spend model confidence on it.**
That is free accuracy, and it also keeps the review queue for the genuinely ambiguous.

**5. Your aggregate is 99.2% and a customer is furious. Explain.**

Two independent reasons and I would check both. First, they are experiencing the *document*
number, not the field number — 99.2% per field is 85% of documents perfect, so one document in
seven has something wrong in it. Second, their errors are probably concentrated: one field, or one
sender's template, or one document type. The aggregate is an average over a distribution nobody
looks at. I would pull their per-field, per-sender breakdown before responding, because the answer
is almost always "one specific thing", and it is fixable in a way "improve accuracy" is not.

**6. How do you get cheaper over time without getting worse?**

Three levers in order of payoff. **Template caching** — recurring senders are most of the volume,
and a known layout is far cheaper and more accurate than general extraction. **Threshold tuning
per field** — a field running well above target is being over-reviewed, and you can loosen it
independently. **Reviewer corrections into the training and eval sets** — every correction is a
labelled example that was free. What you must not do is raise the confidence threshold globally to
cut review costs; that trades accuracy for money silently, and you will not notice until the SLA
report.

**7. What stops the eval set going stale?**

Reviewer corrections flow into it continuously — that is the main mechanism and it costs nothing
extra, because the labelling already happened. On top: sample new senders and new document
templates deliberately rather than waiting for them to appear, and track the eval set's own
composition against production's, because a benchmark that was representative in January is not
in June. Alert when a sender appears in volume whose template is not represented at all.

**8. Confidence is 0.97 and the field is wrong. What went wrong with confidence?**

Confidence is not calibrated — the model is as sure about a wrong answer as a right one. Measure
this directly with a reliability plot: bucket predictions by confidence and check the actual
accuracy in each bucket. If the 0.97 bucket is 80% accurate, confidence is decorative. Fixes:
calibrate against held-out data, use an ensemble or a second pass on disagreement, and prefer
signals that are *structurally* informative — a validator failing, a low OCR score on the source
region, a value outside historical range for that sender. I would also note the failure mode from
building this: a confidence signal whose **noise is large relative to the error rate** flags
something in almost every document, which silently collapses "route by confidence" into "review
everything" while still looking like routing.

**9. Reviewer throughput becomes the bottleneck.**

Expected, and it is the real capacity constraint of the system. In order: cut the work per item
with per-field routing and source highlighting; cut the item count with better validators, since
every deterministic catch is a review avoided; prioritise the queue by downstream error cost so
the bank account is checked before the payment terms; then, if it is still short, tune thresholds
per field with the SLA in front of you. Hiring is the last lever, not the first, because doubling
reviewers doubles a recurring cost while a validator is written once.

---

## One-line summary

Twenty fields at 99% each is 82% of documents perfect, so human review is the architecture rather
than a fallback — and the design is everything that makes the review queue affordable: per-field
confidence routing, deterministic validators for anything arithmetic can prove, template caching
for repeat senders, and per-field reporting, because an aggregate is how one broken field survives
a quarter.

---

## The trap answer to avoid

Agreeing to 99% without noticing the per-field versus per-document distinction. It is the whole
test, and it is an eighteen-point difference. The second trap is quoting a single accuracy number
at all, when the fields differ by twenty points and one of them is nearly half of every error you
will produce.
