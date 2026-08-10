# Revue de code — run live de `check_bloc9_03_hr_leave_workflow_e2e.py` (10/08/2026)

Revue faite à partir de la sortie brute du script collée par l'utilisateur. Raw tool
output et 2 des 3 questions E2E OK ; 1 gap réel trouvé sur la 3e.

## Raw check + bloc9-03a-business + bloc9-03b-technical : OK

`analyser_verrous_securite("hr.leave")` remonte bien les deux messages d'erreur (contrainte
solde + gate N+2/RH) et le groupe technique `hr_holidays.group_hr_holidays_manager` détecté
via `has_group()` — confirme que le fix générique du module 1/8 (Gap 1, extraction
`has_group()` dans `semgrep_locks_analyzer.py`) fonctionne bien sur un 2e cas réel sans
changement de code supplémentaire. Confirme aussi implicitement que le fix J36 (chargement
générique des dépendances directes des modules `custom_*`) charge bien `hr_holidays` (module
core Odoo réel, pas un stand-in `fake_data/code/`) exactement comme il chargeait déjà
`hr_expense`.

Les deux premières questions E2E (formulation business Q2.1, formulation technique nommant
`hr.leave`) remontent tous les marqueurs attendus, y compris le groupe technique explicite.

## Gap — bloc9-03c-urgente-trap INCOMPLETE (`hr_holidays.group_hr_holidays_manager` absent)

**Cause racine** : `_AUTOMATION_PATTERN` (`rag/graph.py`) contenait `automatiq\w*` en
branche libre — ce fragment matche aussi bien "action automatique" (le cas visé) que
l'adverbe ordinaire "automatiquement" dans une question comme *"sa demande est-elle
automatiquement validée ?"*, qui ne parle pas du tout de `ir.actions.server`/
`base.automation`/`sudo()`. Sur un modèle qui a de vrais nœuds `ServerAction` dans le graphe
(`hr.leave` en a, via `hr_holidays`), le garde-fou structurel (`find_server_action_nodes`)
ne filtre pas ce faux positif, donc `analyser_actions_serveur` est dispatché pour rien.

Ce dispatch superflu consomme un hop du budget serré `CI_MAX_HOPS=4` — confirmé en live : le
run s'est arrêté avec `CI_MAX_HOPS (4) reached -- breaking ReAct loop` avant même que la
boucle ReAct ne démarre, et le LLM de synthèse a fini par ne pas citer le groupe technique
`hr_holidays.group_hr_holidays_manager` dans sa réponse — pourtant bien présent dans les
observations brutes (confirmé par le raw check). Même forme d'échec que le Gap 2 du module
1/8 (bruit de dispatch qui noie un fait nécessaire dans le contexte de synthèse), mais
déclenché ici par un faux positif de mot-clé plutôt que par une liste de candidats non
plafonnée.

**Fix** : `_AUTOMATION_PATTERN` exige désormais que le vocabulaire d'automatisation porte
sur une "action" (le nom que cet outil analyse réellement) ou utilise le terme technique plus
spécifique "automatisation" — `automatiq\w*` remplacé par `actions?\s+automatiques?` +
`automatisation\w*`. Un adjectif/adverbe isolé "automatique"/"automatiquement" sans "action"
accolée ne déclenche plus rien. Vérifié par lecture que "mêmes règles" (formulation réelle de
Q5.1) n'a jamais dépendu de cette branche, donc pas de régression attendue sur le benchmark
existant.

**Test ajouté** : `tests/test_graph.py::TestAutomationPatternNoBareAdverbFalsePositive`
(6 tests, sans LLM/Odoo) — vérifie que l'adverbe/adjectif isolé ne déclenche plus rien, que
"action automatique"/"automatisation" déclenchent toujours, que "mêmes règles"/"bypass"/
"contourner" ne régressent pas.

## État de vérification

**Pas encore ré-exécuté** — ni le nouveau test unitaire (`TestAutomationPatternNoBareAdverbFalsePositive`),
ni un rerun complet de `scripts/check_bloc9_03_hr_leave_workflow_e2e.py`, n'ont été lancés
depuis ce fix (accès filesystem uniquement, aucune capacité d'exécution sur cette machine).
Module 3/8 reste ouvert tant qu'un rerun réel n'a pas confirmé les 3 questions E2E vertes
simultanément.

**Reste à faire avant de clore le module 3/8** :
```
pytest miro-rag/tests/test_graph.py -v
python scripts/check_bloc9_03_hr_leave_workflow_e2e.py
```
