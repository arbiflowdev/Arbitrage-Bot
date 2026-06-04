"""Pure arbitrage / dynamic-repricing decision engine.

Given a :class:`MarketContext` (our source cost, the competitor landscape, the
destination marketplace's fees, and our current price) the engine returns a
:class:`RepricingDecision` describing the price to set and why. It implements
the client's Milestone-3 rules exactly:

1. **Undercut** the cheapest competitor by ``undercut`` (EUR 0.01).
2. Never reprice below the minimum safe price, i.e. where net profit stays at
   or above ``max(min_profit_absolute, min_profit_margin * selling_price)``.
3. **Top-3 fallback** — if undercutting the cheapest is unprofitable, position
   EUR 0.01 below the 3rd-cheapest competitor when that is still profitable.
4. **Floor freeze** — if even the 3rd position is unprofitable, freeze at the
   minimum safe price and keep the listing live (the engine NEVER unlists).
5. **Anti-anomaly** — if a competitor crashes more than ``anomaly_drop``
   (EUR 0.50) below the 2nd position, treat it as market manipulation: ignore
   it and jump straight to the Top-3 fallback.

The module is intentionally free of any I/O so the rules are fully testable.
All monetary values are :class:`~decimal.Decimal` in a single base currency
(EUR) — currency conversion happens before the engine is called.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal

_CENT = Decimal("0.01")


def _floor_cent(value: Decimal) -> Decimal:
    """Round down to whole cents (used when undercutting a competitor)."""
    return value.quantize(_CENT, rounding=ROUND_DOWN)


def _ceil_cent(value: Decimal) -> Decimal:
    """Round up to whole cents (used for the minimum safe price)."""
    return value.quantize(_CENT, rounding=ROUND_UP)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class FeeParams:
    """Composite marketplace cost parameters, all in the base currency.

    ``*_percent`` values are fractions (0.11 == 11%).
    """

    sales_percent: Decimal = Decimal("0")
    sales_fixed: Decimal = Decimal("0")
    withdrawal_percent: Decimal = Decimal("0")
    withdrawal_fixed: Decimal = Decimal("0")


@dataclass(slots=True)
class PricingPolicy:
    """Tunable thresholds (sourced from settings / ``.env`` in production)."""

    undercut: Decimal = Decimal("0.01")
    min_profit_absolute: Decimal = Decimal("0.30")
    min_profit_margin: Decimal = Decimal("0.05")  # fraction (5%)
    anomaly_drop: Decimal = Decimal("0.50")
    fallback_rank: int = 3


@dataclass(slots=True)
class MarketContext:
    """Everything the engine needs to make one repricing decision."""

    source_cost: Decimal
    competitors: list[Decimal]
    fees: FeeParams
    current_price: Decimal | None = None
    policy: PricingPolicy = field(default_factory=PricingPolicy)


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class CostBreakdown:
    selling_price: Decimal
    source_cost: Decimal
    sales_fee: Decimal
    withdrawal_fee: Decimal
    net_profit: Decimal
    margin: Decimal


class Strategy(str, enum.Enum):
    UNDERCUT = "undercut"
    TOP3_FALLBACK = "top3_fallback"
    ANOMALY_TOP3 = "anomaly_top3"
    FLOOR_FREEZE = "floor_freeze"
    NO_CHANGE = "no_change"


@dataclass(slots=True)
class RepricingDecision:
    strategy: Strategy
    new_price: Decimal
    breakdown: CostBreakdown
    competitor_reference: Decimal | None = None
    anomaly_detected: bool = False
    changed: bool = True
    notes: str = ""


# ---------------------------------------------------------------------------
# Profit math
# ---------------------------------------------------------------------------
def compute_costs(
    selling_price: Decimal, source_cost: Decimal, fees: FeeParams
) -> CostBreakdown:
    """Net take-home profit after ALL costs for a candidate selling price."""
    sales_fee = selling_price * fees.sales_percent + fees.sales_fixed
    withdrawal_fee = selling_price * fees.withdrawal_percent + fees.withdrawal_fixed
    net = selling_price - source_cost - sales_fee - withdrawal_fee
    margin = net / selling_price if selling_price > 0 else Decimal("0")
    return CostBreakdown(
        selling_price=selling_price,
        source_cost=source_cost,
        sales_fee=sales_fee,
        withdrawal_fee=withdrawal_fee,
        net_profit=net,
        margin=margin,
    )


def _required_profit(selling_price: Decimal, policy: PricingPolicy) -> Decimal:
    """The financial red line: max(absolute floor, margin% of the price)."""
    return max(policy.min_profit_absolute, policy.min_profit_margin * selling_price)


def is_profitable(
    selling_price: Decimal,
    source_cost: Decimal,
    fees: FeeParams,
    policy: PricingPolicy,
) -> bool:
    if selling_price <= 0:
        return False
    net = compute_costs(selling_price, source_cost, fees).net_profit
    return net >= _required_profit(selling_price, policy)


def minimum_safe_price(
    source_cost: Decimal, fees: FeeParams, policy: PricingPolicy
) -> Decimal:
    """Smallest selling price whose net profit still meets the red line.

    Solving ``net(S) = k*S - F`` (k = 1 - sales% - withdrawal%, F = cost +
    fixed fees) against both the absolute floor and the margin floor:

        S >= (F + min_absolute) / k                  (absolute floor)
        S >= F / (k - min_margin)                    (margin floor)
    """
    k = Decimal("1") - fees.sales_percent - fees.withdrawal_percent
    fixed = source_cost + fees.sales_fixed + fees.withdrawal_fixed
    if k <= 0:
        # Fees exceed 100% of the price — no price is ever profitable. Fall back
        # to a non-negative price so the listing can still stay live.
        return _ceil_cent(max(source_cost, _CENT))

    candidates = [(fixed + policy.min_profit_absolute) / k]
    margin_k = k - policy.min_profit_margin
    if margin_k > 0:
        candidates.append(fixed / margin_k)
    return _ceil_cent(max(candidates))


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------
def decide(ctx: MarketContext) -> RepricingDecision:
    policy = ctx.policy
    fees = ctx.fees
    cost = ctx.source_cost
    s_min = minimum_safe_price(cost, fees, policy)

    comps = sorted(c for c in ctx.competitors if c is not None and c > 0)

    def build(
        strategy: Strategy,
        price: Decimal,
        *,
        reference: Decimal | None,
        anomaly: bool,
        notes: str = "",
    ) -> RepricingDecision:
        changed = ctx.current_price is None or ctx.current_price != price
        return RepricingDecision(
            strategy=strategy,
            new_price=price,
            breakdown=compute_costs(price, cost, fees),
            competitor_reference=reference,
            anomaly_detected=anomaly,
            changed=changed,
            notes=notes,
        )

    # No market signal: stay live, never unlist. Keep the current price if it is
    # already safe, otherwise pull up to the minimum safe price.
    if not comps:
        if ctx.current_price is not None and is_profitable(
            ctx.current_price, cost, fees, policy
        ):
            return build(
                Strategy.NO_CHANGE,
                ctx.current_price,
                reference=None,
                anomaly=False,
                notes="No competitors observed; current price already safe.",
            )
        return build(
            Strategy.FLOOR_FREEZE,
            s_min,
            reference=None,
            anomaly=False,
            notes="No competitors observed; holding minimum safe price.",
        )

    anomaly = len(comps) >= 2 and (comps[1] - comps[0]) > policy.anomaly_drop

    # 1) Undercut the cheapest legitimate competitor by one cent.
    if not anomaly:
        candidate = _floor_cent(comps[0] - policy.undercut)
        if is_profitable(candidate, cost, fees, policy):
            return build(
                Strategy.UNDERCUT,
                candidate,
                reference=comps[0],
                anomaly=False,
            )

    # 2) Top-3 fallback (also the entry point when an anomaly is detected):
    #    position one cent below the Nth-cheapest competitor.
    if len(comps) >= policy.fallback_rank:
        rank_price = comps[policy.fallback_rank - 1]
        candidate = _floor_cent(rank_price - policy.undercut)
        if is_profitable(candidate, cost, fees, policy):
            return build(
                Strategy.ANOMALY_TOP3 if anomaly else Strategy.TOP3_FALLBACK,
                candidate,
                reference=rank_price,
                anomaly=anomaly,
                notes=(
                    "Cheapest competitor flagged as an anomaly; positioned "
                    "below the 3rd-cheapest to protect margin."
                    if anomaly
                    else "Undercutting the cheapest was unprofitable; "
                    "positioned below the 3rd-cheapest."
                ),
            )

    # 3) Absolute bottom: freeze at the minimum safe price and stay live.
    return build(
        Strategy.FLOOR_FREEZE,
        s_min,
        reference=comps[min(policy.fallback_rank - 1, len(comps) - 1)],
        anomaly=anomaly,
        notes="Market below profit threshold; frozen at minimum safe price.",
    )
