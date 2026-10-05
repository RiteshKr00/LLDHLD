"""
Scenario 18 - hybrid self-hosted GPU + API inference: finding the crossover.

    python3 solution.py

Four mechanics, each with the failure shown happening FIRST, then the fix:
  1. "cheaper per token" vs the monthly bill, which is what you actually pay
  2. utilisation: the same GPU at 20% costs more per token than the API
  3. continuous batching, and why naive serving wastes most of the card
  4. task placement plus API overflow, and the ops cost nobody budgets

Prices are illustrative but the shape is real. Seeded where random is used.

What to notice: nothing here says self-hosting is cheaper or dearer. It is
cheaper ABOVE A THRESHOLD, and the whole skill is naming the threshold, the
utilisation you can actually sustain, and the salary line.
"""
import random

random.seed(18)

GPU_HOURLY = 2.00                # A100-class, on-demand
HOURS = 730
GPU_MONTHLY = GPU_HOURLY * HOURS         # ~£1,460, paid whether you use it or not
API_PER_1K = 0.0009              # a small/fast API model, per 1k tokens
GPU_TOKENS_PER_S = 2_400         # 7B, continuous batching, healthy concurrency
OPS_MONTHLY = 1_800              # the fraction of an engineer this actually takes


def gpu_capacity_tokens(util):
    """Tokens a single card can actually serve in a month at a given utilisation."""
    return GPU_TOKENS_PER_S * 3600 * HOURS * util


def gpu_cost_per_1k(util, gpus=1, include_ops=True):
    served = gpu_capacity_tokens(util) * gpus
    if served == 0:
        return float("inf")
    monthly = GPU_MONTHLY * gpus + (OPS_MONTHLY if include_ops else 0)
    return monthly / (served / 1000)


def api_cost(tokens):
    return tokens / 1000 * API_PER_1K


def breakeven_tokens(util, gpus=1, include_ops=True):
    """Monthly tokens at which the GPU bill equals the API bill."""
    monthly = GPU_MONTHLY * gpus + (OPS_MONTHLY if include_ops else 0)
    return monthly / API_PER_1K * 1000


# --------------------------------------------------------------------------- #
# 3. batching
# --------------------------------------------------------------------------- #
def naive_throughput(concurrency, batch_window=8):
    """Static batching: wait for a full batch or a timeout, then run it."""
    filled = min(concurrency, batch_window)
    return GPU_TOKENS_PER_S * (filled / batch_window)


def continuous_throughput(concurrency, batch_window=8):
    """Continuous batching: slots refill as sequences finish."""
    return GPU_TOKENS_PER_S * min(1.0, 0.35 + 0.65 * min(concurrency, batch_window) / batch_window)


# --------------------------------------------------------------------------- #
# 4. task placement
# --------------------------------------------------------------------------- #
#  task              monthly tokens   needs frontier?  latency-critical?
TASKS = [("classify support tickets", 14_000_000_000, False, False),
         ("summarise call transcripts", 6_200_000_000, False, False),
         ("extract fields from PDFs",   3_100_000_000, False, False),
         ("draft customer replies",       900_000_000, True,  True),
         ("final answer synthesis",       400_000_000, True,  True),
         ("rerank search results",        260_000_000, False, True)]


def place(task, util):
    name, tokens, frontier, latency = task
    if frontier:
        return "API", "needs frontier quality"
    if tokens < breakeven_tokens(util):
        return "API", "below crossover"
    return "self-hosted", "above crossover"


