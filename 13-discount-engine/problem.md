# Problem 13: Discount / Pricing Rules Engine (LLD)

*Not yet worked through — this problem was added for pattern coverage. Do Steps 1-3 yourself before reading the solution.*

## The prompt (as an interviewer would give it)

> "Design the discount engine for a shopping cart. The business keeps inventing offers — 10% off,
> buy-2-get-1, a coupon code, a category sale, a loyalty tier, free shipping over ₹2000 — and they
> want to turn them on and off without a release. Given a cart, tell me what the customer pays."

### The naive version (write it, then run it in your head)

```python
def total(cart, user, coupon):
    t = sum(l.price * l.qty for l in cart.lines)
    if coupon == "FLAT500":  t -= 500
    if user.tier == "GOLD":  t = t * 0.95
    if t > 2000:             shipping = 0
    return round(t, 2)
```

- **"Add a Diwali offer."** → edit this function. Again. Every fortnight.
- **"Why was my order ₹4,702.50?"** → nobody can say; the intermediate steps are gone.
- **"MEGA40 isn't combinable."** → no way to *stop*; every `if` below still runs.
- **"Marketing put FLAT500 before the 20% — ₹100 a cart."** → the order is buried in source.
- **`round(t, 2)` on floats** → the printed breakdown and the charged amount disagree by a paisa.

Every complaint is a requirement in disguise. That is the whole of Step 1.

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **Rule kinds** — which offer types for v1, will new kinds keep arriving, and does any touch the **shipping fee** rather than the goods?
2. **Order & who owns it** — is pipeline order fixed by engineering or edited by the business, and does order change the total?
3. **Stacking** — do discounts combine, or are some **exclusive** ("not to be clubbed with any other offer")?
4. **Cap** — a maximum total discount? Can a cart reach zero, or go below what the goods cost us?
5. **Explainability** — must the customer see which rules fired and what each took off, or is one number enough?
6. **Coupons** — one per cart or several? Redemption limits, and **where** is a limit enforced?
7. **Money precision** — `Decimal` or integer paise? Which way do we round, and who eats the fraction?

---

## Clarifications (locked scope from Q&A)

1. **Kinds (v1):** percentage · flat · buy-X-get-Y-free · coupon · category % · loyalty-tier % · free shipping over a threshold, and **more will keep arriving** → adding one must not touch the engine. Percentage/flat/loyalty come off the **goods** total; free shipping touches only the **shipping** bucket, so a 20%-off never quietly discounts delivery.
2. **Order is configurable by the business and it changes the total.** Accepted, not a bug — but it must be *visible*: order is a column in the rules table, not a line of code. Merchandisers edit daily, no deploy.
3. **Some offers are exclusive.** When an exclusive rule fires, **nothing after it in the pipeline runs.**
4. **Cap: yes.** Max total discount **40% of subtotal**, and never below the **cost floor** (what the goods cost us) — and the cap must hold *even when an exclusive rule halted the pipeline*.
5. **Line-by-line breakdown is a hard requirement** — rule name, the base it was computed on, the amount off.
6. **One coupon per cart.** Redemption limits are enforced **at order placement**, not at quote time — pricing stays a pure function.
7. **`Decimal` everywhere, never `float`.** Discounts quantize 2dp **ROUND_DOWN**, a floor **ROUND_UP**. The total is **derived** from the breakdown, never computed alongside it.

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- **Price a cart** — subtotal, then an **ordered pipeline**; each rule decides **for itself** if it applies and mutates the running total the next rule sees
- Seven kinds: **percentage · flat · buy-X-get-Y · coupon · category % · loyalty % · free shipping** — and more keep arriving
- An **exclusive** rule **halts the pipeline**; a **discount cap** and a **cost floor** must survive that halt
- An **audit trail** — which rules fired, on what base, how much each took off
- **Attach and validate a coupon**; **consume** its redemption at order placement

### Non-functional (constraints — the "-ilities")
- **Extensible, no deploy** — a new kind is one subclass + one registry entry; percent, threshold, category, exclusivity and **order** are data rows (Open/Closed)
- **Explainable** — a support agent answers "why is this Rs. 4,702.50?" from the quote alone
- **Money-correct and safe** — `Decimal`, one rounding policy stated once, `subtotal + shipping - sum(breakdown) == total` **exactly**, and no config however bad may go negative or below cost
- **Pure, so thread-safety is scoped** — pricing shares nothing and needs no lock; **coupon redemption is the only shared mutable state here**

