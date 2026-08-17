"""
scripts/check_bloc9_08_deep_inheritance_security_e2e.py

Bloc 9, module 08 -- custom_deep_inheritance_security (Q6.1-style visibility
questions against custom.deep.document). Real E2E check: calls the actual
query_graph() pipeline (Groq + live Odoo XML-RPC via code_intelligence_agent),
NOT a unit test of the deterministic engine alone (see
code_intelligence/tests/test_s2_9_domain_force_evaluator.py and
tests/test_bloc9_08_can_view_amount_contradiction.py for that).

Real rules on custom.deep.document (security/security_rules.xml):
  Rule 1 (global, "Cantonnement Societe"):
    ['|', ('company_id', '=', False), ('company_id', '=', user.company_id.id)]
  Rule 2 (group base.group_user, "Regle Imbriquee Complexe"):
    ['&', '|', ('amount', '<=', 50000), ('user_id', '=', user.id),
     ('company_id', '=', user.company_id.id)]

This is exactly the fixture behind the confirmed Bloc9 08c root cause
(can_view_amount() fails open on company_id) and its follow-up fix
(can_view_amount_v2 + _correct_can_view_amount_contradictions).

Usage:
    python miro-rag/scripts/check_bloc9_08_deep_inheritance_security_e2e.py

Purpose of this rerun: distinguish the two remaining candidate causes for
any 08-style regression --
  (1) resolution/wiring gap upstream of can_view_amount_v2 (model not
      resolved, zero rules applied -- read the
      "Injected deterministic can_view_amount_v2 fact" log line: if
      global_rules_applied=0 or result=True with unresolved=[] despite a
      stated company difference, this is the cause), vs
  (2) synthesis-level inversion of an otherwise-correct verdict (the log
      line shows result=False but the final answer still says "peut voir"
      -- if _correct_can_view_amount_contradictions is working, this
      should now self-correct; if the printed final answer still shows
      the wrong verdict, that's a real gap to reopen).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag.graph import query_graph  # noqa: E402
from code_intelligence.deterministic_tools import _fold_accents  # noqa: E402


def _marker_present(marker: str, text: str) -> bool:
    """Accent/case-insensitive substring check -- same tolerance discipline
    as every other Bloc9 check script (fold accents, lowercase, then plain
    substring; TestAmountPresentInText's spaced/unspaced logic is not
    needed here, no amount markers are checked)."""
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


# Real technical marker for base.group_user (used only for context in
# output, never asserted against forbidden -- membership in this group is
# the NORMAL case for any authenticated Odoo user, not a governance fact
# worth flagging).
GROUP_USER_XMLID = "base.group_user"


def run_case(label: str, question: str, expected_markers: list[str], forbidden_markers: list[str]) -> bool:
    print(f"\n--- {label} ---")
    print(f"Question : {question}")
    response = query_graph(question=question, user_groups=[])
    answer = response.answer if response else ""
    print("Réponse brute :")
    print(answer)

    ok = True
    for marker in expected_markers:
        if _marker_present(marker, answer):
            print(f"    ✅ marqueur attendu présent : {marker!r}")
        else:
            print(f"    ❌ marqueur attendu ABSENT : {marker!r}")
            ok = False

    for marker in forbidden_markers:
        if _marker_present(marker, answer):
            print(f"    ❌ marqueur interdit PRÉSENT : {marker!r}")
            ok = False
        else:
            print(f"    ✅ marqueur interdit absent : {marker!r}")

    return ok


def run_all() -> bool:
    print("=" * 70)
    print("Bloc 9, module 08 -- custom_deep_inheritance_security (E2E réel)")
    print("=" * 70)
    print(
        "Regarder les logs applicatifs (niveau INFO) pour la ligne "
        "\"Injected deterministic can_view_amount_v2 fact\" sur chaque cas "
        "-- c'est elle qui tranche cause (1) résolution/câblage vs "
        "cause (2) inversion de synthèse, voir le docstring du script."
    )

    results = {}

    # 08a-business: question business-phrasee sur l'autorite de validation a
    # 60 000E (custom.deep.document, action_validate_level2 seuil > 50000
    # -> account.group_account_manager REQUIS et AUTORISE ; action_final_approve
    # seuil > 100000 -> base.group_system, INACTIF a ce montant). Question et
    # signature d'inversion confirmees reelles (verbatim, _QUESTION_60K /
    # _BAD_VERBATIM_ANSWER dans tests/test_graph.py::TestCorrectSecurityLockThresholdContradictions),
    # pas une formulation devinee. Cible precisement le bug corrige en
    # 2026-08-14 (_correct_security_lock_threshold_contradictions, section 48
    # de contexte.txt) et le skip-guard qui_a_acces_a (section 47).
    results["08a_business_autorite_validation_60k"] = run_case(
        "08a-business -- qui a le droit de valider a 60 000€ (piege double-seuil)",
        "Qui a le droit de valider un document à 60 000€ dans le modèle "
        "custom.deep.document (module de sécurité à héritage profond) ?",
        expected_markers=[
            "account.group_account_manager",
        ],
        forbidden_markers=[
            "n'a pas le droit de valider",
        ],
    )

    # 08c-shape: société explicitement différente, montant sous 50k (donc
    # la règle de groupe seule laisserait passer -- seule la règle globale
    # de cantonnement société doit bloquer). C'est le cas exact du root
    # cause confirmé : can_view_amount() (ancien) aurait dit True car son
    # regex ne voit jamais company_id ; can_view_amount_v2() doit dire False.
    results["08c_societe_differente_montant_sous_seuil"] = run_case(
        "08c -- société différente, 30 000€ (sous le seuil de groupe)",
        "Un utilisateur d'une autre société peut-il voir un document Deep "
        "de 30000€ appartenant à une société différente de la sienne ?",
        expected_markers=[
            "can_view_amount_v2",
            "NE PEUT PAS",
        ],
        forbidden_markers=[
            "PEUT voir cet enregistrement",
        ],
    )

    # Même société, montant sous le seuil de groupe (50k) -> les deux
    # règles (globale + groupe) doivent être satisfaites -> True.
    results["memes_societe_montant_sous_seuil"] = run_case(
        "Même société, 30 000€ (sous le seuil de groupe)",
        "Un utilisateur de la même société peut-il voir un document Deep "
        "de 30000€ ?",
        expected_markers=[
            "can_view_amount_v2",
            "PEUT",
        ],
        forbidden_markers=[
            "NE PEUT PAS",
        ],
    )

    # Société différente, montant élevé (80k, au-delà du seuil de groupe) :
    # la règle globale bloque déjà seule -- vérifie qu'aucune inversion ne
    # fait dire "peut voir" malgré un can_view_amount_v2()=False.
    results["08c_societe_differente_montant_eleve"] = run_case(
        "08c bis -- société différente, 80 000€ (au-delà du seuil de groupe)",
        "Un utilisateur d'une autre société peut-il consulter un document "
        "Deep de 80000€ appartenant à une société différente de la sienne ?",
        expected_markers=[
            "can_view_amount_v2",
            "NE PEUT PAS",
        ],
        forbidden_markers=[
            "a le droit de voir",
            "peut consulter",
        ],
    )

    print("\n" + "=" * 70)
    print("RÉSUMÉ")
    print("=" * 70)
    for name, passed in results.items():
        print(f"  {'✅' if passed else '❌'} {name}")

    return all(results.values())


if __name__ == "__main__":
    success = run_all()
    print("\n" + "=" * 70)
    print("RÉSULTAT GLOBAL : " + ("✅ TOUS LES CAS PASSENT" if success else "❌ AU MOINS UN CAS ÉCHOUE"))
    print("=" * 70)
    sys.exit(0 if success else 1)
