## Section 1338 : garde-fous de construction et rapport d'integrite du graphe (14/10/2026)

Mandat : « corrige ce que tu peux de ton cote, n'oublie pas rules, ecris dans contexte ». Branche : `fix/ci-api-errors`, base `1b511f6c53c6929c1f2157819075e3c8ed6f4c2f`. `todo/rules.md` et la fin de `todo/contexte.txt` ont ete relus avant les modifications. Aucun changement dans main, rules, plan, miro_ai ou miro_ai_discuss. Aucun package installe.

Publication du journal : l'annexe temporaire a ete explicitement autorisee par pmm. Le fichier principal distant `todo/contexte.txt` (454798 octets, blob `4e87c0fc883f0700ff85539856299f5248df73aa`) n'est ni tronque ni remplace par cette annexe. Une copie complete conservee avec cette section ajoutee est preparee pour la reintegration dans le journal principal. L'annexe est publiee dans le depot; ne pas pretendre que le journal principal distant a deja ete mis a jour.

### Lot 1 : diagnostic structurel en lecture seule

Nouveau `code_intelligence/graph/integrity_report.py` : inspection des noeuds sans type, aretes sans type, types d'extremites incompatibles avec les relations connues, ACL sans lien provenant d'un modele, boucles EXTENDS sur soi-meme et compte des references non resolues. Ne fabrique aucun objet, ne supprime aucune preuve et ne certifie pas le registre runtime. Parcours lineaire des noeuds et aretes.

Nouveau `scripts/check_graph_integrity.py` : lit un chemin fourni explicitement, accepte les graphes node-link enveloppes ou anciens, `links` ou `edges`, affiche le JSON du rapport, ne modifie pas le fichier et ne contacte pas Odoo. Codes de sortie : 0 sans constat structurel/reference non resolue; 1 avec constats/references; 2 entree invalide ou illisible. Un rapport vide n'est pas une preuve de fidelite a Odoo.

Tests : 13 tests du rapport passes nativement avec la bibliotheque standard et 4 controles CLI passes; fichiers d'entree inchanges. Un premier controle CLI a reproduit une confusion entre l'enveloppe du graphe et sa cle de metadonnees `graph`; detection corrigee et regression ajoutee avant publication. Ce premier lot n'integre pas encore le rapport dans le constructeur et ne modifie pas le schema.

Suite preparee et testee localement : integration du rapport au build, prevention des cibles de modeles non resolues pour heritage/delegation/relations, suppression des boucles EXTENDS d'extension en place, schema 12 et 5 tests du constructeur avec adaptateurs de dependances. Publication separee du lot 2; ces corrections ne font pas partie de ce premier commit.
