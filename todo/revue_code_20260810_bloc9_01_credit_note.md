# Revue de code — run live de `check_bloc9_01_credit_note_cascade_e2e.py` (10/08/2026)

Revue faite à partir de la sortie brute du script collée par l'utilisateur (`todo/rules.md`,
section terminal en bas du fichier). Trois gaps trouvés côté E2E, malgré un raw tool
output propre (3/3 modules présents).

## Gap 1 — bloc9-01a-business INCOMPLETE (`account.group_account_manager`, `20000` absents)

**Cause racine** : `semgrep_locks_analyzer.py::SecurityLockASTVisitor` extrayait le texte du
`UserError` mais jamais l'identifiant technique du groupe passé à `has_group(...)` — le
verrou `self.env.user.has_group('account.group_account_manager')` dans
`custom_credit_note_approval/models/account_move.py` était donc structurellement
inextractible, business ou technique.

**Fix** : `visit_Call` détecte désormais `<expr>.has_group('xml.id')` (tout receveur), peuple
`PythonSecurityLockAnalysis.required_groups`, plus un fallback regex `_HAS_GROUP_PATTERN`
et une ligne de synthèse dédiée. Verrouillé par
`test_s2_5_semgrep_locks.py::TestHardcodedLockDetection::test_detects_has_group_required_group_bloc9_01a`
+ `test_no_has_group_call_leaves_required_groups_empty` (non-régression).

## Gap 2 — contributeur du Gap 1 (`20000` absent) + hop budget dépassé (hops=6 vs `CI_MAX_HOPS`=4)

**Cause racine** : le pré-dispatch forcé de `analyser_chaine_surcharge_methode`
(`rag/graph.py`) dispatchait TOUTES les méthodes en cascade détectées sur un modèle partagé
(`account.move`, étendu à la fois par le mécanisme avoirs et par le mécanisme expense-risk),
sans plafond ni tri par pertinence — le finding régional 20000€/N+2 se noyait parmi des
findings hors-sujet dans `tool_observations`.

**Fix** : `_MAX_OVERRIDE_CASCADE_DISPATCH = 2` + `_rank_and_cap_override_methods(question,
method_names)` (rapidfuzz `token_set_ratio` contre la question, no-op si déjà ≤ 2 candidats).
Verrouillé par `tests/test_graph.py::TestRankAndCapOverrideMethods` (`test_no_op_below_cap`,
`test_ranks_relevant_method_first_when_over_cap`).

## Gap 3 — bloc9-01b-technical HALLUCINATION (`custom_credit_note_approval_global` fabriqué)

**Constat** : fix déjà présent sur disque, daté 07/08 (même jour que le run qui a servi à
le motiver) dans `method_override_resolver.py` — chaque site de surcharge propre est
désormais explicité ("aucun risque structurel détecté...") au lieu d'être laissé comme une
ligne nue `N. module 'x' -- link`, qui donnait apparemment à la synthèse LLM une "licence"
implicite à fabriquer un 4e module plausible. **Pas re-vérifié en conditions réelles depuis
l'écriture du fix** — à confirmer par le prochain rerun.

## État de vérification

`pytest miro-rag/code_intelligence/tests/test_s2_5_semgrep_locks.py miro-rag/tests/test_graph.py -v`
→ **13/13 PASSED** (sortie fournie par l'utilisateur ce jour). Couvre les Gaps 1 et 2 en tests
rapides/déterministes (sans Groq). Le Gap 3 (hallucination) n'a pas de test de non-régression
dédié pour l'instant — seule preuve disponible est la lecture de code confirmant le fix présent ;
aucun test ne verrouille encore le comportement "ne pas fabriquer de 4e module".

**Reste à faire avant de clore le module 1/8** : rerun complet de
`scripts/check_bloc9_01_credit_note_cascade_e2e.py` (E2E, pas seulement les tests unitaires
ci-dessus) pour confirmer les 3 gaps clos simultanément, notamment le Gap 3 qui n'a jamais
été re-testé E2E depuis son fix.
