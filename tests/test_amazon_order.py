"""Amazon order summaries are read from printed amounts."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.processors.amazon_order import consistency_problems, parse_order

LAYOUT_A = """Order Summary
Order placed October 29, 2026 Order # 111-2222222-3333333
Ship to Payment method Order Summary
Pat Example Prime Visa •••• 0000 Item(s) Subtotal: $11.64
123 EXAMPLE ST UNIT 1 Earns 5% back on all items See terms and conditions Shipping & Handling: $0.00
EXAMPLE CITY, CA 90000-0000 Subscribe & Save: -$1.75
United States Your Coupon Savings: -$4.07
Total before tax: $5.82
Estimated tax to be $0.57
collected:
Grand Total: $6.39
FSA or HSA eligible: $6.39
(inc. tax and shipping)
Delivered November 2
Example Antiseptic Skin Cleanser, 8 oz with Foaming Pump
Sold by: Amazon.com
$11.64
FSA or HSA eligible
"""
LAYOUT_B = """Order Summary
Order placed October 18, 2026 Order # 111-2222222-3333334
Ship to Payment method Order Summary
Pat Example Pat Example Pat Example Amazon Gi! Card Item(s) Subtotal: $38.94
123 EXAMPLE ST UNIT 1 $3.61 balance applied Shipping & Handling: $0.00
EXAMPLE CITY, CA 90000-0000 Prime Visa •••• 0000 Multibuy Discount: -$7.79
United States Earns 5% back on all items See terms and conditions Subscribe & Save: -$5.84
Total before tax: $25.31
View related transactions
Estimated tax to be $2.46
collected:
Gift Card Amount: -$3.61
Grand Total: $24.16
FSA or HSA eligible: $27.77
(inc. tax and shipping)
Delivered November 2
Example Preservative Free Dry Eye Drops
2
FSA or HSA eligible
"""
LAYOUT_C = """Order Summary
Order placed September 27, 2026 Order # 111-2222222-3333335
Ship to Payment method Order Summary
Pat Example Pat Example Pat Example Prime Visa •••• 0000 Item(s) Subtotal: $16.61
123 EXAMPLE ST UNIT 1 Shipping & Handling: $1.00
Amazon Gi! Card
EXAMPLE CITY, CA 90000-0000 Subscription saving: -$0.83
United States Free Shipping: -$1.00
View related transactions
Total before tax: $15.78
Estimated tax to be $1.54
collected:
Gift Card Amount: -$10.80
Grand Total: $6.52
FSA or HSA eligible: $17.32
(inc. tax and shipping)
Delivered September 28
Example Preservative Free Dry Eye Drops
FSA or HSA eligible
"""


def test_layout_a():
    order = parse_order(LAYOUT_A)
    assert order is not None
    assert order.order_number == "111-2222222-3333333"
    assert order.order_placed == date(2026, 10, 29)
    assert (
        order.items_subtotal,
        order.tax,
        order.grand_total,
        order.eligible,
        order.gift_card,
    ) == (Decimal("11.64"), Decimal("0.57"), Decimal("6.39"), Decimal("6.39"), Decimal("0"))
    assert order.adjustments == (
        ("Shipping & Handling", Decimal("0.00")),
        ("Subscribe & Save", Decimal("-1.75")),
        ("Your Coupon Savings", Decimal("-4.07")),
    )
    assert order.eligible_item_count == 1
    assert consistency_problems(order) == []


def test_layout_b():
    order = parse_order(LAYOUT_B)
    assert order is not None
    assert (order.eligible, order.grand_total, order.gift_card) == (
        Decimal("27.77"),
        Decimal("24.16"),
        Decimal("3.61"),
    )
    assert consistency_problems(order) == []


def test_layout_c():
    order = parse_order(LAYOUT_C)
    assert order is not None
    assert (order.eligible, order.grand_total, order.gift_card) == (
        Decimal("17.32"),
        Decimal("6.52"),
        Decimal("10.80"),
    )
    assert ("Shipping & Handling", Decimal("1.00")) in order.adjustments
    assert ("Free Shipping", Decimal("-1.00")) in order.adjustments
    assert consistency_problems(order) == []


def test_item_marker_is_not_eligible_total():
    order = parse_order(LAYOUT_A.replace("FSA or HSA eligible: $6.39\n", ""))
    assert order is not None
    assert order.eligible is None
    assert order.eligible_item_count == 1


def test_ambiguous_summary_is_refused():
    assert (
        parse_order(
            LAYOUT_A.replace("Grand Total: $6.39", "Grand Total: $6.39\nGrand Total: $7.39")
        )
        is None
    )
    assert (
        parse_order(
            LAYOUT_A.replace("Grand Total: $6.39", "Grand Total: $6.39\nGrand Total: $6.39")
        )
        is not None
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "CVS pharmacy receipt $4.00",
        "Order # 111-2222222-3333333",
        # An explicit id: pytest would otherwise use the megabyte string as the test's name
        # and print it on one line under -v, which CI's log handling does not survive.
        pytest.param("x" * 1000000, id="very-long-input"),
    ],
)
def test_non_order_or_garbage_returns_none(text):
    assert parse_order(text) is None


def test_thousands_zero_extra_columns_and_unknown_adjustment():
    text = """Order placed January 1, 2026 Order # 111-2222222-3333333
