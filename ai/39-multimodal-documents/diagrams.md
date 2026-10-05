# Multimodal documents — diagrams

## 1. Ingest once, retrieve structure

```mermaid
flowchart TB
    P["page"] --> LA{"Layout analysis FIRST<br/>segment regions, establish reading order"}
    LA -->|text region| OCR{"OCR if scanned<br/>per-region confidence"}
    LA -->|table region| TE["Table extraction<br/>to a STRUCTURED GRID"]
    LA -->|figure region| FIG["crop + store image<br/>caption with a vision model ONCE"]
    OCR -->|conf >= 0.80| TX["prose chunk"]
    OCR -->|below threshold| QU[("Quarantine<br/>'we cannot read this page'")]
    TE --> TC["table chunk: grid + caption + headers<br/>+ row-wise serialisation"]
    FIG --> FC["figure chunk: caption + image ref<br/>values marked ESTIMATED"]
    TX --> PROV["provenance: document, page, region"]
    TC --> PROV
    FC --> PROV
    PROV --> IDX[("Index")]
    Q["question"] --> RT{"route by modality"}
    RT -->|numeric| TC2["prefer table chunks"]
    RT -->|narrative| TX2["prefer prose chunks"]
    IDX --> TC2
    IDX --> TX2
    TC2 --> GEN["answer"]
    TX2 --> GEN
    GEN --> NG{"numeric grounding:<br/>does an extracted cell back every figure?"}
    NG -->|matches| SHIP["ship, with a link to the cell"]
    NG -->|contradicts| BLK["block"]
    NG -->|no table reports it| REFU["refuse"]
```

---

## 2. The ceiling a text-only pipeline cannot exceed

```mermaid
flowchart LR
    N["salient numbers"] --> T["body text 70%"]
    N --> TB["tables 22%"]
    N --> FG["figures 8%"]
    T --> C1["text-only pipeline<br/>ceiling: 70% numeric recall"]
    TB --> C2["+ table extraction<br/>92%"]
    FG --> C3["+ figure captioning<br/>100%"]
    C1 --- X["not a quality gap.<br/>no model improves past it, because<br/>the information is not in the text layer"]
```

---

## 3. A flattened table keeps the digits and loses the meaning

```mermaid
flowchart TB
    TAB["Table 3: Revenue by region<br/>EMEA  12.4  13.1  11.8  15.2"] --> F{"flatten to reading order"}
    F --> FLAT["'EMEA 12.4 13.1 11.8 15.2'"]
    FLAT --> Q2["question: EMEA in Q3?"]
    Q2 --> CAND["candidates 12.4, 13.1, 11.8, 15.2<br/>column: UNKNOWN"]
    CAND --> G["the model picks one. confidently."]
    TAB --> S{"keep the grid"}
    S --> LOOK["row EMEA, column Q3 -> 11.8"]
    G --- W["every digit survived.<br/>the row and column that made them<br/>mean something did not"]
```

---

## 4. Where to pay: query time vs ingest

```mermaid
flowchart LR
    A["vision model per query<br/>120k queries x 6 pages"] --> A1["£8,640 EVERY month"]
    A1 --> A2["+ seconds of latency per question"]
    A2 --> A3["+ returns PROSE about a table,<br/>so no cell lookup, no grounding,<br/>no citation"]
    B["extract structure at ingest"] --> B1["£4,800 once, £16/month after"]
    B1 --> B2["produces STRUCTURE,<br/>reused by every future query"]
```

---

## 5. OCR confidence: wrong versus unknown

```mermaid
flowchart TB
    SC["scanned page"] --> O{"mean OCR confidence"}
    O -->|0.97 clean| I["'Total revenue for the period was 41.2 million'<br/>index it"]
    O -->|0.71 faxed| QQ["'Tota1 revenne fnr the periud was 4l.2 rnillion'<br/>QUARANTINE"]
    O -->|0.34 scribbled| QQ
    QQ --> H["'we cannot read this page' - recoverable"]
    I2["without the gate"] --> BAD["looks fine to an indexer.<br/>retrieves. answers confidently.<br/>every number wrong"]
```

---

## 6. Numeric grounding has three outcomes, not two

```mermaid
flowchart LR
    ANS["answer contains a figure"] --> CH{"is it in an extracted cell?"}
    CH -->|matches| OK3["ship, with a link to the cell"]
    CH -->|cell says something else| BL["BLOCK"]
    CH -->|no table reports this quantity| RF["REFUSE"]
    RF --- N5["the third outcome is the one people omit,<br/>and it is what catches a plausible DERIVED<br/>figure that no source supports"]
```
