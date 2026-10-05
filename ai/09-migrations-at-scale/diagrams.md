# Migrations — diagrams

## 1. The whole system, end to end

One schema change, from the developer's laptop to a NOT NULL column on a live
10M-row table. Everything below in this file is a fragment of this picture.

```mermaid
flowchart TB
    DEV["developer<br/>alembic revision --autogenerate"] --> REV["revision file in git<br/>upgrade() and downgrade()"]
    REV --> CI["CI: scratch database<br/>only the empty-table path runs"]
    CI --> REL["release: alembic upgrade head"]
    REL --> VER[("alembic_version<br/>one row, the applied revision id")]
    REL --> EXP["1 EXPAND: ADD COLUMN nullable<br/>metadata only, brief lock"]
    EXP --> DB[("primary Postgres<br/>employee_records, 10M rows, 70 req/s")]
    EXP --> APPW["deploy N: code WRITES the column<br/>it does not read it yet"]
    APPW --> BF["2 MIGRATE: backfill worker<br/>batched, resumable, idempotent<br/>runs outside the migration txn"]
    BF --> DB
    DB --> REP[("read replicas<br/>lag is the throttle signal")]
    REP -. throttle on replica lag .-> BF
    BF --> NV["3a CONTRACT: ADD CONSTRAINT NOT VALID<br/>instant, no table scan"]
    NV --> VAL["3b CONTRACT: VALIDATE CONSTRAINT<br/>weak lock, reads and writes continue"]
    VAL --> DB
    VAL --> APPR["deploy N+1: code READS the column"]
    DB -.-> OBS["observability<br/>replica lag, lock waits, batch ETA<br/>abort rule agreed before the start"]
    BF -.-> OBS
```

Two deploys, not one: code and schema move in separate steps so each step is safe
on its own. The only operation that ever takes an `ACCESS EXCLUSIVE` lock here is
the metadata-only `ADD COLUMN`.

## 2. Why it passes CI and fails in production

Same two statements, same order, in both diagrams. The only difference is whether
the table already has rows.

#### CI — scratch database

```mermaid
flowchart TB
    C1["CREATE TABLE fresh"] --> C2["ALTER ... SET DEFAULT"]
    C2 --> C3["ALTER ... SET NOT NULL"]
    C3 --> C4["PASSES — zero rows,<br/>so no row can violate NOT NULL"]
```

#### Production — populated

```mermaid
flowchart TB
    P1[("table with 1M rows,<br/>some record_month NULL")] --> P2["ALTER ... SET DEFAULT"]
    P2 --> P3["applies to FUTURE inserts only<br/>existing NULLs untouched"]
    P3 --> P4["ALTER ... SET NOT NULL"]
    P4 --> P5["FAILS — existing NULLs violate it"]
```

The test suite structurally cannot catch this: the table is always new.

## 3. Expand → migrate → contract

```mermaid
flowchart LR
    A["1. EXPAND<br/>add_column nullable"] --> B["2. MIGRATE<br/>batched UPDATE backfill<br/>WHERE col IS NULL"]
    B --> C["3. CONTRACT<br/>alter_column nullable=False"]
    C --> D{"table large?"}
    D -->|yes| E["add CHECK ... NOT VALID (instant)<br/>then VALIDATE CONSTRAINT (weaker lock)<br/>avoids ACCESS EXCLUSIVE full scan"]
    D -->|no| F["SET NOT NULL directly"]
```

## 4. Django's sequence vs Alembic's graph

#### Django — numbered, serialised

```mermaid
flowchart TB
    D1["0001_initial"] --> D2["0002_add_x"]
    D2 --> D3["0003_add_y"]
    D3 --- DN["the numbering serialises everything,<br/>so branches cannot happen"]
```

#### Alembic — linked list, can branch

```mermaid
flowchart TB
    A1["rev a1b2"] --> A2["rev c3d4"]
    A2 --> A3["rev e5f6 — dev A"]
    A2 --> A4["rev g7h8 — dev B"]
    A3 --> A5["merge revision<br/>two parents, empty body"]
    A4 --> A5
    A5 --- AN["multiple heads until you run<br/>alembic merge explicitly"]
```

Alembic makes the branch visible instead of preventing it. Django's numbering
prevents it, and pays for that with a strictly serial history per app.

## 5. Adopting migrations on a legacy DB

```mermaid
flowchart TB
    S[("existing prod DB<br/>schema built by init_db")] --> B["write ONE baseline revision<br/>matching today's schema"]
    B --> T["alembic stamp head<br/>on every EXISTING database"]
    T --> N["writes alembic_version row<br/>executes NO DDL"]
    B --> F["FRESH databases:<br/>alembic upgrade head -> gets baseline"]
    N --> G["from here: every change<br/>is a new revision"]
    F --> G
    G --> H["init_db shrinks instead of<br/>growing past 63 ADD COLUMNs"]
```
