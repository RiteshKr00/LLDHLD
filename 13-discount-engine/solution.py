"""
Discount / Pricing Rules Engine - LLD solution.

THE PATTERN: Chain of Responsibility. An ordered chain of rules; each link
decides FOR ITSELF whether it applies, sees a RUNNING TOTAL earlier links have
already reduced, and may STOP the chain (an offer that is not combinable).

NOT just a list of Strategies. Strategy: exactly ONE runs, the CALLER picks, no
shared state, order is irrelevant. CoR: ZERO..N run, each HANDLER decides, an
ACCUMULATING context, and ORDER IS LOAD-BEARING. If you need neither the
accumulating context nor the halt, you have a list of Strategies - say so. YAGNI.

DATA vs BEHAVIOUR, both halves live here. Rule KINDS differ in ARITHMETIC ->
subclasses. Rule CONFIG (percent, threshold, exclusive, ORDER) is a TABLE a
merchandiser edits with no deploy -> RULE_REGISTRY + rule_from_config().

MONEY: Decimal only, one rounding policy stated once, and the total is DERIVED
from the audit trail - so the breakdown cannot disagree with the charge.

SAFETY: DiscountCap is an ENGINE INVARIANT, not a chain link, because a link is
skipped by any exclusive rule that halts before it.

CONCURRENCY: pricing is pure, no locks. The one shared mutable thing is the
coupon counter - a check-then-act (TOCTOU), fixed by an atomic try_consume().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from enum import Enum
from typing import Callable, Optional
import threading


# HINT (to rebuild) - the rounding policy, stated ONCE: one quantizer for a
#   DISCOUNT, one for a FLOOR, plus a display helper.
#   ** the two round in OPPOSITE directions on purpose. Direction is chosen by
#      which way the error is SAFE, never by habit: a discount rounded up gives
#      money away, a floor rounded down leaks past the cap.

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")


def money(amount: Decimal) -> Decimal:
    """Quantize a DISCOUNT. 2dp, ROUND_DOWN - never round a giveaway up."""
    return amount.quantize(TWO_PLACES, rounding=ROUND_DOWN)


def floor_money(amount: Decimal) -> Decimal:
    """Quantize a FLOOR. 2dp, ROUND_UP - never let a safety floor sag."""
    return amount.quantize(TWO_PLACES, rounding=ROUND_UP)


def rs(amount: Decimal) -> str:
    return f"Rs. {amount:>10,.2f}"


# HINT (to rebuild) - specific types, never `return None` on failure, because
# each error TYPE becomes an HTTP STATUS CODE at the API layer:
#     UnknownCouponError 404 | CouponExpiredError 410 | CouponExhaustedError 409
#     CouponNotApplicableError 422 | InvalidRuleConfigError 400
#     ChainLinkReusedError -> a programming error, never an HTTP code

class PricingError(Exception):
    """Base for every pricing failure."""


class UnknownCouponError(PricingError):
    pass


class CouponExpiredError(PricingError):
    pass


class CouponExhaustedError(PricingError):
    pass


class CouponNotApplicableError(PricingError):
    pass


class InvalidRuleConfigError(PricingError):
    pass


class ChainLinkReusedError(PricingError):
    pass


# HINT (to rebuild) - three plain enums: Category, LoyaltyTier, Bucket.
#   ** Bucket is the one people forget. One shared running total means "20% off"
#      quietly discounts delivery and "free shipping over 2000" tests the wrong
#      number. Two pots; every audit line says which pot it came out of.

class Category(Enum):
    APPAREL = "APPAREL"
    FOOTWEAR = "FOOTWEAR"
    ACCESSORIES = "ACCESSORIES"


class LoyaltyTier(Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class Bucket(Enum):
    GOODS = "GOODS"
    SHIPPING = "SHIPPING"


# HINT (to rebuild) - a frozen CartLine (priced AND costed), a frozen Customer
#   carrying a tier, and a mutable Cart that can total itself.
#   ** `lines` needs field(default_factory=list) - a bare `= []` is shared by
#      every Cart ever constructed. Recurring bug; do not skip it.
#   ** the COST side is DATA the merchandiser cannot override: it is what stops
#      the cart being discounted below what the goods cost us.

@dataclass(frozen=True)
class CartLine:
    sku: str
    name: str
    category: Category
    unit_price: Decimal
    quantity: int
    cost_price: Decimal = ZERO

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def cost(self) -> Decimal:
        return self.cost_price * self.quantity


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    tier: LoyaltyTier = LoyaltyTier.NONE


@dataclass
class Cart:
    cart_id: str
    customer: Customer
    lines: list[CartLine] = field(default_factory=list)
    coupon_code: Optional[str] = None
    shipping_fee: Decimal = ZERO

    def subtotal(self) -> Decimal:
        return sum((line.subtotal for line in self.lines), ZERO)

    def cost_floor(self) -> Decimal:
        """What the goods cost us. The cart may never be priced below this."""
        return sum((line.cost for line in self.lines), ZERO)

    def lines_in(self, category: Category) -> list[CartLine]:
        return [line for line in self.lines if line.category is category]


# HINT (to rebuild) - ONE entry of the audit trail: which rule, on what base,
#   how much, out of which bucket.
#   ** `base` makes the trail auditable rather than decorative: "took off 247.50"
#      is unverifiable, "5% of 4,950.00 = 247.50" is checkable.
#   ** amount is POSITIVE for money off; only the cap records a NEGATIVE one.

@dataclass(frozen=True)
class DiscountLine:
    rule_name: str
    description: str
    amount: Decimal
    base: Decimal
    bucket: Bucket = Bucket.GOODS


# HINT (to rebuild) - THE ACCUMULATING CONTEXT, the thing that makes this CoR
#   and not a list of Strategies. It holds the cart, the applied DiscountLines
#   and who halted; every running total is a PROPERTY over that list, per bucket.
#   ** DERIVE, DO NOT STORE. A `running_total` field kept beside the audit list
#      drifts from it by a paisa, and the breakdown stops matching the charge.

class PricingContext:
    """State threaded down the chain. Rules mutate it; nobody else does."""

    def __init__(self, cart: Cart):
        self.cart = cart
        self.subtotal: Decimal = cart.subtotal()
        self.shipping_fee: Decimal = cart.shipping_fee
        self.applied: list[DiscountLine] = []
        self.halted_by: Optional[str] = None

    def _taken(self, bucket: Bucket) -> Decimal:
        return sum((d.amount for d in self.applied if d.bucket is bucket), ZERO)

    @property
    def goods_total(self) -> Decimal:
        return self.subtotal - self._taken(Bucket.GOODS)

    @property
    def shipping_due(self) -> Decimal:
        return self.shipping_fee - self._taken(Bucket.SHIPPING)

    @property
    def grand_total(self) -> Decimal:
        return self.goods_total + self.shipping_due

    def record(self, rule_name: str, description: str, amount: Decimal,
               base: Decimal, bucket: Bucket = Bucket.GOODS) -> None:
        self.applied.append(DiscountLine(rule_name, description, amount, base, bucket))


# HINT (to rebuild) - THE CHAIN LINK. It knows its successor and splits the work
#   into TWO @abstractmethod hooks - "can I handle this?" and "how much?" - under
#   one concrete template method, so chain mechanics live in exactly one place.
#   ** the HALT is a link declining to call its successor. No engine-side
#      `if halted: break`; the ability to stop lives in the LINK.
#   ** "applies but computes 0" must NOT count as firing, or a misconfigured 0%
#      exclusive offer silently kills every offer after it.
#   ** @abstractmethod on BOTH hooks, or the ABC instantiates and fails half way
#      down a live pricing chain instead of at construction.

class PricingRule(ABC):
    """One link of the chain."""

    bucket: Bucket = Bucket.GOODS

    def __init__(self, name: str, exclusive: bool = False):
        self.name = name
        self.exclusive = exclusive
        self._next: Optional["PricingRule"] = None
        self._linked = False

    def claim(self) -> None:
        """A rule instance belongs to exactly ONE chain - rewiring a live engine
        is a bug that only shows up once a second pipeline exists."""
        if self._linked:
            raise ChainLinkReusedError(f"{self.name!r} is already in a chain")
        self._linked = True

    def set_next(self, rule: "PricingRule") -> "PricingRule":
        rule.claim()
        self._next = rule
        return rule

    @abstractmethod
    def applies_to(self, ctx: PricingContext) -> bool:
        """Can I handle this cart, in its CURRENT state? Split out from compute()
        so it is testable alone, can answer "why didn't my coupon apply?", and
        leaves compute() with no None return path."""

    @abstractmethod
    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        """(amount_off, base_it_was_computed_on, description)."""

    def handle(self, ctx: PricingContext) -> None:
        """The template method. Subclasses never override it."""
        fired = False
        if self.applies_to(ctx):
            amount, base, description = self.compute(ctx)
            amount = money(amount)
            if amount > ZERO:                     # applying but taking 0 is NOT firing
                ctx.record(self.name, description, amount, base, self.bucket)
                fired = True
        if fired and self.exclusive:
            ctx.halted_by = self.name
            return                                # <-- the successor NEVER runs
        if self._next is not None:
            self._next.handle(ctx)


# HINT (to rebuild) - six BEHAVIOURS: percent off, flat off, category percent,
#   buy-X-get-Y, loyalty tier, free shipping. Each is a DIFFERENT SHAPE of
#   arithmetic - one walks line quantities, one multiplies a single number, one
#   never touches the goods total - which is why they are subclasses, not rows.
#   ** each percentage takes its base from the RUNNING total, so it sees what
#      earlier links took off. That is what makes order load-bearing.
#   ** clamp every amount to what is left, and keep the loyalty tiers in a DICT:
#      four tiers differing only by a number are data, not four classes.

class PercentageOffRule(PricingRule):
    """N% off the goods RUNNING total - so it sees what earlier rules did."""

    def __init__(self, name: str, percent: Decimal, exclusive: bool = False):
        super().__init__(name, exclusive)
        self.percent = percent

    def applies_to(self, ctx: PricingContext) -> bool:
        return ctx.goods_total > ZERO and self.percent > ZERO

    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        base = ctx.goods_total
        return base * self.percent / Decimal(100), base, f"{self.percent}% off cart"


class FlatOffRule(PricingRule):
    """A fixed amount off, clamped so one rule cannot drive the cart negative."""

    def __init__(self, name: str, amount: Decimal, exclusive: bool = False):
        super().__init__(name, exclusive)
        self.amount = amount

    def applies_to(self, ctx: PricingContext) -> bool:
        return ctx.goods_total > ZERO

    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        base = ctx.goods_total
        return min(self.amount, base), base, f"flat {self.amount} off"


class CategoryDiscountRule(PricingRule):
    """N% off ONE category, on that category's ORIGINAL line subtotals - a product
    decision, so two overlapping category rules can exceed the line value and the
    engine cap is the backstop."""

    def __init__(self, name: str, category: Category, percent: Decimal,
                 exclusive: bool = False):
        super().__init__(name, exclusive)
        self.category = category
        self.percent = percent

    def applies_to(self, ctx: PricingContext) -> bool:
        return bool(ctx.cart.lines_in(self.category)) and ctx.goods_total > ZERO

    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        base = sum((ln.subtotal for ln in ctx.cart.lines_in(self.category)), ZERO)
        return (min(base * self.percent / Decimal(100), ctx.goods_total), base,
                f"{self.percent}% off {self.category.value}")


class BuyXGetYFreeRule(PricingRule):
    """Per SKU: every group of (buy + free) units makes `free` of them free.
    Inherently ITEM level, so it belongs early - before the order-level rules."""

    def __init__(self, name: str, buy: int, free: int,
                 category: Optional[Category] = None, exclusive: bool = False):
        super().__init__(name, exclusive)
        if buy < 1 or free < 1:
            raise InvalidRuleConfigError("buy and free must both be >= 1")
        self.buy = buy
        self.free = free
        self.category = category

    def _qualifying(self, ctx: PricingContext) -> list[CartLine]:
        lines = (ctx.cart.lines if self.category is None
                 else ctx.cart.lines_in(self.category))
        return [ln for ln in lines if ln.quantity >= self.buy + self.free]

    def applies_to(self, ctx: PricingContext) -> bool:
        return bool(self._qualifying(ctx))

    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        group, amount, base, units = self.buy + self.free, ZERO, ZERO, 0
        for ln in self._qualifying(ctx):
            gratis = (ln.quantity // group) * self.free
            units += gratis
            amount += ln.unit_price * gratis
            base += ln.subtotal
        return (min(amount, ctx.goods_total), base,
                f"buy {self.buy} get {self.free}: {units} free unit(s)")


class LoyaltyTierRule(PricingRule):
    """Percent by tier. ONE class + a dict - the tiers differ only by a NUMBER."""

    def __init__(self, name: str,
                 percent_by_tier: Optional[dict[LoyaltyTier, Decimal]] = None,
                 exclusive: bool = False):
        super().__init__(name, exclusive)
        self.percent_by_tier: dict[LoyaltyTier, Decimal] = dict(percent_by_tier or {})

    def _percent(self, ctx: PricingContext) -> Decimal:
        return self.percent_by_tier.get(ctx.cart.customer.tier, ZERO)

    def applies_to(self, ctx: PricingContext) -> bool:
        return self._percent(ctx) > ZERO and ctx.goods_total > ZERO

    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        percent = self._percent(ctx)
        base = ctx.goods_total
        tier = ctx.cart.customer.tier.value
        return base * percent / Decimal(100), base, f"{tier} tier {percent}%"


class FreeShippingRule(PricingRule):
    """Waives the SHIPPING bucket. Note it never touches the goods total."""

    bucket = Bucket.SHIPPING

    def __init__(self, name: str, threshold: Decimal, exclusive: bool = False):
        super().__init__(name, exclusive)
        self.threshold = threshold

    def applies_to(self, ctx: PricingContext) -> bool:
        return ctx.shipping_due > ZERO and ctx.goods_total >= self.threshold

    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        # base is the SHIPPING pot, not the goods total: a base must be something
        # the amount can be re-derived FROM. The goods threshold is a
        # precondition, so it belongs in the description instead.
        return (ctx.shipping_due, ctx.shipping_due,
                f"free shipping (goods over {self.threshold})")


# HINT (to rebuild) - a coupon is a DECORATOR, not a seventh arithmetic: it wraps
#   a rule, adds ONE precondition, and delegates bucket and maths to the wrapped.
#   ** CoR vs Decorator, both references live in this one class:
#        _next  -> pass the request ALONG to a SIBLING   (CoR)
#        _inner -> pass it DOWN to what you WRAP         (Decorator)
#      Same shape, opposite intent. An interviewer who sees both WILL ask.

class CouponRule(PricingRule):
    """Adds ONE precondition (the right code is on the cart) to another rule."""

    def __init__(self, code: str, inner: PricingRule, exclusive: bool = False):
        super().__init__(f"COUPON:{code}", exclusive)
        self.code = code
        self._inner = inner

    @property                      # type: ignore[override]
    def bucket(self) -> Bucket:    # delegate - a shipping coupon is possible
        return self._inner.bucket

    def applies_to(self, ctx: PricingContext) -> bool:
        return ctx.cart.coupon_code == self.code and self._inner.applies_to(ctx)

    def compute(self, ctx: PricingContext) -> tuple[Decimal, Decimal, str]:
        amount, base, description = self._inner.compute(ctx)
        return amount, base, f"coupon {self.code}: {description}"


# HINT (to rebuild) - the ENGINE INVARIANT, deliberately NOT a chain link. The
#   LOWEST LEGAL goods total, from TWO floors - a percent of subtotal, and what
#   the goods cost us - with the tighter one winning.
#   ** as the last LINK, any exclusive rule halting earlier would skip it: the
#      one safeguard that must never be skipped becomes the first one skipped.

@dataclass(frozen=True)
class DiscountCap:
    max_percent: Decimal = Decimal("40")
    respect_cost_floor: bool = True

    def floor_for(self, ctx: PricingContext) -> tuple[Decimal, str]:
        """The lowest legal goods total, and which of the two floors set it."""
        # ROUND_UP: rounding a floor DOWN would let the cap leak a paisa.
        by_percent = floor_money(
            ctx.subtotal * (Decimal(100) - self.max_percent) / Decimal(100))
        by_cost = ctx.cart.cost_floor() if self.respect_cost_floor else ZERO
        if by_cost > by_percent:
            return by_cost, f"cost floor {by_cost}"
        return by_percent, f"max {self.max_percent}% of subtotal"


# HINT (to rebuild) - the immutable RESULT: the starting numbers, the audit
#   lines, the bucket totals, the charge, who halted - plus an explain() that
#   renders one printable row per audit line.
#   ** THE MONEY INVARIANT, holding by CONSTRUCTION not by luck:
#         subtotal + shipping_fee - total_discount() == total
#      `total` is DERIVED from the audit lines and computed nowhere else, so the
#      breakdown cannot disagree with the charge: it IS the charge.

@dataclass(frozen=True)
class Quote:
    cart_id: str
    subtotal: Decimal
    shipping_fee: Decimal
    discounts: list[DiscountLine]
    goods_total: Decimal
    shipping_due: Decimal
    total: Decimal
    halted_by: Optional[str] = None

    def total_discount(self) -> Decimal:
        return sum((d.amount for d in self.discounts), ZERO)

    def explain(self) -> list[str]:
        def row(label: str, note: str, cash: str) -> str:
            return f"  {label:<16} {note[:50]:<50} {cash:>18}"

        out = [row("SUBTOTAL", "", rs(self.subtotal)),
               row("SHIPPING", "", rs(self.shipping_fee))]
        for d in self.discounts:
            tag = "" if d.bucket is Bucket.GOODS else " [shipping]"
            sign = "+" if d.amount < ZERO else "-"   # '+' = the cap handing back
            out.append(row(d.rule_name, f"{d.description} (on {d.base:,.2f}{tag})",
                           f"{sign} {rs(abs(d.amount))}"))
        if self.halted_by:
            out.append(row("** HALTED", f"by {self.halted_by} - not combinable", ""))
        out.append(row("TOTAL", "", rs(self.total)))
        return out


# HINT (to rebuild) - owns the ordered chain AND the cap. Construction links the
#   rules head to tail; pricing calls handle() on the HEAD once, enforces the cap
#   ALWAYS - halt or no halt - and freezes the result into a Quote.
#   ** price() is PURE: reads a cart, returns a Quote, mutates nothing shared.
#      That is why there is not a single lock in this class.
#   ** the cap records a NEGATIVE audit line, so a capped cart still explains
#      itself line by line and the trail still sums to the charge.

class PricingEngine:
    """Runs the chain, then enforces the invariant the chain cannot be trusted with."""

    def __init__(self, rules: list[PricingRule], cap: Optional[DiscountCap] = None):
        self._rules = list(rules)
        self._cap = cap if cap is not None else DiscountCap()
        for rule in self._rules[:1]:
            rule.claim()
        for current, following in zip(self._rules, self._rules[1:]):
            current.set_next(following)

    def rule_names(self) -> list[str]:
        return [r.name for r in self._rules]

    def price(self, cart: Cart) -> Quote:
        ctx = PricingContext(cart)
        if self._rules:
            self._rules[0].handle(ctx)          # the WHOLE chain, from one call
        self._enforce_cap(ctx)
        return Quote(cart.cart_id, ctx.subtotal, ctx.shipping_fee,
                     list(ctx.applied), ctx.goods_total, ctx.shipping_due,
                     ctx.grand_total, ctx.halted_by)

    def _enforce_cap(self, ctx: PricingContext) -> None:
        """Runs whether or not a rule halted the chain. That is the whole point."""
        floor, reason = self._cap.floor_for(ctx)
        if ctx.goods_total < floor:
            # both sides are already 2dp, so the give-back needs no rounding
            ctx.record("DISCOUNT_CAP", f"capped: {reason}",
                       ctx.goods_total - floor, ctx.subtotal)


# HINT (to rebuild) - the shared store, and the ONE place a race exists. A Coupon
#   counts redemptions; the repository holds them behind ONE lock and exposes an
#   ATOMIC CLAIM that tests AND increments as one indivisible step.
#   ** THE BUG IT AVOIDS (check-then-act / TOCTOU):
#         if coupon.redeemed < coupon.max_redemptions:   # both threads read 999
#             coupon.redeemed += 1                       # both write 1000
#      FIX: push atomicity into the store. In Postgres, one
#      UPDATE ... WHERE redeemed < max_redemptions, checked by row count.
#   ** the claim returns a BOOL, not an exception: losing a race is expected, not
#      an error. The CALLER turns it into a 409.

@dataclass
class Coupon:
    code: str
    max_redemptions: int
    redeemed: int = 0
    active: bool = True

    @property
    def remaining(self) -> int:
        return max(0, self.max_redemptions - self.redeemed)


class CouponRepository:
    """The shared store. Nothing else in this file holds mutable shared state."""

    def __init__(self, coupons: Optional[list[Coupon]] = None):
        self._coupons: dict[str, Coupon] = {c.code: c for c in (coupons or [])}
        self._lock = threading.Lock()

    def get(self, code: str) -> Coupon:
        # DELIBERATELY LOCK-FREE: its callers hold self._lock already, and
        # threading.Lock is NOT reentrant, so a `with` here would deadlock on the
        # second acquire. Rule: the lock is taken at exactly ONE depth.
        coupon = self._coupons.get(code)
        if coupon is None:
            raise UnknownCouponError(f"no such coupon: {code!r}")
        return coupon

    def try_consume(self, code: str) -> bool:
        """Atomic claim: test AND increment as one indivisible step."""
        with self._lock:
            coupon = self.get(code)
            if not coupon.active or coupon.redeemed >= coupon.max_redemptions:
                return False
            coupon.redeemed += 1
            return True


# HINT (to rebuild) - the only side effects in the file. Attaching a coupon
#   validates it (a distinct error TYPE per failure), prices the cart, then READS
#   THE AUDIT TRAIL to see whether the coupon fired, reverting if not. Placing an
#   order re-prices SERVER SIDE and claims the redemption.
#   ** explainability paid for itself: the trail is not only for the customer.
#   ** THE QUOTE IS A PREVIEW, NOT A RESERVATION - consuming the redemption only
#      at order time is what keeps the engine lock-free.

class CheckoutService:
    def __init__(self, engine: PricingEngine, coupons: CouponRepository):
        self._engine = engine
        self._coupons = coupons

    def attach_coupon(self, cart: Cart, code: str) -> Quote:
        coupon = self._coupons.get(code)                  # raises UnknownCouponError
        if not coupon.active:
            raise CouponExpiredError(f"coupon {code!r} is no longer active")
        if coupon.remaining <= 0:
            raise CouponExhaustedError(f"coupon {code!r} is fully redeemed")

        previous, cart.coupon_code = cart.coupon_code, code
        quote = self._engine.price(cart)
        if not any(d.rule_name == f"COUPON:{code}" for d in quote.discounts):
            cart.coupon_code = previous
            raise CouponNotApplicableError(
                f"coupon {code!r} does not apply to cart {cart.cart_id!r}")
        return quote

    def place_order(self, cart: Cart) -> Quote:
        quote = self._engine.price(cart)                  # re-price, server side
        if cart.coupon_code is not None:
            if not self._coupons.try_consume(cart.coupon_code):
                raise CouponExhaustedError(
                    f"coupon {cart.coupon_code!r} was exhausted before checkout")
        return quote


# HINT (to rebuild) - the DATA half: a registry of kind -> builder turns a config
#   ROW into a rule, and a pipeline builder sorts rows by their `order` column
#   and maps them, returning FRESH objects (so two engines never share a chain).
#   ** the KINDS are classes because their arithmetic differs; percent,
#      threshold, category, exclusivity and ORDER are DATA a merchandiser edits
#      at 2am. `class Diwali20PercentOffRule` is a VALUE pretending to be a TYPE.
#   ** COUPON nests an `inner` row, so the builder RECURSES - the Decorator
#      showing up in the config format.

def _dec(row: dict, key: str) -> Decimal:
    if key not in row:
        raise InvalidRuleConfigError(f"rule {row.get('kind')!r} needs {key!r}")
    try:
        return Decimal(str(row[key]))
    except InvalidOperation as exc:
        raise InvalidRuleConfigError(f"{key!r}={row[key]!r} is not a number") from exc


def _cat(value: str) -> Category:
    try:
        return Category[value]
    except KeyError as exc:
        raise InvalidRuleConfigError(f"unknown category {value!r}") from exc


def _nm(r: dict) -> str:
    return str(r.get("name") or r.get("kind"))


def _x(r: dict) -> bool:
    return bool(r.get("exclusive", False))


RULE_REGISTRY: dict[str, Callable[[dict], PricingRule]] = {
    "PERCENT_OFF": lambda r: PercentageOffRule(_nm(r), _dec(r, "percent"), _x(r)),
    "FLAT_OFF": lambda r: FlatOffRule(_nm(r), _dec(r, "amount"), _x(r)),
    "CATEGORY_PERCENT": lambda r: CategoryDiscountRule(
        _nm(r), _cat(r.get("category", "")), _dec(r, "percent"), _x(r)),
    "BUY_X_GET_Y": lambda r: BuyXGetYFreeRule(
        _nm(r), int(r.get("buy", 0)), int(r.get("free", 0)),
        _cat(r["category"]) if r.get("category") else None, _x(r)),
    "LOYALTY_TIER": lambda r: LoyaltyTierRule(
        _nm(r), {LoyaltyTier[k]: Decimal(str(v))
                 for k, v in (r.get("percent_by_tier") or {}).items()}, _x(r)),
    "FREE_SHIPPING": lambda r: FreeShippingRule(_nm(r), _dec(r, "threshold"), _x(r)),
    "COUPON": lambda r: CouponRule(str(r["code"]), rule_from_config(r["inner"]), _x(r)),
}


def rule_from_config(row: dict) -> PricingRule:
    kind = row.get("kind")
    builder = RULE_REGISTRY.get(str(kind))
    if builder is None:
        raise InvalidRuleConfigError(
            f"unknown rule kind {kind!r} (known: {sorted(RULE_REGISTRY)})")
    try:
        return builder(row)
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidRuleConfigError(f"bad config for {kind!r}: {exc}") from exc


def build_pipeline(rows: list[dict]) -> list[PricingRule]:
    """Config rows -> a fresh, ordered list of rule objects. ORDER is a column."""
    return [rule_from_config(row) for row in sorted(rows, key=lambda r: r.get("order", 0))]


def show(quote: Quote) -> None:
    """The audit trail, line by line, then the money invariant."""
    for line in quote.explain():
        print("  " + line)
    ok = quote.subtotal + quote.shipping_fee - quote.total_discount() == quote.total
    print(f"    invariant  subtotal + shipping - sum(trail) == total : {ok}")


if __name__ == "__main__":
    priya = Customer("u1", "Priya", LoyaltyTier.GOLD)

    def fresh_cart(cart_id: str = "c1", customer: Customer = priya) -> Cart:
        """Carts are mutable (coupon_code), so every scenario gets its own."""
        return Cart(cart_id, customer, lines=[
            CartLine("TSH-01", "T-Shirt", Category.APPAREL,
                     Decimal("1000.00"), 2, Decimal("400.00")),
            CartLine("SHO-09", "Running Shoes", Category.FOOTWEAR,
                     Decimal("3000.00"), 1, Decimal("1800.00")),
            CartLine("SOK-04", "Sport Socks", Category.APPAREL,
                     Decimal("250.00"), 4, Decimal("100.00")),
        ], shipping_fee=Decimal("99.00"))

    base = fresh_cart()
    print(f"CART  subtotal {base.subtotal()}  shipping {base.shipping_fee}"
          f"  cost floor {base.cost_floor()}")

    print("\n=== 1. ORDER MATTERS: same cart, two orderings, two totals ===")
    season = {"kind": "PERCENT_OFF", "name": "SEASON20", "percent": "20"}
    flat = {"kind": "FLAT_OFF", "name": "FLAT500", "amount": "500"}
    cap60 = DiscountCap(Decimal("60"))
    # build_pipeline returns FRESH objects each call: a rule belongs to ONE chain.
    a = PricingEngine(build_pipeline([dict(season, order=1), dict(flat, order=2)]), cap60)
    b = PricingEngine(build_pipeline([dict(flat, order=1), dict(season, order=2)]), cap60)

    qa, qb = a.price(fresh_cart()), b.price(fresh_cart())
    print(f"  pipeline A {a.rule_names()}")
    show(qa)
    print(f"  pipeline B {b.rule_names()}")
    show(qb)
    print(f"  A = {qa.total}   B = {qb.total}   difference = {qb.total - qa.total}\n"
          "  the percentage is taken on the RUNNING total, so whichever percentage\n"
          "  rule runs first sees the larger base. Order is a business lever, so it\n"
          "  is a COLUMN in the config, not a line of code.")

    lonely = PercentageOffRule("REUSED", Decimal("10"))
    PricingEngine([lonely])
    try:
        PricingEngine([lonely])
    except ChainLinkReusedError as exc:
        print(f"  a rule belongs to ONE chain -> {exc}")

    print("\n=== 2. THE FULL PIPELINE from CONFIG ROWS, and the audit trail ===")
    CONFIG = [
        {"order": 10, "kind": "BUY_X_GET_Y", "name": "BUY2GET1", "buy": 2, "free": 1},
        {"order": 20, "kind": "CATEGORY_PERCENT", "name": "SHOES10",
         "category": "FOOTWEAR", "percent": "10"},
        {"order": 30, "kind": "COUPON", "code": "FLAT500",
         "inner": {"kind": "FLAT_OFF", "name": "flat500", "amount": "500"}},
        {"order": 40, "kind": "LOYALTY_TIER", "name": "TIER",
         "percent_by_tier": {"SILVER": "2", "GOLD": "5", "PLATINUM": "10"}},
        {"order": 50, "kind": "FREE_SHIPPING", "name": "SHIPFREE", "threshold": "2000"},
    ]
    engine = PricingEngine(build_pipeline(CONFIG))
    print(f"  pipeline (by the 'order' column): {engine.rule_names()}")
    cart = fresh_cart()
    cart.coupon_code = "FLAT500"
    show(engine.price(cart))
    print("  every line says WHICH rule, on WHAT base, HOW MUCH - that is how support\n"
          "  answers 'why this number?' without a developer.")

    print("\n=== 3. AN EXCLUSIVE RULE HALTS THE CHAIN ===")
    mega = [{"order": 5, "kind": "COUPON", "code": "MEGA40", "exclusive": True,
             "inner": {"kind": "PERCENT_OFF", "name": "mega40", "percent": "40"}}]
    engine_x = PricingEngine(build_pipeline(mega + CONFIG))
    cart_x = fresh_cart()
    cart_x.coupon_code = "MEGA40"
    qx = engine_x.price(cart_x)
    show(qx)
    fired = {d.rule_name for d in qx.discounts}
    print(f"  halted_by = {qx.halted_by}\n"
          f"  never ran = {[n for n in engine_x.rule_names() if n not in fired]}\n"
          "  the exclusive link simply DID NOT CALL its successor - there is no\n"
          f"  engine-side 'if halted: break'. Side effect: shipping is still\n"
          f"  {qx.shipping_due}, because SHIPFREE sat after it. Order the exclusives\n"
          "  last, or lift shipping out of the chain.")

    print("\n=== 4. THE CAP BINDS - an ENGINE INVARIANT, not a chain link ===")
    cart_cap = fresh_cart("c4", Customer("u2", "Arjun", LoyaltyTier.PLATINUM))
    cart_cap.coupon_code = "FLAT1000"
    show(PricingEngine(build_pipeline([
        {"kind": "PERCENT_OFF", "name": "CLEARANCE25", "percent": "25"},
        {"kind": "COUPON", "code": "FLAT1000",
         "inner": {"kind": "FLAT_OFF", "name": "f1000", "amount": "1000"}},
        {"kind": "LOYALTY_TIER", "name": "TIER", "percent_by_tier": {"PLATINUM": "10"}},
    ]), DiscountCap(Decimal("40"))).price(cart_cap))
    print("  the chain wanted 47.5% off; the cap handed money BACK as its own audit\n"
          "  line, so the goods land on exactly 40% and the trail still adds up.")

    print("\n  the COST FLOOR can bind instead of the percentage:")
    cart_floor = fresh_cart("c5")
    cart_floor.coupon_code = "FLAT4000"
    show(PricingEngine(build_pipeline([
        {"kind": "COUPON", "code": "FLAT4000",
         "inner": {"kind": "FLAT_OFF", "name": "f4000", "amount": "4000"}},
    ]), DiscountCap(Decimal("95"))).price(cart_floor))
    print("  95% was allowed so the percent floor did not bind - the cart stopped at\n"
          "  what the goods cost us. Two floors, the tighter one wins.")

    print("\n  and the cap still binds after an EXCLUSIVE rule halted the chain:")
    show(PricingEngine(build_pipeline([
        {"order": 1, "kind": "PERCENT_OFF", "name": "MEGA80", "percent": "80",
         "exclusive": True},
        {"order": 2, "kind": "FREE_SHIPPING", "name": "SHIPFREE", "threshold": "1"},
    ]), DiscountCap(Decimal("40"))).price(fresh_cart("c6")))
    print("  MEGA80 halted the chain so SHIPFREE never ran - but DISCOUNT_CAP still\n"
          "  fired. That is exactly why the cap is not a link.")

    print("\n=== 5. COUPON VALIDATION: one error TYPE per way to fail ===")
    repo = CouponRepository([
        Coupon("FLAT500", max_redemptions=1000),
        Coupon("DEAD", max_redemptions=10, active=False),
        Coupon("USEDUP", max_redemptions=1, redeemed=1),
        Coupon("SHOESONLY", max_redemptions=10),
        Coupon("FLASH3", max_redemptions=3),
    ])
    checkout = CheckoutService(PricingEngine(build_pipeline(CONFIG + [
        {"order": 60, "kind": "COUPON", "code": "SHOESONLY",
         "inner": {"kind": "CATEGORY_PERCENT", "name": "shoes",
                   "category": "FOOTWEAR", "percent": "5"}}])), repo)

    for code in ("NOPE", "DEAD", "USEDUP", "FLAT500"):
        try:
            print(f"  {code:<10} -> OK, total "
                  f"{checkout.attach_coupon(fresh_cart('c8'), code).total}")
        except PricingError as exc:
            print(f"  {code:<10} -> {type(exc).__name__}: {exc}")

    shoeless = Cart("c9", priya, lines=[
        CartLine("SOK-04", "Socks", Category.APPAREL, Decimal("250.00"), 1)])
    try:
        checkout.attach_coupon(shoeless, "SHOESONLY")
    except CouponNotApplicableError as exc:
        print(f"  {'SHOESONLY':<10} -> {type(exc).__name__}: {exc}\n"
              "             the coupon is valid, the CART has no footwear - the\n"
              "             service learned that by READING THE AUDIT TRAIL, and\n"
              f"             rolled cart.coupon_code back to {shoeless.coupon_code!r}")

    print("\n=== 6. TOCTOU: 40 threads race for 3 redemptions of FLASH3 ===")
    store = CouponRepository([Coupon("FLASH3", max_redemptions=3)])
    service = CheckoutService(PricingEngine(build_pipeline(CONFIG)), store)
    won: list[str] = []
    barrier = threading.Barrier(40)

    def rush(i: int) -> None:
        c = fresh_cart(f"race-{i}")
        c.coupon_code = "FLASH3"
        barrier.wait()                      # release everyone at the same instant
        try:
            service.place_order(c)
            won.append(c.cart_id)
        except CouponExhaustedError:
            pass

    threads = [threading.Thread(target=rush, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"  winners {len(won)}   redeemed {store.get('FLASH3').redeemed}/3"
          f"   -> {'OK' if len(won) == 3 else 'OVERSOLD'}\n"
          "  a naive `if redeemed < limit: redeemed += 1` hands all 40 a redemption.\n"
          "  test-and-increment became ONE step; in Postgres that is one\n"
          "  UPDATE ... WHERE redeemed < limit, checked by row count.")

    print("\n=== 7. EXTENSIBILITY: bad config is a typed error, not a crash ===")
    for bad in ({"kind": "MYSTERY_OFFER"},
                {"kind": "PERCENT_OFF"},
                {"kind": "CATEGORY_PERCENT", "category": "SNACKS", "percent": "5"}):
        try:
            rule_from_config(bad)
        except InvalidRuleConfigError as exc:
            print(f"  {str(bad):<56} -> {exc}")

    class HalfBakedRule(PricingRule):
        """applies_to() only - compute() is deliberately missing."""

        def applies_to(self, ctx: PricingContext) -> bool:
            return True

    try:
        HalfBakedRule("OOPS")
    except TypeError as exc:
        print(f"  a rule missing a hook cannot be CONSTRUCTED -> {exc}")
    print("  a new rule KIND = one subclass + one RULE_REGISTRY entry; a new OFFER\n"
          "  = one row, no deploy. That is the data-vs-behaviour split.")
