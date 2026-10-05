"""
Scenario 28 - a fine-tuning pipeline for one high-volume task.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. where the effort actually goes, against where people expect it to
  2. eval contamination - the commonest way a fine-tune's numbers get inflated
  3. the prompted baseline as a gate, not a formality
  4. catastrophic forgetting, and the regression suite that catches it
  5. LoRA adapters: cost, swappability, and rollback as a pointer flip

Seeded, so reruns match exactly.

What to notice: training is the cheap, fast, reliable part. Everything that
goes wrong is data - curation, contamination, and an eval that flatters.
"""
import hashlib
import random

random.seed(28)

EXAMPLES = 8_000
GPU_HOUR = 2.00


# --------------------------------------------------------------------------- #
# 1. effort
# --------------------------------------------------------------------------- #
EFFORT = [("sourcing and labelling data", 34),
          ("cleaning, dedup, decontamination", 26),
          ("building the eval set and baseline", 20),
          ("training runs", 6),
          ("serving and rollout", 14)]


# --------------------------------------------------------------------------- #
# 2. contamination
# --------------------------------------------------------------------------- #
def make_corpus(n_train, n_eval, overlap):
    """Build a train/eval split with a known amount of leakage."""
    evalset = [f"example-{i}" for i in range(n_eval)]
    unique = [f"train-{i}" for i in range(n_train - overlap)]
    leaked = random.sample(evalset, overlap)
    return unique + leaked, evalset


def norm(s):
    return hashlib.md5(s.strip().lower().encode()).hexdigest()


def decontaminate(train, evalset):
    banned = {norm(e) for e in evalset}
    return [t for t in train if norm(t) not in banned]


def measure(train, evalset, true_skill=0.71):
    """Seen examples are answered from memory; unseen show true skill."""
    seen = {norm(t) for t in train}
    hits = 0
    for e in evalset:
        if norm(e) in seen:
            hits += 1                       # memorised
        elif random.random() < true_skill:
            hits += 1
    return hits / len(evalset)


# --------------------------------------------------------------------------- #
# 4. general capability
# --------------------------------------------------------------------------- #
GENERAL = {"instruction following": (0.82, 0.61),
           "multi-turn coherence": (0.79, 0.55),
           "refusing out-of-scope": (0.88, 0.34),
           "arithmetic": (0.74, 0.71),
           "the tuned task": (0.66, 0.93)}


