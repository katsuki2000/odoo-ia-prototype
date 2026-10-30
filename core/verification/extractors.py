import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from core.schemas import ClaimType

GROUP_XMLID_RE = re.compile(r"\b[a-z][a-z0-9_]*\.group_[a-z0-9_]+\b")
METHOD_CALL_RE = re.compile(r"(?<![\w.])((?:[a-z][a-z0-9_]*\.)*)(_*[a-z][a-z0-9_]*)\(\)")
SOURCE_FOOTER_RE = re.compile(r"^\[Source\b[^\n]*", re.MULTILINE)
SYSTEM_BLOCK_RE = re.compile(
    r"^\[(?:RESTRICTED ACCESS|DETERMINISTIC VERIFICATION)\].*",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_LINK_TARGET_RE = re.compile(r"\]\([^)\s]*\)")
_DATE_TIME_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b"
    r"|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"
)
_DOTTED_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){2,}\b")
_NAMED_VERSION_RE = re.compile(r"\b(?:odoo|version|v)\s*\d+(?:\.\d+)?\b", re.IGNORECASE)
_DOT_THOUSANDS_RE = re.compile(r"\d{1,3}(?:\.\d{3})+")
_LINE_REFERENCE_RE = re.compile(
    r"(?:#L|:L?|\bL|\blignes?\s+|\blines?\s+)\d+(?:\s*[-\u2010-\u2015]\s*L?\d+)?",
    re.IGNORECASE,
)
_LIST_NUMBER_RE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+)?(?:[-*>]+[ \t]+)?\d+[.)](?=[ \t])", re.MULTILINE)
_NUMBER_RE = re.compile(
    r"(?<![\w.,])"
    r"(?:\d{1,3}(?:[ \u00a0\u202f,.']\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?!\w)(?![.,]\d)"
)


@dataclass(frozen=True)
class NumberReading:
    value: float
    decimals: int


@dataclass(frozen=True)
class NumberToken:
    raw: str
    start: int
    end: int
    readings: Tuple[NumberReading, ...]


@dataclass(frozen=True)
class Claim:
    claim_type: ClaimType
    text: str
    key: str
    spans: Tuple[Tuple[int, int], ...]
    readings: Tuple[NumberReading, ...] = ()
    owner: str = ""
    name: str = ""


def _blank(match: "re.Match") -> str:
    return re.sub(r"[^\n]", " ", match.group())


def _blank_unless_dot_thousands(match: "re.Match") -> str:
    return match.group() if _DOT_THOUSANDS_RE.fullmatch(match.group()) else _blank(match)


def _mask(text: str, patterns) -> str:
    for pattern in patterns:
        text = pattern.sub(_blank_unless_dot_thousands if pattern is _DOTTED_VERSION_RE else _blank, text)
    return text


def _reading(plain: str) -> NumberReading:
    decimals = len(plain.split(".")[1]) if "." in plain else 0
    return NumberReading(float(plain), decimals)


def _read_number(raw: str) -> Tuple[NumberReading, ...]:
    text = raw.replace("\u00a0", " ").replace("\u202f", " ")
    space_grouped = " " in text or "'" in text
    compact = text.replace(" ", "").replace("'", "")
    separators = [char for char in compact if char in ",."]
    if not separators:
        return (_reading(compact),)
    if space_grouped:
        return (_reading(compact.replace(",", ".")),)
    if len(set(separators)) == 2:
        decimal = separators[-1]
        thousands = "." if decimal == "," else ","
        return (_reading(compact.replace(thousands, "").replace(decimal, ".")),)
    if len(separators) > 1:
        return (_reading(compact.replace(separators[0], "")),)
    integer_part, fraction = compact.split(separators[0])
    as_decimal = _reading(f"{integer_part}.{fraction}")
    if len(fraction) == 3 and 1 <= len(integer_part) <= 3 and not integer_part.startswith("0"):
        return (_reading(integer_part + fraction), as_decimal)
    return (as_decimal,)


def find_number_tokens(text: str) -> List[NumberToken]:
    return [
        NumberToken(match.group(), match.start(), match.end(), _read_number(match.group()))
        for match in _NUMBER_RE.finditer(text)
    ]


def _merge(claims: List[Claim]) -> List[Claim]:
    merged: Dict[Tuple[ClaimType, str], Claim] = {}
    for claim in claims:
        known = merged.get((claim.claim_type, claim.key))
        if known is None:
            merged[(claim.claim_type, claim.key)] = claim
        else:
            merged[(claim.claim_type, claim.key)] = Claim(
                known.claim_type, known.text, known.key, known.spans + claim.spans,
                known.readings, known.owner, known.name,
            )
    return list(merged.values())


def extract_claims(answer: str) -> List[Claim]:
    visible = _mask(answer, (_FENCED_CODE_RE, _LINK_TARGET_RE, SOURCE_FOOTER_RE, SYSTEM_BLOCK_RE))
    claims = [
        Claim(ClaimType.GROUP, match.group(), match.group(), ((match.start(), match.end()),))
        for match in GROUP_XMLID_RE.finditer(visible)
    ]
    for match in METHOD_CALL_RE.finditer(visible):
        owner = match.group(1).rstrip(".")
        name = match.group(2)
        claims.append(Claim(
            ClaimType.METHOD, match.group(), f"{owner}.{name}" if owner else name,
            ((match.start(), match.end()),), owner=owner, name=name,
        ))
    numeric = _mask(visible, (_DATE_TIME_RE, _DOTTED_VERSION_RE, _NAMED_VERSION_RE, _LINE_REFERENCE_RE, _LIST_NUMBER_RE))
    claims.extend(
        Claim(
            ClaimType.NUMBER, token.raw, re.sub(r"\s+", " ", token.raw),
            ((token.start, token.end),), readings=token.readings,
        )
        for token in find_number_tokens(numeric)
    )
    return _merge(claims)
