# Plan d'execution

Objectif : atteindre `architecture_cible.md` (critère : au moins 80 % de reponses correctes sur des
instances Odoo 17 et des questions tenues hors calibrage, abstentions comptees comme erreurs).
Chaque phase est mandatee explicitement avant implementation. Ce document change rarement.

Question à se poser à chaque bifurcation : l'IA pourra-t-elle repondre correctement sur n'importe
quelle instance Odoo 17 ?

## Ordre et dependances

P0 -> P1 -> P2 -> P3 -> P4 -> P5 -> P6 -> P7 -> P8 -> P9 -> P10

P4 et P5 sont independantes entre elles après P3. P7 précède P8 (la verification s'appuie sur le registre).
P9 suppose le contrat d'identite de P3. P10 n'utilise aucun artefact de calibrage.

## P0 -- Socle reproductible

- Arbre git propre : relire les diffs, separer commits de code et de journal.
- Suite de tests deterministe et isolee : aucun test ne depend d'un fichier local, d'un corpus present sur
  un poste ou d'un reseau ; tout ce qui depend de la machine passe par `.env` 
- Configuration unique : un seul fichier `.env` pour fournisseur LLM, hotes autorisés, fenêtre de contexte,
  budgets, chemins ; valeurs par defaut coherentes entre code, README et `.env.example`.
- Documentation coherente : plan, architecture, journal et README sans contradiction.

Sortie : suite verte reproductible sur une machine neuve, une seule source de configuration.

## P1 -- Protocole de mesure gele


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

## P3 -- Empreinte d'instance et contrat d'identite

- Empreinte : modules installés, versions, etats, chemins d'addons accessibles, langues actives, hash.
  Attachee à chaque graphe, lexique, trace, reponse et resultat d'evaluation.
- Identité : toute lecture ERP s'execute par l'ORM sous l'identite du demandeur ; clé du demandeur absente
  signifie lecture refusée ; utilisateur et societe viennent de la session authentifiée, jamais du LLM ;
  aucune élévation implicite, aucun SQL brut. Un mode technique explicite, par variable d'environnement,
  reservé aux scripts et tests, est journalisé.
- Isolation reseau : hotes autorises explicites, fournisseur LLM interchangeable par configuration seule.

Sortie : toute reponse et toute trace rattachées à une empreinte ; aucune lecture possible sans identité.

## P4 -- Lexique unique et resolution metier

- Lexique bidirectionnel (terme vers objet, objet vers libellé) derivé de l'instance : traductions statiques
  et runtime, lié a l'objet exact (modele, champ, menu, selection), à sa source, son module, sa langue.
  Les alias manuels deviennent une couche de surcharges optionnelle, visible et mesurable.
- Resolution : mention technique exacte, lexique, contexte d'ecran, flou puis semantique comme indices,
  puis proposer-verifier par le LLM (noms valides dans le graphe uniquement). Discriminant (champ et valeur)
  dans `ResolutionResult`. Panne du backend d'embeddings signalée, jamais masquée.
- Departage deterministe fondé sur la rareté des indices ; abstention explicite en cas d'ambiguité.

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

- Contrat de lecture : ORM sous l'identité du demandeur, perimètre de societés explicite, ACL et règles
  appliquées, lecture seule, plafond de lignes, budgets de temps et de contexte, journalisation de chaque
  requete, refus declaré hors perimetre. Outils typés, jamais de SQL produit par le LLM.
- Les questions combien, qui, quand passent par le meme pipeline et le meme registre.
- Introspection du registre runtime (vues, actions, server actions en base, Studio) en complement de l'AST.
- Audit d'instance versionné : modules non indexés, extractions en échec, references non resolues, traductions
  manquantes, domaines sans outil de preuve, termes ambigus ; capacités classees `couverte`, `ambigue`,
  `preuve_manquante`, `non_supportée`, alimentant un backlog.
- Sonde de justesse d'instance : questions generées automatiquement à partir du graphe de l'instance, dont la
  reponse attendue se deduit du graphe lui-meme (qui peut approuver une action, quelle regle s'applique, ou une
  regle est definie) ; resultat joint au rapport d'audit comme premier indicateur de justesse, sans remplacer
  l'evaluation avec relecteurs de P1 et P10. Aucune question de la sonde n'est utilisee pour calibrer.

Sortie : questions de données couvertes ou declarées hors perimetre ; rapport d'audit et résultat de la sonde de justesse cohérents avec l'empreinte, produits sur une instance neuve par une seule commande.

## P10 -- Preuve de généralisation

- Plusieurs snapshots independants (versions, langues, modules custom, configurations differents), dont des
  graphes OCA distincts, jamais utilisés pour calibrer.
- Rapport : métriques de P1, intervalle de confiance regroupé par instance, ventilation par instance, module,
  langue et famille, cas d'abstention. La conclusion porte sur les N instances echantillonnees.

Sortie : `accuracy_all_questions >= 80 %` hors calibrage, borne basse à 95 % atteignant 80 %.