def main():
    print("\nFINE-TUNING PIPELINE FOR ONE HIGH-VOLUME TASK")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. WHERE THE EFFORT GOES")
    for name, pct in EFFORT:
        bar = "#" * (pct // 2)
        print(f"   {name:<36}{pct:>3}%  {bar}")
    data_pct = sum(p for n, p in EFFORT if "data" in n or "clean" in n or "eval" in n)
    train_pct = next(p for n, p in EFFORT if n == "training runs")
    assert data_pct > 10 * train_pct / 2
    hrs = 3.5
    print(f"\n   LoRA on a 7B, {EXAMPLES:,} examples: ~{hrs} GPU-hours = "
          f"£{hrs * GPU_HOUR:.0f}")
    print(f"   -> training is {train_pct}% of the effort and costs less than lunch.")
    print(f"      Data work is {data_pct}%. Say this early, because the plan people")
    print("      arrive with allocates the time exactly the other way round.\n")

    # ---------------------------------------------------------------- 2
    print("2. EVAL CONTAMINATION - the commonest self-deception")
    n_eval, TRIALS = 500, 40

    def avg(overlap):
        """Average over trials. A single eval run on 500 examples has a standard
        error near 2 points, which is larger than a small contamination effect -
        so one run cannot tell you whether your split leaked."""
        d = c = 0.0
        for _ in range(TRIALS):
            train, ev = make_corpus(EXAMPLES, n_eval, overlap)
            d += measure(train, ev)
            c += measure(decontaminate(train, ev), ev)
        return d / TRIALS, c / TRIALS

    print(f"   {'overlap with eval set':>22}{'reported score':>17}{'after decontam':>17}"
          f"{'inflation':>11}")
    results = {}
    for overlap in (0, 25, 100, 250):
        d, c = avg(overlap)
        results[overlap] = (d, c)
        print(f"   {str(overlap) + ' of ' + str(n_eval):>22}{d:>17.1%}{c:>17.1%}"
              f"{d - c:>+11.1%}")
    assert results[250][0] > results[250][1] + 0.10
    assert abs(results[0][0] - results[0][1]) < 0.02
    print(f"   (averaged over {TRIALS} runs - one run has a ~2 point standard error,")
    print("    which is larger than a small leak, so a single number cannot detect it)")
    print(f"   -> {250} leaked of {n_eval} inflates the score by "
          f"{results[250][0] - results[250][1]:.0%}.")
    print("      Nothing looks wrong: the split was made, the numbers went up, the")
    print("      model is genuinely better at the examples it memorised. Decontaminate")
    print("      by normalised hash, and fix the held-out split BEFORE any training.\n")

    # ---------------------------------------------------------------- 3
    print("3. THE PROMPTED BASELINE IS THE GATE")
    candidates = [("prompted, zero-shot", 0.68, 0.0),
                  ("prompted, 8 few-shot examples", 0.79, 0.0),
                  ("prompted + a better model", 0.86, 0.0),
                  ("fine-tuned 7B", 0.83, hrs * GPU_HOUR)]
    print(f"   {'approach':<32}{'task score':>12}{'training £':>13}")
    for name, score, cost in candidates:
        print(f"   {name:<32}{score:>12.0%}{cost:>13.0f}")
    ft = dict((n, s) for n, s, _ in candidates)["fine-tuned 7B"]
    best_prompt = max(s for n, s, _ in candidates if n.startswith("prompted"))
    assert ft < best_prompt
    print(f"   -> the fine-tune ({ft:.0%}) loses to a well-prompted stronger model "
          f"({best_prompt:.0%}).")
    print("      That is a common and unwelcome result, and it is exactly why the")
    print("      baseline is a GATE rather than a formality. Fine-tuning still wins on")
    print("      cost per call and latency at volume - but say which axis you are")
    print("      buying, and prove the trade rather than assuming it.\n")

    # ---------------------------------------------------------------- 4
    print("4. CATASTROPHIC FORGETTING - great at one thing, broken at the rest")
    print(f"   {'capability':<26}{'base':>8}{'tuned':>8}{'delta':>9}")
    worst = None
    for cap, (base, tuned) in GENERAL.items():
        d = tuned - base
        if worst is None or d < worst[1]:
            worst = (cap, d)
        print(f"   {cap:<26}{base:>8.0%}{tuned:>8.0%}{d:>+9.0%}")
    assert GENERAL["the tuned task"][1] > GENERAL["the tuned task"][0]
    assert worst[1] < -0.4
    print(f"   -> the task improved {GENERAL['the tuned task'][1] - GENERAL['the tuned task'][0]:+.0%} "
          f"and '{worst[0]}' collapsed {worst[1]:+.0%}.")
    print("      A model that no longer refuses out-of-scope requests is a safety")
    print("      regression that the task eval cannot see. Run a general-capability")
    print("      regression suite on every candidate, not only the task metric.\n")

    # ---------------------------------------------------------------- 5
    print("5. LoRA - cost, swappability, rollback")
    full_gb, lora_gb = 14.0, 0.08
    print(f"   full fine-tune artefact  {full_gb:>7.2f} GB   one model per task")
    print(f"   LoRA adapter             {lora_gb:>7.2f} GB   "
          f"{full_gb / lora_gb:.0f}x smaller, swappable at serve time")
    print(f"   3 tasks, full            {3 * full_gb:>7.2f} GB   3 base copies")
    print(f"   3 tasks, LoRA            {full_gb + 3 * lora_gb:>7.2f} GB   "
          f"1 base + 3 adapters")
    assert full_gb + 3 * lora_gb < 3 * full_gb
    print("   -> and rollback is a POINTER FLIP to the previous adapter, seconds, with")
    print("      the base untouched. Serve behind the same OpenAI-compatible interface")
    print("      and no call site knows a fine-tune exists at all.\n")

    print("WHAT TO NOTICE")
    print("   * training is the cheap, fast, reliable part - everything that goes wrong")
    print("     is data")
    print("   * contamination does not look like a bug: the split was made, the numbers")
    print("     went up, the model really is better at what it memorised")
    print("   * fine-tune for format, style, latency and cost - never for knowledge,")
    print("     which cannot be updated and has no attribution")
    print("   * the prompted baseline is the gate; losing to it is a normal outcome")
    print("\nOK - scenario 28")


if __name__ == "__main__":
    main()
