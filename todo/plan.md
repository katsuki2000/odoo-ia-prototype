# Plan unifie — Agent de Code Intelligence (Odoo)

Ce fichier fusionne l'ancien `real plan.md` (plan operationnel jour par jour, B0-Bloc 16) et `plan_architecture_cible.md` (plan de comblement des ecarts avec `architecture.md`). Un seul fichier de reference pour le projet a partir du 18/08/2026.

**Regle transverse, valable a chaque bloc ci-dessous** : tests ecrits avant/avec le code, revue manuelle ligne a ligne pour tout ce qui touche `ir.rule`/`sudo()`/`has_group()`/`with_user()`, sourcing obligatoire (fichier+ligne ou identifiant d'enregistrement) sur tout element produit, aucune story declaree terminee sans reexecution du benchmark adversarial end-to-end complet (sortie brute conservee).

---

# PARTIE 1 — Blocs clos (B0 a Bloc 9)

*Detail complet dans `etat_reel.md`. Resume ici pour reference.*

## Bloc 0 — B0 : resolveur nom-metier -> nom-technique — CLOS

- J1-J4 (28-31/07). Fuzzy-matching (`rapidfuzz`), table d'alias statique, arbitrage LLM borne.
- Ordre alias-d'abord (pas fuzzy-d'abord) : correction deliberee, verrouillee par `test_s2_0_alias_not_shadowed_by_fuzzy_single_token`.

## Bloc 1 — `ir.rule` via `with_user()` — CLOS

- J5-J7 (03-05/08). Wrapper `with_user()`, algorithme ET global/OU groupe, revue de securite ligne a ligne (`j7_security_review.md`).
- 13/13 J5, 8/8 J6, benchmark vert J7.

## Bloc 2 — `ir.actions.server` / `base.automation` / `ir.cron` — CLOS

- J8-J10 (06-10/08). Lecture LLM bornee du champ `code`, tag de confiance obligatoire.

## Bloc 3 — Regles Semgrep : `_sql_constraints` et `domain=` — CLOS

- J11-J13 (11-13/08). Fixtures TDD, revue de precision (`j13_semgrep_precision_review.md`).

## Bloc 4 — Verification systematique du sourcing — CLOS

- J14 (14/08). Script de verification mecanique fichier+ligne sur les 3 mecanismes.

## Bloc 5 — Non-regression complete + cloture E1/E2 — CLOS

- J15-J17 (17-19/08). Rejeu integral des 9 modules adversariaux, rapport consolide.

## Bloc 6 — Routeur et conflit inter-branches — CLOS

- J18-J21 (20-25/08). Politique de resolution de conflit code-prime-sur-RAG.

## Bloc 7 — Controle d'acces sur la reponse + Bloc 7-bis — CLOS

- J22-J26 (26/08-01/09) + revision 07/08.
- Gating cible : seul `SENSITIVE_BYPASS_MARKER` (sudo(), emails/IDs codes en dur) filtre selon l'identite du demandeur. Gouvernance/portee (ir.rule, groupes, plafonds) ouverte a tous.
- Disponibilite reelle des boutons via `user_groups` + resolveur de groupe tolerant.
- 18/18 tests (authorization_gate + button_availability + e2e_purchase_bypass).

## Bloc 8 — Sprint E : robustesse et cas limites — CLOS

- J27-J33 (02-10/09).
- Cycles d'heritage : 3/3. Symboles ambigus : 7/7. Latence : p90=6.84s (temps algo hors reseau Groq). Extraction massive : refus explicite, `MAX_MODELS_PER_QUERY=3`.

## Bloc 9 — Generalisation au code custom — CLOS (confirme 17/08)

- J34-J36 + 8 modules adversariaux.
- 8/8 modules E2E confirmes verbatim : credit_note_approval, credit_note_visibility, hr_leave_workflow, purchase_request, asset_loan, automation_traps, expense_reimbursement_indirect, deep_inheritance_security.
- Suite pytest : 764/764. `test_graph.py` : 136/136.

---

# PARTIE 2 — Constat de depart (18/08)

Le systeme repond deja aux questions de la vision (`architecture.md`) via un scaffolding deterministe efficace, mais deux briques de l'architecture cible n'existent qu'implicitement :

