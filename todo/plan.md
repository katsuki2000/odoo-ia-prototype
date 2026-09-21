# Plan — Agent de Code Intelligence (Odoo)

**Regle transverse, valable partout** : tests ecrits avant/avec le code, revue manuelle ligne a ligne pour tout ce qui touche `ir.rule`/`with_user()`/`has_group()`/appels privilegies non traces, sourcing obligatoire (fichier+ligne ou identifiant d'enregistrement) sur tout element produit, aucune story consideree terminee sans reexecution du benchmark adversarial end-to-end complet (sortie brute conservee).

Ce fichier liste, brique par brique de `architecture.md`, l'ensemble des taches qui composent le systeme -- ce qui a ete construit et ce qui reste a construire, decrit directement en contenu plutot que par une etiquette de statut. 
---

## Semantic Understanding (resolution nom metier -> nom technique)

*(Bloc B0, H1)*

- Table d'alias statique + fuzzy-matching (`rapidfuzz`) + arbitrage LLM borne, dans `business_resolver.py`.
- Ordre alias-d'abord (pas fuzzy-d'abord) verrouillé par un test dedié (`test_s2_0_alias_not_shadowed_by_fuzzy_single_token`).
- Appel de `resolve_business_term()` en tout debut de `route()`, avant tout dispatch de branche.
- Combinaison du signal de resolution avec un second signal (`GOVERNANCE_SIGNAL_TERMS`) pour eviter le faux positif "resolution reussie => forcement Code Intelligence" -- contre-exemple DOC-08 : resolution correcte vers `custom.asset.loan`, mais la bonne branche est Documentaire.
- Remplacer `GOVERNANCE_SIGNAL_TERMS` (aujourd'hui une liste de mots-cles a la main, calibree sur 5 questions connues : 01c, 03a, 03c, 04c, 05c) par un signal de confiance combine/pondere (`resolved_concept.confidence` + classification structuree de l'intention) plutot qu'une liste de mots-cles etendue au coup par coup.

## Investigation Planner

*(Bloc P1)*

- Generation d'un plan explicite (`InvestigationPlan`/`InvestigationStep`, vocabulaire ferme `PlanAction`, 12 actions) par construction semantique deterministe, avant tout appel d'outil reel (`PlanGenerationSource.DETERMINISTIC_SEMANTIC` -- ni appel LLM dedie, ni reconstruction a posteriori des hops traces).
- Exposition du plan dans la reponse finale (`AssistantResponse.investigation_plan`).
- Garde-fou de coherence plan/execution (`planned_tools ⊆ executed_tools`), couvrant aujourd'hui 4 des 8 categories `QuestionIntent`.
- Etendre ce garde-fou aux 4 categories `QuestionIntent` restantes, qui n'ont pas encore de verification automatisee equivalente.

## Code Intelligence Engine

### Couche 1 — Extraction du systeme

*(Bloc P3/P3.1 OCA, Bloc 9 custom, Bloc N1 natif)*

- Extraction des modeles, champs, methodes, menus, actions, vues, ACL, record rules, server actions, automations, cron, workflows.
- Pipeline CI (`.github/workflows/ci.yml`) declenchee a chaque modification de `code_intelligence/**`.
- Validation a grande echelle sur OCA : 12 depots reels (branche 17.0), 537 modules decouverts/extraits, 0 echec, confirme 3 fois independamment (sandbox, poste local, run GitHub Actions).
- Validation sur code custom et sur modules natifs coeur : detail complet dans "Validation par domaine" ci-dessous.
- Verifier dans le code d'extraction reel si l'introspection du registre Odoo (`env['ir.model']`, `ir.model.fields`, `ir.model.access`, `ir.rule`, `ir.actions`, `ir.ui.view`) en complement de l'AST statique est un vrai trou, et combler si c'est le cas.

### Couche 2 — Knowledge Graph

*(Bloc 8 robustesse, Bloc 10 staleness, Bloc 11 renommage/PyRef)*

