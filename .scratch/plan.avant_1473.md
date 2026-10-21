# Plan et tableau de decision -- MIRO AI

Lecture : **A** = ce qu'il faut decider maintenant ; **B** = plan d'execution P0-P10 ; **C** = Plan R du resolveur (PR0-PR4) ; **D** = audit du resolveur du 15/10 et ce qu'il en reste ; **E** = lots de branches deja fusionnes (memoire).

## A. Decisions en attente (par priorite, etat au 17/10/2026)

1. **Taille de la liste dense de l'arbitre** (`HYBRID_SEMANTIC_LIMIT`, passee de 10 a 20 en 1460, appliquee aussi dans `dense_lookup.py`). Sonde de 120 appels (1467) : HRL-Q1 et HRL-Q2 passent de 0/10 a 10/10 `hr.leave` ; SAL-Q3 et STK-Q2 se stabilisent ; mais PUR-Q1 (temoin, libelle cite) bascule sur `res.users` 3 fois sur 5 a 20 (5/5 `purchase.order` a 10), car la liste plus longue ajoute des aimants (groupe « User »). Options : **A** garder 20 ; **B** revenir a 10 (non recommande : HRL de nouveau a 0) ; **C** garder 20 et ne pas ajouter de candidats denses quand un libelle est cite (ou le resoudre sans arbitre), un seul changement a mesurer sur PUR-Q1 ; **D** epingler le serveur d'inference (voir 2). Recommandation : D puis C.
2. **Epingler le serveur d'inference** (FAIT en 1469, a utiliser) : `core/llm/server_fingerprint.py` ; l'audit affiche `[SERVEUR] <id>`, ecrit `captures/inference_server_fingerprint.json`, ajoute `server` a chaque ligne et avertit si l'empreinte change ; ne comparer deux scores que s'ils portent le meme `server`. Limite : ne distingue pas une autre quantification sous le meme nom si le serveur n'expose ni `system_fingerprint` ni metadonnees. Raison : les reponses de l'arbitre changent de regime apres une reconnexion (1467), et le meme code a donne 45/48 (1456), 46/48 (1461) puis 44/48 (1462) : l'ecart entre deux passages est de la taille du gain mesure.
3. **Amendement a la section 1227** (journal 1436 / `config.json`) : le systeme R0 (resolveur de production avec alias statiques) est retire d'E1 avec les alias ; R1 devient la reference. A valider par pmm.
4. **Decision D1 d'E1 (generateur de candidats hybride en production ?)** : aucun bras teste n'a satisfait son critere pre-ecrit (B = liste de 10 rejetee, 1367 ; C = annotation par les boutons non retenue, 1376). R4 (BM25 + dense, RRF) a mesure 9 positifs sur 12 dans le top 10 contre 7 pour le dense de production et 8 pour le flou (1365) : c'est l'argument pour passer un jour de la concatenation actuelle (libelles cites + 5 lexicaux + N denses) a une fusion RRF. Je n'ai pas trouve de decision D1 formelle dans le journal ; le calibrage reste partiel (decision de pmm du 13/10 : tranche partielle d'abord, >= 120 cas avant D1). A confirmer par pmm : etat reel du calibrage et date de D1.
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

## Plan d'execution

Objectif : atteindre `architecture.md` 

Question à se poser à chaque bifurcation : l'IA pourra-t-elle repondre correctement sur n'importe
quelle instance Odoo 17 ?

### Simplification de l'orchestration