Other column Item(s) Subtotal: $1,234.56
Novel Discount: -$1.00
Other column Shipping & Handling: $0.00
Total before tax: $1,233.56
Estimated tax to be $0.00
Grand Total: $1,233.56
FSA or HSA eligible: $0.00
"""
    order = parse_order(text)
    assert order is not None
    assert order.items_subtotal == Decimal("1234.56")
    assert order.eligible == Decimal("0.00")
    assert order.adjustments == (
        ("Novel Discount", Decimal("-1.00")),
        ("Shipping & Handling", Decimal("0.00")),
    )
    assert consistency_problems(order) == []


def test_grand_total_consistency():
    order = parse_order(LAYOUT_A)
    assert order is not None
    assert consistency_problems(replace(order, grand_total=Decimal("7.39"))) == [
        "Total before tax $5.82 plus tax $0.57 minus gift card $0 does not equal grand total $7.39."
    ]


def test_subtotal_consistency():
    order = parse_order(LAYOUT_A)
    assert order is not None
    assert consistency_problems(replace(order, items_subtotal=Decimal("12.64"))) == [
        "Items subtotal $12.64 plus adjustments equals $6.82, not total before tax $5.82."
    ]


def test_eligible_consistency():
    order = parse_order(LAYOUT_A)
    assert order is not None
    assert consistency_problems(replace(order, eligible=Decimal("7.39"))) == [
        "Eligible amount $7.39 exceeds total before tax $5.82 plus tax $0.57.",
        "Eligible amount $7.39 exceeds grand total $6.39 plus gift card $0.",
    ]


def test_one_line_tax_matches_wrapped_layout():
    wrapped = parse_order(LAYOUT_A)
    one_line = parse_order(
        LAYOUT_A.replace(
            "Estimated tax to be $0.57\ncollected:", "Estimated tax to be collected: $0.57"
        )
    )
    assert one_line == wrapped


def test_missing_total_before_tax_is_reported():
    order = parse_order(LAYOUT_A.replace("Total before tax: $5.82\n", ""))
    assert order is not None
    assert (
        "could not check the page's arithmetic: total before tax not found"
        in consistency_problems(order)
    )


def test_missing_tax_when_totals_match_is_tax_free():
    text = LAYOUT_A.replace("Estimated tax to be $0.57\ncollected:\n", "")
    text = text.replace("Grand Total: $6.39", "Grand Total: $5.82")
    text = text.replace("FSA or HSA eligible: $6.39", "FSA or HSA eligible: $5.82")
    order = parse_order(text)
    assert order is not None
    assert consistency_problems(order) == []


def test_missing_tax_is_reported_when_totals_disagree():
    order = parse_order(LAYOUT_A.replace("Estimated tax to be $0.57\ncollected:\n", ""))
    assert order is not None
    assert "could not check the page's arithmetic: tax not found" in consistency_problems(order)


def test_eligible_checked_against_grand_total_independently():
    order = parse_order(LAYOUT_A)
    assert order is not None
    problems = consistency_problems(replace(order, grand_total=Decimal("5.39")))
    assert "Eligible amount $6.39 exceeds grand total $5.39 plus gift card $0." in problems


def test_eligible_bound_is_checked_when_tax_is_missing():
    order = parse_order(LAYOUT_A.replace("Estimated tax to be $0.57\ncollected:\n", ""))
    assert order is not None
    assert (
        "Eligible amount $6.39 exceeds total before tax $5.82 plus tax $0."
        in consistency_problems(order)
    )
