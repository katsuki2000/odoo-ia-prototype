# Architecture cible de MIRO AI

## 1. Objectif

Mettre en place une IA privée pour Expliquer le comportement réel d'un ERP Odoo 17 à n'importe quel utilisateur, en termes métier, avec preuves, sans FORCEMENT dépendre de la documentation

## 2. Principes

1. **Hiérarchie des sources de vérité** : instance en exécution, puis code source, puis configuration,
   puis documentation interne.
2. **Le LLM n'est jamais une source de vérité.** Comme le RAG, Les faits établis en consultant l'ERP ET Les documents sont injectés au prompt du LLM (ce qui va lui permettre d'utiliser ses propres connaissances mais ne repondre qu'en fonction de ce qu'il a trouvé dans l'ERP) ;
3. UN systeme de routage clair : Par exemple : l'utilisateur precise 'selon le sytème' pour des questions où le llm consulte le systeme et precise 'selon les procedures internes' ou 'd'après la documentation ' ou separer carrement l'interface , une detection automatique du llm serait top mais il se trompait souvent (à moins qu'il y ait une technique, ou un moyen de le faire efficacement)
4. **Toute lecture de données se fait sous l'identité du demandeur** : jamais d'élévation de privilèges
   implicite, jamais de SQL brut.
5. **le coté privé** : aucun prompt, secret ou extrait de code ne quitte l'infrastructure prévue (kaggle en test et dev, aws en prod)
6. **Abstention explicite plutôt que réponse non prouvée.** : precise qu'il a tiré l'information de ses connaissances générales et qu'il n'a pas de preuve


## 3. Pipeline

Le graphe de connaissances est l'index de l'instance. Une question traverse six étages, chacun avec un
contrat d'entrée et de sortie explicite :

```text
 Empreinte ──> Résolution ──> Investigation ──> Registre de faits ──> Rédaction ──> Vérification
                  │               │                    ▲                  │
                  └── Lexique unique (termes <-> libellés) ───────────────┘
                                  └── Budget d'observations ──┘
```

Le retrieval est itératif et guidé par l'investigation (modèle, puis méthode, overrides, sécurité). Ce
n'est pas un top-k unique suivi d'une génération.

## 4. Composants

### 4.1. Empreinte d'instance
Inventaire des modules installés, versions, états, chemins d'addons accessibles, langues actives, et hash
de l'ensemble. L'empreinte est attachée à chaque graphe, lexique, trace et résultat d'évaluation.

### 4.2. Graphe de connaissances
Construit à partir du code (AST Python, vues et données XML, droits d'accès CSV) et du registre runtime
(vues, actions et server actions stockées en base, Studio inclus). Typé (modèles, champs, méthodes,
groupes, règles, ACL, actions, automations, menus, états, boutons), porteur de tags sémantiques à
vocabulaire fermé (comportementaux et techniques). Reconstruit hors ligne puis permuté atomiquement ;
jamais modifié pendant une requête.

### 4.3. Lexique unique
Une seule table, dans les deux sens : terme utilisateur vers objet, objet vers libellé utilisateur.
Chaque entrée est liée à son objet exact (modèle, champ, menu, sélection), à sa source (traduction
statique, traduction runtime, surcharge) et à son module. Les surcharges manuelles sont une couche
optionnelle, visible et mesurable.

### 4.4. Résolution métier
1. Mention technique exacte.
2. Lexique dérivé de l'instance, dans la langue de la requête.
3. Contexte d'écran actif transmis par Odoo.
4. Recherche floue puis sémantique, utilisées comme indices.
5. **Proposer puis vérifier** : le LLM reçoit la question et un contexte compact de l'instance (modules,
   modèles par module), propose jusqu'à 3 noms techniques ; seuls les noms existant dans le graphe sont
   conservés ; aucun nom valide signifie non résolu.

Sortie : objet, confiance, origine (`lexicon`, `override`, `llm_proposal`) ou abstention explicite. Une
question ambiguë (« commande ») n'est jamais résolue par défaut vers un domaine.

