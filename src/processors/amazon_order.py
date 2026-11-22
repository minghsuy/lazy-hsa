"""Read printed Amazon order summary amounts without model arithmetic."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class AmazonOrder:
    order_number: str
    order_placed: date
    items_subtotal: Decimal | None
    total_before_tax: Decimal | None
    tax: Decimal | None
    grand_total: Decimal | None
    eligible: Decimal | None
    gift_card: Decimal
    adjustments: tuple[tuple[str, Decimal], ...]
    eligible_item_count: int


_AMOUNT = r"(-?\$(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})"
_LABELS = {
    "items_subtotal": r"Item\(s\) Subtotal:",
    "total_before_tax": r"Total before tax:",
    "tax": r"Estimated tax to be(?: collected:)?",
    "grand_total": r"Grand Total:",
    "eligible": r"FSA or HSA eligible:",
    "gift_card": r"Gift Card Amount:",
}
_KNOWN_ADJUSTMENTS = (
    "Shipping & Handling",
    "Subscribe & Save",
    "Your Coupon Savings",
    "Multibuy Discount",
    "Subscription saving",
    "Free Shipping",
)


def _amount(value: str) -> Decimal:
    return Decimal(value.replace("$", "").replace(",", ""))


def _adjustment(line: str) -> tuple[str, Decimal] | None:
    for label in _KNOWN_ADJUSTMENTS:
        match = re.search(re.escape(label) + r":\s*" + _AMOUNT, line)
        if match:
            return label, _amount(match.group(1))
    match = re.search(r"^\s*([^:]+?):\s*" + _AMOUNT, line)
    if match:
        return match.group(1).strip(), _amount(match.group(2))
    return None


def parse_order(text: str) -> AmazonOrder | None:
    """Return an order only when its identity and summary are unambiguous."""
    try:
        number = re.search(r"\bOrder\s*#\s*(\d{3}-\d{7}-\d{7})\b", text)
        placed = re.search(r"\bOrder placed\s+([A-Za-z]+ \d{1,2}, \d{4})\b", text)
        if not number or not placed:
            return None
        order_placed = datetime.strptime(placed.group(1), "%B %d, %Y").date()
        lines = text.splitlines()
        values: dict[str, Decimal] = {}
        adjustments: list[tuple[str, Decimal]] = []
        in_adjustments = False
        for line in lines:
            found = False
            for key, label in _LABELS.items():
                match = re.search(label + r"\s*" + _AMOUNT, line)
                if not match:
                    continue
                value = _amount(match.group(1))
                if key in values and values[key] != value:
                    return None
                values.setdefault(key, value)
                if key == "items_subtotal":
                    in_adjustments = True
                elif key == "total_before_tax":
                    in_adjustments = False
                found = True
                break
            if in_adjustments and not found:
                adjustment = _adjustment(line)
                if adjustment:
                    adjustments.append(adjustment)
        return AmazonOrder(
            order_number=number.group(1),
            order_placed=order_placed,
            items_subtotal=values.get("items_subtotal"),
            total_before_tax=values.get("total_before_tax"),
            tax=values.get("tax"),
            grand_total=values.get("grand_total"),
            eligible=values.get("eligible"),
            gift_card=abs(values.get("gift_card", Decimal(0))),
            adjustments=tuple(adjustments),
            eligible_item_count=sum(
                bool(re.fullmatch(r"\s*FSA or HSA eligible\s*", line)) for line in lines
            ),
        )
    except (TypeError, ValueError, InvalidOperation, OverflowError):
        return None


def consistency_problems(order: AmazonOrder) -> list[str]:
    problems = []
    tax = order.tax
    if (
        tax is None
        and order.total_before_tax is not None
        and order.grand_total is not None
        and order.total_before_tax == order.grand_total + order.gift_card
    ):
        tax = Decimal(0)
    for label, value in (
        ("items subtotal", order.items_subtotal),
        ("total before tax", order.total_before_tax),
        ("tax", tax),
        ("grand total", order.grand_total),
    ):
        if value is None:
            problems.append(f"could not check the page's arithmetic: {label} not found")
    if (
        order.total_before_tax is not None
        and tax is not None
        and order.grand_total is not None
        and order.total_before_tax + tax - order.gift_card != order.grand_total
    ):
        problems.append(
            f"Total before tax ${order.total_before_tax} plus tax ${tax} minus gift card "
            f"${order.gift_card} does not equal grand total ${order.grand_total}."
        )
    if order.items_subtotal is not None and order.total_before_tax is not None:
        adjusted = order.items_subtotal + sum(
            (amount for _, amount in order.adjustments), Decimal(0)
        )
        if adjusted != order.total_before_tax:
            problems.append(
                f"Items subtotal ${order.items_subtotal} plus adjustments equals ${adjusted}, "
                f"not total before tax ${order.total_before_tax}."
            )
    if order.eligible is not None and order.eligible < 0:
        problems.append(f"Eligible amount ${order.eligible} is negative.")
    if (
        order.eligible is not None
        and order.total_before_tax is not None
        and order.eligible > order.total_before_tax + (tax or Decimal(0))
    ):
        problems.append(
            f"Eligible amount ${order.eligible} exceeds total before tax ${order.total_before_tax} "
            f"plus tax ${tax or Decimal(0)}."
        )
    if (
        order.eligible is not None
        and order.grand_total is not None
        and order.eligible > order.grand_total + order.gift_card
    ):
        problems.append(
            f"Eligible amount ${order.eligible} exceeds grand total ${order.grand_total} "
            f"plus gift card ${order.gift_card}."
        )
    return problems
