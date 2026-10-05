# Multimodal document pipeline — explained

---

## 1. The ceiling argument

Where the salient numbers actually live in a corpus of reports:

| Location | Share |
|---|---|
| body text | 70% |
| tables | 22% |
| figures | 8% |

So a text-only pipeline has a **hard 70% ceiling on numeric recall**, and no model improves past
it — the information is not in the text layer at all. `solution.py §1`.

Say this in the first minute. It converts "make the documents answerable" from a vague quality
goal into a specific engineering target, and it justifies every component below.

---

## 2. Say this before anything else: the trap is vision-at-query-time

"I'd send the page image to a vision model" works, and it does not scale. Two reasons, and the
second is the one that matters.

**Cost and latency.** `solution.py §3`: 120k queries a month against six pages each is **£8,640
every month**, plus seconds of latency on every question. Extracting once at ingest is £4,800 in
month one and £16 a month thereafter.

**It loses structure.** A vision model looking at a page returns prose about the page. What you
want from a table is the **grid** — this number is in the EMEA row and the Q3 column — and a
screenshot round-trip discards exactly that.

**Extract structure once at ingest; retrieve structure at query time.** That is the design.

---

## 3. A flattened table keeps every digit and loses the meaning

`solution.py §2`. Take a revenue-by-region table and flatten it into reading order. Ask for EMEA
in Q3:

- **Structured lookup:** 11.8
- **From flat text:** candidates `['12.4', '13.1', '11.8', '15.2']`, column *unknown*

Every number survived. What did not survive is which column each belongs to — and a number
without its row and column is not a number. The model will pick one, confidently.

This is why table extraction produces **structured data, not prose**. Store the grid; index the
caption, the headers and a serialised form for retrieval; keep the cells addressable for lookup
and for grounding.

---

## 4. The layers, each named by the failure it prevents

**Layout analysis first** — *prevents:* tables flattened into unreadable soup, and multi-column
pages read straight across. Segment into text / table / figure regions before anything else.

**Table extraction as structured data** — *prevents:* losing the row/column relationship that
makes a number mean something.

**OCR with a confidence threshold** — *prevents:* silently indexing garbage. `solution.py §4`: a
faxed page yields `Tota1 revenne fnr the periud was 4l.2 rnillion` at 0.71 confidence. It looks
fine to an indexer and every number in it is wrong.

**Figures: crop the region, caption it with a vision model at ingest** — *prevents:* paying
vision costs per query. Store the crop so a human can check it.

**Provenance to page and region** — *prevents:* uncheckable citations. A number that cannot be
traced to a cell on a page is not usable for a decision.

**Route by modality at query time** — *prevents:* a numeric question ranking narrative prose
above the table that answers it.

**Numeric grounding check** — *prevents:* a fabricated figure. `solution.py §5`: every number in
an answer is matched against the extracted cells before it ships, and an unsupported quantity is
refused rather than compared against something else.

---

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Table extraction quality** | The hardest part, and it sets the ceiling on numeric answers. |
| 2 | **OCR on poor scans** | Confidently wrong text, indistinguishable from good text downstream. |
| 3 | **Reading order** | Multi-column and footnotes; silent, and it corrupts the text path too. |
| 4 | **Figure grounding** | A captioned chart is an interpretation, not data. |
| 5 | **Ingest cost and time** | It is a batch project, not a deploy. |

---

## The follow-ups, answered

**1. Why not send the page image to a vision model at query time?**

It works, which is why it is tempting. It costs £8,640 a month against £16 in steady state, adds
seconds of latency to every question, and — the real objection — it returns *prose about a table*
rather than the table. You cannot do a cell lookup on a paragraph, you cannot ground a number
against it, and you cannot cite a cell. Pay once at ingest, get structure, and reuse it for every
future query. Vision at query time is the right answer for a one-off human question about one
page, and the wrong architecture for a corpus.

**2. A number lives in a chart with no underlying data table.**

Be honest about what is recoverable. A vision model can read a bar chart approximately, and
approximately is dangerous for a number someone will act on. So: caption the figure at ingest,
extract series values where the chart type allows it and mark them **estimated**, store the
cropped image, and have the answer say "approximately 41, from Figure 3 — see the chart" with the
crop attached. Never present a figure-derived number with the same confidence as a table cell.
Where the underlying data exists elsewhere, prefer it and use the chart only as a pointer.

