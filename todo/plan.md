# Plan unifie — Agent de Code Intelligence (Odoo)

**Regle transverse, valable a chaque bloc ci-dessous** : tests ecrits avant/avec le code, revue manuelle ligne a ligne pour tout ce qui touche `ir.rule`/`sudo()`/`has_group()`/`with_user()`, sourcing obligatoire (fichier+ligne ou identifiant d'enregistrement) sur tout element produit, aucune story declarée terminée sans réexecution du benchmark adversarial end-to-end complet (sortie brute conservée).

---

# PARTIE 1 — Blocs clos (B0 a Bloc 9)

## Bloc 0 — B0 : resolveur nom-metier -> nom-technique — CLOS

- J1-J4 (28-31/07). Fuzzy-matching (`rapidfuzz`), table d'alias statique, arbitrage LLM borne.
- Ordre alias-d'abord (pas fuzzy-d'abord) : correction deliberée, verrouillée par `test_s2_0_alias_not_shadowed_by_fuzzy_single_token`.

## Bloc 1 — `ir.rule` via `with_user()` — CLOS

- J5-J7 (03-05/08). Wrapper `with_user()`, algorithme ET global/OU groupe, revue de securite ligne a ligne (`j7_security_review.md`).
- 13/13 J5, 8/8 J6, benchmark vert J7.

## Bloc 2 — `ir.actions.server` / `base.automation` / `ir.cron` — CLOS

- J8-J10 (06-10/08). Lecture LLM bornée du champ `code`, tag de confiance obligatoire.

## Bloc 3 — Regles Semgrep : `_sql_constraints` et `domain=` — CLOS

- J11-J13 (11-13/08). Fixtures TDD, revue de precision (`j13_semgrep_precision_review.md`).

## Bloc 4 — Verification systematique du sourcing — CLOS

- J14 (14/08). Script de verification mecanique fichier+ligne sur les 3 mecanismes.

## Bloc 5 — Non-regression complete + cloture E1/E2 — CLOS

- J15-J17 (17-19/08). Rejeu integral des 9 modules adversariaux, rapport consolide.

## Bloc 6 — Routeur et conflit inter-branches — CLOS

- J18-J21 (20-25/08). Politique de resolution de conflit code-prime-sur-RAG.
- **Addendum (2026-09-01, voir Bloc P1-bis, PARTIE 3)** : le modele "4 branches coequipieres" decrit ci-dessus a ete substantiellement reoriente par le chantier CI-d'abord/RAG-fallback (todo/contexte.txt sections 405-416) -- `route()` ne pilote plus l'execution reelle que pour l'arbitrage DONNEES_ERP vs le reste, les 3 autres branches convergeant vers un flux unique Code Intelligence avec fallback RAG conditionnel. La politique "code-prime-sur-RAG" citee ci-dessus reste pertinente pour ce seul arbitrage residuel.

## Bloc 7 — Controle d'acces sur la reponse + Bloc 7-bis — CLOS

