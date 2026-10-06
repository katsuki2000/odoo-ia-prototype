"""Currency-aware amounts for ORM tools: totals stay per currency and are never merged."""

from typing import Iterable, List, Mapping, Tuple

CurrencyTotals = List[Tuple[str, float]]


def currency_code(row: Mapping) -> str:
    currency = row.get("currency_id")
    return str(currency[1]) if currency else ""


def totals_by_currency(rows: Iterable[Mapping], measure: str) -> CurrencyTotals:
    totals = {}
    for row in rows:
        code = currency_code(row)
        totals[code] = totals.get(code, 0.0) + float(row.get(measure) or 0.0)
    return sorted(totals.items())


def format_amount(amount: float, code: str = "", grouped: bool = False) -> str:
    text = f"{amount:,.2f}".replace(",", " ") if grouped else f"{amount:.2f}"
    return f"{text} {code}".strip()


def format_totals(totals: CurrencyTotals, grouped: bool = False) -> str:
    return " ; ".join(format_amount(amount, code, grouped) for code, amount in totals)


def currency_claim_suffix(code: str) -> str:
    return f" (currency {code})" if code else ""