1. **Investigation Planner** — la vision veut un plan explicite produit avant l'execution. Le code reel fait dispatcher force par regex + boucle ReAct plafonnee (`CI_MAX_HOPS=4`) — un plan implicite, jamais ecrit, jamais inspectable.
2. **Semantic Layer / Ontologie + tags** — la vision veut des tags explicites sur le graphe (`visibility_rule`, `blocking_rule`, `approval_rule`, `acl`, `computed_field`, `server_action`...). Le code reel encode cette classification en dur dans le choix de l'outil appele, jamais comme attribut porte par les noeuds eux-memes.

Ces deux gaps conditionnent la lisibilite et l'auditabilite du systeme pour un non-developpeur — l'objectif final d'`architecture.md`.

---

# PARTIE 3 — Plan a venir (P0-P6 + Bloc 16)

## Bloc P0 — Verification prealable : statut reel des Blocs 10-12
*Prerequis avant tout le reste — etat des lieux non tranche*

`graph_staleness_detector.py`, `atomic_graph_swap.py`, `graph_symbol_refactor.py`, `graph_version.py` et `reasoning_trace_logger.py` existent deja sur disque et semblent utilises (`reasoning_trace_logger` est appele dans `rag/graph.py`), mais aucune cloture n'apparait dans `etat_reel.md` (qui s'arrete apres Bloc 9) — statut reel inconnu.

- **Jour 1** : Relire `contexte.txt` en entier a la recherche de toute mention Bloc 10/11/12, J37-J48. Lister ce qui est confirme teste (pytest reellement execute, sortie collee) vs. seulement ecrit.
- **Jour 2** : Pour tout ce qui n'a jamais ete confirme par une execution reelle, rejouer : `pytest miro-rag/code_intelligence/tests/test_bloc10_incremental_event_logging.py test_bloc10_j37_39_staleness_detection.py -v`, `pytest miro-rag/code_intelligence/tests/test_j37_j42_staleness_and_atomic_swap.py test_j43_j45_symbol_rename_refactoring.py test_j46_j48_reasoning_trace.py -v`.
- **Jour 3** : Mettre a jour `etat_reel.md` avec un paragraphe Bloc 10-12 explicite, meme si le verdict est "deja fait, juste jamais documente ici".

**Critere de fin** : chaque bloc 10/11/12 a un statut ecrit noir sur blanc dans `etat_reel.md`, appuye sur une execution reelle.

### Rappel du contenu des Blocs 10-12 (plan original)

**Bloc 10 — Sprint F : detection de staleness et mise a jour incrementale**
- J37-J39 : 3 niveaux de mise a jour (recalcul fichier modifie + propagation aretes invalidees + detection cas non couverts par recalcul local).
- J40-J41 : Swap atomique du graphml servi (jamais de modification en place pendant une requete en cours). Versionner l'index avec un hash de commit.
- J42 : Test de non-regression — aucune requete ne voit jamais un graphe a moitie reconstruit pendant un swap.
- Critere de fin : swap atomique teste sous requetes concurrentes, index versionne par commit.

**Bloc 11 — Sprint F : renommage (integration PyRef)**
- J43-J44 : Integrer PyRef (SCAM 2021) dans le hook git.
- J45 : Relabelliser le noeud existant (`nom_precedent` en attribut) plutot que supprimer+recreer. Documenter le taux de rappel mesure (76,1%) comme limite residuelle assumee.
- Critere de fin : cas de renommage teste de bout en bout, limite residuelle documentee.

**Bloc 12 — Sprint F : observabilite et budget**
- J46-J47 : Logging structure du chemin de raisonnement.
- J48 : Chiffrer le budget cout/latence global de l'agent, poser un plafond de sauts/appels par question.
- Critere de fin : dashboard/log exploitable pour une question type, plafond de sauts applique et teste.

---

## Preconditions a valider avant P1/P2
*Hypotheses non tranchees — a statuer avant d'entamer P1/P2*

### H1. Tester `business_resolver` avant `route()`

**Motivation** : le composant le plus robuste (`business_resolver`) intervient aujourd'hui apres le plus fragile (`route()`).

**Dependance sur Bloc P1** : le Bloc P1, Jour 1-2 pose la question « plan genere par LLM dedie, ou reconstruit a posteriori depuis les hops traces ? ». Cette decision depend directement de H1 : si `business_resolver` doit passer avant `route()`, la toute premiere etape du plan change de nature.

