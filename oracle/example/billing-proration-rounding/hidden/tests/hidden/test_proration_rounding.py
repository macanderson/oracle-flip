"""Hidden tests for the example task. The agent never sees this file.

The task description the agent receives: "Prorated charges for a partial month
are off by a cent in some cases, and a partial month can come out more
expensive than the full month. Fix the proration in src/billing/proration.py."
"""

from decimal import Decimal

from billing.proration import prorate_cents


def test_half_cent_rounds_to_even():
    # 1000 cents over 30 days, 15 days used: exactly 500.0, no rounding.
    assert prorate_cents(1000, days_used=15, days_in_month=30) == 500
    # 1001 cents over 30 days, 15 days used: 500.5 cents rounds to 500 (half to even).
    assert prorate_cents(1001, days_used=15, days_in_month=30) == 500
    # 1003 cents, 15 of 30 days: 501.5 rounds to 502.
    assert prorate_cents(1003, days_used=15, days_in_month=30) == 502


def test_partial_month_never_exceeds_full_price():
    for price in range(1, 5000):
        for days in range(1, 31):
            assert prorate_cents(price, days_used=days, days_in_month=31) <= price
    assert isinstance(prorate_cents(1, days_used=1, days_in_month=31), int)
    assert Decimal(prorate_cents(999, days_used=31, days_in_month=31)) == Decimal(999)
