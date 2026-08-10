# Revue de code — run live de confirmation `check_bloc9_02_credit_note_visibility_e2e.py` (10/08/2026)

Revue faite à partir de la sortie brute collée par l'utilisateur : `pytest miro-rag/tests/test_graph.py -v`
suivi du run complet de `scripts/check_bloc9_02_credit_note_visibility_e2e.py`. C'était le
rerun de confirmation demandé en fin de session précédente (`contexte.txt`, section 16) pour
les deux fixes appliqués sur ce module.

## Rappel des deux fixes vérifiés par ce run

**Fix 1 — faux négatif de marqueur de test (bloc9-02a-both-groups)** : le texte brut de l'outil
orthographie les noms de règles sans accents ("visibilite nationale"), le petit LLM de synthèse
les réaccentue correctement en prose ("visibilité nationale") — un `in` littéral rapportait donc
à tort MISSING sur une réponse pourtant correcte. Fix dans le script lui-même :
`_fold_accents`/`_marker_present` (même technique que `deterministic_tools.py::_fold_accents`).

**Fix 2 — bug réel de synthèse (bloc9-02b-no-groups)** : la réponse finale était un simple echo
verbatim de la phrase d'instruction interne au deuxième-personne du singulier injectée dans
`tool_observations` par le short-circuit `can_view_amount` (Bloc 4, J14) — zéro explication,
aucun nom de règle cité. Cause racine : la phrase adressait directement le LLM de synthèse
("...ne doit JAMAIS être recalculé...") mélangée dans le fait lui-même. Fix dans `rag/graph.py` :
extraction en `_format_can_view_amount_fact(amount, can_view)` purement déclaratif, instruction
"ne jamais contredire ce verdict, mais toujours l'expliquer avec les règles citées ailleurs dans
la réponse" déplacée dans `synthesis_prompt`. Verrouillé par
`tests/test_graph.py::TestFormatCanViewAmountFact` (3 tests : marqueur+verdict présents,
locutions impératives bannies absentes).

## État de vérification — CONFIRMÉ ce jour

`pytest miro-rag/tests/test_graph.py -v` → **10/10 PASSED**, y compris
`TestRankAndCapOverrideMethods` (2/2, hérité du module 1/8) et `TestFormatCanViewAmountFact`
(3/3, Fix 2 ci-dessus).

`python scripts/check_bloc9_02_credit_note_visibility_e2e.py` → **E2E confirmé** :
- Raw `evaluer_regles_raw` : `can_view_amount(80000)` = `True` pour BOTH et NONE, comme attendu.
- `bloc9-02a-both-groups` : marqueur attendu présent ("Avoirs - visibilite nationale", matché
  malgré l'accentuation LLM grâce au Fix 1), aucun marqueur interdit.
- `bloc9-02b-no-groups` : marqueur attendu présent ("cantonnement societe" — la réponse explique
  maintenant réellement pourquoi, au lieu de recracher l'instruction interne, confirmant le Fix 2
  en conditions réelles), aucun marqueur interdit.
- Sortie finale du script : `[BLOC 9 - 2/8] custom_credit_note_visibility_rules: E2E confirmed.`
  (exit 0).

## Conclusion

Les deux fixes (Fix 1 côté script de test, Fix 2 côté code produit `rag/graph.py`) sont
désormais confirmés par une exécution réelle, pas seulement par une lecture de code — même
discipline que le module 1/8 (`revue_code_20260810_bloc9_01_credit_note.md`), ici menée à son
terme. **Module 2/8 (`custom_credit_note_visibility_rules`) du Bloc 9 : clos.**

Reste sur le Bloc 9 dans son ensemble : module 1/8 encore ouvert (Gap 3 — hallucination
`custom_credit_note_approval_global` — jamais re-vérifié E2E depuis son fix), et les modules
3/8 à 8/8 (`custom_hr_leave_workflow`, `custom_purchase_request`, `custom_asset_loan`,
`custom_automation_traps`, `custom_expense_reimbursement_indirect`, plus la question de
comptage "7 mécanismes vs 8 modules" documentée dans `contexte.txt` section 14) pas encore
attaqués.
