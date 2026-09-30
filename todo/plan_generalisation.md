# Plan de generalisation -- l'IA comprend le code et l'explique en termes metier, sur toute instance Odoo 17

Statut : PLAN uniquement, aucun code touche. Issu de l'audit des sections 1031 a 1035 de
`contexte.txt` et de la discussion du 30/09/2026 avec pmm. Chaque phase reste a mandater
explicitement avant toute implementation.

Objectif (`architecture.md`) : expliquer le comportement reel d'une instance Odoo 17 (natif, OCA,
custom) a n'importe quel utilisateur, avec preuves, sans dependre de la documentation.

Formulation mesurable : au moins 80 % de reponses correctes sur des instances et des questions
tenues hors calibrage, avec hypotheses d'acces explicites et politique d'abstention. Une garantie
"au pire, sur n'importe quelle instance" n'est pas defendable si l'instance ne fournit ni code,
ni metadonnees runtime, ni acces aux donnees.

## 1. Etat de depart (hypotheses a mesurer en phase 1)

Les chiffres de progression globaux sont volontairement absents : les grandeurs disponibles ne
sont pas comparables. L'extraction reussie de 537 modules OCA sans echec mesure un succes de
parsing sur ce corpus, pas une couverture semantique de 80 %. Les points suivants sont donc des
hypotheses a remplacer par des mesures definies au niveau de chaque phase :

- l'extraction statique peut manquer des comportements dynamiques, des donnees XML chargees en
  base et des integrations externes ;
- la resolution du terme metier depend encore de la table statique ; la seule mesure comparable
  sans cette table est 16/25 sur le banc natif ;
- la qualite des preuves, du rendu metier et de l'acces aux donnees/runtime n'a pas encore de
  baseline independante ;
- la generalisation inter-instance n'est pas mesuree. Le banc OCA actuel (3/50 sans table) n'est
  pas comparable, puisque ses modules ne sont pas dans le graphe utilise.

Les scores 25/25, 50/50 et 20/20 sur les bancs connus sont des mesures de calibration et ne sont
pas des preuves de generalisation.

## 2. Metriques de reference

