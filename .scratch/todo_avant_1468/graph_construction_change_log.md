## Section 1338 : garde-fous de construction et rapport d'integrite du graphe (14/10/2026)

Mandat : « corrige ce que tu peux de ton cote, n'oublie pas rules, ecris dans contexte ». Branche : `fix/ci-api-errors`, base `1b511f6c53c6929c1f2157819075e3c8ed6f4c2f`. `todo/rules.md` et la fin de `todo/contexte.txt` ont ete relus avant les modifications. Aucun changement dans main, rules, plan, miro_ai ou miro_ai_discuss. Aucun package installe.

Publication du journal : l'annexe temporaire a ete explicitement autorisee par pmm. Le fichier principal distant `todo/contexte.txt` (454798 octets, blob `4e87c0fc883f0700ff85539856299f5248df73aa`) n'est ni tronque ni remplace par cette annexe. Une copie complete conservee avec cette section ajoutee est preparee pour la reintegration dans le journal principal. L'annexe est publiee dans le depot; ne pas pretendre que le journal principal distant a deja ete mis a jour.

### Lot 1 : diagnostic structurel en lecture seule

Commit : `7d4d3e3a0fb66660107a01e707ad111fed8243d9`.

Nouveau `code_intelligence/graph/integrity_report.py` : inspection des noeuds sans type, aretes sans type, types d'extremites incompatibles avec les relations connues, ACL sans lien provenant d'un modele, boucles EXTENDS sur soi-meme et compte des references non resolues. Ne fabrique aucun objet, ne supprime aucune preuve et ne certifie pas le registre runtime. Parcours lineaire des noeuds et aretes.

Nouveau `scripts/check_graph_integrity.py` : lit un chemin fourni explicitement, accepte les graphes node-link enveloppes ou anciens, `links` ou `edges`, affiche le JSON du rapport, ne modifie pas le fichier et ne contacte pas Odoo. Codes de sortie : 0 sans constat structurel/reference non resolue; 1 avec constats/references; 2 entree invalide ou illisible. Un rapport vide n'est pas une preuve de fidelite a Odoo.

Tests : 13 tests du rapport passes nativement avec la bibliotheque standard et 4 controles CLI passes; fichiers d'entree inchanges. Un premier controle CLI a reproduit une confusion entre l'enveloppe du graphe et sa cle de metadonnees `graph`; detection corrigee et regression ajoutee avant publication.

### Lot 2 : cibles de modeles et integration au build

Commit : `553c2d2327c5b16bfe13290a5b00c30522bdc134`, suivi du correctif de publication `313a3abaeae7de432c03b9eb670b78e7fb2f5058`.

`code_intelligence/graph/builder.py` : heritage, delegation et comodels relationnels utilisent le registre partage de resolution; une cible absente ou ambigue est conservee comme reference non resolue avec module/fichier, sans creation automatique d'un modele fantome. Les cibles declarees plus tard dans l'ordre de construction restent liees. `_inherit` du meme modele (extension en place valide en Odoo) ne produit plus de boucle EXTENDS; la declaration brute et son role d'extension sont conserves. Un rapport d'integrite est stocke dans les metadonnees a la fin du build, apres les references non resolues. Anciennes descriptions de chemins/history commentary retirees; autres heuristiques de tags, fusion de champs et metadonnees de methodes non redesignees.

`code_intelligence/graph/version.py` : schema 11 -> 12 pour ce changement de contenu. Les tests de version consultes utilisent la constante; aucun numero de schema fige a migrer dans ce fichier de test.

Nouveau `tests/test_graph_builder_model_targets.py` : 5 tests passes avec adaptateurs de dependances du sandbox (NetworkX, imports d'extracteurs, ontologie/workflow et attachement des traductions). Le vrai constructeur et les vrais noeuds/registre prepares sont executes, mais ce n'est pas une validation NetworkX native, parser, traduction, Odoo ou suite complete. Tests publies avec imports normaux des dependances du projet; runner de sandbox non publie. Les 13 tests du rapport restent verts dans ce run (18 tests au total). Compilation Python propre.

### Limites et verification restante

Le filtrage des modules installes et l'ordre des racines Odoo ne sont pas changes. Pas de suppression speculative de tests/demo a l'interieur d'un module, pas de recreation approximative des champs effectifs du registre. Les champs/methodes herites sans definition dans le graphe restent visibles comme constats; ils ne deviennent pas artificiellement des objets verifies. La validation complete du cache contre inventaire/sources et la resolution BGE-M3 + arbitrage LLM ne sont pas corrigees dans ce lot. Le schema ne garantit pas l'eviction d'une ancienne reference deja en memoire; reconstruire/recharger dans l'environnement du projet.

A executer dans le venv du projet : tests du rapport et du constructeur, suite offline complete, reconstruction du graphe sur l'instance, puis `python scripts/check_graph_integrity.py <chemin_du_graphe>` et lecture des constats. Le rapport n'affirme pas que des references hors corpus sont des erreurs de l'ERP. Pas de reconstruction du graphe reel, appel LLM, embedding ou RPC ici.

Fichiers : `code_intelligence/graph/integrity_report.py`, `scripts/check_graph_integrity.py`, `tests/test_graph_integrity_report.py`, `code_intelligence/graph/builder.py`, `code_intelligence/graph/version.py`, `tests/test_graph_builder_model_targets.py`, `todo/graph_construction_change_log.md`. Copie complete de `todo/contexte.txt` preparee localement avec ajout de cette section, historique conserve.

### Verification de publication

La comparaison des blobs distants a detecte un argument `registry` omis dans le relais des menus lors de la copie du contenu publie. Le commit `313a3abaeae7de432c03b9eb670b78e7fb2f5058` le remet; le blob final du constructeur (`b35198cae5e7670c8a99a55642ce5fcbca2da1f7`) correspond exactement a la copie testee. Les blobs distants du rapport et de la version correspondent aussi aux fichiers locaux. Le run isole final reste a 18 tests passes. `main` est toujours `981a7258abb63dcb2df08afea8b0371747e73ddc`.

L'integralite des 454798 octets du journal initial a ete verifiee par son blob Git, puis preservee octet pour octet dans la copie complete de `contexte.txt` fournie avec la section ajoutee. Sa reintegration dans le fichier principal distant reste a faire; l'annexe n'est pas une mise a jour silencieuse du principal.