### 4.5. Investigation
Un plan d'investigation explicite, à vocabulaire d'actions fermé, est produit avant tout appel d'outil.
Les collecteurs déterministes l'exécutent (verrous de sécurité, chaîne d'overrides, accès et règles
d'enregistrement, actions serveur, workflow, héritage, navigation, chemin d'exécution des boutons,
contraintes de données) ; des outils d'approfondissement complètent si nécessaire. Chaque outil produit
des faits, pas seulement du texte. Invariant : outils planifiés ⊆ outils exécutés, pour toutes les
catégories d'intention. La profondeur d'investigation s'adapte à la longueur de la chaîne, sans règle
propre à une question.

### 4.6. Budget d'observations
Un seul objet `ObservationBudget` fixe les limites de taille (par outil, total, mode de dégradation) et
est lu par tous les sites ; aucune limite en dur ailleurs. Il dérive de la fenêtre de contexte
configurée. Quand une observation dépasse son budget, elle est dégradée par priorité (minimum protégé par
bloc, puis répartition proportionnelle), jamais coupée en tête. Toute perte produit un signal structuré
(outil, objet, quantité omise) transmis au registre de faits et à l'évaluation de suffisance : une
réponse bâtie sur une observation incomplète ne peut pas être déclarée suffisante sans le dire.

