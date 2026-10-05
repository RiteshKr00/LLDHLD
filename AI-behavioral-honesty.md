# Behavioral — and the AI-assisted-build question

You built these systems with heavy AI assistance. Interviewers increasingly ask. **Do not
hide it and do not claim you hand-wrote everything** — either gets you caught, and getting
caught on this is fatal in a way the admission never is.

## The frame that works

> "I used AI to move fast, but I own every decision and can defend every trade-off. Let me
> show you."

Then **do it** — that's what this whole track makes possible. Using AI well is now a senior
skill. Being unable to explain your own system is the disqualifier, not the AI use.

## Prepared answers

### "How much of this did AI write?"
> "A lot of the code, and I'd rather say that plainly. What I own is the decisions — why
> the LLM work is on its own queue, why the tenant resolver fails closed, why the
> deterministic validator runs before the LLM check. Ask me about any of them and I'll take
> you through the reasoning and the trade I accepted."

### "Where did the AI get it wrong, and how did you catch it?"
*This is the best question you can get. Have a real answer.*
> "On the CSR evaluation harness, the benchmark came back green and I didn't believe it.
> Headline-fact accuracy was returning `n/a` because the gold facts were keyed to a different
> study id — and `n/a` was being counted as a pass. A regressed enrollment figure had shipped
> under 'all hard gates pass'. I wrote the conclusion down as a rule: a hard gate with no
> ground truth must fail or block, never pass. The lesson was that generated code produces
> *plausible* results, and plausible is exactly what you can't distinguish from correct
> without ground truth."

### "Which part was hardest and why?"
> "Real-time turn-taking on the voice path. Text is request/response; voice has endpointing,
> barge-in, and the platform re-firing the same turn twice. There's a `normalizeTurn` and an
> `isRefiredTurn` in the code specifically because the twin would answer the same question
> twice. None of it is algorithmically hard — it's that the failure modes are invisible until
> you're on a live call, and each one needed its own regression test."

### "Tell me about a bug that took a long time."
> "A persona with uploaded documents was fabricating answers. The retrieval looked fine — the
> chunks were being found. The bug was in prompt composition: the saved writing style was
> being set *instead of* the knowledge context rather than in addition to it. So the model got
> a style instruction and no facts. It took a while because every layer looked correct in
> isolation. The fix was extracting the composition into a pure function with a fail-first
> test, so the additive rule is now pinned by a test rather than by whoever edits the branch
> next."

### "What would you rebuild if you started over?"
> "Schema management. It's an idempotent `init_db` that runs on boot — about ten
> `CREATE TABLE IF NOT EXISTS` and sixty-odd `ADD COLUMN`s. It works, but there's no rollback
> path, no version record, and because tests run against a scratch database the tables are
> always created fresh — so the risky path, altering a *populated* table, is never exercised.
> Adding a NOT NULL column there would pass CI and fail in production. I'd move it to
> versioned migrations with a baseline stamp."

### "What did you learn?"
> "That the interesting problems in AI systems aren't the model — they're everything around
> it. Grounding correctness, tenant isolation, cost attribution, and knowing whether your
> evaluation is telling you the truth. On a four-model bake-off the models landed within
> about a point of each other, and the retrieval scaffold moved quality far more. That
> reordered what I pay attention to."

## The one line to have ready for any weakness question

> "I'd rather tell you the limitation than have you find it."

Then tell them. Volunteered weaknesses are read as calibration. Discovered ones are read as
either ignorance or concealment, and the interviewer can't tell which.
