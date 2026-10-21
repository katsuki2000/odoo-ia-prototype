# Plan et tableau de decision -- MIRO AI

Consolide le 17/10/2026 (journal 1468). Ce fichier remplace `plan.md` (P0-P10), `plan_resolveur.md` (Plan R), les trois bilans du resolveur et les 12 journaux de branche de la semaine du 14-15/10. Il vit a cote de `contexte.txt` (journal, source de verite de l'historique), `architecture.md` et `rules.md`. Les originaux sont dans git (HEAD 228f3b9) et dans `.scratch/todo_avant_1468/`.

Lecture : **A** = ce qu'il faut decider maintenant ; **B** = plan d'execution P0-P10 ; **C** = Plan R du resolveur (PR0-PR4) ; **D** = audit du resolveur du 15/10 et ce qu'il en reste ; **E** = lots de branches deja fusionnes (memoire).

## A. Decisions en attente (par priorite, etat au 17/10/2026)

1. **Taille de la liste dense de l'arbitre** (`HYBRID_SEMANTIC_LIMIT`, passee de 10 a 20 en 1460, appliquee aussi dans `dense_lookup.py`). Sonde de 120 appels (1467) : HRL-Q1 et HRL-Q2 passent de 0/10 a 10/10 `hr.leave` ; SAL-Q3 et STK-Q2 se stabilisent ; mais PUR-Q1 (temoin, libelle cite) bascule sur `res.users` 3 fois sur 5 a 20 (5/5 `purchase.order` a 10), car la liste plus longue ajoute des aimants (groupe « User »). Options : **A** garder 20 ; **B** revenir a 10 (non recommande : HRL de nouveau a 0) ; **C** garder 20 et ne pas ajouter de candidats denses quand un libelle est cite (ou le resoudre sans arbitre), un seul changement a mesurer sur PUR-Q1 ; **D** epingler le serveur d'inference (voir 2). Recommandation : D puis C.
2. **Epingler le serveur d'inference** : modele, version et quantification consignes a chaque audit, comparaisons seulement a serveur constant. Raison : les reponses de l'arbitre changent de regime apres une reconnexion (1467), et le meme code a donne 45/48 (1456), 46/48 (1461) puis 44/48 (1462) : l'ecart entre deux passages est de la taille du gain mesure.
3. **Amendement a la section 1227** (journal 1436 / `config.json`) : le systeme R0 (resolveur de production avec alias statiques) est retire d'E1 avec les alias ; R1 devient la reference. A valider par pmm.
4. **Echeance de livraison du 20/10/2026** (3 jours) : selon le Plan R (C, section 4), seules PR0 et PR1 sont realistes avant ; PR2 seulement si PR1 est favorable ; sinon la livraison documente que les termes ambigus passent par clarification. `todo/perimetre_livraison_20_octobre.md`, cite par le Plan R, **n'existe pas dans le depot** : le retrouver ou le recreer avant toute decision de perimetre.
5. **Decision D1 d'E1 (generateur de candidats hybride en production ?)** : aucun bras teste n'a satisfait son critere pre-ecrit (B = liste de 10 rejetee, 1367 ; C = annotation par les boutons non retenue, 1376). R4 (BM25 + dense, RRF) a mesure 9 positifs sur 12 dans le top 10 contre 7 pour le dense de production et 8 pour le flou (1365) : c'est l'argument pour passer un jour de la concatenation actuelle (libelles cites + 5 lexicaux + N denses) a une fusion RRF. Je n'ai pas trouve de decision D1 formelle dans le journal ; le calibrage reste partiel (decision de pmm du 13/10 : tranche partielle d'abord, >= 120 cas avant D1). A confirmer par pmm : etat reel du calibrage et date de D1.
6. **Echecs de rappel non rattrapables par un reglage** (1459) : MNT-Q4 et DDI-Q2 absents de tous les etages (dense, lexical, liste fermee) ; STK-Q1 (`stock.quant` jamais retenu) ; CNV-Q1 / CNV-Q2 resolvent `res.groups` ; resolutions vers des assistants (`validate.account.move` pour CNA-Q2 ; `payment.refund.wizard` vu en 1461). Seul le lexique lie aux objets (P4) peut les traiter ; non faisable en un seul mandat. **Verite terrain de CNA-Q2 a confirmer** : mon attendu (`account.move`) est un jugement, l'arbitre retient `validate.account.move` 10 fois sur 10.
7. **Suite de tests** : dernier `pytest -m "not integration"` complet (17/10) : 2832 passed, 18 skipped, 2 failed, 1 erreur de collecte ; les 3 ont ete corriges en 1457-1458 (amendement 1436 attendu par `test_e1_arbitration`, parametre retire dans `test_resolver_tiebreaker`, `scripts/run_bloc_n1_benchmark.py` restaure depuis HEAD) mais la suite n'a pas ete rejouee. `test_s2_0_llm_arbitration_picks_valid_candidate` est un flaky connu en suite complete.
8. **Index dense de production** : matrice numpy en memoire (E1) ou Chroma ; a trancher apres PR1 selon persistance, mise a jour incrementale et filtre par type de noeud (note 1281).
9. **Rangement** : `pratiques_odoo.md` (guide de pratiques de code Odoo) n'est pas un plan et reste dans `todo/` ; le deplacer (par exemple `docs/`) ou le supprimer est une decision de pmm.

### Etat des audits de resolution (banque native + custom, 48 questions, `scripts/audit_question_resolution.py`)
41/48 (1435) -> 45/48 (1456, apres libelles cites + phrase de prompt) -> 46/48 et 44/48 a code constant (1461-1462, apres liste a 20). Echecs stables : DDI-Q2, MNT-Q4. « Resolu » ne veut pas dire « correct » : l'audit ne verifie pas le modele choisi.

### Points techniques encore ouverts, herites des lots d'audit du 15/10 (statut a revalider apres la fusion de 1406)
- Chemin des arguments metier de `tool_helpers` : distinct du resolveur du tour, sans arbitrage partage (constat non declare clos).
- Budget strict d'appels LLM : le budget `CI_MAX_HOPS` borne les tentatives d'outils, pas les appels LLM internes aux outils composites.
- Cache disque semantique : verrouillage / fusion interprocessus non traites ; anciens helpers hors chemin actif (`candidates.py`) non supprimes ; cout de l'empreinte du graphe a chaque verification, cold start du cache BGE et latence des suivis non mesures.
- Planification semantique (lot `capability_catalogue` / `capability_planner`) : aucun replay reel Kaggle / BGE / Odoo des paraphrases ; comparaisons de personas du harnais sans candidats distincts par persona ; anciens modules `predispatch_*` conserves ; globals historiques des wrappers de tools non refactores (pas de garantie d'isolation multi-requetes).
- Frontiere API : le point `/api/v1/health` detaille exige un administrateur, le LLM n'y est pas sonde ; politique de visibilite des sources, rattrapages d'acces / d'approbation, suffisance de preuve, etat global de requete et budgets de preuve hors de ces lots ; payloads d'erreur d'ingestion non couverts.
- Verifier de bout en bout qu'aucune regression de synthese ou de securite n'a ete introduite par le remaniement de `loop.py` (1407) : couvert en partie par la suite complete, a rejouer.

---

# B. Plan d'execution (P0 a P10)