### 4.7. Registre de faits
Chaque fait porte : identifiant stable, affirmation, valeur, source (fichier et ligne, ou identifiant
d'enregistrement), portée (société, utilisateur, instant de lecture), contexte **statique ou runtime**,
niveau de preuve et indicateur de complétude. Un mécanisme dérivé du code n'est jamais présenté comme un
état lu en base. Un fait statique n'est émis que si le graphe en apporte la preuve et que la question ne
dépend pas de la configuration runtime. Le registre sait exprimer un conflit entre deux sources.

### 4.8. Filtrage d'habilitation
Toute observation traverse un filtre avant d'atteindre le LLM : les mécanismes de contournement sensibles
sont retirés si le demandeur n'a pas de droits élevés sur l'objet, et chaque élément retenu est consigné
avec son motif.

### 4.9. Rédaction
Le LLM reçoit des faits déjà exprimés avec les libellés de l'utilisateur, dans sa langue, et produit une
réponse en deux niveaux :
- **niveau utilisateur** : explication métier, sans identifiant technique ;
- **niveau vérification** (dépliable) : module, fichier, ligne, identifiant XML, domaine, preuves.
S'ajoute un niveau gouvernance : éléments retenus pour habilitation insuffisante, avec motif.

### 4.10. Vérification
Un vérificateur générique contrôle que la réponse préserve les faits du registre (montants, groupes,
conditions, messages d'exception, contraintes) et ne contredit aucun d'eux. Il remplace les corrections
spécifiques à un cas. Il produit un `VerificationReport` : faits préservés, perdus, ajoutés, contredits.
Une affirmation sans fait support est retirée ou signalée.

### 4.11. Données et runtime
Les questions « combien / qui / quand » passent par le même pipeline, avec les mêmes faits et le même
registre. Contrat de lecture : exécution sous l'identité du demandeur, périmètre de sociétés explicite,
ACL, règles et champs accessibles appliqués, lecture seule, plafond de lignes, budgets de temps et de
contexte, journalisation de chaque requête (utilisateur, société, but, volume, résultat), refus déclaré
hors périmètre pour ce que le demandeur ne peut pas voir.

### 4.12. Audit d'instance
Un rapport versionné, rattaché à l'empreinte : modules non indexés, extractions en échec, références non
résolues, traductions manquantes, domaines sans outil de preuve, termes ambigus. Chaque capacité est
classée `couverte`, `ambiguë`, `preuve_manquante` ou `non_supportée`, et alimente un backlog.

### 4.13. Branche documentaire
Limitée aux procédures et politiques non codées dans l'ERP. Recherche hybride (vectorielle et lexicale),
citations obligatoires et vérifiées contre les passages réellement récupérés. Elle ne fait jamais autorité
sur le comportement de l'installation.

## 5. Interfaces

- `Fact` : seul format de sortie des outils vers la rédaction.
- `ObservationBudget` : seule source des limites de taille.
- `LexiconEntry` : seule source des libellés, dans les deux sens.
- `ResolutionResult` : objet, confiance, origine, abstention.
- `InvestigationPlan` : actions fermées, vérifiable contre l'exécution.
- `VerificationReport` : faits préservés, perdus, ajoutés, contredits.
- `AssistantResponse` : réponse utilisateur, sources, preuves, éléments retenus, statut de suffisance
  (suffisant, insuffisant, conflictuel).

## 6. Évaluation

Un protocole gelé avant tout calibrage : cas figés (hash d'instance, utilisateur, société, langue,
question, intention et objets attendus, preuves acceptables, règle d'abstention), séparation par
instance, module et langue, jamais par tirage aléatoire de questions. Métriques : `accuracy_all_questions`,
`accuracy_answered_questions`, `coverage`, `unsupported_claim_rate`, `wrong_tool_rate`,
`technical_identifier_leak_rate`, `human_business_acceptance_rate`. Métriques par étage pour localiser
l'erreur : `resolution_recall_at_k`, `evidence_completeness`, `answer_faithfulness`. Aucun snapshot de
validation ne sert au calibrage.


Oui. Ton document est déjà très solide, mais je corrigerais surtout **la hiérarchie des sources**, **le rôle de la connaissance générale du LLM**, **le routage**, et la distinction entre **retrieval documentaire** et **retrieval de l’instance**.

Voici une version consolidée que je prendrais comme architecture cible.

# Architecture cible de MIRO AI

## 1. Objectif

Mettre en place une IA privée capable d’expliquer le **comportement réel d'une instance Odoo 17**, y compris ses modules custom, à des utilisateurs métier, en langage naturel, avec des preuves précises et vérifiables.

MIRO doit pouvoir répondre à des questions portant sur :

- le fonctionnement métier de l'instance ;
- les règles de sécurité et d'accès ;
- les workflows et états ;
- les contraintes et validations ;
- les personnalisations Python/XML ;
- les données accessibles à l'utilisateur ;
- les procédures internes et la documentation associée.

La documentation générale d'Odoo est **optionnelle** : elle peut aider MIRO à comprendre les concepts Odoo et à orienter son investigation, mais elle ne constitue pas une preuve du comportement de l'instance.

L'objectif fondamental est :

> **Comprendre ce que fait réellement cette instance Odoo, expliquer pourquoi elle le fait, et montrer précisément d'où provient chaque information utilisée pour répondre.**

---

# 2. Principes

### 2.1. Séparation entre connaissance générale et connaissance de l'instance

MIRO distingue trois types de connaissances :

1. **Connaissance générale**
   - connaissance intrinsèque du LLM ;
   - documentation générale Odoo 17 ;
   - connaissances générales sur les concepts ERP.

2. **Connaissance de l'instance**
   - graphe extrait du code ;
   - registre runtime ;
   - configuration ;
   - données accessibles ;
   - modules custom ;
   - traductions et libellés de l'instance.

3. **Preuves**
   - fichiers et lignes de code ;
   - XML/CSV et identifiants ;
   - enregistrements runtime ;
   - résultats d'outils ;
   - données effectivement lues.

La connaissance générale peut servir à **comprendre la question, générer des hypothèses et orienter le retrieval**.

Elle ne peut pas, à elle seule, établir un fait concernant l'instance.

> **Le LLM peut proposer ; l'instance doit démontrer.**

---

### 2.2. Hiérarchie des sources de vérité

Pour une affirmation portant sur le comportement réel de l'instance, l'ordre de priorité est :

1. **état runtime effectivement observable**, sous l'identité du demandeur ;
2. **code source réellement installé** ;
3. **configuration et métadonnées de l'instance** ;
4. **documentation/procédures internes**, lorsqu'elles décrivent une règle non directement codée ou lorsqu'elles constituent la source contractuelle pertinente ;
5. **documentation générale Odoo 17**, pour le fonctionnement générique ;
6. **connaissance générale du LLM**, uniquement comme connaissance de contexte et jamais comme preuve de l'instance.

Cette hiérarchie ne signifie pas qu'une source supérieure rend les autres inutiles. Elle détermine **quelle source peut établir quel type de fait**.

---

### 2.3. Le LLM n'est jamais une source de vérité

Le LLM peut :

- comprendre une formulation métier ;
- identifier des concepts Odoo ;
- proposer des modèles ou objets candidats ;
- proposer des pistes d'investigation ;
- synthétiser les faits récupérés ;
- reformuler les résultats en langage métier.

Le LLM ne peut pas établir seul :

> « Dans cette instance, cette règle existe. »

Une affirmation concernant l'instance doit être reliée à un ou plusieurs `Fact` provenant du système de retrieval/investigation.

Le prompt augmenté doit donc distinguer explicitement :

```text
CONNAISSANCE GÉNÉRALE
→ aide à comprendre et orienter.

FAITS DE L'INSTANCE
→ seules sources autorisées pour décrire le comportement réel.

PREUVES
→ permettent de vérifier l'origine exacte des faits.
```

Le LLM conserve ainsi ses connaissances générales, mais celles-ci ne doivent pas être silencieusement transformées en faits concernant l'instance.

---

### 2.4. Routage explicite des sources

MIRO ne doit pas laisser le LLM décider seul, de manière implicite, de la source à utiliser.

Chaque question reçoit une **intention de source** explicite :

- `INSTANCE_BEHAVIOR` : comportement réel de l'instance ;
- `INSTANCE_DATA` : données de l'instance ;
- `INTERNAL_DOCUMENTATION` : procédures/politiques internes ;
- `ODOO_GENERAL` : fonctionnement général d'Odoo ;
- `MIXED` : combinaison contrôlée de plusieurs sources.

Le routage peut être :

1. **explicite**, via l'interface ou la formulation de l'utilisateur ;
2. **déterministe**, lorsque certains types de questions imposent une source ;
3. **assisté par LLM**, uniquement pour proposer une intention ;
4. **validé par des règles de routage**, avant l'accès aux sources.

Le LLM ne doit donc pas être libre de choisir silencieusement entre :

> « ce que fait votre système »

et

> « ce qu'Odoo fait généralement ».

Lorsque l'intention reste ambiguë, MIRO demande une clarification ou applique une politique prédéfinie plutôt que de deviner.

Une interface à modes explicites peut être proposée :

```text
[ Instance ] [ Données ] [ Procédures ] [ Odoo général ]
```

Le mode `Instance` constitue le mode par défaut pour les questions métier portant sur le fonctionnement réel de l'ERP.

---

### 2.5. Retrieval itératif plutôt que top-k unique

MIRO n'est pas un RAG classique de type :

```text
question
→ embedding
→ top-k documents
→ LLM
```

Le retrieval est **agentique, itératif et multi-source** :

```text
question
   ↓
résolution
   ↓
modèle / objet
   ↓
méthode
   ↓
héritage / overrides
   ↓
sécurité
   ↓
configuration
   ↓
runtime si nécessaire
   ↓
preuves
   ↓
réponse
```

Le graphe constitue l'**index de connaissance de l'instance**.

Le retrieval peut combiner :

- recherche lexicale ;
- recherche floue ;
- recherche sémantique ;
- navigation du graphe ;
- retrieval de code ;
- outils d'analyse ;
- interrogation runtime autorisée.

Le concept RAG est donc utilisé comme **principe d'augmentation du contexte**, pas comme contrainte imposant des embeddings et un top-k de documents.

---

### 2.6. Abstention explicite

MIRO doit préférer :

> « Je ne peux pas établir ce comportement avec les preuves disponibles »

à une réponse plausible mais non démontrée.

Une réponse peut également indiquer :

> « Cette information correspond à une connaissance générale d'Odoo, mais je n'ai trouvé aucune preuve qu'elle s'applique à cette instance. »

Une affirmation provenant uniquement de la connaissance générale du LLM ne peut pas être présentée comme un fait de l'instance.

---

### 2.7. Sécurité et identité

Toute lecture de données métier s'effectue :

- sous l'identité du demandeur ;
- avec son contexte de sociétés ;
- avec ses ACL ;
- avec ses record rules ;
- avec les champs auxquels il a accès.

Il n'existe aucune élévation implicite de privilèges.

Les outils d'investigation du **code source** peuvent disposer de privilèges techniques nécessaires à l'analyse de l'artefact logiciel, mais ne doivent pas permettre de contourner les droits métier du demandeur lors de la lecture des données runtime.

Les lectures de données métier sont en lecture seule par défaut.

Aucun SQL brut exécuté directement par le LLM.

---

### 2.8. Confidentialité

MIRO est conçu pour fonctionner dans une infrastructure contrôlée.

Aucun :

- prompt ;
- secret ;
- extrait de code ;
- donnée métier ;
- résultat runtime ;

ne doit quitter l'infrastructure autorisée.

En développement/test, l'environnement peut être Kaggle lorsque les données utilisées respectent ce périmètre.

En production, l'exécution est prévue sur AWS ou une infrastructure privée équivalente.

Les fournisseurs de modèles externes ne doivent recevoir que les données explicitement autorisées par la politique de déploiement.

---

# 3. Pipeline général

```text
                         QUESTION
                            │
                            ▼
                    Empreinte d'instance
                            │
                            ▼
                       Routage
                            │
                            ▼
                       Résolution
                            │
                            ▼
                      Investigation
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
           Graph          Code           Runtime
          retrieval      analysis        queries
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                     Registre de faits
                            │
                            ▼
                    Filtrage habilitation
                            │
                            ▼
                     Prompt augmenté
                            │
                            ▼
                         Rédaction
                            │
                            ▼
                       Vérification
                            │
                            ▼
               Réponse + preuves + statut
```

Le pipeline est **agentique** : l'investigation peut produire de nouveaux éléments nécessaires à l'étape suivante.

Il est également **GraphRAG-like** : le graphe constitue l'index structuré de l'instance.

Il est **evidence-grounded** : les affirmations finales doivent être rattachées à des faits vérifiables.

---

# 4. Composants

## 4.1. Empreinte d'instance

Inventaire :

- modules installés ;
- versions ;
- états ;
- chemins d'addons accessibles ;
- langues actives ;
- objets runtime disponibles ;
- hash de l'ensemble.

L'empreinte est attachée à :

- chaque graphe ;
- chaque lexique ;
- chaque trace d'investigation ;
- chaque résultat d'évaluation ;
- chaque jeu de preuves.

Une réponse doit pouvoir être rattachée à **la version exacte de l'instance analysée**.

---

## 4.2. Graphe de connaissances de l'instance

Le graphe est construit à partir de :

- AST Python ;
- XML ;
- CSV de sécurité ;
- métadonnées Odoo ;
- registre runtime ;
- vues ;
- actions ;
- server actions ;
- automatisations ;
- Studio lorsque accessible ;
- traductions et libellés.

Il représente notamment :

- modèles ;
- champs ;
- méthodes ;
- héritages ;
- overrides ;
- modules ;
- groupes ;
- ACL ;
- record rules ;
- actions ;
- automatisations ;
- menus ;
- vues ;
- boutons ;
- états ;
- contraintes ;
- relations.

Le graphe est l'**index structurel de l'instance**.

Il est reconstruit hors ligne puis permuté atomiquement.

Il n'est jamais modifié pendant une requête.

---

## 4.3. Lexique unique

Une table bidirectionnelle :

```text
terme utilisateur ↔ objet technique
```

Chaque entrée est liée :

- à l'objet exact ;
- au modèle ;
- au champ ;
- au menu ;
- à la sélection ;
- au module ;
- à la source du libellé ;
- à la langue ;
- à la surcharge éventuelle.

Sources possibles :

- traductions statiques ;
- traductions runtime ;
- libellés de champs ;
- vues ;
- menus ;
- surcharges manuelles.

Les surcharges manuelles sont optionnelles, visibles et mesurables.

---

## 4.4. Résolution métier

Ordre de résolution :

1. mention technique exacte ;
2. lexique de l'instance ;
3. contexte d'écran transmis par Odoo ;
4. recherche lexicale/fuzzy ;
5. retrieval sémantique ;
6. proposition LLM ;
7. vérification contre le graphe.

Le LLM peut recevoir :

```text
question
+
contexte compact de l'instance
+
modules installés
+
modèles disponibles
+
libellés pertinents
```

Il peut proposer jusqu'à trois candidats.

**Aucun candidat proposé par le LLM n'est accepté sans vérification dans l'instance.**

Ainsi :

```text
LLM → proposition
Graphe → existence
Investigation → pertinence
Preuves → validation
```

Un modèle custom inconnu du LLM peut donc être découvert par l'instance.

Une résolution ambiguë ne doit pas être forcée.

---

## 4.5. Investigation agentique

L'agent produit un `InvestigationPlan` à vocabulaire d'actions fermé.

Exemples :

- sécurité ;
- ACL ;
- record rules ;
- contraintes ;
- chaîne d'overrides ;
- héritage ;
- workflow ;
- actions serveur ;
- automatisations ;
- navigation ;
- chemin d'exécution d'un bouton ;
- configuration ;
- données runtime.

Les outils exécutent le plan et produisent des `Fact`.

Invariant :

```text
outils exécutés ⊆ outils autorisés par le plan
```

Toute modification du plan doit être explicite et traçable.

La profondeur d'investigation s'adapte à la complexité observée et non à une question particulière codée en dur.

---

## 4.6. Retrieval sémantique

Le retrieval sémantique est un **retriever complémentaire**, pas le cœur unique du système.

Il peut effectuer :

```text
question
→ embedding
→ similarité avec les objets/libellés de l'instance
→ candidats
```

Il sert principalement à résoudre les formulations métier qui ne correspondent pas littéralement aux noms techniques.

Il est optionnel et son état doit être visible dans les rapports d'évaluation.

Un échec du backend d'embeddings ne doit jamais être masqué silencieusement par le système.

---

## 4.7. Budget d'observations

Un unique `ObservationBudget` définit :

- taille maximale par outil ;
- taille totale ;
- stratégie de dégradation ;
- minimum protégé par bloc ;
- budget dérivé de la fenêtre de contexte.

Aucune autre limite codée en dur ne doit exister.

Toute troncature produit un signal structuré :

```text
outil
objet
quantité récupérée
quantité omise
raison
```

Une observation incomplète ne peut pas être considérée comme une preuve complète sans que cette limitation soit explicitement prise en compte.

---

## 4.8. Registre de faits

Chaque `Fact` contient :

- identifiant stable ;
- affirmation ;
- valeur ;
- source ;
- fichier/ligne ou identifiant runtime ;
- portée ;
- utilisateur ;
- société ;
- instant de lecture ;
- contexte `static` ou `runtime` ;
- niveau de preuve ;
- complétude ;
- provenance de l'outil.

Un fait issu du code ne doit jamais être présenté comme un état runtime.

Un fait runtime ne doit jamais être généralisé à tous les utilisateurs ou toutes les sociétés sans preuve.

Le registre peut représenter explicitement les conflits.

---

## 4.9. Filtrage d'habilitation

Avant d'atteindre le LLM, toute donnée runtime passe par un filtre d'habilitation.

Sont retirés :

- éléments interdits au demandeur ;
- champs non accessibles ;
- enregistrements hors périmètre ;
- données issues d'un contournement de sécurité.

Chaque élément retenu ou supprimé peut être associé à un motif d'audit.

---

## 4.10. Branche documentaire

La documentation est une source distincte.

Elle comprend :

### Documentation interne

- procédures ;
- politiques ;
- modes opératoires ;
- spécifications ;
- documentation fonctionnelle.

### Documentation générale Odoo

- documentation officielle Odoo 17 ;
- concepts ORM ;
- sécurité ;
- architecture ;
- fonctionnement standard.

La branche documentaire utilise un retrieval hybride :

```text
lexical + semantic retrieval
```

avec citations obligatoires.

Elle ne doit pas être confondue avec le retrieval de l'instance.

**Une documentation générale Odoo peut expliquer ce qu'Odoo est censé faire ; elle ne prouve pas ce que cette instance fait réellement.**

---

## 4.11. Rédaction

Le LLM reçoit :

- les faits retenus ;
- leurs preuves ;
- leur provenance ;
- le statut de complétude ;
- éventuellement des éléments de connaissance générale explicitement séparés.

La réponse possède trois niveaux :

### Niveau métier

Explication compréhensible par l'utilisateur.

### Niveau vérification

Dépliable :

- module ;
- fichier ;
- ligne ;
- méthode ;
- XML ID ;
- domaine ;
- groupe ;
- règle ;
- identifiant runtime ;
- preuve associée.

### Niveau gouvernance

Éléments non communiqués en raison des droits du demandeur et motif du filtrage, lorsque cette information peut être révélée sans elle-même exposer une donnée protégée.

---

## 4.12. Vérification

Un vérificateur générique contrôle :

- faits préservés ;
- faits perdus ;
- faits ajoutés ;
- faits contredits ;
- citations valides ;
- affirmations sans support ;
- confusion runtime/statique ;
- confusion instance/documentation générale.

Il produit un `VerificationReport`.

Une affirmation non supportée est :

1. retirée ;
2. ou explicitement marquée comme non vérifiée.

Les mécanismes `_backfill_*` et `_force_*` spécifiques à des questions doivent progressivement être remplacés par ce mécanisme générique.

---

## 4.13. Données et runtime

Les questions :

> combien ?

> qui ?

> quand ?

> quelles commandes ?

utilisent le même principe de registre de faits.

Contrat :

- identité du demandeur ;
- sociétés explicites ;
- ACL ;
- record rules ;
- champs accessibles ;
- lecture seule ;
- plafond de lignes ;
- timeout ;
- budget de contexte ;
- journalisation ;
- refus explicite hors périmètre.

Le LLM ne génère pas directement du SQL arbitraire.

Les opérations runtime passent par des outils contrôlés et typés.

---

## 4.14. Audit d'instance

Chaque instance possède un rapport versionné :

- modules non indexés ;
- extractions échouées ;
- références non résolues ;
- traductions manquantes ;
- modèles non couverts ;
- comportements sans outil de preuve ;
- termes ambigus ;
- objets runtime non rattachés au graphe ;
- capacités non supportées.

Chaque capacité est classée :

```text
couverte
ambiguë
preuve_manquante
non_supportée
```

L'audit alimente directement le backlog technique.

---

# 5. Interfaces contractuelles

Les interfaces principales sont :

```text
Fact
ObservationBudget
LexiconEntry
ResolutionResult
InvestigationPlan
VerificationReport
AssistantResponse
InstanceFingerprint
```

### `ResolutionResult`

```text
object
confidence
origin
candidates
abstention_reason
```

### `InvestigationPlan`

```text
intent
target
allowed_actions
required_evidence
budget
```

### `Fact`

```text
claim
value
source
scope
context
evidence_level
completeness
```

### `AssistantResponse`

```text
answer
sources
evidence
verification_report
sufficiency_status
```

Statut :

```text
sufficient
insufficient
conflicting
```

---

# 6. Évaluation

Le protocole d'évaluation est gelé avant tout calibrage.

Chaque cas comprend :

- hash de l'instance ;
- utilisateur ;
- société ;
- langue ;
- question ;
- intention ;
- objets attendus ;
- outils attendus ;
- preuves acceptables ;
- règle d'abstention.

Les jeux d'évaluation sont séparés par :

- instance ;
- module ;
- langue ;
- type de question.

Aucune fuite du jeu de validation vers le calibrage.

### Métriques globales

```text
accuracy_all_questions
accuracy_answered_questions
coverage
unsupported_claim_rate
wrong_tool_rate
technical_identifier_leak_rate
human_business_acceptance_rate
```

### Métriques par étage

```text
resolution_recall_at_k
evidence_completeness
answer_faithfulness
citation_precision
citation_completeness
abstention_precision
```

Une métrique importante à ajouter est :

> **instance_generalization_rate** : capacité à résoudre et expliquer des comportements sur des modules/instances jamais utilisés pour le calibrage.

---

# 7. Positionnement architectural

MIRO n'est donc ni :

```text
RAG documentaire classique
```

ni :

```text
GraphRAG pur
```

ni :

```text
Agent qui interroge simplement PostgreSQL
```

L'architecture cible est plutôt :

> **Agentic, evidence-grounded RAG over an Odoo instance knowledge graph.**

Ou en français :

> **Un RAG agentique et fondé sur les preuves, utilisant le graphe de connaissances de l'instance Odoo comme index structurel et des outils spécialisés pour investiguer le comportement réel.**

La chaîne complète est :

```text
Connaissance générale Odoo
          │
          │ compréhension / hypothèses
          ▼
      ┌─────────┐
      │  Agent  │
      └────┬────┘
           │
           ▼
  Retrieval de l'instance
           │
    ┌──────┼───────┐
    ▼      ▼       ▼
  Graph   Code   Runtime
    │      │       │
    └──────┼───────┘
           ▼
        Evidence
           │
           ▼
    Prompt augmenté
           │
           ▼
          LLM
           │
           ▼
       Vérificateur
           │
           ▼
 Réponse métier + preuves
```

**Le graphe n'est donc pas le remplacement du RAG : il est l'un des principaux mécanismes de retrieval du RAG.**

Et surtout, le système conserve une propriété essentielle pour ton objectif :

> **La connaissance générale permet au modèle de comprendre Odoo ; la connaissance de l'instance lui permet de savoir ce que cette instance fait ; les preuves lui permettent de démontrer pourquoi sa réponse est vraie.**