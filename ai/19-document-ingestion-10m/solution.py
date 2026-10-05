"""
Scenario 5 - ingesting 10M documents: it is a resumable pipeline, not a job.

    python3 solution.py        (stdlib only, deterministic, well under a second)

Failure first, then the fix, in three acts: a monolithic job that dies at 60% against a
staged pipeline with a durable per-document ledger; at-least-once redelivery against
append-on-write and against a uuid5 upsert; and per-stage input fingerprints deciding
how far back a config change replays - a new embedding model must not re-run OCR.

1,000 documents stand in for 10M and hours are scaled by 10,000, so the output matches
explained.md and hld.md: 200M chunks at 1,000 embeddings/sec = ~55 hours of embedding,
~12,000 CPU-hours of parse/OCR at 15% scanned. "What to notice" prints at the end.
"""
import hashlib
import random
import uuid

random.seed(5)

N_DOCS         = 1_000                 # 1 document here stands for 10,000 real ones
SCALE          = 10_000_000 / N_DOCS
CHUNKS_PER_DOC = 20
DUP_RATE       = 0.30                  # resends, attachments, template contracts
CPU_BORN, CPU_OCR = 1.5, 20.0          # CPU-seconds to parse: born-digital, scanned
EMBED_RATE     = 1_000                 # chunks/sec the whole embed fleet sustains
CRASH_AT       = int(N_DOCS * 0.60)
NS             = uuid.UUID("00000000-0000-0000-0000-0000000000c5")


def h(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]

def scanned(body):
    """Derived from content, so two copies of one document agree on their cost."""
    return int(h("scan", body), 16) % 100 < 15

def embed_hours(n): return n * SCALE / EMBED_RATE / 3600
def cpu_hours(secs): return secs * SCALE / 3600

def corpus(n):
    docs, bodies = [], []
    for i in range(n):
        if bodies and random.random() < DUP_RATE:
            body = random.choice(bodies)                  # byte-identical resend
        else:
            body = "body-%05d" % i
            bodies.append(body)
        docs.append({"id": "doc-%05d" % i, "body": body})
    return docs

DOCS     = corpus(N_DOCS)
UNIQUE   = len({d["body"] for d in DOCS})
IDEAL    = N_DOCS * CHUNKS_PER_DOC
FULL_CPU = sum(CPU_OCR if scanned(d["body"]) else CPU_BORN for d in DOCS)

class Meter:
    def __init__(self):
        self.parses = self.embeds = self.writes = 0
        self.cpu = 0.0

class Crash(Exception):
    pass

def parse(body, m):
    m.parses += 1
    m.cpu += CPU_OCR if scanned(body) else CPU_BORN
    return "text:" + body

def chunk(text, n):
    return ["%s#%d" % (text, i) for i in range(n)]

def embed(chunks, m):
    m.embeds += len(chunks)
    return [h("vec", c) for c in chunks]

def upsert(store, by_doc, doc_id, vectors, m):
    """SET by deterministic id, then delete the ids this document no longer owns."""
    ids = [uuid.uuid5(NS, "%s:%d" % (doc_id, i)).hex for i in range(len(vectors))]
    for cid, vec in zip(ids, vectors):
        store[cid] = vec                     # a replay overwrites, it never appends
        m.writes += 1
    for orphan in by_doc.get(doc_id, set()) - set(ids):
        del store[orphan]                    # a shorter re-chunk leaves these behind
    by_doc[doc_id] = set(ids)

def run_monolithic(docs, m, rows=None, crash_at=None):
    """One task, one loop. Nothing durable is written until the very end."""
    for i, d in enumerate(docs):
        if i == crash_at:
            raise Crash()
        vectors = embed(chunk(parse(d["body"], m), CHUNKS_PER_DOC), m)
        for j, vec in enumerate(vectors if rows is not None else []):
            rows.append((d["id"], j, vec))   # the naive store: every delivery appends
            m.writes += 1

def run_staged(docs, state, m, crash_at=None, parser="p1", chunker="c1", model="e1"):
    """Every stage checks its input fingerprint before working and writes one after.
    The derived-artefact ledger is keyed by CONTENT, so a resend is free."""
    ledger, doc_state, store, by_doc = state
    n_chunks = CHUNKS_PER_DOC if chunker == "c1" else 16
    for i, d in enumerate(docs):
        if i == crash_at:
            raise Crash()
        ch = h(d["body"])                             # content hash of the raw object
        pfp = h(ch, parser)
        cfp = h(pfp, chunker, n_chunks)
        efp = h(cfp, model)
        rec = ledger.setdefault(ch, {})
        if rec.get("parse") != pfp:
            rec["text"], rec["parse"] = parse(d["body"], m), pfp
            rec.pop("chunk", None)
        if rec.get("chunk") != cfp:
            rec["chunks"], rec["chunk"] = chunk(rec["text"], n_chunks), cfp
            rec.pop("embed", None)
        if rec.get("embed") != efp:
            rec["vectors"], rec["embed"] = embed(rec["chunks"], m), efp
        if doc_state.get(d["id"]) != efp:             # per doc, so resends still index
            upsert(store, by_doc, d["id"], rec["vectors"], m)
            doc_state[d["id"]] = efp

def fresh(): return ({}, {}, {}, {})

def snapshot(s):
    return ({k: dict(v) for k, v in s[0].items()}, dict(s[1]), dict(s[2]),
            {k: set(v) for k, v in s[3].items()})

