# Plan jour par jour — Agent de Code Intelligence (Odoo)

odoo 17(laisse des indications pour les autres versions, mais pas encore à traiter) , code en anglais,  objectif : integration d'une IA sur odoo utilisant llama 3.1 8b

**Règle transverse, valable à chaque jour ci-dessous** : tests écrits avant/avec le code, revue manuelle ligne à ligne pour tout ce qui touche `ir.rule`/`sudo()`/`has_group()`/`with_user()`, sourcing obligatoire (fichier+ligne ou identifiant d'enregistrement) sur tout élément produit, aucune story déclarée terminée sans réexécution du benchmark adversarial end-to-end complet (sortie brute conservée).

## Bloc 0 — B0 : résolveur nom-métier → nom-technique
*Bloquant absolu, priorité sur tout le reste 

- **J1 — mar. 28/07** : Extraire les labels déjà indexés dans le graphe (`string=` des champs, titres de menu, descriptions de modèle) comme cible du fuzzy-matching. Mettre en place `rapidfuzz` avec `token_set_ratio`/`token_sort_ratio` (jamais un ratio sur chaîne entière).
- **J2 — mer. 29/07** : Construire la table d'alias métier statique (courte, maintenue à la main) pour les synonymes sans chevauchement lexical (`mise à disposition ↔ asset.loan`, `avoir ↔ account.move`/`out_refund`). Brancher l'ordre : fuzzy-matching → table d'alias → arbitrage LLM borné sur liste fermée → statut "non résolu" explicite si rien ne matche.

Le code fait l'inverse — alias statique en premier, fuzzy ensuite 
Ce n'est pas une erreur d'implémentation — c'est une correction délibérée et documentée, verrouillée par test_s2_0_alias_not_shadowed_by_fuzzy_single_token. Le scénario réel : la requête "avoirs" (1 token) matchait un label de champ "avoirs" sur res.partner avec un score fuzzy de 100 (aucune pénalité de longueur sur un match 1-token/1-token), et écrasait la bonne réponse account.move. Inverser l'ordre corrige ça.

- **J3 — jeu. 30/07** : Tests unitaires du résolveur seul (cas synonymes, cas ambigus, cas hors périmètre). Brancher le résolveur en amont des 5 outils composites existants (`qui_a_acces_a`, etc.) pour qu'ils reçoivent enfin le bon `modele_odoo`.
- **J4 — ven. 31/07** : **Test de la vraie DoD** (distincte d'un test unitaire isolé) — rejouer le jeu adversarial complet et mesurer si le taux de réussite end-to-end progresse réellement, pas seulement si le résolveur renvoie une valeur plausible en isolation. Ajuster la table d'alias / les seuils fuzzy selon les échecs observés.

**Critère de fin du bloc** : le taux de réussite end-to-end du jeu adversarial progresse mesurablement par rapport aux 0/9 constatés, sortie brute à l'appui.


## Bloc 1 — `ir.rule` via `with_user()`
*Sécurité-critique — revue ligne à ligne obligatoire*

- **J5 — lun. 03/08** : Implémenter le wrapper `with_user(utilisateur_test).search(domaine)` (ou `check_access_rule`) pour chaque profil de test pertinent (aucun groupe / un groupe / groupes combinés) — pas de réimplémentation manuelle de l'algorithme ET global/OU groupe.
- **J6 — mar. 04/08** : Tests sur les cas déjà couverts par le jeu adversarial (test 6 notamment, qui stresse l'algorithme de combinaison). Vérifier la non-confusion avec un effet de contexte sans rapport (langue, société active, date système) — comparer à une observation directe en UI Odoo.
- **J7 — mer. 05/08** : Revue manuelle ligne à ligne documentée du mécanisme (pas seulement "les tests passent"). Rejouer le benchmark adversarial complet.

**Critère de fin** : mécanisme validé end-to-end sur le jeu adversarial + revue de sécurité documentée et archivée.
Où on en est sur le Bloc 1

J5 (wrapper with_user/vérification live) : validé, 13/13.
J6 (non-confusion contexte / test 6 combinaison ET/OU) : validé, 8/8, avec deux ajustements documentés plutôt que masqués :
le bug de direction IMPLIES (inversion in_edges/out_edges) trouvé et corrigé en cours de route — indépendant de Q6.1/Q6.2 mais bien réel, verrouillé par test_implied_group_hierarchy_expansion_direction
la limite mono-société de l'environnement de test, documentée explicitement dans test_active_company_context_restricts_to_authorized_company plutôt que testée à tort comme couverture multi-société
---

J7 (revue de sécurité ligne à ligne + rejeu benchmark) : 
## Bloc 2 — `ir.actions.server` / `base.automation` / `ir.cron`

- **J8 — jeu. 06/08** : Requête ORM des enregistrements (triviale). Mettre en place la lecture LLM bornée du champ `code` avec tag de confiance obligatoire sur chaque résultat.
- **J9 — ven. 07/08** : Vérifier spécifiquement que le bypass fournisseurs (test adversarial 5) est retrouvé **et** correctement tagué "interprétation LLM, confiance faible" — jamais présenté comme fait structurel certain.
- **J10 — lun. 10/08** : Rejouer le benchmark adversarial complet sur ce mécanisme + non-régression sur B0/Bloc 1.

**Critère de fin** : le tag de confiance est systématiquement présent et juste (vérifié par le test adversarial 5 et 9), sortie brute du benchmark à l'appui.

---

## Bloc 3 — Règles Semgrep : `_sql_constraints` et `domain=`

- **J11 — mar. 11/08** : Écrire les fixtures `# ruleid:` (TDD via `semgrep --test`) pour `_sql_constraints`.
- **J12 — mer. 12/08** : Écrire les règles pour `domain=` sur champs relationnels (Many2one/Many2many) avec conditions imbriquées.
- **J13 — jeu. 13/08** : Revue de la précision du pattern YAML (risque faux positif/négatif) — pas une revue de code Python. Rejouer le benchmark.

**Critère de fin** : `semgrep --test` vert sur toutes les fixtures + revue de précision documentée.

---

## Bloc 4 — Vérification systématique du sourcing

- **J14 — ven. 14/08** : Test mécanique (pas à l'œil) que chaque source retournée par les 3 mécanismes ci-dessus (Blocs 1-3) correspond réellement à un élément produit — fichier+ligne ou identifiant d'enregistrement vérifiable, jamais une chaîne plausible non vérifiée.

**Critère de fin** : script de vérification de sourcing passant sur les 3 mécanismes, intégré au harness.

---

## Bloc 5 — Non-régression complète + clôture du cycle E1/E2

- **J15 — lun. 17/08** : Rejouer l'intégralité des 9 modules adversariaux (y compris le module 9, détection d'ignorance).
- **J16 — mar. 18/08** : Consolider le rapport — sortie brute du benchmark collée au rapport, pas un résumé. Comparer à la grille de vérité terrain.
- **J17 — mer. 19/08** : Revue avec le maître de stage — clôture officielle du cycle E1/E2 corrigé (B0 + Blocs 1-4), recalage du planning restant selon la vélocité réellement observée sur ce cycle.

**Critère de fin** : preuve end-to-end complète sur les 9 modules, actée avec le maître de stage.


## Bloc 6 — Sprint C, point resté ouvert : routeur et conflit inter-branches
*RAG documentaire vs Function Calling vs Code Intelligence*

- **J18-J19 — jeu. 20/08 → ven. 21/08** : Construire le jeu d'exemples few-shot couvrant les cas ambigus à la frontière des trois branches (ex. "qui peut approuver un avoir de plus de 500 000 Ar ?" — à la fois gouvernance et potentiellement documenté au wiki RAG).
- **J20-J21 — lun. 24/08 → mar. 25/08** : Implémenter la politique explicite de résolution de conflit (pas seulement de sélection de branche) — le code doit primer comme source de vérité en cas de divergence avec le wiki RAG.

**Critère de fin** : politique de résolution de conflit testée sur le jeu few-shot, décision documentée (quelle branche prime et pourquoi) pour chaque cas ambigu du jeu.


## Bloc 7 — Contrôle d'accès sur la réponse elle-même
*Gap confirmé, distinct du contrôle d'accès aux données déjà couvert par le Function Calling ERP*

- **J22 — mer. 26/08** : Trancher la décision produit avec le maître de stage — gating généralisé (toute explication filtrée selon les droits du demandeur) vs gating ciblé (seuls les contournements déjà identifiés comme sensibles sont masqués/généralisés).
- **J23-J24 — jeu. 27/08 → ven. 28/08** : Implémenter l'option retenue. Ajouter l'état explicite "élément omis pour raison d'autorisation" — distinct du score de couverture (A1), pour ne pas casser le principe de sourcing.
- **J25-J26 — lun. 31/08 → mar. 01/09** : Test sur le test adversarial 3 (liste de validateurs codée en dur) — vérifier qu'un utilisateur sans droit ne reçoit plus l'information brute d'un contournement caché.

**Critère de fin** : décision produit actée, mécanisme testé sur le cas adversarial 3, non-régression sur le reste du benchmark.

## Bloc 7-bis — Revision 2026-08-07 : gouvernance vs contournement, et disponibilite reelle des actions

Deux ajustements decides le 07/08 avec le maitre de stage, en plus du gating cible de J23-24 :

- **Gating resserre au strict contournement** : les noms/`domain_force` d'`ir.rule` pour les groupes dont le demandeur n'est pas membre ne sont plus masques (ils l'etaient depuis J23-24, cible sur une seule ligne). Ce n'est pas un mecanisme de contournement, c'est de la gouvernance/portee (qui voit quoi selon quelle region/plafond) -- meme categorie que « qui peut approuver ? », qui doit rester ouverte a tous. Seul `SENSITIVE_BYPASS_MARKER` (sudo(), emails/IDs codes en dur) reste filtre selon l'identite du demandeur. Voir `authorization_gate.py` (docstring revise) + `test_j23_24_authorization_gate.py::test_ignored_group_rule_details_are_never_redacted`.
- **Disponibilite reelle sur les questions « comment faire X ? »** : `chemin_execution_bouton` accepte desormais `user_groups` et calcule `available_to_demandeur` en reutilisant le meme resolveur de groupe tolerant que le Bloc 1 (jamais une deuxieme implementation de l'algorithme de droits). Si l'action n'est pas disponible pour le demandeur reel (memes groupes signes JWT que le reste du Bloc 7, jamais devines par le LLM), la reponse doit dire explicitement que l'option n'existe pas dans l'interface pour lui, plutot que d'expliquer un mecanisme qu'il ne peut pas declencher. Voir `deterministic_tools.py`, `ci_agent_tools.py`, `rag/graph.py` (CI_SYSTEM_PROMPT regle 6, `_override_user_groups_arg`) et `test_j22bis_button_availability_gate.py`.

**A verifier (non execute dans cette session -- pas d'acces d'execution sur cette machine, uniquement lecture/ecriture de fichiers)** : rejouer `pytest code_intelligence/tests/test_j23_24_authorization_gate.py code_intelligence/tests/test_j22bis_button_availability_gate.py code_intelligence/tests/test_j25_26_e2e_purchase_bypass_gate.py -v`, puis le benchmark adversarial complet (Q1.1/Q1.2 notamment, pour confirmer que les noms de regles regionale/nationale apparaissent desormais dans la reponse) avant de considerer ce point clos.

---

## Bloc 8 — Sprint E : robustesse et cas limites

- **J27 — mer. 02/09** : Cycles d'héritage — test de non-régression avec cycle artificiel injecté dans le corpus de test (détection déjà posée en A2, à couvrir en non-régression ici).
- **J28-J29 — jeu. 03/09 → ven. 04/09** : Symboles ambigus — présenter les candidats multiples à l'agent avec leur module d'origine, laisser l'agent (ou l'utilisateur) trancher plutôt que de choisir arbitrairement le premier trouvé.
- **J30-J31 — lun. 07/09 → mar. 08/09** : Performance — fixer un budget de latence explicite (ex. 90ᵉ percentile sous X secondes pour une navigation à 3 sauts + 1 appel XML-RPC live) et le mesurer réellement.
- **J32-J33 — mer. 09/09 → jeu. 10/09** : Sécurité — test d'injection sur les requêtes d'extraction massive ("liste-moi toutes les règles de tous les modèles"), implémenter rate-limiting logique ou refus explicite au-delà d'un périmètre donné.

**Critère de fin** : les 4 cas limites (cycles, ambiguïté, latence, extraction massive) ont chacun un test de non-régression vert et un chiffre/comportement documenté.

Où on en est sur le Bloc 8 (mis à jour 06/08, plan retrouvé en retard sur le code réel)

J27 (cycles d'héritage) : clos, 3/3 — cycle 2-modèles, cascade 3-modèles, auto-héritage, sous 2s.
J28-J29 (symboles ambigus) : clos, 7/7 — `DEFINED_IN` par module, note "SYMBOLE AMBIGU" exposée à l'agent.
J30-J31 (budget de latence) : **déjà fait**, contrairement à ce que ce plan indiquait — `run_adversarial_benchmark.py` calcule réellement p50/p90/p95 sur le temps effectif (hors attente Groq) et compare à `LATENCY_BUDGET_P90_SECONDS=12.0s`. Chiffre documenté le 06/08 : p90 = 6.84s ✅. Constantes dans `config/settings.py`.
J32-J33 (extraction massive) : **déjà fait** — `_is_massive_extraction_request`/`_is_prompt_injection` (rag/graph.py) + `MAX_MODELS_PER_QUERY=3`, refus explicite testé et vert (`test_j32_33_massive_extraction_guard.py`).
En creusant J28-29, un gap hors-périmètre trouvé le même jour : bug réel de surcharge en cascade sur `action_valider_avoir` (VIP/regional/base), traité comme un mini-cycle complet à part — dispatch forcé ajouté (`analyser_chaine_surcharge_methode`), garde structurelle trop large corrigée (explosion à 17 hops sur un modèle partagé comme account.move), instruction de synthèse manquante corrigée (le finding n'atteignait jamais le prompt de synthèse). Voir Bloc 9 pour la suite (gap de généralisation trouvé en marge).

---

## Bloc 9 — Généralisation au code custom : jeu adversarial complémentaire
*Approfondissement de ce qui existe déjà, en attendant l'accès au vrai code MiroKE*

- **J34-J35 — ven. 11/09 → lun. 14/09** : Construire des modules custom "adversariaux" supplémentaires si les 9 existants ne couvrent pas encore : héritage en cascade sur 4-5 niveaux, `domain_force` complexe à conditions imbriquées, champs calculés à dépendances croisées inter-modules, sécurité vérifiée à la main (`has_group()`) plutôt que via `ir.rule`, code sans docstring.
- **J36 — mar. 15/09** : Rejouer le Sprint D complet sur ce jeu élargi, consolider le rapport en distinguant explicitement "validé sur modules standards" / "validé sur custom synthétique" / "à confirmer sur le vrai code MiroKE".

**Critère de fin** : rapport de couverture à trois niveaux (standard / custom synthétique / vrai code — en attente) documenté et partagé avec le maître de stage.

Où on en est sur le Bloc 9 (mis à jour 06/08)

J34-J35 (module custom adversarial supplémentaire, héritage 5 niveaux) : le module `custom_deep_inheritance_security` existe et sa couche extraction est testée et verte (`test_j34_35_deep_custom_modules.py`, 5 niveaux d'héritage, `domain_force` imbriqué, messages `UserError`/`ValidationError`) — mais ces tests exercent la couche extraction/parsing en isolation, jamais `code_intelligence_agent` de bout en bout. Rejeu manuel via un script de contrôle (`scripts/check_j34_35_e2e.py`, une question réelle sur ce module) a révélé un vrai gap de généralisation, pas ponctuel à ce module : `business_resolver._build_fuzzy_index()` n'indexait jamais le nom technique brut d'un modèle (`_name`), seulement sa `_description`/labels de champs/noms de menu — donc une question nommant le modèle technique verbatim pouvait ne jamais se résoudre, désactivant silencieusement tous les dispatches forcés J8/J9/Bloc 9 pour ce modèle. Corrigé (indexation du nom technique + nouvelle étape "exact_technical_mention" prioritaire dans `resolve_business_term`, 3 tests ajoutés, verts). Deuxième gap trouvé sur le même rejeu : l'outil renvoyait bien les deux verrous réels (seuils 50k€ et 100k€) mais la synthèse ne répondait qu'au premier volet d'une question à deux volets — corrigé par une instruction explicite dans `synthesis_prompt` (traiter chaque partie de la question, chaque message de verrou comme un finding distinct). Rejeu final : les deux seuils sont correctement surfacés. **J34-35 considéré clos côté extraction ET E2E maintenant**, mais la méthode (vérifier E2E, pas seulement les tests unitaires isolés) doit être répliquée sur les 8 autres modules adversariaux avant de clore complètement le bloc.
J36 (rejeu Sprint D complet + rapport à trois niveaux) : **corrigé et confirmé 07/08.** Root cause : `get_code_intelligence_graph()` (rag/graph.py) ne chargeait jamais le vrai module Odoo `hr_expense` (dépendance directe de `custom_expense_risk_base`), donc `model:hr.expense` n'existait jamais dans le graphe -- corrigé en chargeant aussi les dépendances directes (un niveau) de chaque module `custom_*`. Rejeu E2E réel (`eval_j36_expense_risk_llm.py`, vrai `code_intelligence_agent` + LLM) : **8/8 (100%)**, voir `eval_report_j36_expense_risk.md`. Test de non-régression rapide/sans LLM ajouté et exécuté par l'équipe (`test_f08_j36_graph_dependency_loading.py`) : **3/3 verts en 8.92s**. Voir `todo/etat_reel.md` Bloc 9 pour le détail complet et la leçon sur la fraîcheur des docs. Bloc 9 dans son ensemble reste non clos : la méthode de vérification E2E doit encore être répliquée sur les 8 autres modules adversariaux.

---

## Bloc 10 — Sprint F : détection de staleness et mise à jour incrémentale

- **J37-J39 — mer. 16/09 → ven. 18/09** : Implémenter les trois niveaux de mise à jour (recalcul du fichier modifié + propagation aux arêtes invalidées ailleurs dans le graphe + détection des cas non couverts par un recalcul local).
- **J40-J41 — lun. 21/09 → mar. 22/09** : Cohérence pendant le recalcul — construire le nouveau graphe à part, swap atomique du `graphml` servi (jamais de modification en place pendant une requête en cours). Versionner l'index avec un hash de commit.
- **J42 — mer. 23/09** : Test de non-régression — vérifier qu'aucune requête ne voit jamais un graphe à moitié reconstruit pendant un swap.

**Critère de fin** : swap atomique testé sous requêtes concurrentes, index versionné par commit.

---

## Bloc 11 — Sprint F : renommage (intégration PyRef)

- **J43-J44 — jeu. 24/09 → ven. 25/09** : Intégrer PyRef (SCAM 2021) dans le hook git — tourner PyRef entre ancienne et nouvelle version de chaque fichier modifié.
- **J45 — lun. 28/09** : Sur détection de renommage à confiance suffisante, relabelliser le nœud existant (`nom_precedent` en attribut) plutôt que supprimer+recréer. Documenter le taux de rappel mesuré (76,1%) comme limite résiduelle assumée, pas comme angle mort.

**Critère de fin** : cas de renommage testé de bout en bout (nœud relabellisé, historique conservé), limite résiduelle documentée.

---

## Bloc 12 — Sprint F : observabilité et budget

- **J46-J47 — mar. 29/09 → mer. 30/09** : Logging structuré du chemin de raisonnement — un appel d'outil composite + sa traversée interne, indexé et lisible en debug post-hoc.
- **J48 — jeu. 01/10** : Chiffrer le budget coût/latence global de l'agent (nombre d'appels LLM par question vs RAG simple et Function Calling), poser un plafond de sauts/appels par question comme garde-fou budgétaire.

**Critère de fin** : dashboard/log exploitable pour une question type, plafond de sauts appliqué et testé.

---

## Bloc 13 — Interopérabilité inter-version (v11 confirmée dans le parc)
*Gap explicitement différé dans le document source, repris ici une fois le goulot B0 et le cycle E1/E2 clos*

- **J49-J51 — ven. 02/10 → mar. 06/10** : Monter une instance Odoo v11 (ou la plus ancienne confirmée chez un client), rejouer le pipeline d'extraction (A1) tel quel, vérifier le branchement JS legacy (Widget/QWeb pré-OWL) déjà prévu en A1.
- **J52 — mer. 07/10** : Rejouer le jeu adversarial (adapté si nécessaire aux mécanismes disponibles en v11) sur cette instance, consolider les écarts.

**Critère de fin** : rapport explicite "généralisation confirmée / limites observées" sur au moins une version antérieure à v17.

---

## Bloc 14 — Suite de régression vivante sur l'écosystème OCA

- **J53-J56 — jeu. 08/10 → mar. 13/10** : Mettre en place le pipeline en CI, déclenché à chaque modification de l'extracteur ou du registre Semgrep, sur un échantillon large et croissant de vrais modules OCA (branche 17.0).
- **J57 — mer. 14/10** : Premier rapport de couverture représentatif (pas anecdotique) sur cet échantillon, comparé au jeu des 9 cas fixes.

**Critère de fin** : CI opérationnelle et déclenchée automatiquement, premier rapport de couverture OCA produit.

---

## Bloc 15 — Dès accès au vrai code MiroKE obtenu
*Non daté précisément — bloqué par l'accès, pas par la conception ; à insérer dès que l'accès est accordé, quelle que soit la date réelle*

- **Jour A** : Détection de version (`__manifest__.py`), montage d'une instance Odoo de la bonne version avec le vrai corpus.
- **Jour A+1 à A+3** : Rejouer le Sprint A (extraction) sur le vrai code — mesurer le score de couverture réel par module (A1), identifier les patterns non reconnus.
- **Jour A+4 à A+6** : Rejouer le Sprint D complet (jeu de gouvernance en langage métier) sur le vrai corpus, comparer aux résultats obtenus sur modules standards/synthétiques.
- **Jour A+7** : Rapport final de généralisation — confirmer ou infirmer l'hypothèse centrale du projet sur du code custom réel, pas seulement synthétique.

**Critère de fin** : rapport de validation réelle, seule preuve qui compte à terme selon le document source.

---

## Bloc 16 — Marge, consolidation, mémoire

- **J58-J75 — jeu. 15/10 → lun. 09/11** : Marge pour imprévus (accès MiroKE tardif, corrections issues des blocs précédents, allers-retours avec le maître de stage), rattrapage si un bloc a débordé. Rédaction progressive des parties du mémoire correspondant aux blocs déjà clos (choix architectural section 0, état de l'art, taxonomie SAP, résultats du spike).
- **J76-J85 — mar. 10/11 → ven. 20/11** : Rédaction du mémoire (sections restantes), consolidation des rapports de benchmark en annexes, relecture.
- **J86-J90 — lun. 23/11 → lun. 30/11** : Relecture finale, préparation de la soutenance, dernière non-régression complète avant remise.

## Explicitement hors de ce planning (différé au-delà de fin de stage 2026)

Ces points restent dans le plan source mais **ne doivent consommer aucun jour ci-dessus** tant que la condition de déclenchement n'est pas remplie :

- **Interorrivé.


## Table de correspondance rapide (blocpérabilité multi-tenant** (plusieurs clients sur un même serveur mutualisé) — hors scope tant que MiroKE reste l'unique client cible. Redevient un sujet si un deuxième client est ajouté au périmètre.
- **Infrastructure locale, POC démonstrable** — hors scope tant que le matériel local n'est pas a → item du plan source)

| Bloc | Référence dans `plan_unifie_agent_code_intelligence.md` |
|---|---|
| 0 | Partie B, "Prochaines étapes", item 0 (B0) |
| 1-4 | Partie B, "Prochaines étapes", items 1-4 |
| 5 | Partie B, "Prochaines étapes", item 5 |
| 6 | Sprint C, "Routeur étendu et résolution de conflit" |
| 7 | "Contrôle d'accès sur la réponse elle-même" |
| 8 | Sprint E |
| 9 | "Interopérabilité — état réel", point 1 (généralisation) |
| 10-12 | Sprint F |
| 13 | "Interopérabilité — état réel", gap différé |
| 14 | Sprint D, "Suite de régression vivante OCA" |
| 15 | Gaps différés, "Accès au vrai code MiroKE" |






