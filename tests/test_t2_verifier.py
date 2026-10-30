from core.schemas import ClaimType, VerifierMode
from core.verification.context import VerificationContext
from core.verification.verifier import verify_answer_claims

ANSWER = (
    "Le seuil est de 10 000 €. Le groupe purchase.group_purchase_director peut approuver. "
    "Le groupe account.group_account_manager peut valider.\n\n"
    "[Source: Graphe de Connaissances Code Intelligence]"
)


def _context():
    return VerificationContext(
        texts=("if amount > 10000:", "(groupes: account.group_account_manager)"),
    )


def test_off_mode_does_nothing():
    answer, report = verify_answer_claims(ANSWER, _context(), VerifierMode.OFF)
    assert answer == ANSWER
    assert (report.claims_total, report.unsupported_claims) == (0, 0)


def test_report_mode_counts_without_touching_the_answer():
    answer, report = verify_answer_claims(ANSWER, _context(), VerifierMode.REPORT)
    assert answer == ANSWER
    assert report.claims_total == 3
    assert report.unsupported_claims == 1
    assert report.claims_by_type == {ClaimType.NUMBER: 1, ClaimType.GROUP: 2}
    assert report.unsupported_by_type == {ClaimType.GROUP: 1}
    assert [(item.text, item.reason) for item in report.unsupported] == [
        ("purchase.group_purchase_director", "not_in_evidence"),
    ]


def test_answer_without_claims_gives_an_empty_report():
    answer, report = verify_answer_claims("Aucune donnée disponible.", _context(), VerifierMode.ENFORCE)
    assert answer == "Aucune donnée disponible."
    assert report.claims_total == 0


def test_enforce_retires_only_the_sentence_with_the_unsupported_claim():
    answer, report = verify_answer_claims(ANSWER, _context(), VerifierMode.ENFORCE)
    assert "purchase.group_purchase_director peut approuver" not in answer
    assert "Le seuil est de 10 000 €." in answer
    assert "account.group_account_manager peut valider." in answer
    assert report.unsupported_claims == 1


def test_enforce_notice_names_the_claim_and_stays_before_the_source_footer():
    answer, _ = verify_answer_claims(ANSWER, _context(), VerifierMode.ENFORCE)
    notice_at = answer.index("[DETERMINISTIC VERIFICATION]")
    assert "purchase.group_purchase_director" in answer[notice_at:]
    assert notice_at < answer.index("[Source:")
    assert answer.rstrip().endswith("[Source: Graphe de Connaissances Code Intelligence]")


def test_enforce_drops_a_whole_bullet_line():
    text = "Résumé :\n- Groupe purchase.group_purchase_director requis\n- Groupe account.group_account_manager requis"
    answer, _ = verify_answer_claims(text, _context(), VerifierMode.ENFORCE)
    assert "purchase_director requis" not in answer
    assert "- Groupe account.group_account_manager requis" in answer


def test_enforced_answer_verifies_clean_a_second_time():
    first, _ = verify_answer_claims(ANSWER, _context(), VerifierMode.ENFORCE)
    _, report = verify_answer_claims(first, _context(), VerifierMode.REPORT)
    assert report.unsupported_claims == 0


def test_repeated_unsupported_claim_counts_once_and_is_retired_everywhere():
    text = "Le groupe a.group_x est requis. Le groupe a.group_x est aussi nécessaire."
    answer, report = verify_answer_claims(text, _context(), VerifierMode.ENFORCE)
    assert report.claims_total == 1
    assert report.unsupported_claims == 1
    assert "est requis" not in answer
    assert "aussi nécessaire" not in answer
