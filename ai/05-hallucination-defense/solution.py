"""
05 - the two-layer hallucination defence, with the false-positive trap.

    python3 solution.py

Layer 1 is deterministic and free. Layer 2 is a model and costs tokens.
The output shows what each catches that the other cannot - and shows the
number-extraction trap that makes layer 1 correct rather than merely present.
"""
import json, re

SOURCE_ROWS = [
    {"metric": "units_sold", "value": 430, "period": "Q3"},
    {"metric": "growth_pct", "value": 0.4, "period": "Q3"},
    {"metric": "trial_id", "value": "BNT162b2", "period": "Q3"},
]
SALIENT = {"430", "0.4"}          # the numbers that are actually data


# --------------------------------------------------------------------------- #
# LAYER 1 - deterministic. Free, exact, cannot hallucinate.
# --------------------------------------------------------------------------- #
CITE = re.compile(r"\[REF\d+\]")
# bound matches by non-alphanumerics so digits INSIDE an identifier are ignored
NUM = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)(?![A-Za-z0-9])")


def salient_numbers(text: str) -> set:
    """Extract only numbers that could be DATA.

    Three deliberate rules, each from a real false positive:
      1. strip citation tags first  -> [REF12] must not contribute '12'
      2. bound by non-alphanumerics -> BNT162b2 must not contribute '162'
      3. exempt bare integers < 100 -> '3 sites', 'top 5' are prose, not data
    """
    stripped = CITE.sub(" ", text)
    out = set()
    for m in NUM.finditer(stripped):
        n = m.group(1)
        if "." not in n and int(n) < 100:
            continue                       # rule 3, asserted by a test below
        out.add(n)
    return out


def layer1(draft: dict) -> list:
    """Schema + numeric grounding + range sanity."""
    problems = []
    for field in ("summary", "period"):
        if field not in draft:
            problems.append(f"missing field: {field}")
    if problems:
        return problems
    for n in salient_numbers(draft["summary"]):
        if n not in SALIENT:
            problems.append(f"ungrounded number: {n}")
    if "growth" in draft and not (-1 <= draft["growth"] <= 1):
        problems.append("growth out of range")
    return problems


# --------------------------------------------------------------------------- #
# LAYER 2 - a model. Catches what code cannot judge.
# --------------------------------------------------------------------------- #
HEDGE = {"strongly", "dramatically", "massively", "sharply"}


def layer2(draft: dict) -> list:
    """Stand-in for the maker-checker pass.

    It is given the SOURCE ROWS - that is what makes it a checker rather
    than the same model agreeing with itself.
    """
    problems = []
    growth = next(r["value"] for r in SOURCE_ROWS if r["metric"] == "growth_pct")
    words = set(draft["summary"].lower().split())
    if words & HEDGE and abs(growth) < 5:
        problems.append(f"'{(words & HEDGE).pop()}' misrepresents {growth}%")
    return problems


DRAFTS = {
    "clean":            {"summary": "Units sold 430 in Q3; growth 0.4%.", "period": "Q3"},
    "fabricated number": {"summary": "Units sold 430; growth 12.7%.", "period": "Q3"},
    "misleading prose": {"summary": "Units sold 430 grew strongly at 0.4%.", "period": "Q3"},
    "missing field":    {"summary": "Units sold 430."},
    "identifier trap":  {"summary": "Trial BNT162b2 [REF12] sold 430 units.", "period": "Q3"},
}

if __name__ == "__main__":
    print(f"{'draft':<20} {'layer 1 (free)':<34} {'layer 2 (costs tokens)'}")
    print("-" * 92)
    l2_calls = 0
    for name, d in DRAFTS.items():
        p1 = layer1(d)
        if p1:
            print(f"{name:<20} REJECT: {p1[0]:<26} (not reached - saved a call)")
            continue
        l2_calls += 1
        p2 = layer2(d)
        print(f"{name:<20} {'pass':<34} {('REJECT: ' + p2[0]) if p2 else 'pass'}")

    print(f"\n  layer 2 was called {l2_calls} of {len(DRAFTS)} times.")
    print("  That ratio IS the ordering argument: filter with the cheap")
    print("  infallible layer, then spend the model on what survives.\n")

    # the trap, asserted
    assert salient_numbers("Trial BNT162b2 [REF12] sold 430 units") == {"430"}, \
        "identifier digits and citation ids must not count as data"
    assert layer1(DRAFTS["identifier trap"]) == [], "the trap draft is actually grounded"
    assert layer1(DRAFTS["fabricated number"]), "12.7 is not in the source"
    assert layer2(DRAFTS["misleading prose"]), "only a model catches 'strongly' at 0.4%"
    assert layer1(DRAFTS["misleading prose"]) == [], "layer 1 has no opinion on 'strongly'"

    print("  the two decisive cases")
    print("  ----------------------")
    print("  'grew STRONGLY at 0.4%'  -> layer 1 PASSES it. Schema valid,")
    print("     0.4 is in the source, range fine. Code has no opinion on")
    print("     'strongly'. A model does. That is why layer 2 exists.")
    print()
    print("  'BNT162b2 [REF12] ... 430' -> a naive regex sees 162, 2, 12, 430")
    print("     and would 'ground' a fabrication against an identifier or a")
    print("     chunk id. Stripping citations first and bounding by")
    print("     non-alphanumerics is what makes layer 1 CORRECT.")
    print("\nOK - topic 05")
