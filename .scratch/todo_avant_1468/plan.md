# Plan d'execution

Objectif : atteindre `architecture.md` 

Question à se poser à chaque bifurcation : l'IA pourra-t-elle repondre correctement sur n'importe
quelle instance Odoo 17 ?

## Simplification de l'orchestration

Réduire progressivement les heuristiques sémantiques dispersées (routage, intention, résolution et choix
d'outils) au profit d'un plan structuré proposé par le LLM, validé avant exécution. Conserver déterministes
l'identité, les autorisations, le périmètre, la validation des appels, les budgets et la provenance/vérification
des preuves. En cas d'ambiguïté, demander une précision plutôt que deviner. Toute consolidation est guidée par
les échecs mesurés du protocole et ne fusionne pas CI, RAG documentaire et accès ORM en un sous-système opaque.

La direction inverse est à l'étude : récupération hybride dans le graphe (BGE-M3, lexique, BM25) puis expansion
déterministe par arêtes typées, le LLM ne faisant que rédiger à partir d'un prompt augmenté. Elle est évaluée par
les expériences E1 (P4) puis E2 (P6), pré-enregistrées en section 1227 du journal. Aucun changement
d'orchestration, de planificateur ni de boucle ReAct avant leurs résultats.

## Ordre et dependances

P0 -> P1 -> P2 -> T -> P3 -> P4 -> P5 -> P6 -> P7 -> P8 -> P9 -> P10

Apres T, P3 a P7 ne sont lancées que si la mesure de T montre des échecs précis qu'elles corrigeraient, phase par phase. P4 et P5 sont independantes entre elles après P3. P8 etend le verificateur de T ; si P7 est retenue, il s'appuie sur le registre. P9 suppose le contrat d'identite de P3. P10 n'utilise aucun artefact
de calibrage.

## P0 -- Socle reproductible

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

## P1 -- Protocole de mesure gelé


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

## P2 -- Branche documentaire : restitution exhaustive

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


## T -- Tranche verticale minimale

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

## P3 -- Empreinte d'instance et contrat d'identite

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

## P4 -- Lexique unique et resolution metier

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

## P5 -- Routage explicite des sources

- Intention de source : comportement, données, documentation interne,combinaison declarée.
- Ordre de décision : mode explicite de l'utilisateur, formulation explicite, règles déterministes, contexte
d'écran, LLM comme signal avec confiance ; clarification si la confiance est faible.
- Le routage précede tout retrieval ; la recherche documentaire n'est lancée que si la source l'exige.
- Sources utilisées affichées avec la reponse.

Sortie : `RoutingResult` produit avant retrieval, sans choix silencieux.

## P6 -- Investigation pilotée par le plan et budget

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

## P7 -- Registre de faits et habilitation

- Chaine Observation, Evidence, Fact, Claim ; chaque outil emet des observations structurées ; les faits sont
  derivés de facon deterministe, etiquetés statique ou runtime, avec portée et niveau de preuve.
- Un fait statique n'est emis que si le graphe le prouve et que la question ne depend pas de l'etat runtime.
- Filtrage d'habilitation avant le LLM : mecanismes de contournement, champs et enregistrements hors
  perimetre retires, avec motif consigne.
- Trace complete reconstructible, rattachée à l'empreinte.

Sortie : `evidence_completeness` mesuré ; toute observation passe par le filtre.

## P8 -- Redaction et verification

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

## P9 -- Donnees, runtime et audit d'instance

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

## P10 -- Preuve de généralisation

- Plusieurs snapshots independants (versions, langues, modules custom, configurations differents), dont des graphes OCA distincts, jamais utilisés pour calibrer.
- Rapport : métriques de P1, intervalle de confiance regroupé par instance, ventilation par instance, module,
  langue et famille, cas d'abstention. La conclusion porte sur les N instances echantillonnees.

Sortie : `accuracy_all_questions >= 80 %` hors calibrage, borne basse à 95 % atteignant 80 %.
