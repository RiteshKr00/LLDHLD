# Build prompt — finish the study app

> Paste into a **fresh Claude Code session** started in
> `c:\Users\RiteshKumar\Scrap\LLD Interview Prep`. Written for the agent, not for me.
>
> **This replaces the earlier version of this file, which was wrong about the premise.** It assumed
> two half-apps needing to be unified into a new `app/` folder. That is no longer the situation:
> `pwa/` has been retired to `_superseded-pwa/`, and **`mobile/` is now the app.** Do not build a
> new app. Finish this one.

---

## 0. Where things actually stand

Verified in the repo as of 2026-09-01, not assumed:

**The PWA already exists and works.** `mobile/www/` has `manifest.webmanifest`
(`display: standalone`, 192/512/maskable icons, `#/revise` and `#/search` shortcuts), a service
worker, and a 5-tab shell (Home · Concepts · Mock · Revise · Search). It ships **21 mock rounds,
487 checkpoints, 82 cards, 11 problems, 22 reference docs** from a 1.28 MB offline bundle. Run it
with `cd mobile && python serve.py --port 8010` — **port 8010, not 8000**; a stale service worker
from a deleted duplicate is still cached against 8000 and will serve that dead app.

So the question is not "will I get a PWA". It is: **three things are unfinished.** In priority order:

| | Workstream | State |
|---|---|---|
| **A** | 115 unverified content defects + parser bugs that are still live | the audit exists, 1 of 120 fixed |
| **B** | 10 new problems (5 LLD + 5 HLD) drafted but **still oversized** | trim incomplete, see §3 |
| **C** | Accessibility / ease-of-access | mostly **not started** — see §4 for what's real |

And one standing thing that keeps getting deferred: **I have never actually run a mock round.**
21 rounds are sitting there untried. See §6 — do not let this batch of work become the next place to
hide from that.

## 1. Read first, report, wait for my confirmation

- `NEXT-SESSION.md` — the handoff from the last session. Authoritative on what is done.
- `README.md` — accurate as of this session.
- `interview-mode/FORMAT.md` — the parser contract. Headings are stable identifiers.
- `interview-mode/INDEX.md` — manifest, suggested order, and the 5 cross-problem threads.
- `mobile/mockparse.py` — the mock parser. `parse()` for HLD, `parse_lld()` for LLD.
- `mobile/build.py` — `build_decks()` makes the flashcards; `scan()` discovers content.
- `_wip-drafts/AUDIT-findings-cards-mocks.md` — 120 findings, skepticism-checked. **The §2 worklist.**

Tell me what you found and where you disagree with anything below. No code yet.

## 2. Hard constraints

1. **The 11 solved LLD problems are frozen** — all 5 files each (`problem.md`, `solution.py`,
   `diagrams.md`, `explained.md`, `hld.md`), plus the top-level reference docs. These are the canon
   and the record of work I actually did. Snapshot `sha256` of every one before you start; re-verify
   before reporting done. This folder is not a git repo, so hashes are the only safety net.
   Corrections live in the derived layer (`interview-mode/**`) or in the parser — never in the source.
2. **`11-food-delivery/solution.py` has two confirmed races** (`_transition` and `_free_partner`,
   documented in `NEXT-SESSION.md` with repro scripts). It is my capstone code. **Do not fix it
   without asking me** — and if I say go, the fix is `self._lock` around both, keeping the
   `assign_partner` call at the end of `_free_partner` *outside* the lock or it deadlocks
   (`threading.Lock` is not reentrant).
3. **Nothing invented.** Rephrasing a heading into a question and splitting a compound bullet into
   atomic checkpoints are fine. Authoring new technical claims is not. If the notes do not settle
   something, leave it out and list it.
4. **No npm, no framework, no CDN.** Static HTML/CSS/JS plus Python for the build. Fully offline
   after first load.
5. **Do not touch `_superseded-pwa/`.** It is retired. Do not resurrect it, do not port from it, and
   do not create a third app folder.
6. **Phone-first**, 390×844 before desktop. No horizontal page scroll; wide tables, code and
   diagrams scroll in their own container.
7. **Nothing leaves the device.** No account, no analytics, no runtime network calls.

---

# A. Fix the content

## 2a. The still-live parser bugs — verify these first, they are cheap and load-bearing

