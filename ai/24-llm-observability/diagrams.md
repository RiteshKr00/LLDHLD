# LLM observability — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    APP["app + gateway<br/>trace id minted at the EDGE<br/>tenant resolved once, fails closed"] --> SPAN
    SPAN["LLM span: model, prompt_version,<br/>tokens, cost, scores, outcome"] --> RED
    RED["redactor, in-process<br/>FAILS CLOSED: drop payload, keep skeleton"] --> Q
    Q[["bounded async queue, spills to disk<br/>drop-oldest, NEVER blocks the caller"]] --> COL
    COL["collector: tail sampling,<br/>deterministic on the trace id"] --> SPL{"skeleton or payload?"}
    SPL -->|"skeleton, 100%"| SK[("columnar store, 400 days<br/>240M rows, also the cost ledger")]
    SPL -->|"payload, ~5%"| PL[("object store, 30 days<br/>all errors + refusals + 2% random")]
    SK --> MET["metrics: BOUNDED dims only<br/>model x feature x error_class"]
    SK --> ROLL["hourly per-tenant rollup<br/>rows, not TSDB series"]
    PL --> JUDGE["quality scorer, offline and batched<br/>runs on the UNBIASED 2% slice"]
    JUDGE --> SK
    MET --> ALERT["alerts on LEADING indicators<br/>fallback, refusal, parse-failure rates"]
    ROLL --> DASH["per-model, per-tenant,<br/>per-prompt_version dashboards"]
    ANN[("change annotations<br/>prompt, model, retriever, flag flips")] --> DASH
```

Read it as one span's life: emitted with the tenant already attached, redacted before it leaves
the process, buffered so the application never waits on the collector, then split. The
**skeleton** goes everywhere and is never sampled — it is the cost ledger. The **payload** is the
only thing that is sampled, redacted and expired, because it is the only thing that is both
expensive and sensitive. The annotations feed the dashboards so a quality dip arrives with a
list of candidate causes attached.

---

## 2. The sampling decision — made once, at the root

```mermaid
flowchart TB
    RT["root span mints the trace id<br/>the ONLY place the decision is made"] --> D1{"error, refusal or<br/>validation failure?"}
    D1 -->|yes| KEEP["keep payload, weight 1<br/>100% of the rare outcomes"]
    D1 -->|no| D2{"thumbs-down or<br/>human escalation?"}
    D2 -->|yes| KEEP
    D2 -->|no| H["hash of trace id,<br/>lowest 2 percent"]
    H -->|"in the slice"| SAMP["keep payload, weight 50<br/>the UNBIASED baseline"]
    H -->|"the other 98%"| SKEL["skeleton only, 400 bytes<br/>still 100% of the cost ledger"]
    KEEP --> PROP["decision propagates to every child<br/>whole trace kept, or whole trace dropped"]
    SAMP --> PROP
    SKEL --> PROP
```

Three things are load-bearing. The hash is on the **trace id**, so a kept trace is complete
rather than four spans out of six. The decision is made at the **root** and propagated, so no
downstream service disagrees with it. And rare outcomes bypass the dice entirely, because
sampling errors at the same rate as successes leaves you a dozen error traces a day.

---

## 3. Why the sample needs weights

#### Uniform 2% — the corpus you cannot debug with

```mermaid
flowchart LR
    U0["20,000 traces<br/>600 of them errors"] --> U1["sample every trace at 2%"]
    U1 --> U2["~400 kept, ~12 errors"]
    U2 --> U3["3 examples per error class<br/>and the error RATE still looks right,<br/>so nobody notices"]
```

#### Stratified, then re-weighted

```mermaid
flowchart LR
    S0["20,000 traces<br/>600 of them errors"] --> S1{"rare outcome?"}
    S1 -->|yes| S2["keep all 600, weight 1"]
    S1 -->|no| S3["keep 2 percent, ~388, weight 50"]
    S2 --> S4["naive average: ~61% error rate<br/>you measured your own policy"]
    S3 --> S4
    S4 --> S5["weighted sums: back to 3.00%<br/>and the true mean latency"]
```

The failure in the first block is silent: the *rate* is fine, so the dashboard looks healthy
while the debugging corpus is empty. The trap in the second is louder and worse — keeping every
error and averaging the retained set unweighted publishes a 61% error rate. `solution.py`
asserts both numbers.

---

## 4. The record split, and the storage arithmetic

#### Log everything

```mermaid
flowchart LR
    A0["600k calls/day x 20 KB"] --> A1[("12 GB/day<br/>4.8 TB resident at 400 days")]
    A1 --> A2["every prompt and every answer,<br/>for every tenant, in one store"]
    A2 --> A3["expensive AND your largest<br/>data-protection surface"]
```

#### Split it

```mermaid
flowchart TB
    B0["one trace"] --> B1["skeleton, 400 bytes<br/>numbers and enums, no prose"]
    B0 --> B2["payload, 20 KB<br/>prompt, chunks, response"]
    B1 --> B3[("100%, 400 days, 240 MB/day<br/>this IS the cost ledger")]
    B2 --> RD["redact in-process<br/>FAILS CLOSED: drop, keep the skeleton"]
    RD --> B4[("~5% sampled, 30 days<br/>0.59 GB/day, 18 GB resident")]
    B3 --> B5["0.84 GB/day written, 114 GB resident<br/>14x less written, 42x less resident"]
    B4 --> B5
```

One trace becomes two records with different retentions, because they have different costs and
different liabilities. Notice where the redactor sits: inside the process, on the payload only,
before anything is written. Redaction applied at query time is not redaction — the raw text is
already in the replicas and in last night's backup.

---

## 5. Aggregation: cardinality, and what an average hides

#### Where each metric lives

```mermaid
flowchart TB
    M["one metric, five useful dimensions"] --> C{"cardinality"}
    C -->|"model x feature x error_class"| T["metrics backend<br/>256 series, 1s resolution, alerts"]
    C -->|"plus tenant, prompt_version"| R[("hourly rollup table<br/>12k ROWS per day, not series")]
    C -->|"everything, ad hoc"| Z[("columnar trace store<br/>240M skeleton rows at 400 days")]
    X["all five as TSDB labels<br/>2.5M active series"] -.- M
    X --> XB["the monitoring bill overtakes<br/>the inference bill"]
```

#### What a global average hides

```mermaid
flowchart TB
    G["Tuesday: large-b, 8% of traffic,<br/>groundedness 0.90 to 0.55"] --> G1["global average: about -3 points<br/>under the 5-point threshold"]
    G --> G2["p95 latency: about +10 ms"]
    G --> G3["error rate: unchanged"]
    G --> G4["cut by model: about -35 points,<br/>fires on day one"]
    G1 --- N1["three signals say fine.<br/>Only the cut sees it."]
    G2 --- N1
    G3 --- N1
```

The two blocks are the same tension from both sides. You need the cut by model and prompt
version or you cannot see the regression; you cannot afford that cut as TSDB labels. Resolve it
by destination rather than by giving up the dimension: bounded labels in the metrics backend,
per-tenant detail as **rows** in an hourly rollup, and everything else answered ad hoc against
the columnar store.
