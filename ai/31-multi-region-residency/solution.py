"""
Scenario 17 - multi-region serving with data residency.

    python3 solution.py

Four mechanics, each with the failure shown happening FIRST, then the fix:
  1. health-based failover, which is correct for HA and a breach here
  2. the artefacts people forget: embeddings, cache and traces
  3. one global eval suite, and the regional model drift it hides
  4. a residency test in CI that reads config and fails the build

Population: 20,000 requests across 3 regions and 12 tenants, 5 of them
EU-regulated. Seeded, so reruns match exactly.

What to notice: every failure here is a CORRECTLY IMPLEMENTED best practice.
Failover, a shared cache, one eval suite and centralised logging are all the
right answer in a single-region system. Residency inverts each of them.
"""
import hashlib
import random

random.seed(17)

REGIONS = ["eu-west", "us-east", "ap-south"]
N_REQUESTS = 20_000

# tenant -> (home region, regulated?)
TENANTS = {}
for i in range(12):
    home = REGIONS[i % 3]
    TENANTS[f"t{i:02d}"] = (home, home == "eu-west")
REGULATED = {t for t, (_, r) in TENANTS.items() if r}


# --------------------------------------------------------------------------- #
# 1. failover
# --------------------------------------------------------------------------- #
def route_ha(tenant, healthy):
    """Standard HA: nearest healthy region. Correct everywhere except here."""
    home, _ = TENANTS[tenant]
    if home in healthy:
        return home, "home"
    for r in REGIONS:
        if r in healthy:
            return r, "failover"
    return None, "no capacity"


def route_residency(tenant, healthy):
    """Regulated traffic never leaves home. It degrades in place instead."""
    home, regulated = TENANTS[tenant]
    if home in healthy:
        return home, "home"
    if not regulated:
        for r in REGIONS:
            if r in healthy:
                return r, "failover"
        return None, "no capacity"
    return home, "degrade in-region"      # queued, cached, or an honest refusal


# --------------------------------------------------------------------------- #
# 2. the artefacts that are also personal data
# --------------------------------------------------------------------------- #
ARTEFACTS = [
    ("prompt",     "the obvious one - everybody gets this right"),
    ("completion", "also obvious, also usually fine"),
    ("embedding",  "derived from the text, and invertible enough to matter"),
    ("cache entry", "holds the completion, keyed by the prompt"),
    ("trace/log",  "carries prompt and completion as span attributes"),
    ("eval sample", "a snapshot of real customer text, copied into a golden set"),
]

# where each artefact lands in a typical 'we deployed three regions' build
NAIVE_HOME = {"prompt": "home", "completion": "home", "embedding": "global",
              "cache entry": "global", "trace/log": "global", "eval sample": "global"}
FIXED_HOME = {k: "home" for k in NAIVE_HOME}


def leaked(placement):
    return [a for a, _ in ARTEFACTS if placement[a] == "global"]


# --------------------------------------------------------------------------- #
# 3. model parity
# --------------------------------------------------------------------------- #
# same model ID, different rollout state per region - this is the normal case
REGION_MODEL = {"eu-west": ("v2024-03", -4.1),
                "us-east": ("v2024-08", 0.0),
                "ap-south": ("v2024-06", -1.6)}
GATE = 78.0
BASE = 81.0


def eval_score(region):
    _, delta = REGION_MODEL[region]
    noise = sum(random.gauss(0, 1.4) for _ in range(4)) / 4
    return BASE + delta + noise


# --------------------------------------------------------------------------- #
# 4. the CI test
# --------------------------------------------------------------------------- #
DEPLOY_CONFIG = {
    "eu-west": {
        "llm_endpoint":    "https://eu-west.provider.example/v1",
        "vector_store":    "https://vec-eu-west.internal",
        "semantic_cache":  "redis://cache-eu-west.internal",
        "otel_collector":  "https://telemetry.global.example",     # <- the leak
        "eval_bucket":     "s3://evals-eu-west",
    },
    "us-east": {
        "llm_endpoint":    "https://us-east.provider.example/v1",
        "vector_store":    "https://vec-us-east.internal",
        "semantic_cache":  "redis://cache-us-east.internal",
        "otel_collector":  "https://telemetry.global.example",
        "eval_bucket":     "s3://evals-us-east",
    },
}
CARRIES_PERSONAL_DATA = {"llm_endpoint", "vector_store", "semantic_cache",
                         "otel_collector", "eval_bucket"}


def residency_violations(config, regulated_regions=("eu-west",)):
    """Every client a regulated region talks to must name that region."""
    out = []
    for region, clients in config.items():
        if region not in regulated_regions:
            continue
        for key, url in clients.items():
            if key in CARRIES_PERSONAL_DATA and region not in url:
                out.append((region, key, url))
    return out