**Se rattache a** : noeud Semantic Understanding.

**Statut** : Non valide.

---

### H2. Tester `active_model` / `active_id`

**Motivation** : le contexte UI n'est actuellement pas propage.

**Se rattache a** : Semantic Understanding en entree, Couche 4 — Runtime Odoo en aval.

**Statut** : Non valide.

---

### H3. Tester un mecanisme d'arbitrage entre preuves concurrentes

**Se rattache a** : se situe avant Code Intelligence Engine dans le pipeline — donc temporellement a l'oppose d'Evidence Builder, qui intervient apres. Voir la note de desambiguation Evidence Check / Evidence Builder dans `architecture.md`.

**Statut** : Conceptuel. Non implemente.

---

## Bloc P1 — Investigation Planner explicite
*Ferme le premier ecart architecture.md — priorite haute, conditionne la lisibilite du raisonnement pour un non-developpeur*

- **Jour 1-2** : Concevoir le schema d'un "plan" serialisable (liste d'etapes typees : `{action, cible, justification}`), a produire AVANT tout appel d'outil reel — pas un remplacement du dispatch force existant (qui reste le filet de securite deterministe), mais une couche d'explicitation posee devant lui. Decider : plan genere par un appel LLM borne dedie (liste fermee d'actions possibles = les 9 outils existants), ou plan reconstruit a posteriori a partir des hops deja traces par `reasoning_trace_logger.py` (moins de risque, mais ne respecte pas "produit avant l'execution" de la vision — a trancher explicitement, documenter le choix).
- **Jour 3-4** : Implementer le planner choisi. S'il est genere a priori par LLM : un appel dedie, sortie contrainte (schema Pydantic type `QueryRoute`/`DataQueryIntent` deja en place dans `rag/schemas.py`), jamais du texte libre non structure.
- **Jour 5** : Exposer le plan dans la reponse finale, dans le "niveau verification" depliable deja existant (le chevron du widget Discuss) — pas seulement en log serveur.
- **Jour 6** : Tests — le plan produit correspond-il reellement aux outils appeles dans le tour ? (test de coherence plan/execution, pas seulement "un plan a ete genere"). Rejouer le benchmark adversarial complet, verifier zero regression sur les 8 modules Bloc 9.

**Critere de fin** : chaque reponse Code Intelligence porte un plan explicite, inspectable, verifie coherent avec les outils reellement appeles — benchmark adversarial toujours vert.

---

## Bloc P2 — Couche Ontologie + tags semantiques explicites
*Ferme le second ecart architecture.md*

- **Jour 1** : Definir la liste fermee des tags comportementaux (`visibility_rule`, `blocking_rule`, `calculation_rule`, `workflow_rule`, `approval_rule`, `notification_rule`) et techniques (`record_rule`, `acl`, `constraint`, `computed_field`, `server_action`, `cron`) d'`architecture.md`, comme enumeration dans le code (pas en dur dispersee).
- **Jour 2-3** : Annoter chaque noeud pertinent du graphe (`graph_builder.py`) avec ces tags au moment de la construction — derives de ce que l'extraction sait deja (un `Rule` node vient de `ir.rule` -> tag `record_rule` + `visibility_rule` ; un `AccessEntry` -> tag `acl` ; une methode avec `has_group()`+`raise` -> tag `blocking_rule`, etc.). Reutiliser la classification deja faite implicitement par le choix d'outil comme point de depart.
- **Jour 4** : Exposer ces tags aux 5 outils composites (ils peuvent desormais interroger "quels noeuds ont le tag `approval_rule` pour ce modele" au lieu de connaitre statiquement quel outil traite quel cas) — sans casser le dispatch force existant.
- **Jour 5** : Tests de couverture — chaque type de noeud produit par l'extraction a-t-il au moins un tag ? Detecter les noeuds non classes (gap de couverture de l'ontologie elle-meme). Rejouer le benchmark adversarial complet.

**Critere de fin** : 100% des noeuds Rule/AccessEntry/Method-avec-verrou/ServerAction du graphe portent au moins un tag comportemental et un tag technique ; aucune regression sur le benchmark.

---