One bug from the audit was already fixed (`mockparse.py` table-header detection, by lookahead for
the `|---|` separator; checkpoints went 492 → 487). **These are still live** — I confirmed each in
the shipped bundle just now:

**LLD rounds have 3–4 steps where HLD rounds have 9.** `parse_lld()` does `if not cps: continue`,
which silently drops any step whose content is fenced signatures rather than bullets. Measured in
the current bundle:

```
Parking Lot 3 steps · Elevator 3 · Rate Limiter 3 · Food Delivery 3
URL Shortener 4 · Chess 4 · Splitwise 4 · LRU 4 · Movie 4 · Text Editor 4
every HLD round: 9
```

`Step 3 — Relationships & APIs` is gone from parking-lot, elevator and rate-limiter — the step that
holds the API surface. Emit the step with its prose body instead of skipping it, and teach `items()`
to pick up `def …` signature lines inside fenced blocks.

**LLD rounds have no interruptions at all** — `parse_lld()` hard-codes `"followups": []`. Every LLD
mock runs uninterrupted while every HLD mock has interviewer interruptions.

**Clarify answers are still paired by list position.** `clarify = [{"q": q, "a": ans[i] …}]` zips two
independent lists by index. Counts differ in 6 of 11 problems (`02` 6q/7a, `03` 6q/4a, `04` 6q/7a,
`05` 5q/4a, `08` 6q/7a, `11` 7q/9a), so answers are shifted or empty. What parking-lot shows today:

```
Q3 "How is a spot chosen — first available? Nearest?"  ->  "Spot types: Small, Medium, Large."
Q4 "Pricing — hourly, flat, tiered?"                   ->  "Fit rules: Motorcycle -> any …"
Q5 "Capacity/time — max stay?"                          ->  "Pricing: hourly, rate by spot type"
```

Match on the answer's bolded lead-in (`**Pricing:**`, `**Fit rules:**`) which the notes already
provide. Where nothing matches, **drop and report** — never silently empty. Ban positional zipping.

**Two more in `items()`:** it keeps only `cells[:2]`, so a 4-column comparison row loses its verdict
and two rows collapse into apparent duplicates; and a bullet wrapping to a second line is truncated
mid-sentence (`"…errors compound and balances"` — ends there). Join continuation lines before
flushing.

**31 of 82 cards ask no question** — the front is a heading plus "Recall this." / "Recall it." /
"Recall this section." (`scope` 22, `entities` 5, `patterns` 4). Housekeeping headings became study
cards (`"How to grow this file"`, in two decks). Question templates are applied to content they do
not fit — the pattern question *"when does it earn its place, what's the tell?"* asked of
`"Mutable defaults"`; the HLD *"what's the menu of options?"* asked of `"Common Mistakes"`. `hldbank`
runs **Phase 14 → 17 → 16 → 15**. `scope` fronts leak my editing marks (`"✅ LOCKED"`,
`"← YOUR TURN"`) — strip those at build time, **do not edit them out of the frozen source.**

One correction to the audit, which got this wrong: `"Step 1 first: the clarifying-question
checklist"` and `"The checklist"` are **not** duplicates — different backs (the six-category question
table vs the nouns→verbs→orchestrator procedure). Rename the fronts; **merging them deletes real
content.** The genuine near-duplicate is `"How to grow this file"`.

## 2b. The audit worklist — 115 still unverified

`_wip-drafts/AUDIT-findings-cards-mocks.md`: **120 confirmed defects**, each with a verbatim quote,
an independent skeptic's confirmation, and a specific fix. 42 further claims were rejected by that
skeptic and deliberately left out — don't hunt for them. Only the `mockparse.py` one has been acted
on; the last session checked that one, found it real, and parked the rest.

Concentrations: `11-food-delivery/problem.md` 11 · `02-parking-lot` 6 · `08-lru-cache` 6 ·
`06-splitwise` 5 · `HLD-08-ticketmaster` 9 · `HLD-07-web-crawler` 8 · `HLD-10-leaderboard` 7.
By class: `factually-wrong` 28 · `formatting-artifact` 26 · `wrong-answer-pairing` 17 ·
`contradicts-other-note` 14 · `missing` 12 · `not-atomic` 7 · rest 16.

