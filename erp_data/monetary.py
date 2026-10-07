"""Currency-aware amounts for ORM tools: totals stay per currency and are never merged."""

from typing import Iterable, List, Mapping, Tuple

CurrencyTotals = List[Tuple[str, float]]


def currency_code(row: Mapping) -> str:
    currency = row.get("currency_id")
    return str(currency[1]) if currency else "unspecified"


def totals_by_currency(rows: Iterable[Mapping], measure: str) -> CurrencyTotals:
    totals = {}
    for row in rows:
        code = currency_code(row)
        totals[code] = totals.get(code, 0.0) + float(row.get(measure) or 0.0)
    return sorted(totals.items())


def averages_by_currency(rows: Iterable[Mapping], measure: str) -> List[Tuple[str, float, int]]:
    aggregates = {}
    for row in rows:
        code = currency_code(row)
        aggregate = aggregates.setdefault(code, {"amount": 0.0, "count": 0})
        aggregate["amount"] += float(row.get(measure) or 0.0)
        aggregate["count"] += int(row.get("__count") or 0)
    return [
        (code, aggregate["amount"] / aggregate["count"], aggregate["count"])
        for code, aggregate in sorted(aggregates.items())
        if aggregate["count"]
    ]


def format_amount(amount: float, code: str = "", grouped: bool = False) -> str:
    text = f"{amount:,.2f}".replace(",", " ") if grouped else f"{amount:.2f}"
    return f"{text} {code}".strip()


def format_totals(totals: CurrencyTotals, grouped: bool = False) -> str:
    return " ; ".join(format_amount(amount, code, grouped) for code, amount in totals)