- Construction du graphe de connaissances : relations `inherits`, `depends`, `calls`, `opens`, `writes`, `reads`, `triggers`, `defined_in`.
- Robustesse de base : cycles d'heritage (3/3 confirmes), symboles ambigus (7/7 confirmes), latence p90=6.84s hors reseau Groq, refus explicite au-dela de `MAX_MODELS_PER_QUERY=3`.
- Detection de staleness et mise a jour incrementale du graphe, a construire integralement :
  - recalcul du fichier modifie ;
  - propagation des aretes invalidees ;
  - detection des cas non couverts par le recalcul local ;
  - swap atomique du graphml servi, jamais de modification en place pendant une requete en cours ;
  - index versionne avec un hash de commit ;
  - test de non-regression garantissant qu'aucune requete ne voit un graphe a moitie reconstruit pendant un swap.
- Suivi des entites renommees/deplacees (integration PyRef, SCAM 2021), a construire integralement :
  - integrer PyRef dans le hook git ;
  - relabelliser le noeud existant (`nom_precedent` en attribut) plutot que supprimer+recreer ;
  - documenter le taux de rappel mesure (76,1%) comme limite residuelle assumee.
- Conclure formellement la verification prealable de ces deux points (staleness, renommage) -- annoncee une fois (ancien "Bloc P0") mais jamais refermee explicitement.
- Remplacer les relations generiques actuelles par des relations de graphe plus precises : `field_depends_on`, `view_inherits`, `method_overrides`, `security_rule_filters_model`, `button_action_opens`, `server_action_triggered_by`, `workflow_transition_from_state_to_state`.

### Couche 3 — Semantic Layer + Ontologie

*(Bloc P2)*

- Ontologie metier : `invoice`, `credit_note`, `purchase`, `expense`, `asset`, `leave`, `risk`, `approval`.
- Tags comportementaux : `visibility_rule`, `blocking_rule`, `calculation_rule`, `workflow_rule`, `approval_rule`, `notification_rule`.
- Tags techniques : `record_rule`, `acl`, `constraint`, `computed_field`, `server_action`, `cron`.
- 100% des noeuds `Rule`/`AccessEntry`/`Method`-avec-verrou/`ServerAction` tagues ; `WorkflowState`/`Menu` tagues ; `Group`/`Module` deliberement non tagues.
- 40 tests dedies couvrant cette ontologie.
- Rejouer le benchmark adversarial complet (8 modules custom) specifiquement dans le cadre de la couverture de cette ontologie -- jamais fait explicitement pour cette couche en particulier.

### Couche 4 — Runtime Odoo

*(Bloc 1 with_user, H2 contexte actif systray)*

