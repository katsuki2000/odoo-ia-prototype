# Plan unifie — Agent de Code Intelligence (Odoo)

**Regle transverse, valable a chaque bloc ci-dessous** : tests ecrits avant/avec le code, revue manuelle ligne a ligne pour tout ce qui touche `ir.rule`/`sudo()`/`has_group()`/`with_user()`, sourcing obligatoire (fichier+ligne ou identifiant d'enregistrement) sur tout element produit, aucune story declaree terminee sans reexecution du benchmark adversarial end-to-end complet (sortie brute conservee).

---

# PARTIE 1 — Blocs clos (B0 a Bloc 9)

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
- **STATUT ROUVERT (21/08, voir todo/contexte.txt section 86), REFERME (21/08, voir todo/contexte.txt sections 89-92)** : fuite de securite reelle trouvee -- `code_intelligence/auxiliary_tools.py::lire_code_source_precis` (lecture de code source brut, outil B.2.4 lie a l'agent ReAct) ne passe jamais par un analyseur et ne porte donc jamais `SENSITIVE_BYPASS_MARKER` -- il echappe entierement au gating de `authorization_gate.py`, quels que soient les droits reels du demandeur (emails/IDs codes en dur, `sudo()` lisibles en clair). Root cause identifiee, diff correctif redige (reutilise les regex existantes de `server_action_analyzer.py`/`semgrep_locks_analyzer.py`), applique sur mandat explicite section 89. Une DEUXIEME fuite distincte trouvee en live lors de la confirmation (section 90) : `code_intelligence/server_action_analyzer.py::interpret_server_action_with_llm` pouvait reformuler en prose les memes faits sensibles sans jamais porter le marqueur -- corrigee sur mandat explicite section 91 (tag conditionnel sur la ligne de synthese LLM des que `has_sudo`/`has_hardcoded_ids`). **Les deux fix confirmes par execution reelle section 92** : pytest 432/432 sans regression, `scripts/check_bloc9_06_automation_traps_e2e.py` colle par l'utilisateur montre bloc9-06a-anonymous-masked propre (IDs 42/108/231 absents du corps de reponse, direct et full-pipeline), et cette fois sans le "succes accidentel" du a un 429 qui avait fausse la lecture section 90 (voir contexte.txt section 92 pour le detail de cette distinction).

## Bloc 8 — Sprint E : robustesse et cas limites — CLOS

- J27-J33 (02-10/09).
- Cycles d'heritage : 3/3. Symboles ambigus : 7/7. Latence : p90=6.84s (temps algo hors reseau Groq). Extraction massive : refus explicite, `MAX_MODELS_PER_QUERY=3`.

## Bloc 9 — Generalisation au code custom — CLOS (confirme 17/08, puis reconfirme par execution reelle au fil des sessions filesystem-only -- voir `todo/contexte.txt` sections 14-88 pour le detail module par module)

- J34-J36 + 8 modules adversariaux.
- 8/8 modules E2E confirmes verbatim : credit_note_approval, credit_note_visibility, hr_leave_workflow, purchase_request, asset_loan, automation_traps, expense_reimbursement_indirect, deep_inheritance_security.
- Suite pytest : 764/764 a la cloture initiale (chiffre depuis depasse -- un run complet plus recent a mesure 755 passed/2 failed sur `pytest miro-rag/ -v`, les 2 echecs etant sans rapport avec Bloc 9, voir `todo/contexte.txt` section 45).
- **STATUT REFERME (25/08, voir todo/contexte.txt sections 128-163)** : les 8/8 modules adversariaux ont ete rejoues et reconfirmes verts (raw/direct/full-pipeline) au fil des sessions filesystem-only qui ont suivi la reouverture du 21/08. Bilan par point :
  - **Pattern H4** : CORRIGE (fix `CONDITIONAL_AMOUNT_TERMS`/AND-gate dans `core/routing.py`, section 131) et confirme par pytest (sections 132/133) ainsi que par les rejeux reels des modules 01-08, tous verts en full-pipeline sur des cas qui declenchaient auparavant ce pattern.
  - **Module 08, bug (a)** (mot-cle "consulter" absent des listes de `core/routing.py`, dont `CODE_INTEL_KEYWORDS`) : CORRIGE (ajoute le 21/08, voir section 93) et desormais confirme exerce en conditions reelles pour la premiere fois par le rejeu du module 08 (question 08c-bis, section 155) -- auparavant corrige sur le disque mais jamais sollicite par une question reelle du benchmark.
  - **Module 08, bug (b)** (`tool_observations` vide dans `code_intelligence_agent` sur formulation informelle "document Deep" au lieu du nom technique `custom.deep.document`) : **CORRIGE** -- diagnostic cible via `scripts/test_resolver.py` (sections 157-159) ayant revele que le probleme etait en realite plus grave que documente ici (non seulement `unresolved` pour "document Deep", mais une fausse resolution confiante vers `ai.document` pour "le document Deep") ; fix (b2) : deux alias statiques `"document deep"`/`"deep document"` ajoutes a `business_resolver.py::BUSINESS_ALIASES`, confirme par execution reelle sans regression (sections 160/163).
  - Decouvertes annexes sans rapport direct avec cette reouverture, trouvees en marge de ces memes rejeux (desynchronisation de noms d'outils dans `ci_agent_node.py` ; hallucination de `interpret_override_chain_with_llm` sur `hr_leave.py` ; faux positif de `_UnguardedSuperVisitor` sur garde par soustraction de recordset dans `hr_expense.py`) : toutes corrigees et confirmees par execution reelle, a l'exception de la confirmation stricte du fix 2/2 sur l'hallucination `hr_leave` qui reste partielle (voir todo/contexte.txt section 147) -- fil de suivi independant de cette reouverture Bloc 9, ne bloque pas sa cloture.

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

`graph_staleness_detector.py`, `atomic_graph_swap.py`, `graph_symbol_refactor.py`, `graph_version.py` et `reasoning_trace_logger.py` existent deja sur disque et semblent utilises (`reasoning_trace_logger` est appele dans `rag/graph.py`), mais aucune cloture n'apparaissait dans `etat_reel.md` avant sa suppression -- statut reel toujours a confirmer par une relecture de `contexte.txt`.

- **Jour 1** : Relire `contexte.txt` en entier a la recherche de toute mention Bloc 10/11/12, J37-J48. Lister ce qui est confirme teste (pytest reellement execute, sortie collee) vs. seulement ecrit.
- **Jour 2** : Pour tout ce qui n'a jamais ete confirme par une execution reelle, rejouer : `pytest miro-rag/code_intelligence/tests/test_bloc10_incremental_event_logging.py test_bloc10_j37_39_staleness_detection.py -v`, `pytest miro-rag/code_intelligence/tests/test_j37_j42_staleness_and_atomic_swap.py test_j43_j45_symbol_rename_refactoring.py test_j46_j48_reasoning_trace.py -v`.
- **Jour 3** : Documenter le statut Bloc 10-12, explicitement (destination a redecider puisque `etat_reel.md` n'existe plus -- soit un fichier dedie, soit une section de ce plan), meme si le verdict est "deja fait, juste jamais documente ici".

**Critere de fin** : chaque bloc 10/11/12 a un statut ecrit noir sur blanc quelque part sur disque, appuye sur une execution reelle.

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

**Statut** : **Tranchee (25/08, voir todo/contexte.txt section 166)**. L'hypothese naive ("`resolved_concept.is_resolved` seul implique CODE_INTELLIGENCE") est INVALIDEE -- confirmee dangereuse par le contre-exemple DOC-08 (resout parfaitement vers `custom.asset.loan` via alias statique, mais la bonne branche est DOCUMENTAIRE, cf. docstring de `_concept_suggests_code_intelligence` dans `core/routing.py`). L'hypothese bornee ("`business_resolver` doit tourner avant le dispatch de branche, mais son signal seul ne suffit pas -- il doit etre combine a un second signal") est VALIDEE et deja implementee dans `core/routing.py::route()` : `resolve_business_term()` est appele en tout debut de fonction, avant tout dispatch, et son resultat n'est consulte que dans les deux replis de dernier recours, gate par `GOVERNANCE_SIGNAL_TERMS` (`_concept_suggests_code_intelligence`).

**Mais ce gate actuel est explicitement retenu comme un correctif provisoire, pas la solution finale** : `GOVERNANCE_SIGNAL_TERMS` est une liste de mots-cles a la main (`valid`, `regle`, `s'applique`, `echappe`, `automatique`, `controle`), calibree sur exactement les 5 questions H4 connues (01c, 03a, 03c, 04c, 05c) -- un futur cas similaire avec un vocabulaire different repasserait inapercu, meme si `business_resolver` a correctement identifie le modele concerne. **Decision utilisateur (25/08)** : le Bloc P1 (Investigation Planner) doit remplacer ce patch ad hoc par un mecanisme plus robuste -- probablement un signal de confiance combine/pondere (ex. `resolved_concept.confidence` + une classification structuree de l'intention de la question, produits comme sortie explicite d'une etape de planification) plutot qu'une liste de mots-cles etendue au coup par coup. Cette exigence est desormais une contrainte de conception explicite du Bloc P1, pas seulement une observation empirique en marge -- voir la note ajoutee au Bloc P1 lui-meme (PARTIE 3).

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

**Contrainte de conception ajoutee (25/08, decision H1, voir todo/contexte.txt section 166 et PARTIE 3 section H1 ci-dessus)** : le planner doit remplacer le gate ad hoc actuel de `core/routing.py` (`GOVERNANCE_SIGNAL_TERMS`, une liste de mots-cles calibree a la main sur les 5 questions H4 connues) par un mecanisme plus robuste et generalisable pour arbitrer entre le signal deterministe de `business_resolver` (`resolved_concept`, deja calcule en tete de `route()`) et les autres signaux de routage -- probablement une combinaison ponderee de `resolved_concept.confidence` et d'une classification structuree de l'intention de la question (gouvernance/comportement vs information factuelle), plutot qu'une liste de mots-cles etendue au coup par coup a chaque nouveau cas H4-like decouvert. Cette contrainte s'ajoute aux jours ci-dessous, elle ne les remplace pas.

- **Jour 1-2** : Concevoir le schema d'un "plan" serialisable (liste d'etapes typees : `{action, cible, justification}`), a produire AVANT tout appel d'outil reel — pas un remplacement du dispatch force existant (qui reste le filet de securite deterministe), mais une couche d'explicitation posee devant lui. Decider : plan genere par un appel LLM borne dedie (liste fermee d'actions possibles = les 9 outils existants), ou plan reconstruit a posteriori a partir des hops deja traces par `reasoning_trace_logger.py` (moins de risque, mais ne respecte pas "produit avant l'execution" de la vision — a trancher explicitement, documenter le choix). Cette meme etape doit egalement concevoir comment `resolved_concept` (deja calculé en tete de `route()`, cf. H1) s'integre au plan comme signal de premiere classe, remplacant `GOVERNANCE_SIGNAL_TERMS`.
- **Jour 3-4** : Implementer le planner choisi. S'il est generé a priori par LLM : un appel dedié, sortie contrainte (schema Pydantic type `QueryRoute`/`DataQueryIntent` deja en place dans `rag/schemas.py`), jamais du texte libre non structuré.
- **Jour 5** : Exposer le plan dans la reponse finale, dans le "niveau verification" depliable deja existant (le chevron du widget Discuss) — pas seulement en log serveur.
- **Jour 6** : Tests — le plan produit correspond-il reellement aux outils appeles dans le tour ? (test de coherence plan/execution, pas seulement "un plan a ete genere"). Rejouer le benchmark adversarial complet, verifier zero regression sur les 8 modules Bloc 9, ET verifier specifiquement que le remplacement de `GOVERNANCE_SIGNAL_TERMS` ne regresse pas les 5 questions H4 ni le contre-exemple DOC-08.

**Critere de fin** : chaque reponse Code Intelligence porte un plan explicite, inspectable, verifie coherent avec les outils reellement appeles — benchmark adversarial toujours vert, ET le gate `GOVERNANCE_SIGNAL_TERMS` remplace par le mecanisme plus robuste conçu au Jour 1-2.

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

- **Jour 1** : Confirmer le materiel local disponible (GPU, VRAM) — condition bloquante deja documentee dans `config/settings.py`. Modele local cible mis a jour depuis la version initiale de ce plan : Qwen3-14B via Ollama (le choix `gpt-oss:20b` en local reste egalement une option coherente cloud/local, voir PARTIE 5).
- **Jour 2-3** : Cabler `get_chat_llm("ollama")` (actuellement `NotImplementedError` volontaire) une fois le materiel confirme.
- **Jour 4-5** : Rejouer l'integralite du benchmark adversarial (les 8 modules Bloc 9 + Bloc 8 latence) sur le modele local — chiffrer le vrai budget de latence local (le chiffre p90=6.84s actuel est explicitement documente comme non representatif, temps algorithmique hors reseau Groq).
- **Jour 6** : Comparer le taux de reussite E2E local vs cloud — si degradation, verifier si le scaffolding deterministe (backfills, corrections de contradiction) suffit a compenser un modele local plus faible que le modele cloud actuel (`openai/gpt-oss-20b`), ou s'il faut un modele local plus gros.

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

- **Inference cloud, pas locale (le point le plus important)** : le prototypage a date (B0 a Bloc 9) valide l'architecture et la methodologie de l'agent de Code Intelligence, mais entierement sur Groq (API cloud, `openai/gpt-oss-20b`, MoE 21B) — la contrainte de confidentialite fondatrice du projet n'est pas encore demontree en pratique. Modele local cible : Qwen3-14B via Ollama. Voir Bloc P3.
- **Budget de latence non representatif du deploiement final** : le chiffre mesure (p90=6.84s) reflete le temps algorithmique hors attente reseau Groq — pas une mesure de ce que donnera Qwen3-14B en local.
- **Fiabilite structurellement dependante d'un scaffolding deterministe lourd** : dispatch force, gating, garde-fous compensent les limites du modele. Caracteristique assumee de l'architecture — a nommer explicitement comme choix de conception dans le memoire. Le passage de 8B (llama-3.1-8b-instant, abandonne) a 14-21B (Qwen3-14B / gpt-oss-20b) reduit ce risque.
- **Volume et diversite du jeu adversarial encore limites** : 9 questions de base + modules custom synthetiques. Le Bloc P6 (vrai code MiroKE) reste la seule preuve qui compte a terme.
- **Infrastructure de production hors perimetre** : multi-tenant et stack de production (Qdrant, vLLM a charge) explicitement hors du planning actuel.
- **RAG documentaire non detaille dans ce plan** : le pipeline documentaire (PDF, wikis) du document source (Sprint B) n'apparait pas dans le detail, centre sur l'agent de Code Intelligence seul.

---

# PARTIE 6 — Ce que ce plan ne couvre pas

- **Couche 4 (Runtime Odoo)** au-dela de ce qui existe deja (`with_user()`, resolution xmlid, contexte societe qualitatif) — reste partiel par design tant que Data Intelligence (branche ORM separee, domaine B d'`architecture.md` : "Combien ? Qui ? Quand ? Liste-moi ?") n'est pas fusionnee avec Code Intelligence ; fusion non entamee, a trancher comme decision produit separee.
- **RAG documentaire** (Sprint B du document source) — chantier parallele non repris dans ce fichier.
- **Infrastructure multi-tenant / production** — explicitement hors perimetre de stage.

---

# PARTIE 7 — Perspectives (au-dela de la fin de stage)

- Fine-tuning cible (Option C du document source, differee a 12-18 mois) sur les patterns ou le modele echoue le plus souvent malgre le dispatch force (ex. synthese multi-volets, priorisation de findings contradictoires).
- Multi-tenant (isolation stricte entre clients, Qdrant en production) des qu'un deuxieme client rejoint le perimetre.
- Integration au RAG documentaire via le meme principe de routage/resolution de conflit (Bloc 6).
- Suite de regression OCA (Bloc P5) : piste de valorisation externe (publication, contribution communautaire).

---

# PARTIE 8 — Explicitement hors de ce planning

Ces points restent dans le plan source mais **ne doivent consommer aucun jour ci-dessus** tant que la condition de declenchement n'est pas remplie :

- **Interoperabilite multi-tenant** — hors scope tant que MiroKE reste l'unique client cible.
- **Infrastructure locale, POC demonstrable** — hors scope tant que le materiel local n'est pas arrive (voir Bloc P3 pour la validation d'inference locale elle-meme, distincte de ce point d'infrastructure de production).

---

# PARTIE 9 — Perimetre de validation du PoC : module Documentaire implemente mais non score

**Decision (2026-08-19)** : le PoC reste architecture sur 3 branches -- Code Intelligence, ERP, Documentaire (voir le diagramme dans `architecture.md`, non modifie) -- mais l'evaluation principale du PoC ne porte que sur un sous-ensemble explicite de cette architecture.

**Ce qui EST evalue** :
- Code Intelligence (agent, resolution de business terms, tracabilite des hops)
- ERP Runtime (donnees reelles, execution)
- Tracabilite des preuves (dossier de preuves, Evidence Builder)

**Ce qui est implemente mais explicitement HORS du perimetre de l'evaluation principale** :
- Module Documentaire (RAG classique -- embeddings, reranker, ingestion de documents) -- code non supprime, conserve tel quel, simplement non compte dans le score du PoC.
- Sa contribution a la branche HYBRIDE de `route()` (cas ou une question combine un terme documentaire/quantitatif) suit la meme regle : implementee, non scoree.

**Pourquoi cette decision, pas une suppression** : le module documentaire ne resout pas le probleme le plus risque du projet -- comprendre le comportement reel d'un code Odoo inconnu -- qui est deja couvert, largement resolu ailleurs (embeddings, reranking, qualite documentaire sont des problemes matures). Le sortir du perimetre de *validation* recentre l'evaluation sur ce qui est original et non demontre ailleurs, sans perdre le code ni la couverture de tests qui en depend deja (`test_hybrid_detects_doc_anchor_not_only_doc_keyword`, cas DOC/HYBRIDE de `tests/test_j18_routing_fewshot.py`).

**Argument de soutenance** : si la question "et les documents internes ?" est posee, la reponse est "l'architecture le permet deja, le module existe (voir le code et les tests), mais l'objectif du PoC etait de valider la comprehension du comportement reel d'Odoo -- la partie la plus risquee et la moins couverte par les solutions existantes". Cette reponse ne tient que si le diagramme et le code documentaire restent visibles et testes -- d'ou le choix de ne rien supprimer.

**Limite a ne pas survendre** : cette decision de perimetre ne change PAS le score actuel de `tests/eval_routing_accuracy.py` (94.6%, 35/37 -- voir `todo/contexte.txt` sections 63bis et 65). Les 2 echecs connus a cette date (DOC-09 "qui doit approuver un avoir", ERP-13 melange procedures+montant) sont des limites du script d'evaluation lui-meme, pas des problemes de qualite documentaire -- ne pas presenter cette decision de perimetre comme la cause d'une amelioration de ce chiffre, le jury peut verifier.

**Non tranche ici, volontairement** : ceci est une decision de *perimetre d'evaluation*, pas de *desactivation runtime*. Si le module documentaire devait un jour etre reellement desactive (pas seulement exclu du score), il faudrait d'abord decider explicitement ce que devient la branche HYBRIDE de `route()` dans `core/routing.py` (repli sur `donnees_erp` seul, ou sur `documentaire` seul) -- question de routage a part entiere, pas cosmetique, qui n'est pas posee par la decision de ce tour.

**Suggere, non fait ce tour** : adapter `tests/eval_routing_accuracy.py` pour rapporter separement l'accuracy sur le sous-ensemble Code Intelligence/ERP (le perimetre score) et sur le reste (Documentaire/Hybride, hors perimetre), plutot que de melanger les deux dans un seul pourcentage.

---

# PARTIE 10 — Revue externe de l'architecture (21/08, document colle par l'utilisateur, non source sur disque)

**Origine** : relecture externe de `architecture.md`/la vision du projet, comparee point par point a l'etat reel du plan par Claude (session filesystem-only), synthese validee par l'utilisateur qui a demande l'ajout ici -- sans suppression, additif uniquement.

## Points de la revue deja couverts par l'existant (confirmation croisee, pas de nouveau travail requis)

- **Couche semantique (c)** : la revue recommande labels Odoo comme amorce + seuil de confiance + validation manuelle sur mappings critiques + synonymes en base controlee (pas seulement en prompt) -- correspond deja a Bloc 0 (`business_resolver.py` : alias statiques `BUSINESS_ALIASES` + fuzzy `rapidfuzz` + arbitrage LLM borne, ordre alias-d'abord verrouille par `test_s2_0_alias_not_shadowed_by_fuzzy_single_token`).
- **Runtime Odoo (d)** : "executer en tant qu'utilisateur", tracabilite -- deja couvert par `with_user()` (Bloc 1) + `reasoning_trace_logger.py` (Bloc 12).
- **LLM Writer / hallucination (f)** : la recommandation (citer chaque fait, ne rien ajouter hors preuves) est deja depassee en pratique par la mecanique de correction chirurgicale de contradiction post-hoc (`_correct_can_view_amount_contradictions`, override cascade, redaction `SENSITIVE_BYPASS_MARKER` -- Bloc 7/7-bis) : le systeme ne se contente pas de contraindre le LLM en amont, il verifie et corrige sa sortie contre les faits deterministes.
- **Evaluation et tests (g)** : benchmark adversarial 8/8 modules (Bloc 9) + `eval_routing_accuracy.py` (94.6%, 35/37) deja dans l'esprit demande (couverture cas simples/multi-modules/runtime, mesure de precision).
- **Suggestion 3 (versionner graphe + preuves, commit hash)** : `graph_version.py`/`atomic_graph_swap.py` existent deja sur disque (Bloc 10-11) -- statut d'execution reelle non confirme, deja objet du Bloc P0 planifie (aucun nouveau travail a ajouter, P0 couvre deja ce point).
- **Suggestion 4 (perimetre vertical avant generalisation)** : deja fait, Bloc 9 (module custom + module natif cible, 8 modules adversariaux).

## Gaps reels identifies par la revue, non couverts par l'existant confirme -- non planifies, en attente de decision (aucun mandat d'execution donne)

- **(a) Introspection du registre Odoo reel en complement de l'AST statique** (`env['ir.model']`, `ir.model.fields`, `ir.model.access`, `ir.rule`, `ir.actions`, `ir.ui.view`) : l'extraction actuelle (Sprint A / A1, reference dans P4/P6) semble reposer sur l'analyse statique Python/XML (+ Semgrep) ; aucune confirmation trouvee d'une introspection du registre a l'execution en complement. A verifier dans le code d'extraction reel avant de trancher si c'est un vrai trou ou deja couvert autrement.
- **(b) Relations de graphe plus precises** (`field_depends_on`, `view_inherits`, `method_overrides`, `security_rule_filters_model`, `button_action_opens`, `server_action_triggered_by`, `workflow_transition_from_state_to_state`) versus les relations generiques actuelles d'`architecture.md` (`inherits`, `depends`, `calls`, `opens`, `writes`, `reads`, `triggers`, `defined_in`) -- a comparer avec `graph_builder.py` reel pour voir si le detail y est deja implicite ou s'il manque vraiment.
- **(e) Decomposition explicite en 4 moteurs deterministes specialises** (moteur d'acces / moteur de visibilite / moteur de workflow / moteur de calcul), chacun produisant des faits structures consommes par l'Evidence Builder -- l'existant (`server_action_analyzer.py`, `semgrep_locks_analyzer.py`, `authorization_gate.py`...) couvre fonctionnellement une partie de ce role mais sans cette organisation explicite en 4 moteurs nommes. Refactor de clarte/architecture potentiel, pas une correction de bug.
- **(Suggestion 2) Schema de preuves JSON normalise et versionne** (type/module/fichier/ligne/snippet/commit_hash) -- le "dossier de preuves" existe en esprit (Evidence Builder, niveau verification depliable) mais pas sous forme de schema structure explicite tel que propose par la revue.
- **(Suggestion 5) Perimetre vues/JavaScript OWL** -- non couvert a ce jour, aucune mention explicite d'un perimetre JS dans `plan.md`/`architecture.md`. A trancher : le perimetre reste serveur (Python/XML) uniquement, ou inclut-il le comportement JS/OWL cote UI ?

**Statut** : ces 5 gaps sont **enregistrés pour memoire, non priorises, non planifies dans un bloc**, en attente d'une decision explicite sur leur priorite relative aux blocs P0-P6 deja en cours de planification. Aucune modification de code ni de perimetre n'a ete decidee a partir de cette revue -- consignation seule, sur demande explicite de l'utilisateur.

---

# PARTIE 11 — Decision de sequencement avant P1 (21/08, decision utilisateur, additif -- rien supprime/renumerote ailleurs)

**Constat utilisateur** : le plan est juge solide, realiste et bien documente. Quatre risques identifies avant d'attaquer P1 :

1. Bugs Bloc 9 non fermes qui polluent le benchmark de reference (voir Bloc 9, section "STATUT ROUVERT", et `todo/contexte.txt` sections 86-88 : pattern H4 sur 5 questions/3 modules, plus les deux bugs distincts du module 08 -- mot-cle "consulter" absent, `tool_observations` vide sur formulation informelle).
2. H1 (tester `business_resolver` avant `route()`) non tranchee, alors que le Bloc P1 Jour 1-2 en depend directement (voir section H1, PARTIE 3).
3. Choix du modele local cible (Qwen3-14B vs un modele 7/8B) a trancher selon le materiel reellement disponible et des tests, avant de caler le Bloc P3 Jour 1.
4. Gaps de la revue externe (PARTIE 10) a prioriser explicitement -- actuellement listes mais non hierarchises.

**Decision actee** : avant d'attaquer P1, trois preconditions doivent etre remplies dans cet ordre de priorite :

- (i) Clore les bugs Bloc 9 encore ouverts (les deux "STATUT ROUVERT" actuels).
- (ii) Trancher H1 explicitement (valider ou invalider l'hypothese, pas seulement la noter "observation empirique en sa faveur" comme actuellement).
- (iii) Decider du modele local cible (14B vs 7/8B) -- decision qui conditionne le Bloc P3 mais n'a pas besoin d'attendre P3 pour etre prise, dans la mesure ou elle peut influer sur des choix faits plus tot (P1/P2).

**Ordre d'enchainement retenu apres ces 3 preconditions** : **P2 puis P1 puis P3** -- ordre different de celui actuellement liste dans la PARTIE 3 de ce document (qui presente P1 avant P2 avant P3). Motif reporte par l'utilisateur, non detaille davantage ce tour.

**Non fait ce tour** : aucune des 3 preconditions n'est levee par cette entree -- ni fermeture effective des bugs Bloc 9, ni tranchage reel de H1, ni choix du modele local. Cette section n'acte que la **decision de sequencement** (quoi faire avant quoi), pas l'execution des etapes elles-memes, qui restent chacune soumises a mandat explicite au moment voulu, conformement a la discipline du projet. Le gap de la revue externe (item 4, PARTIE 10) reste egalement non priorise -- signale ici comme risque, pas encore arbitre.

**A faire avant de rouvrir P1 dans les faits** : mettre a jour le texte d'introduction de la PARTIE 3 (et/ou l'ordre d'affichage des blocs P1/P2/P3) pour refleter le nouvel ordre P2->P1->P3 une fois les 3 preconditions levees -- non fait ce tour pour eviter de renumeroter/deplacer du contenu existant sans mandat separe (la consigne de ce tour etait "ajoute, ne supprime rien").

**Mise a jour (25/08, voir todo/contexte.txt section 156, additif -- rien supprime/renumerote ci-dessus)** : precondition (i) partiellement levee depuis la redaction de ce qui precede -- Bloc 9 (PARTIE 1) n'est plus au statut "STATUT ROUVERT" cite ci-dessus mais "STATUT PARTIELLEMENT REFERME" : le bug (a) (mot-cle "consulter" absent de `core/routing.py`) est CORRIGE et desormais confirme par execution reelle (rejeu module 08, todo/contexte.txt section 155) ; seul le bug (b) (`tool_observations` vide sur formulation informelle "document Deep") reste ouvert. Bloc 7-bis (l'autre "STATUT ROUVERT" mentionne au point 1 ci-dessus) etait deja REFERME au moment meme de la redaction de cette PARTIE 11 (sections 89-92, meme date du 21/08). Precondition (i) se reduit donc desormais a une seule question ouverte : decider si le bug (b) doit etre corrige avant de considerer (i) entierement levee, ou si son caractere mineur/non exerce par le benchmark actuel permet de clore (i) tel quel -- decision utilisateur non prise a ce jour. Preconditions (ii) et (iii) restent non levees, inchangees.

**Mise a jour (25/08, voir todo/contexte.txt sections 163/166, additif)** :

- **Precondition (i)** : desormais **entierement levee**. Le bug (b) (`tool_observations` vide sur "document Deep") est CORRIGE (fix (b2), alias statiques "document deep"/"deep document" dans `business_resolver.py::BUSINESS_ALIASES`), confirme par execution reelle E2E (`scripts/test_resolver.py`) et par tests unitaires dedies (42/42 verts, `test_business_resolver.py`), zero regression. Bloc 9 passe de "STATUT PARTIELLEMENT REFERME" a "STATUT REFERME" (voir Bloc 9, PARTIE 1). Les 3 preconditions ne bloquent donc plus sur (i).
- **Precondition (ii)** : **tranchee**. H1 n'est ni simplement validee ni invalidee -- verdict nuance : l'hypothese naive (signal de `business_resolver` seul suffisant) est invalidee (contre-exemple DOC-08), l'hypothese bornee (`business_resolver` tourne avant le dispatch, mais son signal doit etre combine a un second signal) est validee et deja implementee via `GOVERNANCE_SIGNAL_TERMS`. Ce gate actuel est explicitement acte comme un correctif provisoire, pas la solution finale -- decision utilisateur : **Bloc P1 (Investigation Planner) doit le remplacer par un mecanisme plus robuste et generalisable** (contrainte de conception ajoutee au Bloc P1 lui-meme, PARTIE 3). Voir H1, PARTIE 3, pour le detail complet.
- **Precondition (iii)** : **reste non levee**, mais reformulee suite a la decision utilisateur -- le materiel local n'est pas encore arrive, ce qui n'est PAS considere comme un blocage : au contraire, l'etape de choix du modele local cible (Bloc P3 Jour 1) servira a **decider quel materiel acheter**, plutot que d'attendre un materiel deja possede pour choisir le modele. La sequence causale est donc inversee par rapport a la formulation initiale de cette precondition (qui presupposait le materiel deja disponible comme prealable au choix de modele) -- a refleter si besoin dans le Bloc P3 lui-meme le moment venu.

**Consequence sur l'ordre de sequencement P2->P1->P3 retenu plus haut** : la decision H1 (precondition (ii)) rattache desormais explicitement le remplacement de `GOVERNANCE_SIGNAL_TERMS` au Bloc P1 -- ceci renforce, plutot que ne contredit, l'ordre deja retenu (P2 avant P1) : la couche d'ontologie/tags semantiques de P2 pourrait fournir une partie du signal structure (ex. tag `approval_rule`/`blocking_rule` sur les noeuds du graphe) dont le mecanisme plus robuste de P1 aurait besoin pour remplacer une simple liste de mots-cles -- lien non tranche formellement ce tour, signale pour memoire.

**Seule precondition non levee restante avant d'attaquer P2 (premier bloc de l'ordre retenu)** : (iii), mais desormais explicitement non-bloquante par decision utilisateur (voir ci-dessus) -- **P2 peut donc demarrer sans attendre (iii)**.