def crashing(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except Crash:
        pass


if __name__ == "__main__":
    print(f"{N_DOCS:,} documents stand in for 10M ({UNIQUE:,} unique, "
          f"{N_DOCS - UNIQUE:,} duplicates). Hours scaled x{SCALE:,.0f}.\n")

    mono = Meter()
    crashing(run_monolithic, DOCS, mono, crash_at=CRASH_AT)
    run_monolithic(DOCS, mono)                        # restart: nothing was recorded
    state, stg = fresh(), Meter()
    crashing(run_staged, DOCS, state, stg, crash_at=CRASH_AT)
    run_staged(DOCS, state, stg)                      # restart: the ledger survived

    print(f"1. IT DIES AT 60% (document {CRASH_AT:,}), THEN RESTARTS")
    print(f"   {'':<34}{'embeddings':>12}{'embed hours':>13}{'parse CPU-h':>13}")
    for label, em, cp in (("monolithic job, restart at zero", mono.embeds, mono.cpu),
                          ("staged + ledger + content dedup", stg.embeds, stg.cpu),
                          ("reference: clean run, no dedup", IDEAL, FULL_CPU)):
        print(f"   {label:<34}{em:>12,}{embed_hours(em):>13.1f}{cpu_hours(cp):>13,.0f}")
    assert mono.embeds == (CRASH_AT + N_DOCS) * CHUNKS_PER_DOC
    assert stg.embeds == UNIQUE * CHUNKS_PER_DOC  # every chunk embedded exactly once, ever
    assert stg.parses == UNIQUE                   # and every unique document parsed once
    assert mono.embeds > 1.8 * stg.embeds
    print("   -> the crash cost the staged run one in-flight batch, not 33 hours.\n")

    rows, m1 = [], Meter()
    run_monolithic(DOCS, m1, rows=rows)
    run_monolithic(DOCS[:100], m1, rows=rows)         # the broker redelivers 100 docs
    s2, m2 = fresh(), Meter()
    run_staged(DOCS, s2, m2)
    run_staged(DOCS[:100], s2, m2)
    print("2. AT-LEAST-ONCE DELIVERY (100 documents redelivered)")
    print(f"   {'append-on-write rows':<34}{len(rows):>12,} chunks  "
          f"({len(rows) - IDEAL:,} phantom copies)")
    print(f"   {'uuid5 idempotent upsert':<34}{len(s2[2]):>12,} chunks  (0 phantom copies)")
    assert len(rows) == (N_DOCS + 100) * CHUNKS_PER_DOC
    assert len(s2[2]) == IDEAL
    print("   -> duplicates are a RETRIEVAL bug: top-k returns one passage three")
    print("      times and the context window fills with a single document.\n")

    print("3. WHAT A CONFIG CHANGE COSTS, REPLAYED OVER A FINISHED CORPUS")
    print(f"   {'what changed':<30}{'parses':>9}{'parse CPU-h':>13}"
          f"{'embeddings':>12}{'embed h':>9}")
    matrix = {}
    for label, kw in (("nothing - re-run the job", {}),
                      ("chunk size 20 -> 16",      {"chunker": "c2"}),
                      ("embedding model v1 -> v2", {"model": "e2"}),
                      ("parser / OCR upgrade",     {"parser": "p2"})):
        s, m = snapshot(state), Meter()
        run_staged(DOCS, s, m, **kw)
        matrix[label] = (m, s)
        print(f"   {label:<30}{m.parses:>9,}{cpu_hours(m.cpu):>13,.0f}"
              f"{m.embeds:>12,}{embed_hours(m.embeds):>9.1f}")

    free = matrix["nothing - re-run the job"][0]
    assert (free.parses, free.embeds, free.writes) == (0, 0, 0)
    rechunk, rstate = matrix["chunk size 20 -> 16"]
    assert rechunk.parses == 0
    assert len(rstate[2]) == N_DOCS * 16          # ids 16-19 deleted, not left matching
    newmodel = matrix["embedding model v1 -> v2"][0]
    assert newmodel.parses == 0 and newmodel.cpu == 0.0
    assert newmodel.embeds == UNIQUE * CHUNKS_PER_DOC
    assert matrix["parser / OCR upgrade"][0].parses == UNIQUE

    print(f"""
what to notice
  - The monolithic run issued {mono.embeds:,} embeddings to produce {IDEAL:,}: it paid for 60%
    of the corpus twice, {embed_hours(mono.embeds):.0f} hours instead of {embed_hours(stg.embeds):.0f}. Nothing clever bought
    the difference - the staged run had written down, per document, how far it got.
  - The staged run embedded exactly {UNIQUE * CHUNKS_PER_DOC:,} chunks: unique content x 20. Dedup and
    resume are one mechanism seen twice, and that assert is an equality rather
    than an inequality because "roughly once" is a bug.
  - Row 1 of act 3 is load-bearing: re-running a finished pipeline costs ZERO.
    If it does not, you have logs, not fingerprints.
  - A model swap costs 0 parses and {embed_hours(newmodel.embeds):.0f} hours, so the {cpu_hours(stg.cpu):,.0f} CPU-hours of OCR
    already paid for are reused in full. A re-chunk costs 0 parses too and
    DELETES chunk ids 16-19 - orphans keep matching queries forever, which is
    the version of this that actually ships.
  - What none of it touches: 200M chunks needs ~30M tokens/minute sustained to
    finish in 55 hours. That is quota, not concurrency, and it breaks first.
""")
    print("OK - scenario 5")