`accuracy_all_questions`, `accuracy_answered_questions`, `coverage`, `unsupported_claim_rate`,
`wrong_tool_rate`, `technical_identifier_leak_rate` (identifiants techniques dans le texte destine
a l'utilisateur), et `human_business_acceptance_rate`. Une abstention compte comme une erreur dans
`accuracy_all_questions` et n'est jamais masquee dans le score.

Un cas d'evaluation fige : hash de l'instance, version et modules, utilisateur/societe/langue,
question, intention/objets/predicats attendus, preuves acceptables, affirmations attendues, regle
d'abstention. Separation par instance, module et langue, jamais par split aleatoire de questions.

**Critere statistique pre-enregistre avant calibrage** : `accuracy_all_questions >= 80 %`, avec une
couverture minimale fixee avant le run (proposition initiale : 90 %), et une borne basse d'intervalle
de confiance a 95 % atteignant 80 %. La borne ne doit pas etre calculee uniquement sur toutes les
questions poolees : les questions d'une meme instance sont correlees ; le rapport doit fournir une
incertitude robuste au regroupement par instance (bootstrap par instance ou methode cluster-robuste)
et ventiler le resultat par instance, module, langue et famille de question. A titre d'ordre de
grandeur seulement, 100 questions independantes demanderaient environ 88 % observe pour une borne
basse de Wilson a 95 % a 80 % ; le seuil reel sera plus exigeant avec le regroupement par instance.

## 3. Phases

### Phase 0 -- assainir l'existant

- Relever dynamiquement `git status --short` au debut de la phase (le nombre de fichiers modifies
  et non suivis est une observation volatile, pas une valeur du plan) ; relire les diffs et les
  tests non suivis des sections 1027 a 1029 ; commiter code et journal separement.
- Reconcilier `plan.md` et `contexte.txt` : le banc natif y est marque a construire alors que le
  journal montre un banc de 25 questions rejoue.
- Corriger dans `architecture.md` la reference a une section "Preconditions H3" absente de
  `plan.md`.
- Retirer les commentaires qui nomment des modules du banc et le residu `diag_ngrok.py`.

Sortie : arbre propre, plan et journal coherents.

### Phase 1 -- figer le protocole de mesure (G0, test uniquement)

- Conserver le script d'ablation et les 25 cas ; ajouter des contre-exemples d'ambiguite
  ("commande" ne doit pas aller par defaut vers achat ou vente).
- Implementer les metriques du paragraphe 2, dont `technical_identifier_leak_rate`.
- Figer ce protocole avant tout calibrage.

Sortie : protocole gele, mesure de depart re-etablie.

### Phase 5a -- empreinte de l'instance (prerequis a G1)

- Interroger `ir.module.module` pour inventorier tous les modules installes, leurs versions et
  leur etat ; relever les chemins d'addons effectivement accessibles.
- Relever les langues actives et la langue de la requete, ainsi qu'un hash de l'empreinte
  (modules/versions/chemins/langues) et les disponibilites du code source. Cette empreinte est
  attachee a chaque graphe, lexique, trace et resultat d'evaluation.
- Ne pas confondre cette empreinte avec l'introspection complete de la base : les vues/actions
  stockees en base et le registre runtime sont le perimetre de 5b.

Sortie : empreinte versionnee de l'instance, prete a limiter G1 aux modules et langues pertinents.

### Phase 2 -- lexique derive de l'instance (G1)

- Extraire les traductions `.po` et runtime ; lier chaque entree a son objet exact (modele, champ,
  menu, selection) avec sa source (`po`, runtime ou surcharge) et son module.
- Injecter ce lexique dans l'index fuzzy ; `BUSINESS_ALIASES` devient une couche de surcharges
  optionnelles, visibles et mesurables.
- Modules custom sans traduction : repli LLM borne deja existant, avec abstention si le signal
  manque.

Sortie : ablation table videe >= 24/25 sur le banc natif comme plancher de non-regression, sans
dependance a un nom de module ni a une question du banc ; verification precision/rappel des
termes anglais et francais, des ambiguites et des abstentions ; rapport de couverture derivee
contre surcharges. Ce seuil est un plancher de non-regression, pas le critere de generalisation
a 80 %.

### Phase 3 -- rendu metier sortant

- Construire, pour chaque objet de preuve, son libelle cote utilisateur dans la langue de
  l'utilisateur : libelle du champ, de la selection, chemin de menu, texte du bouton, nom du
  groupe. Meme source que la phase 2 : un seul lexique pour les deux sens.
- Le redacteur recoit des faits deja exprimes avec ces libelles.
- Controle deterministe : aucun identifiant technique dans la partie "niveau utilisateur" ; la
  partie depliable "niveau verification" les conserve.
- Organiser une relecture aveugle par des non-techniciens avec une grille pre-enregistree :
  exactitude du sens metier, intelligibilite sans connaissance technique, fidelite aux preuves
  et absence de conseil/procedure invente. Une erreur metier critique invalide le cas ; publier
  `human_business_acceptance_rate` et les desaccords, et fixer le seuil avant la mesure.

Sortie : `technical_identifier_leak_rate` a 0 dans la zone destinee a l'utilisateur (la zone de
verification est exemptee), plus un taux d'acceptation humaine conforme au seuil pre-enregistre.

### Phase 4 -- remplacer le scaffolding par un mecanisme (decoupage obligatoire)

- G2, en changement isole et independant : retirer `_force_dynamic_uncertainty_answer` et sa
  reponse liee au scenario `custom_expense_reimbursement_indirect`.
- **4a -- registre de faits** : representer chaque fait avec sa provenance, sa portee, son
  contexte statique/runtime et son niveau de preuve ; distinguer un mecanisme derive du graphe
  d'un etat lu dans l'ORM.
