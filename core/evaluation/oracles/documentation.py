"""Draft documentary cases: complete lists of a document, the document itself being the ground truth."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from core.evaluation.instances import InstanceSpec
from core.evaluation.oracles.common import DEFAULT_COMPANY, DEFAULT_USER, language_phrases, slug
from core.evaluation.protocol_metrics import normalize
from document_rag.ingestion.docx_reader import docx_to_markdown
from document_rag.ingestion.file_formats import is_supported_document
from document_rag.ingestion.pdf_loader import extract_native_text, strip_page_markers

READERS = {
    ".docx": docx_to_markdown,
    ".pdf": lambda path: strip_page_markers(extract_native_text(path)),
}
MIN_ITEMS = 3
TERMS_PER_CLAIM = 2
MIN_WORD_LENGTH = 4
MIN_NUMBER_LENGTH = 2
INTERNAL_DOCS_MODULE = "internal_docs"

MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(\S.*?)\s*#*\s*$")
NUMBERED_TITLE = re.compile(r"^\d+[.)]\s+(\S.*?)\s*$")
BULLET = re.compile(r"^(\s*)[-*•]\s+(\S.*?)\s*$")
NUMBERED_ITEM = re.compile(r"^(\s*)\d+[.)]\s+(\S.*?)\s*$")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_RULE = re.compile(r"^[\s|:\-]+$")
WORD = re.compile(r"\w+", re.UNICODE)

STOPWORDS = frozenset(
    "dans pour avec sans sont etre cette leurs leur plus moins tout tous toute toutes comme apres avant "
    "chaque entre vers sous ainsi aussi ou donc mais that this with from have been will your their "
    "which when where into only each other than then them they these those".split()
)

PHRASES = {
    "fr": {"question": "Quels sont tous les éléments de « {topic} » dans la documentation interne ?"},
    "en": {"question": "What are all the items of \"{topic}\" in the internal documentation?"},
}


@dataclass
class Section:
    document: str
    title: str
    heading: str
    items: list = field(default_factory=list)


def clean_heading(text: str) -> str:
    stripped = re.sub(r"^\d+[.)]\s*", "", text.strip()).strip("*_ ")
    return stripped.lower() if stripped.isupper() else stripped


def document_title(lines: Sequence[str], fallback: str) -> str:
    for line in lines:
        text = line.strip().lstrip("#").strip()
        if text:
            return text
    return fallback


def next_line(lines: Sequence[str], index: int) -> str:
    return next((line for line in lines[index + 1:] if line.strip()), "")


def is_numbered_title(lines: Sequence[str], index: int) -> bool:
    line = lines[index]
    return (
        NUMBERED_TITLE.match(line) is not None
        and not line.startswith((" ", "\t"))
        and BULLET.match(next_line(lines, index)) is not None
    )


def cells(row: str) -> str:
    return " ".join(cell.strip() for cell in row.strip().strip("|").split("|") if cell.strip())


def parse_sections(text: str, document: str) -> list:
    lines = text.splitlines()
    title = document_title(lines, document)
    sections: list = []
    current: Section | None = None
    table_header_seen = False
    for index, line in enumerate(lines):
        heading = MARKDOWN_HEADING.match(line)
        numbered = NUMBERED_TITLE.match(line) if is_numbered_title(lines, index) else None
        if heading or numbered:
            current = Section(document, title, clean_heading((heading or numbered).group(1)))
            sections.append(current)
            table_header_seen = False
            continue
        if current is None:
            continue
        row = TABLE_ROW.match(line)
        item = BULLET.match(line) or NUMBERED_ITEM.match(line)
        if row:
            if TABLE_RULE.match(line):
                continue
            if not table_header_seen:
                table_header_seen = True
                continue
            current.items.append(cells(line))
        elif item:
            table_header_seen = False
            current.items.append(item.group(2))
        elif line.strip() and current.items and line.startswith((" ", "\t")):
            current.items[-1] = f"{current.items[-1]} {line.strip()}"
        elif not line.strip():
            table_header_seen = False
    return sections


def words(text: str) -> list:
    return WORD.findall(text)


def is_significant(word: str) -> bool:
    short_number = len(word) >= MIN_NUMBER_LENGTH and any(char.isdigit() for char in word)
    return (len(word) >= MIN_WORD_LENGTH or short_number) and normalize(word) not in STOPWORDS


def distinctive_terms(item: str, others: Iterable[str], count: int = TERMS_PER_CLAIM) -> list:
    taken = {normalize(word) for other in others for word in words(other)}
    pool = list(dict.fromkeys(word for word in words(item) if is_significant(word)))
    unique = [word for word in pool if normalize(word) not in taken]
    chosen = unique or pool
    ranked = sorted(chosen, key=lambda word: (not any(char.isdigit() for char in word), -len(word)))
    return ranked[:count] if unique else ranked[:count + 1]


def claims_for(items: Sequence[str]) -> list:
    claims = []
    for position, item in enumerate(items, start=1):
        terms = distinctive_terms(item, items[:position - 1] + items[position:])
        if not terms:
            raise ValueError(f"item without a significant term: {item!r}")
        claims.append({"claim_id": f"item_{position:02d}", "statement": item, "all_of": terms})
    return claims


def case_from_section(spec: InstanceSpec, section: Section, phrases: Mapping, user: str, claims: list) -> dict:
    return {
        "case_id": slug("documentation", Path(section.document).stem, section.heading),
        "split": spec.split,
        "instance": spec.name,
        "user_context": {"user": user, "company": DEFAULT_COMPANY, "language": spec.language, "groups": []},
        "question": phrases["question"].format(topic=section.heading),
        "module": INTERNAL_DOCS_MODULE,
        "expected_intent": "documentary_policy",
        "expected_sources": ["internal_docs"],
        "expected_objects": [],
        "acceptable_evidence": [{"kind": "document", "source": section.document}],
        "expected_claims": claims,
        "abstention_rule": "none",
        "ground_truth": {
            "author": "documentation",
            "method": "documentation",
            "reference": f"{section.document}: {section.title} / {section.heading} ({len(claims)} items)",
        },
    }


def read_document(path: Path) -> str:
    reader = READERS.get(path.suffix.lower())
    return reader(path) if reader else path.read_text(encoding="utf-8")


def collect_sections(directory: Path, min_items: int = MIN_ITEMS) -> list:
    sections = []
    for path in sorted(Path(directory).iterdir()):
        if path.is_file() and is_supported_document(path):
            sections += [item for item in parse_sections(read_document(path), path.name) if len(item.items) >= min_items]
    return sections


def sections_to_cases(
    spec: InstanceSpec, sections: Sequence[Section], limit: int | None = None, user: str = DEFAULT_USER,
) -> tuple:
    phrases = language_phrases(PHRASES, spec.language)
    cases, skipped, seen = [], [], set()
    for section in sections:
        try:
            claims = claims_for(section.items)
        except ValueError as error:
            skipped.append(f"{section.document} / {section.heading}: {error}")
            continue
        case = case_from_section(spec, section, phrases, user, claims)
        if case["case_id"] in seen:
            skipped.append(f"{section.document} / {section.heading}: duplicate case id")
            continue
        seen.add(case["case_id"])
        cases.append(case)
    return (cases[:limit] if limit else cases), skipped