The arithmetic ones matter most, because I will recite these numbers in a room:

- **`HLD-04-youtube` STEP 2** calls 30,000 *views started per second* "30,000 **concurrent
  streams**" → 150 Gbps. Concurrency = arrival × duration, so at ~300 s watch it is ~9M concurrent
  and **~45 Tbps**. Off by ~300×, in the step FORMAT.md calls "most-skipped, most-penalised".
- **`HLD-08-ticketmaster`**: `"49,950,000 of 2M"` doesn't derive — it is `2,000,000 − 50,000`.
- **`HLD-01`**: `"2M/day per 100M… say 0.2/day"` mixes rates differing 10×; every other number in
  that block is correct.
- **`HLD-02`** presence trap says 500M writes/cycle; its own STEP 7 says 3M QPS (100M concurrent ÷ 30 s).
- **`HLD-10`** calls rank #47,000,000 of 100M `"Top 8%"`. It is top 47%.
- **`HLD-02`** `messages(…)` lacks `client_msg_id`, which DEEP DIVE, STEP 8 and the Staff rubric all
  require for retry dedup.

**Work it high-severity first, report as `n of 120`, and push back on anything you think is wrong
rather than implementing it** — three of that audit's claims about *my own spec* were themselves
wrong, so it is not infallible.

**On the 45 findings located in frozen `NN-*/problem.md`:** nearly all are defects in how the parser
reads them — fix the parser. A handful need a clarification bullet the notes never had (`03-elevator`
Q5/Q6 have no answer written anywhere, `06-splitwise` has no money-precision answer, `08-lru-cache`'s
O(1) requirement has no matching question). Those go in the derived layer. Two findings suggest
deleting a stale `← YOUR TURN` from a source heading — **don't**; strip it at build time.

## 2c. Build gates — write these BEFORE the fixes

In `mobile/test/`, extending the existing cscript-based rig. Each must **fail on today's content** —
show me that failure output first. A gate that passes before the fix tests nothing.

| Gate | Catches |
|---|---|
| parsed step count == source step count, per problem | the dropped `Step 3`s |
| every LLD round has ≥ 1 followup | the hard-coded `[]` |
| every clarify question has an answer, **matched by label not position** | the 6 mismatched problems |
| no card front matching `^Recall (this\|it\|this section)` | the 31 questionless cards |
| no item from a skip-listed housekeeping heading | `"How to grow this file"` |
| question template asserted per source-section type | both broken branches of `build_decks()` |
| no checkpoint that is a table header row, or ends mid-sentence | `items()` truncation |
| every item carries `{source_file, heading}` provenance | traceability |
| duplicate detection **prints what it merged** | so a distinct-but-ambiguous pair is caught by eye |
| numbered sections emitted in numeric order | `hldbank` 14→17→16→15 |
| no `✅ ⛔ ← YOUR TURN LOCKED 📝` in any question text | leaked editing marks |
| every `STEP 2` number has a visible derivation on its line | FORMAT.md rule 5 |
| frozen-file hashes unchanged | constraint 1 |

---

# B. Land the 10 new problems

## 3. They are drafted and verified, but the trim did not finish

5 LLD (thread pool · discount engine · logging framework · expression evaluator · connection pool)
and 5 HLD (search & ranking · ad serving/RTB · data pipeline · recommendation serving · distributed
coordination). Chosen to close real machinery gaps — Chain of Responsibility, Decorator+Singleton,
Interpreter+Composite, a concurrency *primitive*, resource lifecycle; and on the HLD side an
inverted index, a hard real-time latency budget, batch-vs-stream, ML-infra serving, and the
Raft/consensus machinery that job-scheduler's leader election *uses but never explains*.

