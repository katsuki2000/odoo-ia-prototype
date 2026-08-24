"""Tests -- __init__.py ajoute (2026-08-24), root cause d'un ModuleNotFoundError
en collecte pytest, pas un simple contournement.

Cause reelle : ce repertoire etait le SEUL des cinq repertoires de tests du
depot (core/, document_rag/, erp_data/, code_intelligence/, et celui-ci)
sans __init__.py -- les quatre autres l'ont deja (cf. todo/contexte.txt
section 118). tests/test_j18_routing_fewshot.py fait un import absolu
`from tests.few_shot_routing_examples import (...)`, qui suppose que
`tests` est un vrai package resoluble depuis la racine du projet.

Sans __init__.py, pytest (mode d'import "prepend" par defaut) remonte les
repertoires parents tant qu'il trouve des __init__.py pour determiner ou
inserer un chemin dans sys.path ; comme tests/ n'en avait pas, c'etait
tests/ lui-meme -- et non la racine du projet -- qui etait insere comme
point de depart pour importer le module de test. Le package `tests`
reference par l'import absolu du fichier de test pouvait alors echouer a
se resoudre correctement (`ModuleNotFoundError: No module named
'tests.few_shot_routing_examples'`) malgre la presence reelle du fichier
sur le disque, selon l'ordre de collecte pytest.

Avec ce __init__.py, tests/ devient un package explicite : pytest remonte
desormais jusqu'a la racine du projet pour l'insertion sys.path, exactement
comme pour les quatre autres repertoires de tests deja corriges section
118 -- l'import absolu `from tests.X import Y` se resout alors normalement.
Aucun changement de logique de test, aucun fichier de test renomme ou
deplace.
"""