**3. How do you index a table so a numeric question finds it?**

Several representations of the same table, because different queries need different handles.
Index the **caption and headers** as text, since "revenue by region" is how people ask. Index a
**serialised row-wise form** — "EMEA: Q1 12.4, Q2 13.1..." — which retrieves well for
row-oriented questions. Keep the **structured grid** addressable for lookup and grounding. And
attach surrounding context, because a table titled "Table 3" means nothing without the paragraph
that introduces it. At query time, route numeric questions preferentially to table chunks.

**4. OCR returns garbage. How do you know?**

Mean character confidence from the OCR engine is the first gate, and it is usually enough:
`solution.py §4` shows a faxed page at 0.71 against a clean page at 0.97. Below threshold,
**quarantine rather than index** — the honest state is "we cannot read this page", which is
recoverable, whereas confidently wrong text is not. Add cheap sanity checks on top: dictionary
hit rate, the ratio of digits to letters against expectations for the document type, and whether
extracted totals reconcile. Then track the quarantine rate as a metric, because a rise means a
scanner or a supplier changed something.

**5. What is your chunk, once a page has text, a table and a figure?**

Not the page. Three chunks of different types, each with page and region provenance: a prose
chunk, a table chunk carrying the structured grid, and a figure chunk carrying the caption and a
reference to the cropped image. They are linked as siblings so retrieving one can pull its
neighbours for context. Mixing them into one chunk is how a table becomes soup, and it also makes
modality routing impossible, because you can no longer prefer table chunks for a numeric question.

**6. A user asks for a number. How do they check it?**

Provenance to **page and region**, surfaced as a link that opens the page with the cell or figure
highlighted. Not "according to the annual report" — the specific cell. This is the difference
between an answer a finance team can use and one they cannot, and it is much easier to build at
ingest than to retrofit, because it means carrying the region coordinates through the whole
pipeline.

**7. Two-column layout with footnotes. What breaks?**

Reading order, silently. A naive extractor reads straight across the page, interleaving the two
columns into alternating half-sentences, and pulls footnote text into the middle of a paragraph.
Nothing errors and the text looks superficially plausible. Layout analysis has to establish
reading order before extraction — column detection, then within-column ordering, with footnotes
and headers separated out as their own regions rather than inlined. This is why layout analysis
is step one and not a refinement: it corrupts the text path too, not only tables.

**8. How do you measure whether this pipeline is good?**

Per stage, because an end-to-end number tells you nothing about where to spend. Table extraction:
cell-level accuracy on a labelled set, plus structure accuracy — did you get the right number of
rows and columns. OCR: character error rate by scan quality band. Retrieval: recall of the
correct region for a question, split by whether the answer lives in text, a table or a figure —
that split is the whole point, since it is where the ceiling shows up. End to end: numeric
accuracy with provenance correctness, which is stricter than answer accuracy and is what
actually matters.

**9. Your table extractor is 85% accurate. Is the product viable?**

It depends entirely on what the 15% looks like and whether the failures are detectable, and I
would want that breakdown before answering. If errors are concentrated in complex merged-cell
layouts and the extractor knows it struggled, route those to review and the product is viable at
85%. If the errors are uniformly distributed and silent, then roughly one in seven numeric
answers is wrong with no signal, and it is not viable for anything financial. So the question to
answer first is not "how do we get to 95%" but "can we tell which 15%" — a detectable failure
becomes a review queue, and an undetectable one becomes a liability.

---

## One-line summary

If 30% of the salient numbers live in tables and figures then a text-only pipeline has a hard 70%
ceiling on numeric recall, so the design is layout analysis first, table extraction to structured
data rather than prose, OCR gated on confidence, figures cropped and captioned once at ingest —
never per query — with provenance to page and region and every number in an answer checked
against the extracted cells before it ships.

---

## The trap answer to avoid

"I'd send the page image to a vision model." It works, it costs hundreds of times more in steady
state, it adds seconds per query, and it returns prose about a table instead of the table — so
you cannot look up a cell, ground a number, or cite one. The quieter trap is treating a flattened
table as extracted: every digit is still there, which makes it look successful, and the row and
column that made those digits mean something are gone.
