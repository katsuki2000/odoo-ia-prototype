import pytest

from core.evaluation import frozen_cases as fc
from core.evaluation import protocol_metrics as pm
from core.evaluation.instances import InstanceSpec
from core.evaluation.oracles import documentation as doc
from tests.frozen_case_samples import make_case
from tests.pdf_samples import write_text_pdf

WIKI = """WIKI INTERNE — Procédure d'approbation

1. DEMANDE DE MISE À DISPOSITION
   - Initiée par le chef de projet via le module Projet
   - Approuvée par le Directeur Technique si montant < 500 000 Ar
   - Approuvée par le Directeur Général si montant >= 500 000 Ar
   - Délai de traitement : 48h ouvrables

2. COURTE LISTE
   - Un point
   - Un autre point
"""

MARKDOWN = """# Guide

## Sauvegardes

- Sauvegarde complète quotidienne à 2h00
- Sauvegarde incrémentale toutes les 6 heures
  conservée sur un disque séparé
- Rétention de 30 jours

## Tableau des seuils

| Niveau | Délai |
| --- | --- |
| Critique | 1h |
| Majeur | 4h |
| Mineur | 24h |
"""

SPEC = InstanceSpec("hr_suite", "held_out", ("hr",), "fr_FR", False, ())


def test_numbered_title_followed_by_bullets_is_a_section():
    sections = doc.parse_sections(WIKI, "wiki.txt")
    assert [(section.heading, len(section.items)) for section in sections] == [
        ("demande de mise à disposition", 4),
        ("courte liste", 2),
    ]


def test_markdown_lists_continuations_and_tables():
    sections = {section.heading: section for section in doc.parse_sections(MARKDOWN, "guide.md")}
    assert len(sections["Sauvegardes"].items) == 3
    assert "disque séparé" in sections["Sauvegardes"].items[1]
    assert sections["Tableau des seuils"].items == ["Critique 1h", "Majeur 4h", "Mineur 24h"]


def test_each_claim_is_told_apart_from_its_sibling_items():
    items = ["Approuvée par le Directeur Technique", "Approuvée par le Directeur Général"]
    technical, general = (claim["all_of"] for claim in doc.claims_for(items))
    assert "Technique" in technical and "Général" in general
    assert "Approuvée" not in technical + general


def test_single_digit_numbers_are_not_matching_terms():
    assert doc.distinctive_terms("Certificat valide 1 an renouvelable", ["Autre"]) == ["renouvelable", "Certificat"]


def test_item_without_a_significant_term_skips_the_whole_section():
    section = doc.Section("d.txt", "t", "titre", ["oui", "non", "ok"])
    cases, skipped = doc.sections_to_cases(SPEC, [section])
    assert cases == [] and "significant term" in skipped[0]


def test_generated_cases_are_valid_frozen_cases_with_documentary_truth():
    sections = [item for item in doc.parse_sections(WIKI, "wiki.txt") if len(item.items) >= doc.MIN_ITEMS]
    cases, skipped = doc.sections_to_cases(SPEC, sections)
    assert skipped == []
    case = fc.parse_cases(cases)[0]
    assert case.expected_sources == ("internal_docs",)
    assert case.expected_intent == "documentary_policy"
    assert case.ground_truth.method == "documentation"
    assert case.acceptable_evidence[0].kind == "document" and case.acceptable_evidence[0].source == "wiki.txt"
    assert len(case.expected_claims) == 4
    assert "demande de mise à disposition" in case.question


def test_collect_sections_reads_only_supported_documents(tmp_path):
    (tmp_path / "wiki.txt").write_text(WIKI, encoding="utf-8")
    (tmp_path / "guide.md").write_text(MARKDOWN, encoding="utf-8")
    (tmp_path / "data.csv").write_text(WIKI, encoding="utf-8")
    headings = sorted(section.heading for section in doc.collect_sections(tmp_path))
    assert headings == ["Sauvegardes", "Tableau des seuils", "demande de mise à disposition"]


def test_collect_sections_reads_word_documents_and_skips_lock_files(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Sauvegardes Word", level=2)
    for item in ("Sauvegarde complete quotidienne", "Sauvegarde incrementale horaire", "Retention de 30 jours"):
        document.add_paragraph(item, style="List Bullet")
    document.save(str(tmp_path / "guide.docx"))
    (tmp_path / "~$guide.docx").write_bytes(b"lock")
    sections = doc.collect_sections(tmp_path)
    assert [(section.document, section.heading) for section in sections] == [("guide.docx", "Sauvegardes Word")]
    assert len(sections[0].items) == 3


def test_collect_sections_reads_pdf_text_without_page_markers(tmp_path):
    write_text_pdf(tmp_path / "guide.pdf", [
        "Guide PDF",
        "1. Sauvegardes PDF",
        "- Sauvegarde complete quotidienne",
        "- Sauvegarde incrementale horaire",
        "- Retention de 30 jours",
    ])
    sections = doc.collect_sections(tmp_path)
    assert [(section.document, section.title, section.heading) for section in sections] == [
        ("guide.pdf", "Guide PDF", "Sauvegardes PDF")
    ]
    assert len(sections[0].items) == 3


def test_collect_sections_ignores_pdf_without_native_text(tmp_path):
    write_text_pdf(tmp_path / "scan.pdf", [])
    assert doc.collect_sections(tmp_path) == []


def documentary_case():
    sections = [item for item in doc.parse_sections(WIKI, "wiki.txt") if len(item.items) >= doc.MIN_ITEMS]
    cases, _ = doc.sections_to_cases(SPEC, sections)
    return fc.parse_cases(cases)[0]


def test_claim_recall_counts_restituted_items():
    case = documentary_case()
    statements = [claim.statement for claim in case.expected_claims]
    full = " ".join(statements)
    partial = statements[0]
    assert pm.claim_recall(case, pm.CaseResult(case.case_id, "answered", full)) == 1.0
    assert pm.claim_recall(case, pm.CaseResult(case.case_id, "answered", partial)) == 0.25


def test_claim_recall_is_zero_without_an_answer_and_absent_outside_documents():
    case = documentary_case()
    assert pm.claim_recall(case, pm.CaseResult(case.case_id, "abstention")) == 0.0
    code_case = fc.FrozenCase.from_dict(make_case())
    assert pm.claim_recall(code_case, pm.CaseResult(code_case.case_id, "answered", "x")) is None


def test_aggregate_reports_documentary_recall_only_when_there_are_documentary_cases():
    case = documentary_case()
    code_case = fc.FrozenCase.from_dict(make_case())
    docs = pm.score_case(case, pm.CaseResult(case.case_id, "abstention"))
    code = pm.score_case(code_case, pm.CaseResult(code_case.case_id, "answered", "x"))
    assert pm.aggregate([docs, code], k=5)["claim_recall_documentary"] == 0.0
    assert pm.aggregate([code], k=5)["claim_recall_documentary"] is None