### Explicitly out of scope (say this out loud — it is a senior move)
- Tax / GST · multi-currency · gift cards · ML pricing · A/B testing · inventory · payments

> 📝 Trap (Step 1): the **cap** is the easiest thing here to write down as "just another rule at the end of the list" — and that is the bug. A rule at the end of a chain is skipped by any exclusive rule that halts before it, so the one safeguard that must never be skipped becomes the first one skipped. Decide here: RULE or ENGINE INVARIANT, and why.

> 📝 Trap (Step 1): "show the customer the breakdown" sounds like a UI concern and gets dropped from the requirements. It is functional and it constrains the data model — if the engine returns only a number, no frontend can recover which rules fired. The trail must be produced *while* pricing.

---

## Step 2 — Entities  (nouns → classes)
_Format: `Name — single responsibility — key attributes/methods`_

1. **Enums (DATA)** — `Category` · `LoyaltyTier` · `Bucket` (GOODS/SHIPPING — which pot a discount comes out of)
2. **CartLine · Customer · Cart** — `CartLine(sku, category, unit_price, quantity, cost_price)`; `Cart` + `subtotal()`, `cost_floor()`, `lines_in()` — `cost_price` is what makes a floor possible
3. **PricingContext** (+ **DiscountLine**: `rule_name, description, amount, base, bucket`) — the **accumulating context threaded down the chain** — `applied, halted_by` · `record()`, `total_discount()`, and `goods_total`/`shipping_due`/`grand_total` as **properties**
4. **PricingRule** *(ABC, the chain link)* — `name, exclusive, bucket, _next` · `set_next()`, `applies_to()` and `compute()` *(both abstract)*, `handle()` *(template method, never overridden)*
5. **The six kinds** — `PercentageOffRule` · `FlatOffRule` · `CategoryDiscountRule` · `BuyXGetYFreeRule` · `LoyaltyTierRule` · `FreeShippingRule`. `LoyaltyTierRule` is **one class plus a dict**, not four subclasses
6. **CouponRule** — **wraps another rule**, adding one precondition (`cart.coupon_code == code`) — Decorator, not a seventh piece of arithmetic
7. **DiscountCap** — `max_percent, respect_cost_floor` · `floor_for(ctx)` — the lowest legal goods total. **Deliberately NOT a chain link**
8. **Quote · PricingEngine** — `Quote(subtotal, shipping_fee, discounts, goods_total, shipping_due, total, halted_by)` + `explain()`; the engine owns the chain **and** the cap — `price(cart)`, `rule_names()`
9. **Coupon · CouponRepository · CheckoutService** — the repo is the shared store where the **atomic claim** lives (`get`, `try_consume`, `remaining`); the service holds the only side effects (`attach_coupon`, `place_order`)
10. **RULE_REGISTRY / rule_from_config(row) / build_pipeline(rows)** — the DATA half — plus `PricingError` and its six subtypes: `UnknownCoupon`, `CouponExpired`, `CouponExhausted`, `CouponNotApplicable`, `InvalidRuleConfig`, `ChainLinkReused`

### Why this is Chain of Responsibility and not a list of Strategies

From outside they are identical — an ABC with one method, several implementations, injected from
config. The difference is what the *engine* does with them.

| | Strategy | **Chain of Responsibility** |
|---|---|---|
| How many run | exactly **one**, chosen | **zero to N**, in order |
| Who decides | the **caller** picks | each **handler** decides for itself (`applies_to`) |
| Shared state | none, pure `in -> out` | an **accumulating context** threaded through all of them |
| Can one stop the rest | no | **yes** — and that is the point |
| Does order matter | no | **it is load-bearing** |

**Say this out loud:** `for rule in rules: total -= rule.apply(total)` is CoR in disguise. What makes it
real is the accumulating context plus the ability to **halt** — a strategy loop has neither, so it
cannot express "MEGA40 is not combinable", cannot tell a rule what earlier rules took off, and produces
no trail. Need none of those three? Then it *is* Strategies — say so and stop (**YAGNI**). And the
cousin: `CouponRule` holds a reference to another rule just like a link does, but **CoR passes the
request ALONG to a sibling while Decorator passes it DOWN to what it wraps.**