- Wrapper `with_user()` pour l'evaluation ACL/record rules reelle.
- Resolution xmlid.
- Contexte societe qualitatif.
- Contexte actif systray (`active_model`/`active_id`) : cablage `miro_ai.js` -> `controllers/main.py` -> `api/main.py::AskRequestV1` -> `core/graph.py::query_graph()`/`RAGState` -> `code_intelligence/business_resolver.py::resolve_business_term()` (Step 1.5 "active_context"), bandeau de contexte visible dans le widget Discuss, 46 tests dedies.
- Trancher et mettre en oeuvre la fusion de Data Intelligence (branche ORM/donnees, aujourd'hui separee) avec Code Intelligence -- decision produit a prendre, chantier non entame.

## Evidence Builder

*(Bloc 4 sourcing, Bloc 7 gating)*

- Sourcing obligatoire fichier+ligne sur les 3 mecanismes concernes, verifie par un script mecanique dedie.
- Gating d'acces sur la reponse selon l'identite du demandeur : marqueur de contournement sensible sur tout appel privilegie non trace/identifiants codes en dur ; deux fuites de securite reelles trouvees et corrigees (lecture de code source brute, synthese LLM d'action serveur).
- Disponibilite reelle des boutons via `user_groups` + resolveur de groupe tolerant.
- Construire un schema de preuves JSON normalise et versionne (type/module/fichier/ligne/snippet/commit_hash) -- suggere, jamais entame.

## Raisonnement deterministe

*(Bloc 1 acces, Bloc 2 workflow, H3 arbitrage de preuves concurrentes)*

- Acces : `ir.rule` via `with_user()`, algorithme ET global/OU groupe, revue de securite ligne a ligne.
- Workflow/Server Actions : `ir.actions.server`/`base.automation`/`ir.cron`, lecture LLM bornee du champ `code`, tag de confiance obligatoire.
- Calcul via le graphe : champs/`depends`/overrides.
- Statut `EvidenceSufficiencyStatus.CONFLICTING` cable comme statut de premiere classe (distinct d'INSUFFICIENT), trace explicitement par `ci_evidence_decision()` avant tout fallback RAG.
- Construire le detecteur reel de preuves contradictoires -- `assess_evidence_sufficiency()` ne retourne jamais `CONFLICTING` aujourd'hui : la branche est instrumentee et testee mais aucune logique de detection de contradiction reelle n'existe encore.
- Decomposer explicitement le raisonnement en 4 moteurs deterministes specialises (acces / visibilite / workflow / calcul) -- refactor de clarte identifie, pas encore fait.
- Garder Evidence Builder (post-analyse, construction des preuves) distinct d'Evidence Check/H3 (pre-analyse, arbitrage entre preuves concurrentes) -- deux concepts differents dans `architecture.md`, a ne pas confondre.

## LLM Writer (synthese)

*(Bloc P4 inference locale)*

- Modele actuel : llama-3.1-8b-instant via Groq (cloud).
- `get_chat_llm("ollama")` deja fonctionnel (`core/llm/llm_client.py`) pour un provider local.
- Scaffolding deterministe compensant les points faibles recurrents du LLM de synthese (hallucination, dropped literals, degenerescence) : dispatch force, gating, garde-fous a chaque etage amont.
- Passage en inference locale (necessite mandat explicite pour reprendre, voir `todo/contexte.txt` section 568) :
  - confirmer le materiel local disponible (GPU, VRAM) -- modele local cible : Qwen3-14B via Ollama ;
  - rejouer l'integralite du benchmark adversarial (8 modules custom + benchmark de latence) sur le modele local ;
  - chiffrer le vrai budget de latence local -- le p90=6.84s actuel (Couche 2) est explicitement mesure hors reseau Groq, donc non representatif du cout local reel ;
  - comparer le taux de reussite E2E local vs cloud ; si degradation constatee, verifier si le scaffolding deterministe suffit a compenser ou s'il faut un modele local plus gros.
- Fine-tuning cible (differe a 12-18 mois) sur les patterns ou le modele echoue le plus souvent malgre le dispatch force (ex. synthese multi-volets, priorisation de findings contradictoires) -- decision de calendrier a documenter dans le memoire.

## Cas particulier : Documentation (RAG)

*(Bloc P1-bis routage CI-d'abord/RAG-fallback)*

- RAG limite architecturalement aux documents (pas de code) depuis le 30/08 : `ingest_all.py`/`watcher.py`/`scheduler.py` ne peuplent plus la collection `odoo_code`, `get_retriever()` ne construit plus qu'un seul `ChromaManager('odoo_docs')`.
- Declenchement du RAG limite a 3 conditions : le systeme ne contient pas la reponse, la documentation apporte un complement utile, ou l'utilisateur demande explicitement une reponse d'apres les documents/la procedure/la politique interne.
- `ci_evidence_decision()`/`format_output()` verifient `_has_explicit_doc_request(state)` en tout premier, avant meme le statut de suffisance CI -- une demande documentaire explicite bascule vers `generate()` (RAG) quel que soit le statut CI (SUFFICIENT/CONFLICTING/INSUFFICIENT confondus).
- Test dedie couvrant le scenario SUFFICIENT + demande documentaire explicite (`test_ci_evidence_decision_sufficient_with_doc_request_falls_back_to_generate`), question verbatim du signalement reel qui a revele le trou.
- Nettoyer ou expliciter comme obsolete le recall@5 "code questions" calcule par `tests/eval_retrieval.py`, desormais sans objet puisque le RAG ne porte plus que sur les documents.
- Confirmer si le tag module `unknown` porte par tous les chunks documentaires est attendu, ou le corriger.
- Separer dans `tests/eval_routing_accuracy.py` l'accuracy sur le perimetre score (Code Intelligence/ERP) du reste (Documentaire/Hybride, hors perimetre).
- Backend d'embeddings : `local_light` (`all-MiniLM-L6-v2`, ONNX integre a ChromaDB, 384 dims) en usage apres abandon du tunnel `local_server`/`nomic-embed-text` (tunnel ngrok/Colab mort, `404` sur `/v1/embeddings`).
  - Recalibrer `VECTOR_SIMILARITY_FLOOR` pour ce backend (aujourd'hui 0.20, valeur de repli historique non recalibree -- chevauchement on-topic/hors-sujet observe : "Gestion des stocks" et "meteo" a egalite, 0.330, sur l'echantillon teste).
  - Corriger le label cosmetique `embedding_model` dans `get_stats()` (affiche toujours `nomic-ai/nomic-embed-text-v1.5`, sans impact fonctionnel reel -- la dimension mesuree 384 confirme que l'embedding reel est bien `all-MiniLM-L6-v2`).

## Validation par domaine (`architecture.md`, "Domaines supportes")

### A. Code Intelligence — custom

*(Bloc 9)*

- 14 modules custom / 8 mecanismes de gouvernance couverts, confirmes verbatim en E2E (raw/direct/full-pipeline) : `credit_note_approval`, `credit_note_visibility`, `hr_leave_workflow`, `purchase_request`, `asset_loan`, `automation_traps`, `expense_reimbursement_indirect`, `deep_inheritance_security`.
- 3 bugs trouves lors d'une reouverture temporaire, corriges et confirmes par execution reelle : pattern H4 (mot-cle routeur manquant), mot-cle "consulter" absent des listes de `core/routing.py`, resolution business term en echec sur formulation informelle ("document Deep").

### A. Code Intelligence — OCA (generalisation open source)

*(Bloc P3/P3.1)*

- Pipeline d'extraction sur 12 depots reels (branche 17.0) : 537 modules decouverts/extraits, 0 echec, confirme 3 fois independamment.
- Banc de 50 questions reelles sur 10 modules OCA, categorisees par capacite (securite/workflow/heritage/server_actions/contraintes/vue-UI/reporting) : 50/50 validees, confiance 1.0, 0 echec.

### A. Code Intelligence — natif (coeur Odoo)

*(Bloc N1, voir `todo/contexte.txt` sections 747-748)*

- Ferme un ecart explicite d'`architecture.md` ("natifs, OCA et custom") : ni le volet custom ni le volet OCA ne couvrent les modules natifs coeur -- `CORE_MODULES_ALWAYS_LOADED` (account/sale/stock) garantit seulement que ces modules sont charges dans le graphe de production, pas qu'ils sont valides par un banc de questions.
- Perimetre retenu, 5 modules : purchase (workflow/approbation -- double seuil `po_double_validation_amount`, defaut 5000€, `_approval_allowed()`, comparable directement a `custom_credit_note_*`), sale (data intelligence), account (calcul/etat, cite litteralement dans les exemples d'`architecture.md`), stock (mecanisme distinct -- quantites temps reel, multi-entrepot), maintenance (`owner_user_id`/`assign_date` sur `maintenance.equipment`, equivalent natif de "mise a disposition"/`custom.asset.loan`).
- Extraction technique confirmee sur les 5 modules (rapide, aucune limite d'echelle cote extracteur) : purchase 19 modeles/8 regles/38 ACL/40 vues/5 groupes/4 server actions ; sale 35/27/54/55/3/3 ; account 90/31/163/131/10/12 ; stock 75/16/91/128/18/12 ; maintenance 7/8/10/25/1/0.
- Construire le banc de questions/verite-terrain pour chacun des 5 modules -- travail manuel de lecture de code + verification, delegue a pmm (goulot humain, pas technique : account/stock sont 4-5x plus gros que purchase/sale en nombre de modeles). Commencer par purchase ou maintenance (les plus petits).
- Ecrire le script de verification dedie par module, une fois le banc disponible pour au moins un module (miroir du pattern `scripts/check_bloc9_0N_*.py`).
- Confirmer chacun des 5 modules end-to-end (raw/direct/full-pipeline) avec verite terrain verifiee, meme standard que le volet custom.

### B. Data Intelligence (runtime ERP)

- Donnees reelles, execution via runtime Odoo -- fait partie, avec Code Intelligence et la tracabilite des preuves, du perimetre principal d'evaluation du PoC (decision produit du 19/08/2026).

### C. Documentation Intelligence

- Implementee, mais explicitement hors perimetre de l'evaluation principale du PoC (decision produit du 19/08/2026) -- fonctionnement detaille dans "Cas particulier : Documentation" ci-dessus.

## Chantiers, par ordre de priorite suggere

1. **Natif (purchase/sale/account/stock/maintenance)** -- detail complet ci-dessus, "Validation par domaine".
2. **Detecteur de contradiction reel (H3)** -- detail ci-dessus, "Raisonnement deterministe".
3. **Inference locale** -- necessite mandat explicite pour reprendre, voir `todo/contexte.txt` section 568. *Situe ici, avant les chantiers 4-6, car le planner et l'ontologie doivent etre stables avant de changer le modele qui les consomme.* Detail ci-dessus, "LLM Writer".
4. **Staleness / mise a jour incrementale du graphe** -- detail ci-dessus, "Couche 2".
5. **Renommage (PyRef)** -- detail ci-dessus, "Couche 2".
6. **Fusion Data Intelligence / Code Intelligence (Couche 4)** -- detail ci-dessus, "Couche 4".
7. **Vrai code MiroKE** -- necessite mandat explicite pour reprendre, voir `todo/contexte.txt` section 568. Bloque par l'acces au corpus reel, pas par la conception.
   - Jour A : detection de version (`__manifest__.py`), montage d'une instance Odoo de la bonne version avec le vrai corpus.
   - Jour A+1 a A+3 : rejouer le Sprint A (extraction) sur le vrai code -- mesurer le score de couverture reel par module.
   - Jour A+4 a A+6 : rejouer le Sprint D complet (jeu de gouvernance en langage metier) sur le vrai corpus.
   - Jour A+7 : rapport final de generalisation -- confirmer ou infirmer l'hypothese centrale du projet sur du code custom reel.
8. **Memoire, consolidation** -- necessite mandat explicite pour reprendre, voir `todo/contexte.txt` section 568.
   - J76-J85 : redaction du memoire (sections restantes), consolidation des rapports de benchmark en annexes, relecture.
   - J86-J90 : relecture finale, preparation de la soutenance, derniere non-regression complete avant remise.

## Gaps mineurs, non priorises (enregistres pour memoire)

- Contrat de couverture d'outils / trajectory recall (lacune 4.4, recherche externe section 860) -- plan detaille dans todo/plan_tool_coverage_contract.md, pas encore mandate.

- Introspection du registre Odoo reel en complement de l'AST statique (voir Couche 1).
- Relations de graphe plus precises (voir Couche 2).
- Decomposition en 4 moteurs deterministes specialises (voir Raisonnement deterministe).
- Schema de preuves JSON normalise et versionne (voir Evidence Builder).
- Perimetre vues/JavaScript OWL -- non couvert a ce jour, a trancher.
- Dette RAG documentaire (metrique obsolete, tag `unknown`, split accuracy) -- voir "Cas particulier : Documentation".

## Points a trancher ou a documenter dans le memoire

- Fiabilite structurellement dependante d'un scaffolding deterministe lourd : dispatch force, gating, garde-fous compensant les limites du LLM de synthese -- caracteristique d'architecture a nommer explicitement.
- Couche 4 (Runtime Odoo) reste partielle tant que la fusion Data Intelligence / Code Intelligence (chantier 6 ci-dessus) n'est pas tranchee.
- Fine-tuning cible differe a 12-18 mois -- decision de calendrier a documenter.

---

*Historique detaille (mises a jour datees, corrections, reouvertures, diagnostics complets) archive dans `todo/contexte.txt`.*