- J22-J26 (26/08-01/09) + revision 07/08.
- Gating cible : seul `SENSITIVE_BYPASS_MARKER` (sudo(), emails/IDs codes en dur) filtre selon l'identite du demandeur. Gouvernance/portée (ir.rule, groupes, plafonds) ouverte a tous.
- Disponibilite réelle des boutons via `user_groups` + resolveur de groupe tolerant.
- 18/18 tests (authorization_gate + button_availability + e2e_purchase_bypass).
- **STATUT ROUVERT (21/08, voir todo/contexte.txt section 86), REFERME (21/08, voir todo/contexte.txt sections 89-92)** : fuite de securite réelle trouvée -- `code_intelligence/auxiliary_tools.py::lire_code_source_precis` (lecture de code source brut, outil B.2.4 lie a l'agent ReAct) ne passe jamais par un analyseur et ne porte donc jamais `SENSITIVE_BYPASS_MARKER` -- il echappe entierement au gating de `authorization_gate.py`, quels que soient les droits réels du demandeur (emails/IDs codes en dur, `sudo()` lisibles en clair). Root cause identifiée, diff correctif redige (reutilise les regex existantes de `server_action_analyzer.py`/`semgrep_locks_analyzer.py`), applique sur mandat explicite section 89. Une DEUXIEME fuite distincte trouvée en live lors de la confirmation (section 90) : `code_intelligence/server_action_analyzer.py::interpret_server_action_with_llm` pouvait reformuler en prose les memes faits sensibles sans jamais porter le marqueur -- corrigée sur mandat explicite section 91 (tag conditionnel sur la ligne de synthese LLM des que `has_sudo`/`has_hardcoded_ids`). **Les deux fix confirmes par execution réelle section 92** : pytest 432/432 sans regression, `scripts/check_bloc9_06_automation_traps_e2e.py` colle par l'utilisateur montre bloc9-06a-anonymous-masked propre (IDs 42/108/231 absents du corps de reponse, direct et full-pipeline), et cette fois sans le "succes accidentel" du a un 429 qui avait fausse la lecture section 90 (voir contexte.txt section 92 pour le detail de cette distinction).

## Bloc 8 — Sprint E : robustesse et cas limites — CLOS

- J27-J33 (02-10/09).
- Cycles d'heritage : 3/3. Symboles ambigus : 7/7. Latence : p90=6.84s (temps algo hors reseau Groq). Extraction massive : refus explicite, `MAX_MODELS_PER_QUERY=3`.

## Bloc 9 — Generalisation au code custom — CLOS (confirme 17/08, puis reconfirme par execution réelle au fil des sessions filesystem-only -- voir `todo/contexte.txt` sections 14-88 pour le detail module par module)

- J34-J36 + 8 modules adversariaux.
- 8/8 modules E2E confirmes verbatim : credit_note_approval, credit_note_visibility, hr_leave_workflow, purchase_request, asset_loan, automation_traps, expense_reimbursement_indirect, déep_inheritance_security.
- Suite pytest : 764/764 a la cloture initiale (chiffre depuis depasse -- un run complet plus recent a mesure 755 passed/2 failed sur `pytest miro-rag/ -v`, les 2 echecs etant sans rapport avec Bloc 9, voir `todo/contexte.txt` section 45).
- **STATUT REFERME (25/08, voir todo/contexte.txt sections 128-163)** : les 8/8 modules adversariaux ont ete rejoues et reconfirmes verts (raw/direct/full-pipeline) au fil des sessions filesystem-only qui ont suivi la reouverture du 21/08. Bilan par point :
  - **Pattern H4** : CORRIGE (fix `CONDITIONAL_AMOUNT_TERMS`/AND-gate dans `core/routing.py`, section 131) et confirme par pytest (sections 132/133) ainsi que par les rejeux réels des modules 01-08, tous verts en full-pipeline sur des cas qui declenchaient auparavant ce pattern.
  - **Module 08, bug (a)** (mot-cle "consulter" absent des listes de `core/routing.py`, dont `CODE_INTEL_KEYWORDS`) : CORRIGE (ajoute le 21/08, voir section 93) et desormais confirme exerce en conditions réelles pour la premiere fois par le rejeu du module 08 (question 08c-bis, section 155) -- auparavant corrige sur le disque mais jamais sollicite par une question réelle du benchmark.
  - **Module 08, bug (b)** (`tool_observations` vide dans `code_intelligence_agent` sur formulation informelle "document Déep" au lieu du nom technique `custom.déep.document`) : **CORRIGE** -- diagnostic cible via `scripts/test_resolver.py` (sections 157-159) ayant revele que le probleme etait en realite plus grave que documente ici (non seulement `unresolved` pour "document Déep", mais une fausse resolution confiante vers `ai.document` pour "le document Déep") ; fix (b2) : deux alias statiques `"document déep"`/`"déep document"` ajoutes a `business_resolver.py::BUSINESS_ALIASES`, confirme par execution réelle sans regression (sections 160/163).
  - Decouvertes annexes sans rapport direct avec cette reouverture, trouvées en marge de ces memes rejeux (desynchronisation de noms d'outils dans `ci_agent_node.py` ; hallucination de `interpret_override_chain_with_llm` sur `hr_leave.py` ; faux positif de `_UnguardedSuperVisitor` sur garde par soustraction de recordset dans `hr_expense.py`) : toutes corrigées et confirmées par execution réelle, a l'exception de la confirmation stricte du fix 2/2 sur l'hallucination `hr_leave` qui reste partielle (voir todo/contexte.txt section 147) -- fil de suivi independant de cette reouverture Bloc 9, ne bloque pas sa cloture.

---

# PARTIE 2 — Constat de depart (18/08)

Le systeme repond deja aux questions de la vision (`architecture.md`) via un scaffolding deterministe efficace, mais deux briques de l'architecture cible n'existent qu'implicitement :

1. **Investigation Planner** — la vision veut un plan explicite produit avant l'execution. Le code réel fait dispatcher force par regex + boucle ReAct plafonnée (`CI_MAX_HOPS=4`) — un plan implicite, jamais ecrit, jamais inspectable.
2. **Semantic Layer / Ontologie + tags** — la vision veut des tags explicites sur le graphe (`visibility_rule`, `blocking_rule`, `approval_rule`, `acl`, `computed_field`, `server_action`...). Le code réel encode cette classification en dur dans le choix de l'outil appele, jamais comme attribut porte par les noeuds eux-memes.

Ces deux gaps conditionnent la lisibilite et l'auditabilite du systeme pour un non-developpeur — l'objectif final d'`architecture.md`.

---

# PARTIE 3 — Plan a venir (P0-P6 + Bloc 16)

## Bloc P0 — Verification prealable : statut réel des Blocs 10-12
### Rappel du contenu des Blocs 10-12 (plan original)

**Bloc 10 — Sprint F : detection de staleness et mise a jour incrementale**
- J37-J39 : 3 niveaux de mise a jour (recalcul fichier modifié + propagation aretes invalidées + detection cas non couverts par recalcul local).
- J40-J41 : Swap atomique du graphml servi (jamais de modification en place pendant une requete en cours). Versionner l'index avec un hash de commit.
- J42 : Test de non-regression — aucune requete ne voit jamais un graphe a moitié reconstruit pendant un swap.
- Critere de fin : swap atomique teste sous requetes concurrentes, index versionne par commit.

**Bloc 11 — Sprint F : renommage (integration PyRef)**
- J43-J44 : Integrer PyRef (SCAM 2021) dans le hook git.
- J45 : Relabelliser le noeud existant (`nom_precedent` en attribut) plutot que supprimer+recréer. Documenter le taux de rappel mesure (76,1%) comme limite residuelle assumée.
- Critere de fin : cas de renommage teste de bout en bout, limite residuelle documentée.


## Preconditions a valider avant P1/P2
*Hypotheses non tranchées — à statuer avant d'entamer P1/P2*

### H1. Tester `business_resolver` avant `route()`

**Motivation** : le composant le plus robuste (`business_resolver`) intervient aujourd'hui après le plus fragile (`route()`).

**Dependance sur Bloc P1** : le Bloc P1, Jour 1-2 pose la question « plan genéré par LLM dedié, ou reconstruit a posteriori depuis les hops traces ? ». Cette decision depend directement de H1 : si `business_resolver` doit passer avant `route()`, la toute premiere etape du plan change de nature.

**Se rattache à** : noeud Semantic Understanding.

**Statut** : L'hypothese naive ("`resolved_concept.is_resolved` seul implique CODE_INTELLIGENCE") est INVALIDée -- confirmée dangereuse par le contre-exemple DOC-08 (resout parfaitement vers `custom.asset.loan` via alias statique, mais la bonne branche est DOCUMENTAIRE, cf. docstring de `_concept_suggests_code_intelligence` dans `core/routing.py`). L'hypothese bornée ("`business_resolver` doit tourner avant le dispatch de branche, mais son signal seul ne suffit pas -- il doit etre combine a un second signal") est VALIDée et deja implementée dans `core/routing.py::route()` : `resolve_business_term()` est appele en tout debut de fonction, avant tout dispatch, et son resultat n'est consulte que dans les deux replis de dernier recours, gate par `GOVERNANCE_SIGNAL_TERMS` (`_concept_suggests_code_intelligence`).

**Mais ce gate actuel est explicitement retenu comme un correctif provisoire, pas la solution finale** : `GOVERNANCE_SIGNAL_TERMS` est une liste de mots-cles a la main (`valid`, `regle`, `s'applique`, `echappe`, `automatique`, `controle`), calibrée sur exactement les 5 questions H4 connues (01c, 03a, 03c, 04c, 05c) -- un futur cas similaire avec un vocabulaire different repasserait inapercu, meme si `business_resolver` a correctement identifie le modele concerne. **Decision utilisateur (25/08)** : le Bloc P1 (Investigation Planner) doit remplacer ce patch ad hoc par un mecanisme plus robuste -- probablement un signal de confiance combine/pondere (ex. `resolved_concept.confidence` + une classification structurée de l'intention de la question, produits comme sortie explicite d'une etape de planification) plutot qu'une liste de mots-cles etendue au coup par coup. Cette exigence est desormais une contrainte de conception explicite du Bloc P1, pas seulement une observation empirique en marge -- voir la note ajoutée au Bloc P1 lui-meme (PARTIE 3).

---

### H2. Tester `active_model` / `active_id`

**Motivation** : le contexte UI n'est actuellement pas propagé.

**Se rattache à** : Semantic Understanding en entrée, Couche 4 — Runtime Odoo en aval.

**Statut** : Non validé.

**Mise a jour (07/09, voir todo/contexte.txt sections 569-572)** : diagnostic complet fait (4 points de rupture confirmes par lecture directe), assistant plein-ecran supprime sur mandat pmm pour restreindre H2 au seul systray, design (b)/(c) propose et valide par pmm, puis implemente bout-en-bout (miro_ai.js -> controllers/main.py -> api/main.py::AskRequestV1 -> core/graph.py::query_graph()/RAGState -> code_intelligence/business_resolver.py::resolve_business_term(), nouveau Step 1.5 "active_context"). Le prefixe texte-libre `[Contexte: modele X]` est retire, remplace par les champs structures `active_model`/`active_id`. 4 tests unitaires ecrits sur le nouveau Step 1.5. **Statut toujours "Non validé" au sens strict du projet** : session filesystem-only, aucun des tests (nouveaux ou de regression) n'a ete reellement execute -- H2 passe donc de "non teste, trou structurel" a "implemente, en attente de confirmation par execution reelle" (voir section 572 pour le detail exact et la reserve explicite).

**Mise a jour (07/09, voir todo/contexte.txt section 573)** : `code_intelligence/tests/test_business_resolver.py` rejoue en conditions reelles par pmm -- 46/46 passed (42 preexistants + 4 nouveaux Step 1.5), aucune regression. Statut affine : **implemente et confirme au niveau unitaire (resolver)**, mais **pas encore "Valide" au sens plein** -- reste a couvrir avant cloture : (a) rejeu du benchmark adversarial complet avec ce chantier explicitement en tete (aucune regression attendue a priori, jamais verifie explicitement) ; (b) test end-to-end reel systray -> controller -> API -> graph -> resolver sur une instance Odoo/FastAPI vivante ; (c) ~~verification visuelle du bandeau de contexte dans le widget Discuss~~ **FAIT** -- confirme par Trunk, voir todo/contexte.txt section 638.

---

### H3. Tester un mecanisme d'arbitrage entre preuves concurrentes

**Se rattache à** : se situe avant Code Intelligence Engine dans le pipeline — donc temporellement a l'opposé d'Evidence Builder, qui intervient après. Voir la note de desambiguation Evidence Check / Evidence Builder dans `architecture.md`.

**Statut** : Conceptuel au niveau de l'arbitrage reel (aucun detecteur de contradiction implemente a ce jour). **Mise a jour (2026-09-01, voir Bloc P1-bis ci-dessous, todo/contexte.txt sections 406-416)** : le schema/contrat existe desormais et est cable en aval -- `core/evidence_sufficiency.py::EvidenceSufficiencyStatus.CONFLICTING` est un statut de premiere classe (distinct d'`INSUFFICIENT`/`indeterminate`, correction utilisateur section 406), et `core/graph.py::ci_evidence_decision()` le trace explicitement par log avant fallback RAG. En pratique, `assess_evidence_sufficiency()` ne retourne jamais `CONFLICTING` aujourd'hui (aucune logique de detection de contradiction reelle n'existe encore) -- la branche est instrumentee et testee (`tests/test_bloc_p1_tranche2_ci_first_evidence_routing.py`, Groupe A) mais actuellement inatteignable. Reste a faire pour clore H3 : le detecteur lui-meme (deux preuves valides reellement contradictoires).