**Data vs behaviour, both halves live:** kinds differ in **behaviour** (`BuyXGetYFreeRule` does integer
division over line quantities, `FreeShippingRule` empties a different bucket) → one subclass each.
Config (`percent=20`, `threshold=2000`, `exclusive=true`, `order=30`) is **data** edited at 2am → table
rows, `RULE_REGISTRY` the seam. `class Diwali20PercentOffRule` is the failure mode: a *value*
pretending to be a *type*.

> 📝 Trap (Step 2): the tempting split is one class per *offer* (`DiwaliOffer`, `SummerSaleOffer`, `GoldMemberOffer`) — subtyping on data, and how a codebase ends up with 200 rule classes calling the same three lines. Split on the *arithmetic*, parameterise the rest. The other easy miss is the **bucket**: with one shared running total, "20% off" silently discounts delivery and "free shipping over 2000" reads the wrong number.

> 📝 Trap (Step 2): `PricingContext` looks like loose variables and gets left off the entity list, when it is the entity that makes this CoR rather than a loop. If you find yourself passing `(cart, running_total, discounts_so_far, shipping, halted)` as five parameters, you have discovered it the hard way.

---

## Step 3 — Relationships & APIs

```
PricingEngine ──owns the ordered chain──▶ PricingRule(head) ──_next──▶ ... ──▶ None
              ──composition────────────▶ DiscountCap    (an invariant, NOT a link)
PricingRule   ──reads & mutates────────▶ PricingContext ──appends──▶ DiscountLine[]
CouponRule    ──wraps (Decorator)──────▶ PricingRule    (_inner)
CheckoutService ──uses─────────────────▶ PricingEngine, CouponRepository
```

### The chain link, in six lines

```python
def handle(self, ctx):
    fired = False
    if self.applies_to(ctx):                      # 1. do I apply to THIS cart?
        amount, base, desc = self.compute(ctx)    # 2. -> (amount_off, base, description)
        amount = money(amount)                    #    2dp ROUND_DOWN, stated once
        if amount > 0:
            ctx.record(self.name, desc, amount, base, self.bucket)   # 3. mutate the context
            fired = True
    if fired and self.exclusive:
        ctx.halted_by = self.name
        return                                    # 4. successor NEVER called -> chain STOPS
    if self._next is not None:
        self._next.handle(ctx)                    # 5. otherwise pass it along
```

`applies_to` is split from `compute` on purpose: it is the CoR "can I handle this?" question, testable
alone, it answers "why didn't my coupon apply?", and it spares `compute` a `None` return path. `handle`
is a **template method** — subclasses fill the two `@abstractmethod` hooks and never touch chain
mechanics. **Applying but computing 0 is not firing**, so a 0% exclusive offer cannot kill the rest.

### Why order matters — with the actual numbers

Cart subtotal **6,000.00**, two rules: `SEASON20` (20% off) and `FLAT500` (500 off).

```
[SEASON20, FLAT500]   6000.00 -20%-> 4800.00 -500-> 4300.00
[FLAT500, SEASON20]   6000.00 -500-> 5500.00 -20%-> 4400.00
                                                    ------
                                          difference  100.00 per cart
```

A percentage is taken **on the running total**, so whichever runs first sees the larger base. The rules
are not commutative and no testing will make them so. Name both options:

- **Sequential (chosen):** every rule sees what earlier ones did; order becomes a business lever, an `order` column. What real commerce engines do.
- **All against the original subtotal:** order-independent, but two 60% offers now total 120% and the cap does all the work.

### Where the cap goes — and why it is not a rule

```
   chain: r1 -> r2 -> r3(exclusive) -X   r4, r5 never run
                                     |
   engine: _enforce_cap(ctx)  <------+   ALWAYS runs, halt or no halt
```

`floor_for(ctx)` = `max(subtotal x (100 - max_percent) / 100, cart.cost_floor())`. Below that floor the
engine appends **one more audit line with a negative amount** — money handed back — so the trail still
explains the final number. A safety invariant living inside the thing it guards is not an invariant.

### Money — the same family as the Splitwise vanishing paisa

`money()` rounds 2dp **DOWN** so the shop never gives away a paisa it did not compute; `floor_money()`
rounds **UP** or the cap leaks — **direction chosen by which way the error is safe.** 10% off
`33.33 / 33.33 / 33.35` is where the paisa vanishes:

```
per line, ROUND_DOWN:   3.33 + 3.33 + 3.33 =  9.99
on the total:                    10.001    -> 10.00      they differ by 0.01
```

Neither is wrong; doing **both** is. Fix: compute money once, at one granularity, and DERIVE the rest.
`total = subtotal + shipping - sum(audit lines)`, computed nowhere else, so the breakdown cannot
disagree with the total — it *is* the total.