def main():
    print("\nMULTI-REGION SERVING UNDER DATA RESIDENCY")
    print("=" * 74)
    print(f"{len(TENANTS)} tenants across {len(REGIONS)} regions, "
          f"{len(REGULATED)} of them EU-regulated\n")

    # ---------------------------------------------------------------- 1
    print("1. FAILOVER - the right answer everywhere else")
    healthy = {"us-east", "ap-south"}                 # eu-west provider is down
    print(f"   eu-west provider is down. healthy: {', '.join(sorted(healthy))}")
    reqs = [random.choice(list(TENANTS)) for _ in range(N_REQUESTS)]
    for label, router in (("nearest healthy", route_ha), ("residency-aware", route_residency)):
        breaches = served = degraded = 0
        for t in reqs:
            region, how = router(t, healthy)
            if how == "degrade in-region":
                degraded += 1
            elif region:
                served += 1
                if t in REGULATED and region != TENANTS[t][0]:
                    breaches += 1
        print(f"   {label:<17} served {served:>6,}   degraded in-region {degraded:>6,}   "
              f"CROSS-BORDER {breaches:>5,}")
    ha_breaches = sum(1 for t in reqs
                      if t in REGULATED and route_ha(t, healthy)[1] == "failover")
    rz_breaches = sum(1 for t in reqs
                      if t in REGULATED and route_residency(t, healthy)[1] == "failover")
    assert ha_breaches > 0                 # the failure
    assert rz_breaches == 0                # the fix
    print(f"   -> the HA router did exactly what it was built to do and produced")
    print(f"      {ha_breaches:,} cross-border requests. Availability and residency are in")
    print("      direct conflict; residency wins, so regulated traffic degrades in place.\n")

    # ---------------------------------------------------------------- 2
    print("2. WHAT COUNTS - the artefacts a three-region deploy still leaks")
    print(f"   {'artefact':<14}{'naive':>9}{'fixed':>9}   why it counts")
    for name, why in ARTEFACTS:
        print(f"   {name:<14}{NAIVE_HOME[name]:>9}{FIXED_HOME[name]:>9}   {why}")
    n_leak, f_leak = leaked(NAIVE_HOME), leaked(FIXED_HOME)
    assert len(n_leak) == 4 and not f_leak
    print(f"   -> the naive build routes the PROMPT correctly and still leaks "
          f"{len(n_leak)} artefacts:")
    print(f"      {', '.join(n_leak)}.")
    print("      Every one is derived from customer text, and every one is a default that")
    print("      shipped because it is the sensible choice in a single-region system.\n")

    # ---------------------------------------------------------------- 3
    print("3. MODEL PARITY - one eval suite hides three models")
    print(f"   {'region':<10}{'model version':>16}{'score':>8}{'gate ' + str(GATE):>12}")
    scores = {}
    for r in REGIONS:
        ver, _ = REGION_MODEL[r]
        scores[r] = eval_score(r)
        verdict = "PASS" if scores[r] >= GATE else "FAIL"
        print(f"   {r:<10}{ver:>16}{scores[r]:>8.1f}{verdict:>12}")
    global_score = sum(scores.values()) / len(scores)
    print(f"   {'GLOBAL':<10}{'avg of 3':>16}{global_score:>8.1f}"
          f"{'PASS' if global_score >= GATE else 'FAIL':>12}")
    assert global_score >= GATE            # the false pass
    assert scores["eu-west"] < GATE        # the region that actually fails
    print(f"   -> the aggregate passes at {global_score:.1f} while eu-west sits at "
          f"{scores['eu-west']:.1f}, below the gate.")
    print("      Same model ID, different rollout state. Three regions is three eval")
    print("      surfaces, and averaging them is how you ship a regression to one.\n")

    # ---------------------------------------------------------------- 4
    print("4. THE CI TEST - config, not intent")
    v = residency_violations(DEPLOY_CONFIG)
    for region, key, url in v:
        print(f"   VIOLATION  {region}  {key:<16} -> {url}")
    assert len(v) == 1 and v[0][1] == "otel_collector"
    print(f"   -> {len(v)} violation. Four of the five clients were regionalised; the")
    print("      telemetry collector was not, because observability is configured by a")
    print("      different team and traces do not look like customer data until you read")
    print("      the span attributes. This is a twelve-line test that fails the build.\n")

    fixed = {r: dict(c) for r, c in DEPLOY_CONFIG.items()}
    fixed["eu-west"]["otel_collector"] = "https://telemetry-eu-west.internal"
    assert residency_violations(fixed) == []
    print("   after pinning the collector in-region: 0 violations")
    print("   (aggregate metrics may still cross - counts and latencies, never payloads)\n")

    print("WHAT TO NOTICE")
    print("   * all four failures are correctly implemented best practices. Failover, a")
    print("     shared cache, one eval suite and central logging are RIGHT single-region")
    print("   * the prompt is the artefact everyone protects and the least likely to leak")
    print("   * availability and residency genuinely conflict - you cannot have both, so")
    print("     decide per tenant and write it down")
    print("   * the only durable control is the test, because the config drifts and the")
    print("     team that breaks it will not be the team that read the policy")
    print("\nOK - scenario 17")


if __name__ == "__main__":
    main()