Drafts are at
`C:\Users\RITESH~1\AppData\Local\Temp\claude\c--Users-RiteshKumar-Scrap\31996f39-fb1e-4cd1-b536-ffb8f56e0134\scratchpad\{hld2,lld2}\`.

**A trim workflow ran and left the job half done.** Measured now:

| | target | actual | verdict |
|---|---|---|---|
| HLD round `.md` | 12–15 KB | **28–36 KB** | ~2–2.5× over |
| LLD `problem.md` | 12–15 KB | **20–25 KB** | ~1.7× over |
| LLD `solution.py` | 18–24 KB | **44–58 KB** | ~2.4× over, **not trimmed at all** |

The `problem.md` files were re-trimmed at 15:51; the `solution.py` files have not been touched since
11:22–11:33. Finish the trim before installing anything. Cut restatement and prose-that-should-be-a-
table; **preserve every number, tradeoff and worked example**; keep the FORMAT.md parser contract
intact; bring LLD checkpoints to 25–32 (drafts came in at 51–66 against an existing range of 16–34,
which is the clearest measure of the padding); and **re-run every `solution.py` after trimming** —
all 5 executed cleanly before, and must still.

Two more findings files, recovered from the interrupted workflows' journals, cover these drafts:
`_wip-drafts/findings-wf_e2fc22a6-1cb.md` (5 HLD rounds, 65 findings) and
`findings-wf_71c82c90-b22.md` (4 LLD problems, 29 findings). **Treat them as reference, not a
worklist** — most were already applied to the drafts before the interruption, and only 2 of 5 blocks
name their file. Two that are worth acting on regardless, because they are the kind that survives
into a real interview:

- `16-connection-pool`: a `validate()` that *raises* (and a real one is `SELECT 1`, which does)
  permanently leaks pool slots at three sites, and makes `sweep()` — the self-healing mechanism —
  destroy healthy connections. Verified with a repro.
- `HLD-12-ad-serving`: the latency budget contradicts itself (5+5+2 = 12, but the timeline says
  fan-out at t=17 and guillotine at t=77), and the ONE-LINER I would memorise recites arithmetic
  summing to 98, not 100.

Also: the ad-serving draft references "HLD-11" as the search round. That now exists
(`hld2/HLD-11-search.md`), so those cross-references resolve — but check them rather than assuming.

**Install order:** trim → verify sizes and that every `solution.py` runs → copy in → `python
mobile/build.py` → confirm the mock count goes **21 → 31**. `INDEX.md` needs its heading count, ten
new rows and the suggested order updated. The 5 new LLD problems will still lack `diagrams.md`,
`explained.md` and `hld.md` — leave that; it should wait until I have actually worked the problems.

**Keep one distinction:** the new LLD problems get `📝 Trap (Step N):` and an italic line under the
h1 saying *"not yet worked through"*. They do **not** get `📝 Review note` — that shape is a record
of real coaching on work I actually did, and faking it would corrupt the one signal I trust.

---

# C. Accessibility and ease-of-access

## 4. What exists, what doesn't — measured, not guessed

Already there, build on it rather than replacing it:

- **Design tokens**: `--fs: 1rem`, `--lh: 1.65`, `--colw`, `--safe-t` / `--safe-b` / `--nav-h`,
  plus the full colour set. `body` already reads `font-size: var(--fs)` — **font scaling is plumbed.**
- **Settings sheet** with `openSettings()`, and `state.settings = { theme, size, wake }` persisted.
- **Theme**: `data-theme` on `<html>`, a light block, `prefers-color-scheme`, follow-system default.
- **Wake lock**, already wired.
- `prefers-reduced-motion` respected in one place.
- `maximum-scale=5` (not 1) in the viewport, so browser pinch-zoom is not blocked. Keep it that way.

**Missing entirely — zero occurrences in `app.js` or `styles.css`:**

| Ask | Count today |
|---|---|
| Fullscreen / immersive (`requestFullscreen`) | **0** |
| Read-aloud (`speechSynthesis`) | **0** |
| Voice answers (`SpeechRecognition`) | **0** |
| `aria-live`, `aria-expanded`, `aria-label`, `role=`, `tabindex` | **0 — no ARIA at all** |
| Haptics (`navigator.vibrate`) | **0** |

## 5. Build these

**Fullscreen and immersion** — a toggle in Settings and a one-tap control on a problem screen
(Fullscreen API; the manifest is already `standalone`). Hide the appbar and tab bar on scroll-down,
restore on scroll-up.

**Reading comfort** — extend the existing `size` setting to **5 steps driving `--fs`** so everything
scales. Add `--lh` and `--colw` toggles (comfortable / compact). Add **AMOLED black**, **sepia/warm
night** (low blue, for 1 a.m.) and **high-contrast** to the theme list. Verify every theme hits WCAG
AA and report the ratios. Optional dyslexia-friendly font stack and a no-italics switch. Extend
`prefers-reduced-motion` to kill *all* transitions.

**Hands and thumbs** — keep primary actions in the lower third. Enforce **44×44 px minimum tap
targets** and prove it with a test. Swipe between steps and cards, swipe-down to dismiss sheets —
and **every gesture also gets a visible button**; a gesture is never the only way. Wake lock already
works, make sure it engages for a mock round. Landscape and split-screen must not break; give
diagrams the extra room in landscape. Optional haptics at step-budget and round end.

**Keyboard** (desktop revision) — `j`/`k` or arrows next/prev, `space` reveal, `1`–`5` tabs, `/`
search, `?` shortcut sheet, `Esc` back/close, `f` fullscreen. Visible focus rings, logical tab order,
focus moved to the new view's heading on every route change, skip-to-content link.

**Screen reader** — this is the biggest gap, and it is all of the semantics. Real landmarks
(`header`/`nav`/`main`), headings in order, `<button>` for buttons. `aria-expanded` on every
collapsible. `aria-live="polite"` on the timer, score and toasts; `aria-live="assertive"` on
interviewer interruptions. **Checkpoints must be real checkboxes with labels**, not styled divs —
announced state is the whole point in a self-scoring app. Diagrams get `role="img"` with a real
`<title>`/`<desc>` in the SVG and a text equivalent.

**Hands-free** — `speechSynthesis` read-aloud for the prompt, the one-liner and a problem's summary,
with play/pause and speed, so I can revise while walking. Degrade silently where unavailable.

---

# D. Then actually use it

## 6. The mock loop is the point, and I have used it zero times

21 rounds, 487 checkpoints, and no attempts. Once A and C are done, **the deliverable is that I sit
one round end to end and the debrief tells me something I did not know about my own gaps.**

Check the existing Mock flow against `interview-mode/FORMAT.md` and close whatever is missing:

- **Prompt only** to start. Clock on tap.
- **Clarify phase where not asking costs me** — I type what I would ask; an answer is revealed only
  for a question I actually asked; unasked ones land in the debrief as misses. FORMAT.md specifies
  this and a row of tappable reveals does not implement it.
- **Per-step time budget** with a nudge at 80%, never a hard stop. HLD's timing model is in FORMAT.md.
- **Interruptions** from FOLLOWUPS at a semi-random point, holding the step until I respond.
- **Answer capture**: text, *or* dictation, *or* "I said it aloud" — in a real round I speak.
- **Hint budget**: 3, each visibly costing score.
- **Score over all steps**, DEEP DIVE weighted double, mapped through RUBRIC to a mid/senior/staff
  verdict quoting the line that justifies it.
- **"What you missed"** — every unticked checkpoint and unasked question, each linking to the
  section that covers it.
- **Drill deck auto-built from the misses only**, SRS-scheduled (1d/3d/7d/21d), so tomorrow's Revise
  tab is *my* misses rather than random cards.

## 7. Phases — stop and show me after each

1. **Survey** (§1). Findings and disagreements. No code.
2. **Reproduce**: the §2a parser bugs at the command line, plus the 5 highest-severity audit
   findings. No fixes.
3. **Write the §2c gates** and show me them failing on today's content.
4. **Work the audit**, high severity first, gates going green. Report `n of 120`.
5. **Finish the trim** (§3), verify sizes and that all 5 `solution.py` run, install, `21 → 31`.
6. **Accessibility** (§5), item by item, with the audit output and contrast ratios.
7. **Mock loop** (§6) — then I sit one round and we see.

## 8. Done means

- LLD rounds have their real step count; no round has a mispaired or empty clarify answer.
- No "Recall this" cards; no table headers or truncated fragments as checkpoints.
- Gates pass, and each one demonstrably failed before its fix.
- 31 rounds, every new file inside its size band, every `solution.py` running.
- Every §4 "missing" row is no longer zero. Checkpoints are real checkboxes.
- Frozen-file hashes unchanged; `11-food-delivery/solution.py` untouched unless I said otherwise.
- **I have completed one mock round and the debrief was useful.**

If anything here conflicts with what you find in the repo, say so and propose the fix — the last
version of this file was wrong about its central premise, so assume this one can be too.