### Concurrency — scoped, and where the TOCTOU actually is

Pricing is pure: a cart in, a `Quote` out, no locks. The race is one method away.

```python
# check-then-act (TOCTOU) — two checkouts, one redemption left, both succeed
if coupon.redeemed < coupon.max_redemptions:   # both threads read 999
    coupon.redeemed += 1                       # both write 1000
```

Same shape as the URL shortener's duplicate code and the movie-booking double-sold seat. **Fix: push
atomicity into the shared store** — `try_consume(code)` tests and increments as one step, returning a
bool; in Postgres, `UPDATE ... SET redeemed = redeemed + 1 WHERE code = ? AND redeemed < limit` checked
by row count. And **a quote is a preview, not a reservation**, so redemption happens at `place_order`.

> 📝 Trap (Step 3): halting is the reason this is a chain, and it is easy to implement as a flag the engine loop checks (`if ctx.halted: break`). That hands chain control back to the engine. In real CoR the handler halts by **not calling its successor** — the ability to stop lives in the link, which is what makes each rule autonomous.

> 📝 Trap (Step 3): an exclusive rule halts *everything* after it, including rules nobody thinks of as offers — put `FreeShippingRule` after an exclusive coupon and the customer loses free shipping as a side effect of using one. Also: a rule holds `_next`, so it belongs to exactly ONE chain; reusing one silently rewires the first.

---

## REST API mapping  (LLD method -> HLD endpoint)

| LLD method | HTTP |
|---|---|
| `price(cart)` | `POST /api/v1/carts/{id}/quote` -> **200** `{subtotal, shipping, discounts[], total, halted_by}` · **404**. A POST though it reads nothing: the result is per-customer and time-varying, so not cacheable. `explain()` gets no endpoint — `discounts[]` **is** the trail |
| `attach_coupon(cart, code)` | `POST /api/v1/carts/{id}/coupon` -> **200** re-quoted · **404** unknown · **410** expired · **409** fully redeemed · **422** valid but does not apply to this cart |
| `place_order(cart)` | `POST /api/v1/orders` with an **`Idempotency-Key`** -> **201** · **409** lost the redemption race · **422** price changed since the quote. `try_consume()` gets no endpoint — it runs inside this one, in the order's transaction |
| `rule_from_config(row)` | `POST /api/v1/admin/pricing-rules` -> **201** · **400** unknown kind. `PATCH .../{id}` `{order: 30}` -> **200**: **reordering the pipeline is a column update, not a deploy** |

> **Five status codes, five exception types** — 404 / 410 / 409 / 422 / 400, in that order. That is why
> the repo raises specific exceptions instead of returning `None`: a `None` at the domain layer becomes
> a 500, or worse, a lie at the API layer. And **re-price server-side at order placement** — never trust
> a client total; the customer may have sat on the page while a sale ended. Which is why pricing being
> **pure and deterministic** was an NFR.

## Notes / decisions (log the "why" here)
- **CoR, not a list of Strategies** — justified by three pains: exclusivity (a rule must stop the rest), accumulation (a rule must see what earlier rules did), and the audit trail. Without all three, YAGNI says a `for` loop is right and you should say so.
- **`handle()` is a template method; `applies_to`/`compute` are the abstract hooks** — chain mechanics exist once, so a new kind cannot get the halting semantics wrong.
- **The cap is an ENGINE INVARIANT, not a chain link** — a link is skippable by an exclusive rule, and a safety floor must not be.
- **The total is DERIVED from the audit trail**, never computed in parallel — Splitwise's derive-don't-store move applied to money. One rounding policy in one function, direction chosen by which way the error is safe.
- **Two buckets, GOODS and SHIPPING**, so a percentage cannot leak onto delivery and a free-shipping threshold reads the right number.
- **Kinds are polymorphism; config is table rows.** `RULE_REGISTRY` is the seam; `LoyaltyTierRule` proves the data half — four tiers are a `dict`, not four subclasses. `CouponRule` wraps rather than duplicating arithmetic.
- **A rule object belongs to one chain** — `set_next` raises `ChainLinkReusedError` rather than silently rewiring a live engine.
- **Pricing is pure, so no locks.** The only shared mutable state is the redemption counter, and `try_consume` is an atomic claim inside the store — the same fix as `save_if_absent` (URL shortener) and the seat claim (movie booking).