- **4b -- verificateur en mode shadow** : construire le verificateur generique de preservation
  des faits (montants, groupes, conditions, messages d'exception) et le comparer aux 22 fonctions
  `_backfill_*` / `_force_*`, sans modifier encore la reponse en production.
- **4c -- comparaison et rejeux** : mesurer les faits perdus, ajoutes ou contredits par le LLM,
  les divergences entre verificateur et gardes, ainsi que les affirmations non supportees.
- **4d -- retrait par lots** : retirer les gardes seulement par lots, chaque lot valide par le
  rejeu du banc gele et par des cas hors calibrage.
- Un fait statique natif (par exemple `sale.group_auto_done_setting`) ne peut etre emis que si le
  graphe en apporte la preuve et si la question ne depend pas de l'etat runtime. Si l'etat depend
  de la configuration ou de l'ORM, le fait doit etre lu dynamiquement ou reste incertain.

Sortie : verificateur compare en shadow, puis moins de gardes sans regression sur le banc gele,
aucune affirmation native non sourcee, et aucune substitution d'un fait dynamique par un fait
statique.

### Phase 5b -- compilateur d'instance et audit runtime

- Introspection du registre en complement de l'AST : vues, actions et server actions stockees en
  base, y compris Studio.
- Composant `instance_audit` : rapport versionne (modules non indexes, extractions en echec,
  references non resolues, traductions manquantes, domaines sans outil de preuve, termes
  ambigus) ; sondes generees a partir de l'ontologie en mode table videe ; capacites classees
  `couverte` / `ambigue` / `preuve_manquante` / `non_supportee`, transformees en backlog.
- Remettre `scripts/coverage_report.py` en phase avec l'enveloppe actuelle de `active_graph.json`.

Sortie : graphe et rapport d'audit coherents avec l'empreinte 5a, lacunes transformees en backlog,
et distinction explicite entre couverture du corpus et capacites effectivement prouvables.

### Phase 6 -- donnees

**Contrat de securite et de perimetre, a approuver avant toute fusion** :

- executer les lectures sous `with_user()` du demandeur ; jamais de `sudo` implicite ni de SQL
  brut ;
- expliciter le perimetre de societes et appliquer les ACL, regles et champs accessibles dans ce
  contexte ;
- imposer un plafond de lignes, une execution en lecture seule et des budgets de temps/contexte ;
- journaliser chaque requete, son utilisateur/societe, son but, son volume et son resultat ;
- refuser ou declarer hors perimetre les donnees auxquelles le demandeur n'a pas acces.

- Seulement apres validation du contrat : decision produit sur la fusion Data Intelligence / Code
  Intelligence (aujourd'hui non entamee), puis integration avec contexte utilisateur, societe et
  langue.

Sortie : les questions "combien / qui / quand" sont couvertes ou declarees hors perimetre.

### Phase 7 -- preuve de generalisation (G3)

- Construire plusieurs snapshots independants (versions, langues, modules custom et
  configurations differents), dont un ou plusieurs graphes OCA distincts. Aucun snapshot de
  validation ne sert a calibrer regles, seuils, lexique ou alias.
- Separer les donnees par instance entiere, puis ventiler par module, langue, configuration et
  famille de question ; ne pas melanger les questions d'une meme instance entre calibrage et
  validation.
- Rechercher `accuracy_all_questions >= 80 %` (abstentions incluses comme erreurs), la couverture
  minimale pre-enregistree et une borne basse a 95 % atteignant 80 % avec incertitude regroupee par
  instance. La conclusion honnete porte sur `N` instances echantillonnees ; elle ne dit pas
  « toute instance ».

Sortie : rapport avec les metriques du paragraphe 2, l'intervalle de confiance, les resultats par
instance/module/langue/famille et les cas d'abstention ; cible >= 80 % hors calibrage sur les `N`
instances annoncees.

## 4. Ordre et dependances

Phase 0, puis 1, puis 5a, puis 2, puis 3. G2 est independant et reste isole ; les sous-phases 4a
a 4d ne commencent qu'avec le protocole gele et avancent apres 3. 5b precede 6, puis 7. Les
chantiers existants de `plan.md` (inference locale, memoire, vrai code MiroKE) ne changent pas.

## 5. Repartition

- pmm : verite-terrain, relecture de la traduction metier par des non-techniciens, chargement et
  caracterisation de plusieurs snapshots independants (long), execution des suites de tests
  completes.
- Claude : scripts, code, diffs, tests cibles, journalisation.

## 6. Regles transverses

Aucune valeur machine-dependante en dur (`.env` avec repli explicite) ; aucune reponse ni alias
lie a un module ou a une question du banc ; journal avant code ; `dryRun` avant chaque ecriture ;
`py_compile` puis sweep d'import apres chaque edition ; jamais `pytest tests/` complet.
Question a se poser a chaque bifurcation : l'IA pourra-t-elle repondre correctement sur
n'importe quelle instance Odoo 17 ?
