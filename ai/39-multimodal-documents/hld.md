# The multimodal pipeline at scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Corpus | 400k pages | |
| Numbers in body text | 70% | the text-only ceiling |
| In tables | 22% | the hard, valuable part |
| In figures | 8% | approximate at best |
| Vision at query time | ~£8,640/month | recurring, plus seconds of latency |
| Structure at ingest | ~£4,800 once, £16/month | and it produces structure |

## 2. The ingest pipeline

1. **Layout analysis.** Segment into text / table / figure regions; establish reading order.
   Everything downstream inherits this, including the plain-text path.
2. **OCR where needed**, with per-region confidence. Below threshold → quarantine, not index.
3. **Table extraction** to a structured grid, plus caption and headers.
4. **Figure handling**: crop, store the image, caption with a vision model **once**.
5. **Chunking by region**, not by page — prose, table and figure chunks, linked as siblings.
6. **Provenance** carried throughout: document, page, region coordinates.

Step 1 first is not a preference. Reading order corrupts the text path as readily as the table
path, and it does so silently.

## 3. Retrieval

Route by modality. A numeric question prefers table chunks; a narrative question prefers prose.
Index tables in several forms — caption, headers, row-wise serialisation — because different
question shapes need different handles.

Retrieve the **structured grid**, not a rendering of it, so the answer path can do a cell lookup
and the grounding check has something to compare against.

## 4. Numeric grounding

Every number in a generated answer is matched against an extracted cell before the answer ships.
Three outcomes: matches, contradicts (block), or **no extracted table reports this quantity**
(refuse). The third is the one people omit, and it is what catches a plausible derived figure
that no source supports.

Cheap, deterministic, and the only defence that scales — nobody eyeballs 120,000 answers a month.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Table extraction quality | Measure cell AND structure accuracy; route hard layouts to review |
| 2 | OCR on poor scans | Confidence gate, quarantine queue, alert on quarantine rate |
| 3 | Reading order | Layout analysis before extraction, not after |
| 4 | Figure numbers | Mark estimated; never present at table-cell confidence |
| 5 | Ingest cost and duration | Treat as a batch project; checkpoint and resume |

## 6. Observability

Per stage, always. OCR character error rate by scan-quality band. Quarantine rate, trending — a
rise means a scanner or supplier changed. Table extraction cell accuracy and structure accuracy
on a labelled set. **Retrieval recall split by where the answer lives** — text, table, figure —
because that split is where the ceiling becomes visible. Grounding-check outcomes: matched,
blocked, refused. And provenance correctness, sampled by a human, because a citation to the wrong
cell is worse than no citation.