---

## Bloc P1 — Investigation Planner explicite — CLOS (marqueur pose 31/08 sur mandat direct de l'utilisateur, voir reserve ci-dessous)
*Ferme le premier ecart architecture.md — priorite haute, conditionne la lisibilite du raisonnement pour un non-developpeur*

**Contrainte de conception ajoutée : le planner doit remplacer le gate ad hoc actuel de `core/routing.py` (`GOVERNANCE_SIGNAL_TERMS`, une liste de mots-clés calibrée a la main sur les 5 questions H4 connues) par un mécanisme plus robuste et generalisable pour arbitrer entre le signal deterministe de `business_resolver` (`resolved_concept`, deja calculé en tete de `route()`) et les autres signaux de routage -- probablement une combinaison ponderée de `resolved_concept.confidence` et d'une classification structurée de l'intention de la question (gouvernance/comportement vs information factuelle), plutot qu'une liste de mots-cles etendue au coup par coup a chaque nouveau cas H4-like decouvert. Cette contrainte s'ajoute aux jours ci-dessous, elle ne les remplace pas.

- **Jour 1-2** : Concevoir le schéma d'un "plan" serialisable (liste d'etapes typées : `{action, cible, justification}`), à produire AVANT tout appel d'outil réel — pas un remplacement du dispatch force existant (qui reste le filet de securite deterministe), mais une couche d'explicitation posée devant lui. Decider : plan generé par un appel LLM borne dedié (liste fermée d'actions possibles = les 9 outils existants), ou plan reconstruit a posteriori a partir des hops deja traces par `reasoning_trace_logger.py` (moins de risque, mais ne respecte pas "produit avant l'execution" de la vision — a trancher explicitement, documenter le choix). Cette meme etape doit egalement concevoir comment `resolved_concept` (deja calculé en tete de `route()`, cf. H1) s'integre au plan comme signal de premiere classe, remplacant `GOVERNANCE_SIGNAL_TERMS`.
- **Jour 3-4** : Implementer le planner choisi. S'il est generé a priori par LLM : un appel dedié, sortie contrainte (schema Pydantic type `QueryRoute`/`DataQueryIntent` deja en place dans `rag/schemas.py`), jamais du texte libre non structuré.
- **Jour 5** : Exposer le plan dans la reponse finale, dans le "niveau verification" depliable deja existant (le chevron du widget Discuss) — pas seulement en log serveur.
- **Jour 6** : Tests — le plan produit correspond-il réellement aux outils appeles dans le tour ? (test de coherence plan/execution, pas seulement "un plan a été genere"). Rejouer le benchmark adversarial complet, verifier zero regression sur les 8 modules Bloc 9, ET verifier specifiquement que le remplacement de `GOVERNANCE_SIGNAL_TERMS` ne regresse pas les 5 questions H4 ni le contre-exemple DOC-08.

**Critere de fin** : chaque reponse Code Intelligence porte un plan explicite, inspectable, verifie coherent avec les outils réellement appelés — benchmark adversarial toujours vert, ET le gate `GOVERNANCE_SIGNAL_TERMS` remplacé par le mecanisme plus robuste conçu au Jour 1-2.

**Mise a jour (28/08, voir todo/contexte.txt sections 282-283) -- statut reel, correction d'un constat errone de la section 281** : Bloc P1 est en realite substantiellement implemente (`code_intelligence/investigation_plan.py`, `test_bloc_p1_j1_2_investigation_plan.py`, `test_bloc_p1_j6_plan_execution_coherence.py`, champ `investigation_plan` dans `AssistantResponse`) -- decouvert par lecture directe du disque, contredisant un constat anterieur (section 281) qui affirmait a tort "Jours 1-5 jamais entames". Statut par jour :
- **Jour 1-2 (schema + choix d'architecture)** : FAIT. Schema serialisable `InvestigationPlan`/`InvestigationStep` (Pydantic strict, `{action, cible, justification}`) et vocabulaire ferme `PlanAction` (12 actions) en place. Choix d'architecture desormais tranche et documente ici (etait fait dans le code sans jamais etre ecrit comme decision explicite) : **generation par construction semantique deterministe** (`PlanGenerationSource.DETERMINISTIC_SEMANTIC`) -- ni un appel LLM borne dedie a priori, ni une reconstruction a posteriori depuis les hops de `reasoning_trace_logger.py`, mais une troisieme voie : classification d'intention (`QuestionIntent`) + reutilisation directe des memes fonctions de predicat que le pre-dispatch reel (`forced_dispatch_predicates.py`), produite AVANT tout appel d'outil. Justification : coherence structurelle garantie par construction avec l'execution reelle (verifiee par le test Jour 6), zero cout/latence LLM supplementaire pour cette etape, zero variance non-deterministe, et alignement avec la decision H1 (signal combine `resolved_concept` + intention structuree plutot qu'une liste de mots-cles). Limite assumee : ne couvre avec verification automatisee que les intentions ayant un equivalent de dispatch partage cote execution (4 des 8 categories `QuestionIntent` -- perimetre du test Jour 6) ; les 4 autres intentions produisent un plan deterministe mais sans garde-fou de coherence automatise equivalent a ce jour.
- **Jour 3-4 (implementation)** : FAIT. `generate_investigation_plan()` implemente, sortie Pydantic contrainte, jamais de texte libre.
- **Jour 5 (exposition dans la reponse finale)** : PARTIEL. Le champ `investigation_plan` est cable cote backend (`AssistantResponse`, peuple par `core/routing.py::route()`). Non confirme ce tour : rendu reel dans le widget Discuss cote frontend (niveau verification depliable).
- **Jour 6 (tests de coherence)** : FAIT et confirme par execution reelle (voir todo/contexte.txt sections 226-262) sur son perimetre (4 categories partagees, 5 questions H4), critere d'inclusion `planned_tools ⊆ executed_tools`.
- **Consequence** : Bloc P1 restait SANS marqueur `CLOS` jusqu'a ce tour -- il manquait la confirmation Jour 5 cote frontend et un rejeu confirme des 2 suites de tests. **Mise a jour (10/09, voir todo/contexte.txt section 638)** : confirmation Jour 5 (rendu reel du plan dans le widget Discuss) desormais levee sur confirmation directe de Trunk.

**Marqueur CLOS pose (31/08, mandat direct utilisateur, voir todo/contexte.txt section 373/suite)** : Jours 1-2/3-4/6 restent faits et confirmes (inchange ci-dessus). **Reserve explicite non levee** : la confirmation Jour 5 cote frontend (rendu reel du plan dans le widget Discuss) n'a jamais ete verifiee visuellement, et les 2 suites de tests (`test_bloc_p1_j1_2_investigation_plan.py`, `test_bloc_p1_j6_plan_execution_coherence.py`) n'ont pas ete rejouees dans le cadre de cette cloture. Le marqueur est pose sur mandat explicite, pas sur preuve complete au sens habituel du projet (todo/rules.md : aucune story declaree terminee sans reexecution du benchmark) -- si un doute survient plus tard sur ce bloc, cette reserve doit etre levee par un rejeu reel avant de s'y fier pleinement.

---

## Bloc P1-bis — Reorientation CI-d'abord / RAG-fallback (alignement architecture.md) — CLOS (2026-09-01, voir todo/contexte.txt sections 405-417)

**Origine** : ecart constate entre `core/routing.py` (routeur a 4 branches coequipieres, issu du chantier classifieur LLM section 394+) et le modele cible d'`architecture.md` -- "Le RAG n'est pas le moteur principal. Le RAG intervient uniquement lorsque : le systeme ne contient pas la reponse OU la documentation apporte un complement utile." Confirme par relecture complete d'`architecture.md` (section 405), qui ne montre pas 4 branches coequipieres au premier niveau mais Code Intelligence + Data Intelligence (Domaines A/B) alimentant ensemble une seule "Construction des preuves", RAG (Domaine C) intervenant uniquement en dernier recours.

**Contenu livre, 3 tranches** :
- **Tranche 1** (sections 406-407) : nouveau primitif `core/evidence_sufficiency.py::assess_evidence_sufficiency()` -- statut `SUFFICIENT`/`INSUFFICIENT`/`CONFLICTING`. Correction utilisateur integree : un verdict `indeterminate` (champ de contexte manquant, dispatch dynamique non resolu) mappe vers `INSUFFICIENT`, PAS `CONFLICTING` -- reserve a une situation ou deux preuves valides se contredisent reellement (lien H3 ci-dessus). 12/12 tests confirmes en conditions reelles (section 407).
- **Tranche 2** (constat section 408 -- deja ecrite et cablee sur le disque au moment de la lecture, non journalisee par son auteur, verifiee conforme aux contraintes utilisateur) : `core/graph.py::build_graph()` -- `route` ne dispatche plus qu'entre `code_intelligence_agent` (DOCUMENTAIRE/HYBRIDE/CODE_INTELLIGENCE convergent vers le meme noeud) et `orm_agent_loop` (DONNEES_ERP seul) ; nouvelle edge conditionnelle `ci_evidence_decision()` apres `code_intelligence_agent` : `SUFFICIENT` -> reponse directe (`format_output`), sinon (`INSUFFICIENT` ou `CONFLICTING`, trace explicitement par log) -> `generate` (RAG). `hybrid_node` retire du graphe compile (reste importable ; son role est repris par le fallback CI->RAG).
- **Tranche 3** (sections 409-410) : `tests/test_bloc_p1_tranche2_ci_first_evidence_routing.py` (nouveau fichier, 20 tests, 3 groupes -- decision `ci_evidence_decision()` y compris tracabilite CONFLICTING/INSUFFICIENT via `caplog` ; structure reelle du graphe compile via `app.get_graph()` -- confirme que `route` ne dispatche plus que vers 2 noeuds, `hybrid_node` absent des noeuds compiles ; non-regression `format_output()`/OCR). 20/20 confirmes en conditions reelles (section 410).

**Bug reel trouve et corrige en cours de route** (sections 414-416) : `format_output()` portait un disjoint mort `route == QueryRoute.DOCUMENTAIRE.value` (reste de l'ancien cablage pre-Tranche 2), atteignable a tort via les 3 refus precoces de `code_intelligence_agent` (out-of-scope / injection / extraction massive, qui ne peuplent jamais `ci_evidence_sufficiency`) -- faux positif d'avertissement OCR/backfill de sources sur un simple message de refus, si `route()` avait classe la question `documentaire` juste avant. Disjoint retire ; `ci_fell_back_to_rag` seul est desormais un signal complet et suffisant sous le graphe compile CI-d'abord (`generate()` n'a plus qu'une seule edge entrante). Le test qui verrouillait ce comportement comme "non-regression historique" a ete retravaille pour verrouiller l'absence de fuite au lieu de la fuite elle-meme. Confirme 20/20 (section 416).

**Consequence sur le statut du classifieur d'intention (`QuestionIntent`)** : les 5 divergences connues entre classifieur LLM et filet keyword (todo/contexte.txt section 404, rejouees section 411 -- 62 passed/5 failed) sont **declassees** comme risque de routage (decision utilisateur "option 4", section 417, hors du cadre d'options A/B/C/D initialement propose) -- sous le cablage CI-d'abord, `route()` ne pilote plus l'execution reelle que pour DONNEES_ERP (les 3 autres valeurs convergent vers le meme noeud `code_intelligence_agent`), donc une divergence de classification n'a plus de consequence architecturale directe pour la majorite des questions. `QuestionIntent` n'est pas supprime -- repositionne comme signal interne au Planner/CI (comprendre le type de question, preparer l'investigation via `generate_investigation_plan()`), plus comme decideur de routage "RAG ou CI" de premier niveau. Le cas HYBRIDE ne necessite plus de categorie dediee dans `QuestionIntent` -- resolu naturellement par le flux CI-d'abord (CI repond a ce qu'il peut, RAG complete en aval si `assess_evidence_sufficiency() != SUFFICIENT`), sans taxonomie d'intention a 5 categories. Les 5 tests correspondants ont ete corriges a la racine (fixture autouse forcant le filet deterministe pour 4 d'entre eux, 1 entierement retravaille pour verifier un invariant structurel plutot qu'une valeur de route litterale) -- 67/67 confirmes (section 413).

**Non fait / dette residuelle** : retrait effectif de `QuestionIntent`/`INTENT_TO_ROUTE`/le classifieur LLM comme mecanisme de routage de premier niveau (evoque comme possibilite depuis la section 405, jamais mandate au niveau code) -- seul le STATUT/role documente a change ce chantier, pas le code de `investigation_plan.py`/`routing.py` lui-meme (`resolve_question_intent()`/`INTENT_TO_ROUTE` restent en place, verifies non pilotants pour 3 des 4 valeurs). `tests/few_shot_routing_examples.py` (golden-master des 16 exemples) volontairement non touche -- reste la specification de la politique de resolution de conflit voulue, independante de la sortie actuelle du LLM. Docstring perime de `test_j18_routing_fewshot.py` ("no LLM, no retrieval") neutralise par un fixture autouse plutot que reecrit en profondeur.

---

## Bloc P2 — Couche Ontologie + tags semantiques explicites — CLOS (2026-09-02, voir todo/contexte.txt section 483)
*Ferme le second ecart architecture.md*
- **Jour 1** : Definir la liste fermée des tags comportementaux (`visibility_rule`, `blocking_rule`, `calculation_rule`, `workflow_rule`, `approval_rule`, `notification_rule`) et techniques (`record_rule`, `acl`, `constraint`, `computed_field`, `server_action`, `cron`) d'`architecture.md`, comme enumeration dans le code (pas en dur dispersée).
- **Jour 2-3** : Annoter chaque noeud pertinent du graphe (`graph_builder.py`) avec ces tags au moment de la construction — derives de ce que l'extraction sait deja (un `Rule` node vient de `ir.rule` -> tag `record_rule` + `visibility_rule` ; un `AccessEntry` -> tag `acl` ; une methode avec `has_group()`+`raise` -> tag `blocking_rule`, etc.). Reutiliser la classification deja faite implicitement par le choix d'outil comme point de depart.
- **Jour 4** : Exposer ces tags aux 5 outils composites (ils peuvent desormais interroger "quels noeuds ont le tag `approval_rule` pour ce modele" au lieu de connaitre statiquement quel outil traite quel cas) — sans casser le dispatch force existant.
- **Jour 5** : Tests de couverture — chaque type de noeud produit par l'extraction a-t-il au moins un tag ? Detecter les noeuds non classes (gap de couverture de l'ontologie elle-meme). Rejouer le benchmark adversarial complet.

**Critere de fin** : 100% des noeuds Rule/AccessEntry/Method-avec-verrou/ServerAction du graphe portent au moins un tag comportemental et un tag technique ; aucune regression sur le benchmark.

**Statut reel a la cloture (2026-09-02)** : Jours 1-5 tous implementes et confirmes par execution pytest reelle (`test_semantic_tags.py`, `test_bloc_p2_j2_3_graph_tagging.py`, `test_bloc_p2_j4_composite_tools_tag_exposure.py`, `test_bloc_p2_j5_ontology_coverage.py` -- 40/40 passed). Decouvert deja substantiellement implemente sur le disque (session(s) anterieure(s) non retracables -- voir reserve ci-dessous), verifie ligne a ligne contre le code reel avant cloture, pas seulement suppose depuis les docstrings. Jour 5 : `Group`/`Module` restent deliberement sans tag (aucun signal exploitable sans deviner, decision actee) ; `WorkflowState`/`Menu` tagues (le second par pure propagation des tags du `Model` qu'il ouvre). **Reserve non levee** : le benchmark adversarial complet (8 modules Bloc 9) n'a pas ete rejoue specifiquement dans le cadre de cette cloture -- seuls les 4 fichiers de tests P2 dedies ont ete confirmes.

**Reserve de tracabilite (sans rapport avec le contenu du bloc lui-meme)** : les commentaires du code source citent des sections `todo/contexte.txt` (170, 172, 174, 179) anterieures a la section 225, qui est actuellement la premiere section presente dans le fichier `contexte.txt` sur le disque. Les sections 1-224 sont absentes du fichier actuel alors que ce meme `plan.md` cite des sections comme 43x/92/128-163 comme ayant existe -- ecart signale a l'utilisateur, cause non elucidee (rotation/archivage du fichier vs perte reelle), a investiguer separement si la tracabilite historique de ces sections redevient necessaire.

---

## Bloc P3 — Suite de regression OCA — CLOS (marqueur pose 04/09, voir todo/contexte.txt sections 277-280, 520)

- **J53-J56** : Mettre en place le pipeline en CI, declenche a chaque modification de l'extracteur ou du registre Semgrep, sur un echantillon large et croissant de vrais modules OCA (branche 17.0).
- **J57** : Premier rapport de couverture representatif sur cet echantillon, comparé au jeu des 9 cas fixes.

**Note (11/08) — choix d'outillage d'evaluation** : un framework LLM-judge (DéepEval, RAGAS, etc.) n'apporterait pas de valeur ajoutée nette a ce stade (verification deterministe contre verite terrain connue, pas jugement semantique). Le bon moment est ici (volume OCA), pas avant. A réevaluer si le volume du jeu adversarial croit significativement avant ce bloc.

**Critere de fin** : CI operationnelle et declenchée automatiquement, premier rapport de couverture OCA produit.

**Statut reel a la cloture (verifie ce tour, 04/09)** : critere de fin atteint tel qu'ecrit ci-dessus. `.github/workflows/ci.yml` (`OCA Coverage Pipeline`) declenche `scripts/run_oca_coverage.py` a chaque modification de `code_intelligence/**` ou du script lui-meme (push/PR/workflow_dispatch) -- clone 12 depots OCA reels (branche 17.0 : account-financial-reporting, sale-workflow, server-tools, server-ux, purchase-workflow, hr, account-invoicing, stock-logistics-warehouse, partner-contact-management, reporting-engine, web, project). Rapport de couverture confirme 3 fois independamment (sandbox, poste local, run GitHub Actions #8, todo/contexte.txt sections 277-280) : 537 modules decouverts/extraits, 0 echec. Marqueur `CLOS` absent jusqu'ici par pur oubli de traçabilite (constate section 520), pas par travail manquant -- corrige ce tour sans nouveau code.

**Ne pas confondre avec le Bloc P3.1 (chantier distinct, todo/contexte.txt sections 520-521, CLOS -- voir sections 557-566)** : P3 mesure uniquement le succes du PARSING statique (le graphe se construit sans exception) -- il n'invoque jamais l'agent CI et ne pose aucune question metier. P3.1 est un chantier separe et non couvert par le marqueur P3 ci-dessus : banc de 50 questions reelles (10 modules OCA x 5, categorises par capacite -- securite/workflow/heritage/server_actions/contraintes/vue-UI/reporting) destine a mesurer la reussite fonctionnelle de l'agent CI sur du code OCA reel, pas seulement l'extraction. Etat P3.1 : selection des modules (`scripts/categorize_oca_modules.py`) et dataset des 50 questions (`tests/oca_p3_1_question_bank.json`, verifie contre le code reel) tous deux ecrits ; **execution reelle des 50 questions via `query_graph()`/MIRO AI faite et confirmee** -- 10/10 modules, 50/50 questions validees, confiance 1.0, 0 echec a trier par capacite (purchase_request, animal, base_tier_validation, stock_inventory, sale_order_type, account_invoice_section_sale_order, database_cleanup, stock_archive_constraint, auditlog, kpi -- detail module par module todo/contexte.txt sections 557-566). Date de cloture non retracee precisement dans ce tour (travail effectue lors d'une session anterieure) -- a preciser si besoin.

---
## Bloc P4 — Inference locale — **EN PAUSE (mise de cote explicite sur mandat pmm, voir todo/contexte.txt section 568, 07/09) : ne pas reprendre sans mandat explicite de reprise**
*Deja nommé "le point le plus important" — resitué ici après P1/P2 parce que le planner et l'ontologie doivent etre stables avant de changer le modele qui les consomme*

- **Jour 1** : Confirmer le materiel local disponible (GPU, VRAM) — condition bloquante deja documentée dans `config/settings.py`. Modele local cible mis a jour depuis la version initiale de ce plan : Qwen3-14B via Ollama .
- **Jour 2-3** : Cabler `get_chat_llm("ollama")` (actuellement `NotImplementedError` volontaire) une fois le materiel confirme.
- **Jour 4-5** : Rejouer l'integralite du benchmark adversarial (les 8 modules Bloc 9 + Bloc 8 latence) sur le modele local — chiffrer le vrai budget de latence local (le chiffre p90=6.84s actuel est explicitement documente comme non representatif, temps algorithmique hors reseau Groq).
- **Jour 6** : Comparer le taux de reussite E2E local vs cloud — si dégradation, verifier si le scaffolding deterministe (backfills, corrections de contradiction) suffit a compenser un modele local plus faible que le modele cloud actuel (`openai/gpt-oss-20b`), ou s'il faut un modele local plus gros.

**Critere de fin** : benchmark adversarial complet rejoué et documenté en conditions 100% locales, chiffre de latence réel (pas extrapole) — la contrainte de confidentialite fondatrice du projet enfin demontrée en pratique.

---
## Bloc P5 — Vrai code MiroKE — **EN PAUSE (mise de cote explicite sur mandat pmm, voir todo/contexte.txt section 568, 07/09) : ne pas reprendre sans mandat explicite de reprise**
*Non daté — bloqué par l'acces, pas par la conception*

- **Jour A** : Detection de version (`__manifest__.py`), montage d'une instance Odoo de la bonne version avec le vrai corpus.
- **Jour A+1 a A+3** : Rejouer le Sprint A (extraction) sur le vrai code — mesurer le score de couverture réel par module (A1).
- **Jour A+4 a A+6** : Rejouer le Sprint D complet (jeu de gouvernance en langage metier) sur le vrai corpus.
- **Jour A+7** : Rapport final de generalisation — confirmer ou infirmer l'hypothese centrale du projet sur du code custom réel, pas seulement synthetique.

**Critere de fin** : rapport de validation réelle, seule preuve qui compte a terme.

---

## Bloc 16 — Marge, consolidation, memoire — **EN PAUSE (mise de cote explicite sur mandat pmm, voir todo/contexte.txt section 568, 07/09) : ne pas reprendre sans mandat explicite de reprise**

- **J76-J85** : Redaction du memoire (sections restantes), consolidation des rapports de benchmark en annexes, relecture.
- **J86-J90** : Relecture finale, preparation de la soutenance, derniere non-regression complete avant remise.

---

# PARTIE 4 — Table de correspondance

| Bloc (ce fichier) | Brique `architecture.md` visée | Ancien nom |
|---|---|---|
| B0-Bloc 9 | Couches 1-2, Evidence Builder, Raisonnement deterministe, Preuves | `real plan.md` Blocs 0-9 |
| P0 | (vérification, prérequis d'hygiene de suivi) | `plan_architecture_cible.md` P0 |
| P1 | Investigation Planner | `plan_architecture_cible.md` P1 |
| P1-bis | Alignement RAG-en-dernier-recours (Domaine C) sur Couche 4/Construction des preuves | (nouveau, sans equivalent dans `plan_architecture_cible.md` -- issu d'un ecart constate a l'usage, section 405) |
| P2 | Couche 3 — Couche semantique (ontologie metier + tags) | `plan_architecture_cible.md` P2 |
| P3 | Confidentialite fondatrice (inference locale) | `real plan.md` Bloc 9bis / `plan_architecture_cible.md` P3 |
| P4 | Generalisation multi-version | `real plan.md` Bloc 13 / `plan_architecture_cible.md` P4 |
| P5 | Generalisation a grande echelle OCA | `real plan.md` Bloc 14 / `plan_architecture_cible.md` P5 |
| P6 | Preuve finale sur le vrai code custom | `real plan.md` Bloc 15 / `plan_architecture_cible.md` P6 |
| Bloc 16 | Memoire de stage | `real plan.md` Bloc 16 |

---

# PARTIE 5 — Limites connues du plan

- **Fiabilite structurellement dependante d'un scaffolding deterministe lourd** : dispatch force, gating, garde-fous compensent les limites du modele. Caracteristique assumée de l'architecture — à nommer explicitement comme choix de conception dans le memoire.
- **Couche 4 (Runtime Odoo)** au-dela de ce qui existe deja (`with_user()`, resolution xmlid, contexte societe qualitatif) — reste partiel par design tant que Data Intelligence (branche ORM separée, domaine B d'`architecture.md` : "Combien ? Qui ? Quand ? Liste-moi ?") n'est pas fusionnée avec Code Intelligence ; fusion non entamée, a trancher comme decision produit separée.
- Fine-tuning cible (Option C du document source, differée a 12-18 mois) sur les patterns ou le modele échoue le plus souvent malgre le dispatch force (ex. synthese multi-volets, priorisation de findings contradictoires).


# PARTIE 6 — Perimetre de validation du PoC :

**Decision (2026-08-19)** : le PoC reste architecture sur 3 branches -- Code Intelligence, ERP, Documentaire (voir le diagramme dans `architecture.md`, non modifie) -- mais l'evaluation principale du PoC ne porte que sur un sous-ensemble explicite de cette architecture.

**Ce qui EST evalue** :
- Code Intelligence (agent, resolution de business terms, tracabilite des hops)
- ERP Runtime (données réelles, execution)
- Tracabilite des preuves (dossier de preuves, Evidence Builder)

**Ce qui est implemente mais explicitement HORS du perimetre de l'evaluation principale** :
- Module Documentaire (RAG classique -- embeddings, reranker, ingestion de documents) -- code non supprime, conserve tel quel, simplement non compte dans le score du PoC.
- Sa contribution a la branche HYBRIDE de `route()` (cas ou une question combine un terme documentaire/quantitatif) suit la meme regle : implementée, non scorée.

**Mise a jour (2026-08-30, voir todo/contexte.txt sections 347-353) -- decision produit PERMANENTE, distincte de la ligne "hors perimetre d'evaluation" ci-dessus** : le module Documentaire ne se contente plus d'etre hors score, il est desormais architecturalement limite aux documents uniquement -- l'ingestion de code par la branche RAG (`ingest_all.py`/`watcher.py`/`scheduler.py`, qui mirroraient auparavant le perimetre de Code Intelligence) a ete retiree des defauts (`code_dir`/`watched_paths`/`DEFAULT_SCAN_ROOTS` ne portent plus sur le code), et la collection ChromaDB `odoo_code` n'est plus jamais peuplee par defaut. En consequence, `document_rag/vectorstore/search.py::get_retriever()`/`retrieve()` ont ete corriges a la racine (pas de patch de surface) : l'ancien routage `is_code_query` vers une collection `odoo_code` -- qui interrogeait silencieusement une collection desormais toujours vide -- a ete supprime ; `get_retriever()` ne construit plus qu'un seul `ChromaManager('odoo_docs')`. Repere de perimetre desormais explicite : Code Intelligence traite le code, RAG documentaire traite les documents, et n'intervient qu'en dernier recours si aucune reponse n'est trouvee ailleurs (branche HYBRIDE/DOCUMENTAIRE de `route()`).

**Dette residuelle signalee, non traitee ce tour** : `tests/eval_retrieval.py` calcule encore un recall@5 separe pour des "code questions", metrique desormais sans objet (la collection qu'elle mesure est vide par construction) -- a nettoyer ou a expliciter comme obsolete dans un mandat separe. Chunks documentaires ingeres tous tagges module `unknown` -- a confirmer si attendu (le tagging par module semble concu pour la branche code) ou si un champ pertinent existe pour des documents.

**Suggere, non fait ce tour** : adapter `tests/eval_routing_accuracy.py` pour rapporter separement l'accuracy sur le sous-ensemble Code Intelligence/ERP (le perimetre score) et sur le reste (Documentaire/Hybride, hors perimetre), plutot que de melanger les deux dans un seul pourcentage.

---

- **(a) Introspection du registre Odoo réel en complement de l'AST statique** (`env['ir.model']`, `ir.model.fields`, `ir.model.access`, `ir.rule`, `ir.actions`, `ir.ui.view`) : l'extraction actuelle (Sprint A / A1, reference dans P4/P6) semble reposer sur l'analyse statique Python/XML (+ Semgrep) ; aucune confirmation trouvée d'une introspection du registre a l'execution en complement. A verifier dans le code d'extraction réel avant de trancher si c'est un vrai trou ou deja couvert autrement.
- **(b) Relations de graphe plus precises** (`field_depends_on`, `view_inherits`, `method_overrides`, `security_rule_filters_model`, `button_action_opens`, `server_action_triggered_by`, `workflow_transition_from_state_to_state`) versus les relations generiques actuelles d'`architecture.md` (`inherits`, `depends`, `calls`, `opens`, `writes`, `reads`, `triggers`, `defined_in`) -- a comparer avec `graph_builder.py` réel pour voir si le detail y est deja implicite ou s'il manque vraiment.
- **(e) Decomposition explicite en 4 moteurs deterministes specialises** (moteur d'acces / moteur de visibilite / moteur de workflow / moteur de calcul), chacun produisant des faits structures consommes par l'Evidence Builder -- l'existant (`server_action_analyzer.py`, `semgrep_locks_analyzer.py`, `authorization_gate.py`...) couvre fonctionnellement une partie de ce role mais sans cette organisation explicite en 4 moteurs nommes. Refactor de clarte/architecture potentiel, pas une correction de bug.
- **(Suggestion 2) Schema de preuves JSON normalise et versionne** (type/module/fichier/ligne/snippet/commit_hash) -- le "dossier de preuves" existe en esprit (Evidence Builder, niveau verification depliable) mais pas sous forme de schema structure explicite tel que propose par la revue.
- **(Suggestion 5) Perimetre vues/JavaScript OWL** -- non couvert a ce jour, aucune mention explicite d'un perimetre JS dans `plan.md`/`architecture.md`. A trancher : le perimetre reste serveur (Python/XML) uniquement, ou inclut-il le comportement JS/OWL cote UI ?

**Statut** : ces 5 gaps sont **enregistrés pour memoire, non priorises, non planifies dans un bloc**, en attente d'une decision explicite sur leur priorite relative aux blocs P0-P6 deja en cours de planification. Aucune modification de code ni de perimetre n'a ete decidée a partir de cette revue -- consignation seule, sur demande explicite de l'utilisateur.

---

# PARTIE 7 — Decision de sequencement avant P1

**Decision actée** : avant d'attaquer P1, trois preconditions doivent etre remplies dans cet ordre de priorite :

- (i) Clore les bugs Bloc 9 encore ouverts (les deux "STATUT ROUVERT" actuels).
- (ii) Trancher H1 explicitement (valider ou invalider l'hypothese, pas seulement la noter "observation empirique en sa faveur" comme actuellement).
- (iii) Decider du modele local cible (14B vs 7/8B) -- decision qui conditionne le Bloc P3 mais n'a pas besoin d'attendre P3 pour etre prise, dans la mesure ou elle peut influer sur des choix faits plus tot (P1/P2).

**Ordre d'enchainement retenu après ces 3 preconditions** : **P2 puis P1 puis P3** -- ordre different de celui actuellement liste dans la PARTIE 3 de ce document (qui presente P1 avant P2 avant P3). Motif reporte par l'utilisateur, non detaille davantage ce tour.

**Mise a jour (25/08, voir todo/contexte.txt section 156, additif -- rien supprime/renumerote ci-dessus)** : precondition (i) partiellement levée depuis la rédaction de ce qui precede -- Bloc 9 (PARTIE 1) n'est plus au statut "STATUT ROUVERT" cite ci-dessus mais "STATUT PARTIELLEMENT REFERME" : le bug (a) (mot-cle "consulter" absent de `core/routing.py`) est CORRIGE et desormais confirmé par execution réelle (rejeu module 08, todo/contexte.txt section 155) ; seul le bug (b) (`tool_observations` vide sur formulation informelle "document Déep") reste ouvert. Bloc 7-bis (l'autre "STATUT ROUVERT" mentionne au point 1 ci-dessus) etait deja REFERME au moment meme de la redaction de cette PARTIE 11 (sections 89-92, meme date du 21/08). Précondition (i) se reduit donc desormais a une seule question ouverte : decider si le bug (b) doit etre corrige avant de considerer (i) entierement levée, ou si son caractere mineur/non exercé par le benchmark actuel permet de clore (i) tel quel -- décision utilisateur non prise a ce jour. Préconditions (ii) et (iii) restent non levées, inchangées.

**Correction (2026-08-28, voir todo/contexte.txt section 281)** : la phrase precedente ("préconditions (ii) et (iii) restent non levées") est desormais PARTIELLEMENT PERIMEE et laissee telle quelle pour tracabilite historique -- ne pas la lire comme l'etat actuel. (i) : bug (b) (`tool_observations` vide sur "document Déep") CORRIGE et confirmé (todo/contexte.txt sections 157-163, 276). (ii) H1 : VALIDEE en version bornée (voir le corps de la section "Preconditions a valider avant P1/P2" ci-dessus, qui documente deja cette decision -- incoherence interne au present document, cette note la resout en faveur du corps de la section H1, plus recent et plus detaille). (iii) materiel local : toujours NON tranchee a ce jour. Plus important : **le Bloc P1 lui-meme (Investigation Planner explicite, Jours 1-5) n'a jamais ete entame** -- le travail effectue sous l'etiquette "Jour 6 Bloc P1" (todo/contexte.txt sections 229-262) a porte sur le durcissement du dispatch/resolver existant (fix H4, specificite business_resolver, rotation Groq, regressions Bloc 9), pas sur la construction du plan serialisable/inspectable qui est l'objet reel de P1. Bloc P1 reste donc NON CLOS, Jours 1-5 a faire integralement.

**2e correction (2026-08-28, voir todo/contexte.txt sections 282-285)** : la correction ci-dessus est elle-meme PERIMEE sur son affirmation centrale -- "le Bloc P1 lui-meme ... n'a jamais ete entame" etait inexacte, contredite par une lecture directe du disque (`code_intelligence/investigation_plan.py`, `semantic_tags.py`, 2 suites de tests dediees, champ `investigation_plan` dans `AssistantResponse`) ainsi que par les sections 224-229 de ce meme journal, non couvertes par la relecture qui a produit la correction precedente. Etat reel detaille et choix d'architecture du Jour 1-2 desormais documentes dans la note sous Bloc P1 lui-meme (PARTIE 3, "Mise a jour (28/08, voir todo/contexte.txt sections 282-283)") -- cette note fait foi, plus recente et plus detaillee que celle-ci. Bloc P1 n'est PAS "Jours 1-5 a faire integralement" : Jours 1-2/3-4/6 faits et confirmes, Jour 5 partiel (backend cable, frontend non confirme), seul le marqueur `CLOS` manque encore.