Réduire progressivement les heuristiques sémantiques dispersées (routage, intention, résolution et choix
d'outils) au profit d'un plan structuré proposé par le LLM, validé avant exécution. Conserver déterministes
l'identité, les autorisations, le périmètre, la validation des appels, les budgets et la provenance/vérification
des preuves. En cas d'ambiguïté, demander une précision plutôt que deviner. Toute consolidation est guidée par
les échecs mesurés du protocole et ne fusionne pas CI, RAG documentaire et accès ORM en un sous-système opaque.

La direction inverse est à l'étude : récupération hybride dans le graphe (BGE-M3, lexique, BM25) puis expansion
déterministe par arêtes typées, le LLM ne faisant que rédiger à partir d'un prompt augmenté. Elle est évaluée par
les expériences E1 (P4) puis E2 (P6), pré-enregistrées en section 1227 du journal. Aucun changement
d'orchestration, de planificateur ni de boucle ReAct avant leurs résultats.

### Ordre et dependances

P0 -> P1 -> P2 -> T -> P3 -> P4 -> P5 -> P6 -> P7 -> P8 -> P9 -> P10

Apres T, P3 a P7 ne sont lancées que si la mesure de T montre des échecs précis qu'elles corrigeraient, phase par phase. P4 et P5 sont independantes entre elles après P3. P8 etend le verificateur de T ; si P7 est retenue, il s'appuie sur le registre. P9 suppose le contrat d'identite de P3. P10 n'utilise aucun artefact
de calibrage.

### P0 -- Socle reproductible

- Arbre git propre : relire les diffs, separer commits de code et de journal.
- Suite de tests deterministe et isolee : aucun test ne depend d'un fichier local, d'un corpus present sur
  un poste ou d'un reseau ; tout ce qui depend de la machine passe par `.env` 
- Configuration unique : un seul fichier `.env` pour fournisseur LLM, hotes autorisés, fenêtre de contexte,
  budgets, chemins ; valeurs par defaut coherentes entre code, README et `.env.example`.
- Documentation coherente : plan, architecture, journal et README sans contradiction.
- Réutiliser l'existant avant d'ajouter ou de réécrire : inventorier les intégrations LLM et embeddings,
  le RAG, les capacités agentiques, les bibliothèques et les fonctions natives d'Odoo 17. N'ajouter une
  dépendance ou un nouveau sous-système que si un besoin mesuré et non couvert le justifie.
- Distinguer les modules présents sur disque des modules réellement installés dans l'instance. Le graphe
  actif représente les modules installés ; les chemins d'addons servent à retrouver leur code, pas à
  déclarer tous les dossiers disponibles comme installés. Les addons OCA tiers sont rangés sous
  `odoo_addons/` selon la convention du projet ; `addons_path` doit viser le répertoire parent des modules.

Sortie : suite verte reproductible sur une machine neuve, une seule source de configuration.

### P1 -- Protocole de mesure gelé


- Cas d'evaluation figés : hash d'instance, utilisateur, société, langue, question, intention et objets
  attendus, preuves acceptables, affirmations attendues, règle d'abstention.
- Métriques : `accuracy_all_questions`, `accuracy_answered_questions`, `coverage`, `unsupported_claim_rate`,
  `wrong_tool_rate`, `technical_identifier_leak_rate`, `human_business_acceptance_rate`, et par étage
  `resolution_recall_at_k`, `evidence_completeness`, `answer_faithfulness`.
- Contre-exemples d'ambiguite (un terme générique ne se resout jamais par defaut vers un domaine).
- Critère statistique pre-enregistré : `accuracy_all_questions >= 80 %`, couverture minimale fixée avant le
  run, borne basse a 95 % atteignant 80 %, incertitude robuste au regroupement par instance, ventilation par
  instance, module, langue et famille de question.
- Separation par instance entiere, jamais par tirage aleatoire de questions ; aucun snapshot de validation
  n'est utilise pour calibrer regles, seuils, lexique ou alias.

Sortie : protocole figé, mesure de depart etablie, harnais rejouable en une commande.

### P2 -- Branche documentaire : restitution exhaustive

- Cas figes documentaires : questions dont la reponse est une liste, un tableau ou une procedure complete
  presente dans un document ; mesure du rappel des elements attendus et de `answer_faithfulness` sur ce
  perimetre.
- Localisation de la cause par etage, avec comparaison au comportement anterieur au refactoring : decoupage
  des documents (liste ou tableau coupe entre fragments), recuperation (nombre de fragments, fusion
  hybride, reclassement), construction du contexte (budget, troncature), consignes de generation, post-traitement.
- Correction a la racine : recuperation des fragments contigus quand un passage est une liste ou un tableau ;
  budget de contexte derive de la fenetre configuree ; consigne de generation exigeant la restitution de tous
  les elements presents dans les passages recuperes ; controle deterministe qu'aucun element du passage cite
  n'est omis.
- Aucune regle liee a un document ou a une question precise ; tests de non-regression sur des corpus varies.

Sortie : toute reponse documentaire restitue l'ensemble des elements presents dans les passages recuperes,
mesure sur les cas figes.


### T -- Tranche verticale minimale

- Chaine : routeur, puis graphe de code, documents et lecture ORM, puis LLM, puis verificateur deterministe.
  Chaque etage a un seul role ; aucun composant de P3 a P7 n'est requis.
- Verificateur deterministe limite a trois types d'affirmations : nombre (compare au resultat ORM), groupe
  (cherche dans le graphe), methode (surcharge verifiee dans le graphe). Affirmation non supportee retiree ou
  signalee ; aucun LLM dans la verification.
- Mesure : protocole gele de P1 rejoue tel quel, sans changer cas ni seuils.
- Chaque echec mesure est rattache a un etage ; une phase de P3 a P7 n'est lancee que pour corriger un echec
  demontre par cette mesure.

Sortie : mesure de T avec echecs ventiles par etage ; liste des phases de P3 a P7 retenues, chacune avec
l'echec qui la justifie.

### P3 -- Empreinte d'instance et contrat d'identite

- Empreinte : modules effectivement installés dans Odoo, versions et états issus de l'instance,
  chemins d'addons accessibles, langues actives, hash. Les modules disponibles sur disque mais non installés
  sont inventoriés séparément et exclus du graphe actif. Les dépendances déclarées et les dépendances
  effectivement observées sont distinguées. Attachee à chaque graphe, lexique, trace, reponse et resultat
  d'evaluation.
- Identité : toute lecture ERP s'execute par l'ORM sous l'identite du demandeur ; clé du demandeur absente
  signifie lecture refusée ; utilisateur et societe viennent de la session authentifiée, jamais du LLM ;
  aucune élévation implicite, aucun SQL brut. Un mode technique explicite, par variable d'environnement,
  reservé aux scripts et tests, est journalisé.
- Isolation reseau : hotes autorises explicites, fournisseur LLM interchangeable par configuration seule.

Sortie : toute reponse et toute trace rattachées à une empreinte ; aucune lecture possible sans identité.

### P4 -- Lexique unique et resolution metier

- Lexique bidirectionnel (terme vers objet, objet vers libellé) derivé de l'instance : traductions statiques
  et runtime, lié a l'objet exact (modele, champ, menu, selection), à sa source, son module, sa langue.
  Les alias manuels sont retires du code (journal 1436-1438) : aucune table d'alias, aucune couche de surcharge.
- Resolution : mention technique exacte, lexique, contexte d'ecran, flou puis semantique comme indices,
  puis proposer-verifier par le LLM (noms valides dans le graphe uniquement). Discriminant (champ et valeur)
  dans `ResolutionResult`. Panne du backend d'embeddings signalée, jamais masquée.
- Departage deterministe fondé sur la rareté des indices ; abstention explicite en cas d'ambiguité.
- Mesurer ce que le flou et le sémantique (bge-m3) resolvent seuls ; si le sémantique domine, réduire les seuils flous, puis étendre l'index aux champs, menus, boutons et groupes. Le sémantique reste un indice : aucune décision d'accès n'en dépend.
- **Expérience E1 (pré-enregistrée, section 1227 du journal)** : hors ligne, sans appel LLM, sans changer le
  comportement de MIRO. Compare le résolveur actuel (R1, sans alias ; R0 avec alias retiré, journal 1438) à une recherche sur des fiches
  de nœuds du graphe : lexique et BM25 (R2), BGE-M3 (R3), fusion RRF (R4), puis expansion déterministe par arêtes
  typées (R5). Les cas gelés sont tous `held_out` et ne portent que sur des modèles : un jeu de calibrage séparé
  est construit (familles : terme paraphrasé, libellé exact, cible non-modèle, terme ambigu, terme absent, fr et en),
  avec vérité terrain par oracle Odoo ou relecture humaine, jamais déduite du graphe. Tout réglage se fait sur ce
  jeu ; la configuration est figée, puis un seul passage sur les `held_out`. Critères D1 à D3 fixés avant le calcul ;
  la décision sur le planificateur LLM n'en fait pas partie (voir E2 en P6).

Sortie : `resolution_recall_at_k` mesure, ablation sans table d'alias au niveau du plancher fixe en P1.

### P5 -- Routage explicite des sources

- Intention de source : comportement, données, documentation interne,combinaison declarée.
- Ordre de décision : mode explicite de l'utilisateur, formulation explicite, règles déterministes, contexte
d'écran, LLM comme signal avec confiance ; clarification si la confiance est faible.
- Le routage précede tout retrieval ; la recherche documentaire n'est lancée que si la source l'exige.
- Sources utilisées affichées avec la reponse.

Sortie : `RoutingResult` produit avant retrieval, sans choix silencieux.

### P6 -- Investigation pilotée par le plan et budget

- `InvestigationPlan` produit avant tout appel d'outil, vocabulaire d'actions ferme, validé par le moteur ;
  il porte les preuves requises, generiques par intention.
- Le moteur execute exclusivement le plan ; le LLM propose, ne decide pas.
  Invariant : outils executés inclus dans outils planifiés inclus dans outils autorisés.
- Boucle : après chaque action, réevaluation des obligations ; arret à satisfaction ou épuisement du budget.
- Porte de suffisance : suffisant, insuffisant ou conflictuel, calculee sur obligations de preuve.
- `InvestigationBudget` unique, toutes valeurs en configuration, derivées de la fenetre de contexte ;
  degradation par priorité avec signal structuré de toute perte, transmis à la porte de suffisance.
- Contexte d'instance compact et deterministe pour planifier et rediger.
- **Expérience E2 (conditionnelle)** : lancée seulement si E1 satisfait D1 à D3. Compare bout en bout la boucle
  ReAct actuelle et la récupération hybride avec collecteurs déterministes (`wrong_tool_rate`,
  `evidence_completeness`, `answer_faithfulness`, latence, coût, appels LLM), d'abord sur le jeu de calibrage, puis
  en un seul passage sur les `held_out`. C'est elle, et non E1, qui décide si le planificateur LLM est conservé,
  réduit ou supprimé pour certaines familles de questions.

Sortie : `wrong_tool_rate` mesuré ; aucun outil executé hors plan ; aucune limite de taille en dur.

### P7 -- Registre de faits et habilitation

- Chaine Observation, Evidence, Fact, Claim ; chaque outil emet des observations structurées ; les faits sont
  derivés de facon deterministe, etiquetés statique ou runtime, avec portée et niveau de preuve.
- Un fait statique n'est emis que si le graphe le prouve et que la question ne depend pas de l'etat runtime.
- Filtrage d'habilitation avant le LLM : mecanismes de contournement, champs et enregistrements hors
  perimetre retires, avec motif consigne.
- Trace complete reconstructible, rattachée à l'empreinte.

Sortie : `evidence_completeness` mesuré ; toute observation passe par le filtre.

### P8 -- Redaction et verification

- Redaction en deux niveaux plus gouvernance : explication metier sans identifiant technique, niveau
  verification depliable ; prompt en trois blocs (connaissance generale, faits, preuves) ; libelles issus
  du lexique unique.
- Verification deterministe de la chaine Claim, Fact, Evidence ; affirmation sans support retirée ou signalée ;
  `VerificationReport` (faits preservés, perdus, ajoutés, contredits) ; etage semantique sans ajout de fait.
- Mode shadow d'abord : comparaison du verificateur avec les correctifs textuels existants sur le protocole gelé.
- Retrait des correctifs propres à un cas, par lots, chaque lot validé par rejeu du protocole gelé et par
  des cas hors calibrage.
- Releve humain par des non-techniciens avec grille pre-enregistree ; une erreur metier critique invalide le cas.

Sortie : `answer_faithfulness`, `unsupported_claim_rate` et `technical_identifier_leak_rate` (zone utilisateur
a 0) conformes aux seuils fixes en P1 ; correctifs specifiques retires sans regression.

### P9 -- Donnees, runtime et audit d'instance

- Reprendre `erp_data` comme sous-systeme runtime autonome, sans le fusionner avec le CI. L'agent ReAct et
  les outils metier codes en dur deviennent progressivement un plan d'investigation borne et des outils
  typés, decouverts selon le schema et les droits de l'instance.
- Evaluer MCP comme interface interoperable pour ces outils : schemas d'entree/sortie structures,
  decouverte et appels standardises. MCP est une couche de transport et de contrat ; il ne fournit pas
  l'autorisation Odoo, l'identite du demandeur, les ACL, les regles d'enregistrement, le perimetre de
  societes, les budgets ni la provenance des faits.
- Le serveur runtime doit appeler l'ORM sous l'identite authentifiee par Odoo, sans `sudo` ni SQL brut.
  Le LLM ne recoit aucun outil generique `execute_kw` ; le moteur valide chaque modele, champ, domaine,
  operation, limite et societe avant execution.
- Pour limiter le temps de mise en oeuvre, conserver d'abord l'adaptateur XML-RPC existant vers l'ORM ;
  verifier la disponibilite de l'API externe selon l'offre et le mode d'hebergement. Un module Odoo avec
  controleur JSON et appels ORM directs reste l'alternative si XML-RPC n'est pas disponible. Ne pas
  prendre le JSON-RPC interne du client Web pour un contrat externe stable. MCP pourra s'ajouter ensuite
  comme facade interoperable, sans etre un prerequis.
- Premier lot d'outils ORM read-only : `fields_get`, `search`, `read`, `search_count`, `read_group` et
  `name_search`. Ce dernier sert a resoudre les noms metier en enregistrements ; borner ses resultats,
  valider le modele et les champs, et ne pas le traiter comme un remplacement de `search` (`name_search`
  retourne principalement des paires identifiant/nom et son resultat depend du modele).
- Chaque appel produit une Observation structuree puis des Evidence et Facts avec identite, societe,
  horodatage, source, volume et signal de troncature. Les questions de donnees consomment ce registre
  commun ; le CI reste un moteur separe qui pourra emettre les memes contrats.
- Contrat de lecture : ORM sous l'identité du demandeur, perimètre de societés explicite, ACL et règles
  appliquées, lecture seule, plafond de lignes, budgets de temps et de contexte, journalisation de chaque
  requete, refus declaré hors perimetre. Outils typés, jamais de SQL produit par le LLM.
- Les questions combien, qui, quand passent par le meme pipeline et le meme registre.
- Introspection du registre runtime (vues, actions, server actions en base, Studio) en complement de l'AST.
- Audit d'instance versionné : modules non indexés, extractions en échec, references non resolues, traductions
  manquantes, domaines sans outil de preuve, termes ambigus ; capacités classees `couverte`, `ambigue`,
  `preuve_manquante`, `non_supportée`, alimentant un backlog.
- Sonde de justesse d'instance : questions generées automatiquement à partir du graphe de l'instance, dont la
  reponse attendue se deduit du graphe lui-meme (qui peut approuver une action, quelle règle s'applique, ou une règle est definie) ; resultat joint au rapport d'audit comme premier indicateur de justesse, sans remplacer
  l'evaluation avec relecteurs de P1 et P10. Aucune question de la sonde n'est utilisée pour calibrer.

Sortie : questions de données couvertes ou declarées hors perimetre ; rapport d'audit et résultat de la sonde de justesse cohérents avec l'empreinte, produits sur une instance neuve par une seule commande.

### P10 -- Preuve de généralisation

- Plusieurs snapshots independants (versions, langues, modules custom, configurations differents), dont des graphes OCA distincts, jamais utilisés pour calibrer.
- Rapport : métriques de P1, intervalle de confiance regroupé par instance, ventilation par instance, module,
  langue et famille, cas d'abstention. La conclusion porte sur les N instances echantillonnees.

Sortie : `accuracy_all_questions >= 80 %` hors calibrage, borne basse à 95 % atteignant 80 %.

---

# C. Plan R -- Resolveur metier (PR0 a PR4)

## Plan R -- Resolveur metier : le graphe borne, le LLM choisit (brouillon v2, 13/10/2026)

Statut : brouillon valide par pmm le 13/10/2026 (section 1278) ; seuils R6 encore a fixer ; rien d'applique au code. A valider par pmm avant tout mandat. Echeance de reference : livraison du 20/10/2026
(`todo/perimetre_livraison_20_octobre.md`). Lie a P4 / E1 (section 1227) et aux points (4)-(5) de la section 1277.
Nommage : phases du plan = PR0 a PR4 ; systemes experimentaux E1 = R1 a R6 (R0 retire avec les alias, journal 1438 ; R6 = R4 + arbitrage LLM, a creer).
v2 : integre une relecture externe, chaque point verifie dans le code local (branche `main`, HEAD e42dadf).

### 1. Constats lus dans le code

1. `resolve_business_term` : mention exacte -> dense (decide seul si score >= 0.25 et ecart
   >= 0.10) -> fuzzy + departage deterministe + arbitrage LLM borne. Un dense confiant n'est jamais verifie par le LLM.
2. L'arbitrage LLM est une liste fermee (hors liste = rejet) ; sa shortlist combine fuzzy et candidats semantiques si un client LLM
   est fourni. Sorties admises aujourd'hui : un candidat exact ou `NONE`. `AMBIGU` n'existe pas : il est traite comme hors liste.
3. Trois appelants, deux comportements : `core/routing/routing.py:103` (`llm=None`), `agent/loop.py:592` (LLM passe),
   `agent/tool_helpers.py:86` (sans LLM).
4. `conftest.py` force `RESOLVER_SEMANTIC_RETRIEVAL_ENABLED=false` (autouse) : les 2 tests `plan_steps` en echec mesurent exact +
   fuzzy, sans dense ni arbitrage. A requalifier, pas a « corriger » par un retour des alias.
5. Le harnais E1 n'a pas de client LLM : R1 a R4 mesurent la generation de candidats, jamais le choix LLM.
6. Calibrage E1 : 8 cas, `status: seed_incomplete`. Cible deja inscrite en 1227 : >= 20 cas par famille, >= 120 au total, seconde
   instance `en_US` ouverte. `frozen_cases.json` : 249 cas, tous `held_out`.
7. Mesure dense deja faite (sondes /tmp, section 1277) : sur 4 formulations de « conges », `hr.leave` n'est dans aucun top 6.
   Preuve negative sur le dense seul uniquement.
8. Aucune etape deterministe de libelle metier exact : `exact_mention.py` ne traite que les noms techniques de modeles et de
   modules (les libelles d'instance ne servent qu'aux heuristiques de rarete de `matching.py` et au dense). « Conges » -> `hr.leave`
   n'est donc pas garanti sans alias.
9. Metriques E1 (`metrics.py`) : `recall_at_k` mesure le classement, pas la decision ; `silent_false_resolution` se calcule sur
   `candidates[0]`, pas sur le choix rendu ; `clarify_correct` est vrai des qu'il y a >= 2 candidats distincts (propriete des
   candidats, pas une vraie demande de precision) ; `run.py` ne charge que le calibrage.
10. Contradiction D1 : `config.json` D1 contient `held_out_recall_at_5_R4_ge_R0_minus_points`, alors que le `held_out` doit rester
    intact jusqu'a un passage unique. Et `run.py` ne calcule rien sur le `held_out`.
11. `card_node_types` (config E1) inclut deja Model, Menu, Field, Method, Group, Rule, Button : les mesures E1 portent deja sur ces
    types. Ce qui n'existe pas, c'est leur exploitation en production : `ResolvedConcept` ne rend que modeles et modules.

### 2. Principe

- Le graphe (lexique d'instance, BM25, BGE-M3, fusion RRF) **genere des candidats** ; il ne decide pas.
- Le LLM (Qwen3) **choisit dans une liste fermee** de candidats annotes (libelle d'instance, module, description, source du
  libelle) ou repond `NONE` / `AMBIGU`. Toute autre sortie = invalide = aucune resolution automatique, jamais de choix par defaut.
- `NONE`, `AMBIGU` ou sortie invalide -> clarification avec 2 ou 3 libelles metier de l'instance, sans noms techniques.
- Aucune table d'alias manuelle requise. Un libelle d'instance exact et unique decide sans LLM (regle a creer, constat 8).
- Le prompt dit que l'instance prime sur la connaissance d'Odoo ; chaque candidat porte son module (standard / OCA / specifique).

### 3. Phases (chacune = un mandat, une validation, un journal)

#### PR0 -- Rendre la mesure possible (aucun changement de comportement MIRO)
- M1 : `DenseCardIndex.build` ecrit le cache apres chaque lot ; `run.py` persiste le resultat de chaque systeme des qu'il termine.
  Test hermetique (embedding factice qui echoue au milieu : la seconde construction ne recalcule que les cartes manquantes).
- M2 : client LLM injectable dans le harnais E1 + systeme R6, avec le contrat `NONE`/`AMBIGU`/invalide. Amendement a 1227 :
  journalise et fige avant tout calcul.
- M3 : metriques de decision, definies **avec leurs denominateurs avant calcul** :
  recall du candidat correct dans la liste (@1/@5/@10) ; decision correcte (choix rendu = attendu) ; faux choix silencieux calcule
  sur le choix rendu, parmi les cas resolus et parmi tous les cas ; clarification correcte stricte (MIRO demande vraiment) sur les
  cas ambigus ou absents ; taux de recours au LLM, latence, erreurs d'appel LLM et d'embeddings.
- M4 : calibrage. Decision de pmm requise : (a) viser la cible 1227 (>= 120 cas, >= 20 par famille, instance `en_US`) ou (b) une
  tranche partielle de ~60 cas, etiquetee « calibrage partiel », utilisable pour deboguer R6 mais **pas** pour la decision D1
  (risque d'une confiance artificielle).
  DECIDE par pmm (13/10/2026) : (b) calibrage partiel d'abord ; completer vers 120 avant la decision D1. Verite terrain par oracle Odoo ou relecture humaine, jamais
  deduite d'un systeme compare. Aucun cas pris dans les `held_out`. Inclure `adversarial_custom` (modele ou libelle renomme).
- Sortie : tableau R1..R4 + R6 sur le calibrage, par famille et par langue.
- Requalifier les 2 tests `plan_steps` ; reecrire `test_j6_context_validation` sans figer les langues actives.

#### PR1 -- Decision (criteres ecrits avant calcul)
- D1 a D3 de `config.json` repris, sauf la clause `held_out` de D1 : retiree par amendement (DECIDE par pmm le 13/10/2026, section
  1278), a appliquer dans `config.json` et a journaliser avant tout calcul. D1 se decide sur le calibrage seul (>= 120 cas) ; le
  `held_out` n'est touche qu'en PR4.
- Pour R6 (seuils a fixer par pmm avant de lancer) : faux choix silencieux de R6 <= celui de R4, meme cas, meme definition ;
  decision correcte sur les cas non ambigus ; clarification stricte attendue sur les cas ambigus et absents.
- Si D1 echoue : le resolveur reste en l'etat, la limite est documentee, pas de retour aux alias sans decision explicite.

#### PR2 -- Implementation (seulement si PR1 est favorable)
- [1446-1447 : regle deterministe de libelle de plusieurs mots, retiree en 1450 (decision sans arbitre : STK-Q1, STK-Q5 faux). `resolution/label_mention.py` fournit maintenant les libelles cites comme preuves en tete de la liste fermee ; l'arbitre decide.]
- Regle deterministe de libelle exact : normaliser (casse, accents, langue demandee) ; un seul modele -> resolu sans LLM ; plusieurs
  -> clarification ; aucun -> candidats puis arbitrage. Tests : « Conges » -> `hr.leave` alias desactives ; deux objets de meme libelle.
- Contrat d'arbitrage `NONE` / `AMBIGU` / invalide / panne LLM : quatre tests distincts, quatre statuts distincts dans `diagnostics`.
- Un seul point d'entree, appele avec le meme LLM par routage, boucle et `tool_helpers` ; resultat conserve dans l'etat de session.
- Retirer ou requalifier le « dense decide seul » (constat 1).
- Cache : cle = question normalisee + empreinte du graphe/instance + langue + version de configuration du resolveur ; invalide si
  modele LLM, prompt ou contrat de sortie changent.
- Panne BGE-M3 ou LLM : visible dans `diagnostics`, resolution degradee signalee ou clarification, jamais de choix par defaut.

#### PR3 -- Cibles hors modeles en production (menus, champs, boutons, groupes)
- Les mesures E1 couvrent deja ces types (constat 11). PR3 n'est lance que si D2 passe et consiste a faire rendre ces cibles par
  `ResolvedConcept`, meme principe, memes garde-fous.

#### PR4 -- Un seul passage held_out
- Configuration figee, protocole gele rejoue tel quel, sans toucher cas ni seuils. Aucun reglage apres ce passage.

#### Note (13/10/2026, section 1281) -- index dense de production
- E1 reste sur une matrice numpy en memoire (cosinus exact). Chroma ou matrice pour un index dense de production sur les cartes du
  graphe : a trancher apres PR1, selon les besoins de persistance, de mise a jour incrementale et de filtre par type de noeud.

### 4. Risques et garde-fous
- Fuite du `held_out` : tout reglage se fait sur le calibrage ; un echec held_out n'autorise aucun reglage sur ce meme jeu.
- Cout : arbitrage seulement sans libelle exact unique ; taux de recours et latence mesures en PR0 (M3).
- Biais « modele qui connait Odoo » : famille de surcharge/renommage sur `adversarial_custom`.
- Echeance du 20/10 : seules PR0 et PR1 sont realistes avant ; PR2 seulement si PR1 est favorable. Sinon la livraison documente que
  la resolution des termes ambigus passe par clarification.
- Ce brouillon n'est pas dans `perimetre_livraison_20_octobre.md` ; il vit ici tant que pmm ne l'a pas figé.

### 5. A executer par pmm (long ou dependant du tunnel)
Runs E1 (`python -m code_intelligence.evaluation.e1.run --systems ...`), suite pytest complete, reconstruction du graphe,
passage held_out. 

---

# D. Audit du resolveur du 15/10/2026 (branche `audit/business-model-resolver`) : constats et statut

Audit statique (aucun appel Odoo / BGE / LLM), puis trois lots de correction ; les 5 commits (`2612cbe`, `5c5bdad`, `62b4831`, `473a9ca`, `fde0bc3`) sont dans HEAD (fusion de la branche : section 1406). Validation de l'epoque : 22 + 26 tests isoles (fixtures, sans services reels) ; la suite complete a ete rejouee depuis (voir A.7).

| # | Constat de l'audit | Correction | Reste |
|---|---|---|---|
| 1 | Le modele d'embeddings serveur choisi par `RESOLVER_SEMANTIC_EMBEDDING_MODEL` n'etait pas respecte pour les backends serveur (le RAG documentaire lit `LOCAL_EMBEDDING_MODEL`) | Override respecte ; defaut Chroma serveur conserve ; `RESOLVER_SEMANTIC_EMBEDDING_REVISION` pour invalider les vecteurs sous un meme tag | Le nouveau namespace de cache provoque une re-embedding initiale |
| 2 | Routeur (`llm=None`), boucle et outils decidaient chacun leur resolution | `resolve_turn` : decision partagee par tour (question, langue, historique, configuration, snapshot du graphe) ; abstention reutilisee, plan regenere si le graphe change | Chemin des arguments de `tool_helpers` encore distinct |
| 3 | Une abstention pouvait etre remplacee par l'ancien sujet (« sticky ») | Remplacements sticky retires (1409, 1410, 1412) | -- |
| 4 | Candidats alternatifs et vraies cibles multiples confondus (le lexical promouvait tous ses resultats) | Contrat de choix ferme JSON mono / multi-cibles et abstention ; une candidature stricte sans concurrent peut etre deterministe | Qualite des selections multiples non mesuree |
| 5 | Cache semantique mal identifie et non invalide (nom du client sans endpoint ni revision, pas de digest du corpus, vecteurs non finis acceptes) | Identite de configuration du cache, digest du corpus, validation des vecteurs (jamais de secret dans une cle) | Verrouillage interprocessus du cache disque |
| 6 | Retrieval repete, shortlist non uniforme | Pool de candidats unique dans le chemin actif | Helpers exportes de `candidates.py` hors chemin actif non supprimes |
| 7 | Appels d'arbitrage sous-comptes (compteur limite a `llm_arbitration`) | Trace des tentatives d'arbitrage ; compteurs reportes | Budget strict d'appels LLM non implemente |

Planification semantique des analyses (lot du 15/10, 19:11) : le LLM choisit parmi des appels generes cote serveur depuis les entites du graphe (`capability_catalogue.py`, `capability_planner.py`), ce qui supprime la dependance aux mots-cles et aux conventions de modeles / methodes standards pour les modules personnalises ; chaque tour est revalide sur le graphe courant, execute par le meme executeur, les echecs consomment `CI_MAX_HOPS`, la selection libre ReAct est desactivee sur ce parcours. Limites : voir A (points techniques ouverts).

---

# E. Lots de branches deja fusionnes (memoire, un lot par ligne)

- **`fix/ci-api-errors`, frontiere d'erreurs API (14/10)** : `api/public_errors.py` (classificateur commun, messages publics fixes, 503 pour les pannes de connexion / timeout / HTTP 429-5xx XML-RPC, 500 sinon), `routes_ask.py` et `routes_system.py` utilisent la frontiere ; `/api/v1/health` detaille reserve aux administrateurs, `/health` leger public, endpoint LLM retire de la reponse ; 14 tests unitaires + 5 structurels.
- **`fix/ci-source-evidence-boundary` (14/10)** : rendu des sources en preuve uniquement (blocs numerotes contigus observes), jamais de code reconstruit depuis le disque, bornes invalides rejetees avant tout acces fichier ; commits `76ff66d`, `fe87cb6` ; 19 regressions.
- **Suite de la frontiere de sources (14/10)** : plages de provenance validees (lignes positives croissantes ; commit `8ffd672`), scanner de blocs de code ferme / ouvert / indente / CRLF pour fermer les contournements (27 tests au total) ; la verification de citations de `dispatch_guards.py` est restee inchangee.
- **Resolution des references de modeles indexee (14/10)** : index deterministe du corpus de references de modeles (`code_intelligence/model_references.py`) ; commit `5abd815`, partie de la tranche B (section 1338) ; `resolve_model_xmlref` retire (code mort, 1359).
- **Construction du graphe (section 1338, 14/10)** : garde-fous de construction et rapport d'integrite (`graph/integrity_report.py`, `scripts/check_graph_integrity.py`) ; anomalies `unresolved_endpoint` / `untyped_node` traitees en 1384-1387 ; langues du graphe pilotees par `GRAPH_TRANSLATION_LANGUAGES` (1388).
- **`feat/document-rag-google-drive` (14/10)** : connecteur Drive API v3 en lecture seule (ADC), inventaire recursif, formats PDF / TXT / MD / DOCX, sources stables, chunks deterministes ; corpus partage approuve par pmm (`GOOGLE_DRIVE_APPROVED_FOR_RAG=true` obligatoire), garde de disponibilite avant reranking, coordinateur de reconciliation avec purge seulement apres inventaire complet (404 racine = purge du corpus Drive de la collection, jamais des documents locaux), `--watch` avec `GOOGLE_DRIVE_SYNC_INTERVAL_SECONDS` ; commits `ff074d3`, `a08df4e`, `288fffb`, `72772fa`.
- **Resolveur du 15/10** : audit, corrections et planification semantique : voir D.
