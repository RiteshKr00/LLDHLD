# Next session — pick up here

_State saved 2026-09-01. The repo is clean and consistent: 16 LLD problems, 15 HLD rounds,_
_31 mocks live in the app, 772 checkpoints. Nothing is half-applied._

---

## Run the app

```bash
cd mobile
python serve.py --port 8010
```

**Use port 8010, not 8000.** A stale service worker from a deleted duplicate app is still cached
against `localhost:8000` and will serve that dead app instead. 8010 is a clean origin.

---

## What's done

- **All 11 original LLD problems have all 5 files** (`problem.md`, `solution.py`, `diagrams.md`,
  `explained.md`, `hld.md`).
- **5 new LLD problems (12–16)** closing pattern gaps: thread pool, discount/pricing rules engine
  (Chain of Responsibility), logging framework (Decorator + Singleton), expression evaluator
  (Interpreter + Composite), connection pool. Each has `problem.md` + `solution.py` only — no
  `diagrams.md` / `explained.md` / `hld.md` yet, and arguably shouldn't until actually worked
  through. They carry `📝 Trap` lines, not `📝 Review note` (that shape means real coaching on
  work done — these haven't been worked yet), plus an italic "not yet worked through" line under
  the h1.
- **5 new HLD rounds (11–15)** in `interview-mode/hld/`: search & ranking, ad serving/RTB, data
  pipeline, recommendation serving, distributed coordination/consensus.
- **`HLD-method-bank.md` is complete** — 20 sections, house density, zero thin sections.
- **Two real check-then-act races in `11-food-delivery/solution.py` are fixed** —
  `_transition` and `_free_partner` were both check-then-act with no lock (same shape
  `assign_partner` already got right). Verified with a forced `threading.Barrier` interleaving
  after 300 random-timing runs failed to reproduce either — the natural window is too narrow for
  CPython to hit by chance. `diagrams.md` and `problem.md` updated to match.
- **`mobile/mockparse.py`** parses both new LLD problems (via `parse_lld`) and new HLD rounds
  (via `parse`) — no code changes needed for these, the existing parser handled them.
- **README.md is accurate** — LLD table now 16 rows, HLD table now 15 rows, "patterns unmet" note
  says all four are now covered (13/14/14/15).

## Known imperfection, accepted deliberately — read this before "fixing" it further

**The 10 new files (5 LLD, 5 HLD) are bigger than the existing bar**, because the workflow that
drafted them had no explicit length ceiling (the exact mistake already made and fixed once this
session on the method-bank sections — and forgotten again for this later batch).

| | new files | existing bar |
|---|---|---|
| HLD round `.md` | 18–28 KB (was 27–40 before a trim pass) | 11–13 KB |
| LLD `problem.md` | 16–18 KB (was 24–30) | 11–13 KB |
| LLD `solution.py` | 26–36 KB (was 43–57) | 11–23 KB |

**The part that actually matters is fixed: checkpoint counts.** LLD problems were originally
51–66 fake-inflated checkpoints (padding, not real content) — a trim pass brought them to
**25–33**, matching the existing 16–34 range. HLD rounds were already at 23–32 checkpoints
throughout, which is correct. **772 total checkpoints, zero garbage** (verified by parsing
`content.js` directly and checking for empty/separator-only checkpoint text).

**Why it stopped at "still oversized" instead of finishing the trim to the KB target:** the
trim workflow started hitting `API Error: Connection lost mid-response` repeatedly — a
transient API/network issue, not a logic bug — right at the point of emitting a large single
Write. Switching to chunked `Edit`-based trimming got real progress (e.g. one `solution.py`
went 45 KB → 26 KB) but several more agents still hit the same connection error mid-edit.
Every file was verified to still be syntactically valid Python / correctly-parsing markdown and
to still **execute cleanly** after those partial runs, so nothing is corrupted — it's just not
as compact as the target. Given the checkpoint counts were already right and files were
confirmed working, the decision was made to install as-is rather than keep burning retries
against a flaky connection.

**If you want to finish the trim later:** it's a cosmetic/readability improvement, not a
correctness one. Re-run a chunked-Edit trim pass per file (see the pattern used for the last
5 solutions), same rules as the method-bank trim: cut restatement, hedging, and — the specific
thing bloating these — `# HINT (to rebuild):` blocks that ballooned to 25–34 lines and now spell
out full method signatures instead of just what a class must do (4–6 lines in the existing
files). Never cut: numbers, the last worked example proving a claim, named tradeoffs, the parser
contract (real em dashes in headings, `### CHECKPOINTS/TRAPS/FOLLOWUPS`, 1:1 numbered
clarify-question/answer pairs).

## Still open

1. **The 5 new LLD problems need `diagrams.md` / `explained.md` / `hld.md`** — deferred on
   purpose; consider waiting until the user has actually worked through Steps 1–3 of each,
   consistent with how the original 11 were built (interviewer-led, not pre-written).
2. **`_wip-drafts/AUDIT-findings-cards-mocks.md`** — an unsolicited 119 KB audit surfaced earlier
   this session, claiming 120 defects across the *original* content. Only 1 was verified (a real
   `mockparse.py` bug, now fixed). **115 findings remain unverified**, concentrated in
   `11-food-delivery/problem.md` (11), `02-parking-lot/problem.md` (6), `08-lru-cache/problem.md`
   (6). Worth a look — the one checked was real.
3. **Deploy** — still local only. `mobile/README.md` has the Netlify/Vercel/GitHub Pages steps.

## The actual next thing, unchanged across several sessions now

**Mock interviews.** 31 rounds are sitting in the app, zero attempted. Content has stopped being
the bottleneck — it was true before this session's expansion and it's even more true now. Don't
let a future "let's add N more problems" become the next way of avoiding this.