## Bloc P3 — Inference locale (ex-Bloc 9bis)
*Deja nomme "le point le plus important" — resitue ici apres P1/P2 parce que le planner et l'ontologie doivent etre stables avant de changer le modele qui les consomme*

- **Jour 1** : Confirmer le materiel local disponible (GPU, VRAM) — condition bloquante deja documentee dans `config/settings.py` (`gpt-oss:20b` choisi comme cible coherente cloud/local mais jamais teste en local).
- **Jour 2-3** : Cabler `get_chat_llm("ollama")` (actuellement `NotImplementedError` volontaire) une fois le materiel confirme.
- **Jour 4-5** : Rejouer l'integralite du benchmark adversarial (les 8 modules Bloc 9 + Bloc 8 latence) sur le modele local — chiffrer le vrai budget de latence local (le chiffre p90=6.84s actuel est explicitement documente comme non representatif, temps algorithmique hors reseau Groq).
- **Jour 6** : Comparer le taux de reussite E2E local vs cloud — si degradation, verifier si le scaffolding deterministe (backfills, corrections de contradiction) suffit a compenser un modele local plus faible que `gpt-oss-20b` cloud, ou s'il faut un modele local plus gros.

**Critere de fin** : benchmark adversarial complet rejoue et documente en conditions 100% locales, chiffre de latence reel (pas extrapole) — la contrainte de confidentialite fondatrice du projet enfin demontree en pratique.

---

## Bloc P4 — Interoperabilite v11 (ex-Bloc 13)

- **J49-J51** : Monter une instance Odoo v11 (ou la plus ancienne confirmee chez un client), rejouer le pipeline d'extraction (A1) tel quel, verifier le branchement JS legacy (Widget/QWeb pre-OWL) deja prevu en A1.
- **J52** : Rejouer le jeu adversarial (adapte si necessaire aux mecanismes disponibles en v11) sur cette instance, consolider les ecarts.

**Critere de fin** : rapport explicite "generalisation confirmee / limites observees" sur au moins une version anterieure a v17.

---

## Bloc P5 — Suite de regression OCA (ex-Bloc 14)

- **J53-J56** : Mettre en place le pipeline en CI, declenche a chaque modification de l'extracteur ou du registre Semgrep, sur un echantillon large et croissant de vrais modules OCA (branche 17.0).
- **J57** : Premier rapport de couverture representatif sur cet echantillon, compare au jeu des 9 cas fixes.

**Note (11/08) — choix d'outillage d'evaluation** : un framework LLM-judge (DeepEval, RAGAS, etc.) n'apporterait pas de valeur ajoutee nette a ce stade (verification deterministe contre verite terrain connue, pas jugement semantique). Le bon moment est ici (volume OCA), pas avant. A reevaluer si le volume du jeu adversarial croit significativement avant ce bloc.

**Critere de fin** : CI operationnelle et declenchee automatiquement, premier rapport de couverture OCA produit.

---

## Bloc P6 — Vrai code MiroKE (ex-Bloc 15)
*Non date — bloque par l'acces, pas par la conception*

- **Jour A** : Detection de version (`__manifest__.py`), montage d'une instance Odoo de la bonne version avec le vrai corpus.
- **Jour A+1 a A+3** : Rejouer le Sprint A (extraction) sur le vrai code — mesurer le score de couverture reel par module (A1).
- **Jour A+4 a A+6** : Rejouer le Sprint D complet (jeu de gouvernance en langage metier) sur le vrai corpus.
- **Jour A+7** : Rapport final de generalisation — confirmer ou infirmer l'hypothese centrale du projet sur du code custom reel, pas seulement synthetique.

**Critere de fin** : rapport de validation reelle, seule preuve qui compte a terme.

---

## Bloc 16 — Marge, consolidation, memoire

- **J58-J75** : Marge pour imprevus (acces MiroKE tardif, corrections issues des blocs precedents, allers-retours avec le maitre de stage), rattrapage si un bloc a deborde. Redaction progressive des parties du memoire correspondant aux blocs deja clos.
- **J76-J85** : Redaction du memoire (sections restantes), consolidation des rapports de benchmark en annexes, relecture.
- **J86-J90** : Relecture finale, preparation de la soutenance, derniere non-regression complete avant remise.

---

# PARTIE 4 — Table de correspondance

