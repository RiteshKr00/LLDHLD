# Interview-Mode File Format (the app contract)

Every file in `interview-mode/` follows this exact structure so a parser can drive a mock
interview from it. Headings are **stable identifiers** — don't rename them.

## Why this format instead of a worked solution

A finished answer is something you *read*. This is something you *do*: the app shows you the prompt,
waits for your answer, then reveals the checkpoints so you can score yourself. Reading a solution
feels like learning and isn't; being unable to produce a checkpoint is real information.

---

## Section contract

| Heading | Purpose | App behaviour |
|---|---|---|
| `## META` | difficulty, time, tags | filter / sort / progress tracking |
| `## PROMPT` | the vague one-liner an interviewer gives | shown first, alone |
| `## CLARIFY` | questions the candidate *should* ask, each with the interviewer's answer | hidden; revealed **only when the user asks that question** (or gives up) |
| `## STEP n — <name>` | one step of the 9-step spine | one screen each, in order |
| `### CHECKPOINTS` | bullet list — the things a good answer contains | revealed **after** the user submits; user self-scores |
| `### TRAPS` | the specific mistakes people make here | revealed with checkpoints |
| `### FOLLOWUPS` | what the interviewer probes with next | shown as interruptions mid-step |
| `## DEEP DIVE` | the crux of this problem | the step that decides the round |
| `## RUBRIC` | mid vs senior vs staff answer | scoring at the end |
| `## REFERENCE` | the full worked answer | revealed **last**, after self-scoring |
| `## ONE-LINER` | the single sentence to say in a real interview | flashcard mode |

## Rules for the content

1. **CHECKPOINTS are atomic and checkable.** "Estimates read QPS" ✅ — not "understands scale" ❌.
   The app scores by counting hits, so each bullet must be independently yes/no.
2. **TRAPS are specific.** "Forgets that fan-out on write breaks for celebrities" ✅ —
   not "doesn't think about scale" ❌.
3. **FOLLOWUPS are real interviewer sentences**, quotable verbatim.
4. **REFERENCE comes last** so it can't be read before attempting.
5. **Numbers are always shown with their derivation**, never as a bare figure.

## Timing model (for the app's clock)

```
45-minute round:
  Step 1 Requirements ......  5 min
  Step 2 Capacity .........  5 min   <- most-skipped, most-penalised
  Step 3 API ..............  3 min
  Step 4 Data model + DB ...  5 min
  Step 5 Architecture ......  8 min
  Step 6 DEEP DIVE ......... 10 min   <- the round is won here
  Step 7 Scale .............  5 min
  Step 8 Failure ...........  2 min
  Step 9 Wrap ..............  2 min
```

## Modes the app should support

| Mode | Behaviour |
|---|---|
| **Study** | all sections visible, no clock — read like a normal doc |
| **Mock** | prompt only → clock runs → step by step → interruptions from FOLLOWUPS → self-score against CHECKPOINTS → REFERENCE at the end |
| **Drill** | CHECKPOINTS only, as rapid-fire questions ("what's the read:write ratio here?") |
| **Flashcard** | PROMPT front / ONE-LINER back |

## File naming

```
interview-mode/
  FORMAT.md          <- this file
  INDEX.md           <- manifest the app reads first
  hld/HLD-01-news-feed.md ... HLD-10-leaderboard.md
  lld/LLD-01-url-shortener.md ...   (the 11 already-solved problems, same format)
```
