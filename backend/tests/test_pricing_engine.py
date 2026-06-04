"""Unit tests for the pure arbitrage/repricing decision engine.

These tests encode the client's exact Milestone-3 pricing rules:

* Undercut the cheapest competitor by EUR 0.01.
* Never reprice below ``max(EUR 0.30, 5% margin)`` net profit.
* If undercutting the cheapest is unprofitable, position EUR 0.01 below the
  3rd-cheapest competitor (Top-3 fallback) when that is profitable.
* If even the 3rd position is unprofitable, FREEZE at the minimum safe price
  and keep the listing live (never unlist).
* Anti-anomaly: ignore a competitor that drops more than EUR 0.50 below the
  2nd position and jump straight to the Top-3 fallback.

The engine is pure (no DB / no network), so it is fully unit-testable.
"""

from __future__ import annotations

from decimal import Decimal

from app.pricing.engine import (
    FeeParams,
    MarketContext,
    PricingPolicy,
    Strategy,
    compute_costs,
    decide,
    minimum_safe_price,
)

# Kinguin-style composite fee: 11% + EUR 0.35, no withdrawal buffer.
KINGUIN_FEES = FeeParams(
    sales_percent=Decimal("0.11"),
    sales_fixed=Decimal("0.35"),
    withdrawal_percent=Decimal("0"),
    withdrawal_fixed=Decimal("0"),
)


def _ctx(source_cost: str, competitors: list[str], **kw) -> MarketContext:
    return MarketContext(
        source_cost=Decimal(source_cost),
        competitors=[Decimal(c) for c in competitors],
        fees=KINGUIN_FEES,
        **kw,
    )


# ---------------------------------------------------------------------------
# Profit math
# ---------------------------------------------------------------------------
def test_compute_costs_subtracts_all_fees() -> None:
    fees = FeeParams(
        sales_percent=Decimal("0.10"),
        sales_fixed=Decimal("0.50"),
        withdrawal_percent=Decimal("0.02"),
        withdrawal_fixed=Decimal("1.00"),
    )
    c = compute_costs(Decimal("20.00"), Decimal("10.00"), fees)
    assert c.sales_fee == Decimal("2.50")  # 20*0.10 + 0.50
    assert c.withdrawal_fee == Decimal("1.40")  # 20*0.02 + 1.00
    assert c.net_profit == Decimal("6.10")  # 20 - 10 - 2.50 - 1.40
    assert round(c.margin, 4) == Decimal("0.3050")  # 6.10 / 20


def test_minimum_safe_price_guarantees_threshold() -> None:
    # C=10.00, k=0.89, F=10.35 -> sb dominates: 10.35/0.84 = 12.3214 -> 12.33
    s_min = minimum_safe_price(Decimal("10.00"), KINGUIN_FEES, PricingPolicy())
    assert s_min == Decimal("12.33")
    net = compute_costs(s_min, Decimal("10.00"), KINGUIN_FEES).net_profit
    required = max(Decimal("0.30"), Decimal("0.05") * s_min)
    assert net >= required


# ---------------------------------------------------------------------------
# Strategy: undercut the cheapest competitor
# ---------------------------------------------------------------------------
def test_undercuts_cheapest_competitor_by_one_cent() -> None:
    d = decide(_ctx("5.00", ["10.00", "10.50", "11.00"]))
    assert d.strategy is Strategy.UNDERCUT
    assert d.new_price == Decimal("9.99")
    assert d.competitor_reference == Decimal("10.00")
    assert d.anomaly_detected is False
    assert d.breakdown.net_profit > Decimal("0.30")


# ---------------------------------------------------------------------------
# Strategy: Top-3 fallback when undercutting the cheapest is unprofitable
# ---------------------------------------------------------------------------
def test_top3_fallback_when_cheapest_unprofitable() -> None:
    # Spacing stays under the EUR 0.50 anomaly gap (0.40, 0.80) so this is a
    # genuine "cheapest is unprofitable" fallback, not an anomaly. C=9.50 makes
    # 10.99 unprofitable but 12.19 (below the 3rd-cheapest) profitable.
    d = decide(_ctx("9.50", ["11.00", "11.40", "12.20"]))
    assert d.strategy is Strategy.TOP3_FALLBACK
    assert d.anomaly_detected is False
    assert d.new_price == Decimal("12.19")
    assert d.competitor_reference == Decimal("12.20")
    required = max(Decimal("0.30"), Decimal("0.05") * d.new_price)
    assert d.breakdown.net_profit >= required


# ---------------------------------------------------------------------------
# Strategy: freeze at the minimum safe price when even Top-3 is unprofitable
# ---------------------------------------------------------------------------
def test_floor_freeze_when_even_top3_unprofitable() -> None:
    # Sub-anomaly spacing; cost so high that even below the 3rd-cheapest is a
    # loss -> freeze at the minimum safe price (above market) and stay live.
    d = decide(_ctx("10.00", ["11.00", "11.40", "12.20"]))
    assert d.strategy is Strategy.FLOOR_FREEZE
    assert d.new_price == Decimal("12.33")  # the minimum safe price
    required = max(Decimal("0.30"), Decimal("0.05") * d.new_price)
    assert d.breakdown.net_profit >= required


# ---------------------------------------------------------------------------
# Anti-anomaly: ignore a competitor that crashes >EUR 0.50 below 2nd place
# ---------------------------------------------------------------------------
def test_anomaly_competitor_is_ignored_and_jumps_to_top3() -> None:
    # 5.00 is 5.00 below the 2nd position (10.00) -> anomaly, skip it.
    d = decide(_ctx("5.00", ["5.00", "10.00", "10.50", "11.00"]))
    assert d.anomaly_detected is True
    assert d.strategy is Strategy.ANOMALY_TOP3
    assert d.new_price == Decimal("10.49")  # EUR 0.01 below 3rd-cheapest 10.50
    assert d.competitor_reference == Decimal("10.50")


def test_small_drop_is_not_treated_as_anomaly() -> None:
    # 9.60 is only 0.40 below the 2nd position (10.00) -> NOT an anomaly.
    d = decide(_ctx("5.00", ["9.60", "10.00", "10.50"]))
    assert d.anomaly_detected is False
    assert d.strategy is Strategy.UNDERCUT
    assert d.new_price == Decimal("9.59")


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------
def test_never_unlists_and_price_is_always_positive() -> None:
    # No competitors at all -> stay live at a safe price, never unlist.
    d = decide(_ctx("10.00", []))
    assert d.strategy in (Strategy.FLOOR_FREEZE, Strategy.NO_CHANGE)
    assert d.new_price > Decimal("0")


def test_no_change_when_current_price_already_safe_and_no_market() -> None:
    d = decide(_ctx("10.00", [], current_price=Decimal("15.00")))
    assert d.strategy is Strategy.NO_CHANGE
    assert d.new_price == Decimal("15.00")
    assert d.changed is False


def test_fewer_than_three_competitors_freezes_when_unprofitable() -> None:
    d = decide(_ctx("10.00", ["11.00", "11.40"]))
    assert d.strategy is Strategy.FLOOR_FREEZE
    assert d.new_price == Decimal("12.33")