def main():
    print("\nHYBRID SELF-HOSTED GPU + API INFERENCE")
    print("=" * 76)
    print(f"GPU £{GPU_HOURLY:.2f}/hr -> £{GPU_MONTHLY:,.0f}/month FIXED, "
          f"plus £{OPS_MONTHLY:,} ops")
    print(f"API £{API_PER_1K:.4f}/1k tokens, billed only on use\n")

    # ---------------------------------------------------------------- 1
    print("1. 'CHEAPER PER TOKEN' - true, and the wrong question")
    util = 0.70
    print(f"   at {util:.0%} utilisation, GPU costs £{gpu_cost_per_1k(util, include_ops=False):.5f}/1k "
          f"vs API £{API_PER_1K:.4f}/1k  -> GPU looks "
          f"{API_PER_1K / gpu_cost_per_1k(util, include_ops=False):.0f}x cheaper")
    print()
    print(f"   {'monthly tokens':>16}{'API bill':>12}{'GPU bill':>12}{'winner':>14}")
    be = breakeven_tokens(util)
    for tokens in (500_000_000, 2_000_000_000, 6_000_000_000, 20_000_000_000):
        a = api_cost(tokens)
        gpus = max(1, -(-int(tokens) // int(gpu_capacity_tokens(util))))
        g = GPU_MONTHLY * gpus + OPS_MONTHLY
        print(f"   {tokens:>16,}{a:>11,.0f} {g:>11,.0f} "
              f"{('self-hosted' if g < a else 'API'):>14}")
    print(f"   -> break-even is {be / 1e6:,.0f}M tokens/month INCLUDING ops.")
    assert api_cost(500_000_000) < GPU_MONTHLY + OPS_MONTHLY        # small task loses
    assert api_cost(20_000_000_000) > GPU_MONTHLY * 5 + OPS_MONTHLY  # large task wins
    print("      Below it you are swapping a variable cost for a fixed one and losing.")
    print("      Per-token price is a ratio; the bill is a product. Only one arrives.\n")

    # ---------------------------------------------------------------- 2
    print("2. UTILISATION - the same card, the same month, different answers")
    print(f"   {'utilisation':>12}{'tokens served':>18}{'£/1k tokens':>14}{'vs API':>12}")
    for u in (0.05, 0.20, 0.40, 0.70, 0.95):
        c = gpu_cost_per_1k(u)
        print(f"   {u:>11.0%}{gpu_capacity_tokens(u):>18,.0f}{c:>14.5f}"
              f"{('DEARER' if c > API_PER_1K else 'cheaper'):>12}")
    assert gpu_cost_per_1k(0.05) > API_PER_1K       # the failure
    assert gpu_cost_per_1k(0.70) < API_PER_1K       # the fix
    print("   -> a 5%-utilised GPU is more expensive than the API it replaced. Utilisation")
    print("      is not an optimisation here, it is the entire business case, and it is")
    print("      set by the SHAPE of your traffic rather than its total.\n")

    # ---------------------------------------------------------------- 3
    print("3. BATCHING - where the utilisation actually comes from")
    print(f"   {'concurrent reqs':>16}{'static batch':>15}{'continuous':>13}{'gain':>8}")
    for c in (1, 2, 4, 8, 16):
        n, cb = naive_throughput(c), continuous_throughput(c)
        print(f"   {c:>16}{n:>13,.0f}/s{cb:>11,.0f}/s{cb / n:>7.1f}x")
    assert naive_throughput(1) < continuous_throughput(1) / 2
    print("   -> static batching idles the card waiting for a batch to fill. At low")
    print("      concurrency it wastes most of what you are paying for, which is exactly")
    print("      the regime a first self-hosting attempt runs in.\n")

    # ---------------------------------------------------------------- 4
    print("4. PLACEMENT - per task, not per platform")
    print(f"   {'task':<28}{'tokens/mo':>16}{'placement':>14}   reason")
    self_tokens = api_tokens = 0
    for t in TASKS:
        where, why = place(t, util)
        if where == "self-hosted":
            self_tokens += t[1]
        else:
            api_tokens += t[1]
        print(f"   {t[0]:<28}{t[1]:>16,}{where:>14}   {why}")

    gpus = max(1, -(-self_tokens // int(gpu_capacity_tokens(util))))
    all_api = api_cost(self_tokens + api_tokens)
    hybrid = GPU_MONTHLY * gpus + OPS_MONTHLY + api_cost(api_tokens)
    print(f"\n   all-API monthly            £{all_api:>10,.0f}")
    print(f"   hybrid ({gpus} GPU + API)      £{hybrid:>10,.0f}   "
          f"saving {1 - hybrid / all_api:.0%}")
    naive = GPU_MONTHLY * gpus + api_cost(api_tokens)
    print(f"   the version in the deck    £{naive:>10,.0f}   "
          f"saving {1 - naive / all_api:.0%}  (ops omitted)")
    assert hybrid < all_api and naive < hybrid
    print(f"   -> the £{OPS_MONTHLY:,} ops line moves the headline saving by "
          f"{(hybrid - naive) / all_api:.0%}. Not a rounding")
    print("      error, and the line most likely to be missing from the business case.\n")

    print("WHAT TO NOTICE")
    print("   * per-token price is a ratio, the bill is a product - a task can be 3x")
    print("     cheaper per token and still cost four times as much per month")
    print("   * the crossover is PER TASK, so the answer is a routing table, not a verdict")
    print("   * frontier-quality tasks are not candidates at any volume; naming them first")
    print("     keeps the conversation honest")
    print("   * utilisation is set by traffic shape, and batch work is what fills a trough")
    print("\nOK - scenario 18")


if __name__ == "__main__":
    main()