| Bloc (ce fichier) | Brique `architecture.md` visee | Ancien nom |
|---|---|---|
| B0-Bloc 9 | Couches 1-2, Evidence Builder, Raisonnement deterministe, Preuves | `real plan.md` Blocs 0-9 |
| P0 | (verification, prerequis d'hygiene de suivi) | `plan_architecture_cible.md` P0 |
| P1 | Investigation Planner | `plan_architecture_cible.md` P1 |
| P2 | Couche 3 — Couche semantique (ontologie metier + tags) | `plan_architecture_cible.md` P2 |
| P3 | Confidentialite fondatrice (inference locale) | `real plan.md` Bloc 9bis / `plan_architecture_cible.md` P3 |
| P4 | Generalisation multi-version | `real plan.md` Bloc 13 / `plan_architecture_cible.md` P4 |
| P5 | Generalisation a grande echelle OCA | `real plan.md` Bloc 14 / `plan_architecture_cible.md` P5 |
| P6 | Preuve finale sur le vrai code custom | `real plan.md` Bloc 15 / `plan_architecture_cible.md` P6 |
| Bloc 16 | Memoire de stage | `real plan.md` Bloc 16 |

---

# PARTIE 5 — Limites connues du plan

- **Inference cloud, pas locale (le point le plus important)** : le prototypage a date (B0 a Bloc 9) valide l'architecture et la methodologie de l'agent de Code Intelligence, mais entierement sur Groq (API cloud, `llama-3.1-8b-instant`) — la contrainte de confidentialite fondatrice du projet n'est pas encore demontree en pratique. Voir Bloc P3.
- **Budget de latence non representatif du deploiement final** : le chiffre mesure (p90=6.84s) reflete le temps algorithmique hors attente reseau Groq — pas une mesure de ce que donnera un modele local sur materiel modeste.
- **Fiabilite structurellement dependante d'un scaffolding deterministe lourd** : dispatch force, gating, garde-fous compensent les limites d'un modele 8B. Caracteristique assumee de l'architecture a ce niveau de taille de modele — a nommer explicitement comme choix de conception dans le memoire.
- **Volume et diversite du jeu adversarial encore limites** : 9 questions de base + modules custom synthetiques. Le Bloc P6 (vrai code MiroKE) reste la seule preuve qui compte a terme.
- **Infrastructure de production hors perimetre** : multi-tenant et stack de production (Qdrant, vLLM a charge) explicitement hors du planning actuel.
- **RAG documentaire non detaille dans ce plan** : le pipeline documentaire (PDF, wikis) du document source (Sprint B) n'apparait pas dans le detail, centre sur l'agent de Code Intelligence seul.

---

# PARTIE 6 — Ce que ce plan ne couvre pas

- **Couche 4 (Runtime Odoo)** au-dela de ce qui existe deja (`with_user()`, resolution xmlid, contexte societe qualitatif) — reste partiel par design tant que Data Intelligence (branche ORM separee) n'est pas fusionnee avec Code Intelligence ; fusion non entamee, a trancher comme decision produit separee.
- **RAG documentaire** (Sprint B du document source) — chantier parallele non repris dans ce fichier.
- **Infrastructure multi-tenant / production** — explicitement hors perimetre de stage.

---

# PARTIE 7 — Perspectives (au-dela de la fin de stage)

- Fine-tuning cible (Option C du document source, differee a 12-18 mois) sur les patterns ou le modele 8B echoue le plus souvent malgre le dispatch force.
- Multi-tenant (isolation stricte entre clients, Qdrant en production) des qu'un deuxieme client rejoint le perimetre.
- Integration au RAG documentaire via le meme principe de routage/resolution de conflit (Bloc 6).
- Suite de regression OCA (Bloc P5) : piste de valorisation externe (publication, contribution communautaire).

---

# PARTIE 8 — Explicitement hors de ce planning

Ces points restent dans le plan source mais **ne doivent consommer aucun jour ci-dessus** tant que la condition de declenchement n'est pas remplie :

- **Interoperabilite multi-tenant** — hors scope tant que MiroKE reste l'unique client cible.
- **Infrastructure locale, POC demonstrable** — hors scope tant que le materiel local n'est pas arrive (voir Bloc P3 pour la validation d'inference locale elle-meme, distincte de ce point d'infrastructure de production).
