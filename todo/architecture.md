# Architecture cible de MIRO AI

## 1. Objectif

Mettre en place une IA privée qui explique le comportement réel d'un ERP Odoo 17 (natif, OCA et custom) à n'importe quel utilisateur, en termes métier, avec des preuves vérifiables, sans dépendre nécessairement de la documentation.

Elle répond sur le fonctionnement métier de l'instance, les règles de sécurité et d'accès, les workflows et
états, les contraintes et validations, les personnalisations Python/XML, les données accessibles à
l'utilisateur et les procédures internes.

> Comprendre ce que fait cette instance, expliquer pourquoi, et montrer d'où vient chaque information utilisée.

**Critère de réussite** : au moins 80 % de réponses correctes sur des instances et des questions tenues hors
calibrage, avec hypothèses d'accès explicites et politique d'abstention (protocole de mesure : section 6).

**Cadrage** : un moteur d'investigation fondé sur les preuves. Le graphe de l'instance en est l'index
structurel ; le LLM y intervient comme planificateur borné et comme rédacteur ; il ne décide jamais de ce qui
est vrai sur l'instance.

## 2. Principes

1. **Le LLM n'est jamais une source de vérité.** Le LLM connaît Odoo ; le graphe connaît cette instance. Les faits établis en consultant l'ERP et les documents sont injectés au prompt : le LLM s'appuie sur ses connaissances générales pour comprendre la question, formuler des hypothèses et orienter l'investigation, mais ne répond sur l'instance qu'à partir de ce qui a été trouvé. Le prompt sépare trois blocs : la
   connaissance générale (aide à comprendre), les faits de l'instance (seul fondement d'une affirmation sur
   l'installation) et les preuves (origine vérifiable des faits). Le LLM propose, l'instance démontre.

2. **L'autorité dépend du type d'affirmation à établir**, pas d'un classement fixe des sources :

   | Affirmation à établir | Source faisant autorité |
   |---|---|
   | Valeur, volume ou statut actuel | Runtime, sous l'identité du demandeur |
   | Ce que le demandeur voit ou peut faire | Runtime, ACL, règles d'enregistrement, groupes |
   | Pourquoi un bouton, un blocage ou un calcul se comporte ainsi | Code installé, vues et actions, confirmés par le runtime quand l'état compte |
   | Règle de sécurité applicable | ACL, règles, groupes, code |
   | Procédure ou politique interne | Documentation interne |
   | Fonctionnement standard d'Odoo | Documentation Odoo 17 et connaissance générale (ne prouve rien sur l'instance) |

   Une question « pourquoi » exige en général deux sources : le runtime montre l'effet sans en donner la
   cause, le code montre le mécanisme sans dire s'il s'applique maintenant.

3. **Un routage de sources explicite.** Chaque question reçoit une intention de source : comportement de
   l'instance, données de l'instance, documentation interne, Odoo général, ou combinaison déclarée. Le choix
   vient d'abord de l'utilisateur (mode choisi dans l'interface, ou formulation du type « selon le système »,
   « selon les procédures internes », « d'après la documentation »), puis de règles déterministes et du
   contexte d'écran. Le LLM n'est qu'un signal de plus, avec un score de confiance : quand la confiance est
   faible, MIRO demande une clarification au lieu de deviner. Les sources effectivement utilisées sont
   affichées avec la réponse.

4. **Toute lecture de données se fait sous l'identité du demandeur**, par l'ORM d'Odoo : jamais d'élévation de
   privilèges implicite, jamais de SQL brut. L'utilisateur et la société
   viennent de la session authentifiée, jamais d'une sortie du LLM. Les outils d'analyse du code peuvent
   avoir des privilèges techniques ; ils ne servent jamais à lire des données métier.

5. **Le côté privé** : aucun prompt, secret, extrait de code ou donnée ne quitte l'infrastructure prévue
   (Kaggle en test et développement, AWS en production). Passer en local ne demande de modifier qu'un seul
   fichier de configuration.

6. **Abstention explicite plutôt que réponse non prouvée.** Quand une information vient seulement des
   connaissances générales du LLM, la réponse le dit et précise qu'aucune preuve ne l'établit pour cette
   instance.

7. **Investigation bornée.** Le LLM planifie dans un vocabulaire d'actions fermé ; il ne crée pas d'outil, ne choisit ni l'utilisateur ni la société, et chaque appel est contrôlé par le moteur (outil, objet et périmètre autorisés) avant exécution. Partout où le LLM n'est pas indispensable (extraction du graphe,résolution exacte, contrôles de vérification), le traitement est déterministe.

8. **Réutiliser l'existant avant de réimplémenter.** Avant d'ajouter une bibliothèque, un service ou un moteur,
   inventorier les capacités déjà présentes dans le projet et celles de l'écosystème retenu. Réutiliser les
   intégrations LLM et embeddings, le RAG existant, les mécanismes d'agentic AI et les fonctions natives
   d'Odoo 17 (ORM, manifests, dépendances, ACL, règles d'enregistrement, modules et contexte utilisateur)
   lorsqu'ils couvrent correctement le besoin. S'appuyer sur la documentation officielle Odoo 17 pour le
   comportement standard, sans la confondre avec une preuve sur l'instance. Toute nouvelle dépendance ou
   réimplémentation doit répondre à un écart mesuré, documenté et couvert par des tests.

## 3. Pipeline

```text
 Question ──> Routage ──> Résolution ──> Investigation ──> Registre de faits ──> Rédaction ──> Vérification ──> Réponse
                              │              ▲   │                │
                              │              └───┴── porte de suffisance (obligations de preuve satisfaites ?)
                 Lexique unique (termes <-> libellés)

 Empreinte d'instance : rattachée à chaque étape et à chaque trace.
 Budget d'investigation : borne toute l'investigation.
```

Le retrieval est itératif et guidé par l'investigation (modèle, puis méthode, overrides, sécurité,
configuration, runtime si nécessaire). Ce n'est pas un top-k unique suivi d'une génération.

Après la résolution, MIRO établit la liste des preuves requises pour l'intention détectée. L'investigation
boucle tant qu'une preuve requise manque et que le budget le permet. La porte de suffisance décide ensuite :
suffisant (rédaction), insuffisant (abstention ou réponse partielle déclarée comme telle), conflictuel (conflit
exposé).

## 4. Composants

### 4.1. Empreinte d'instance
Inventaire des modules installés, versions, états, chemins d'addons accessibles, langues actives, et hash de
l'ensemble. L'empreinte est attachée à chaque graphe, lexique, trace et résultat d'évaluation : une réponse est
toujours rattachée à la version exacte de l'instance analysée.

### 4.2. Graphe de connaissances et état runtime
Deux objets distincts.

- **Graphe logiciel** : représente les modules effectivement installés dans l'instance Odoo, natifs,
  OCA et personnalisés. La liste d'installation et les états viennent de l'instance ; les chemins d'addons
  accessibles servent uniquement à localiser le code correspondant. Un dossier présent sur disque, même
  sous `odoo_addons/`, ne prouve pas qu'un module est installé et n'entre pas dans le graphe actif s'il ne
  l'est pas. Les modules disponibles mais non installés peuvent figurer dans un inventaire séparé.
  Les manifests et dépendances déclarées sont analysés, sans les confondre avec les dépendances runtime
  réellement observées. Le graphe est construit à partir du code des modules installés (AST Python, vues et
  données XML, droits d'accès CSV) et du registre runtime (vues, actions et server actions stockées en base,
  Studio inclus). Typé (modèles, champs, méthodes, groupes, règles, ACL, actions, automations, menus, états,
  boutons), porteur de tags sémantiques à vocabulaire fermé (comportementaux et techniques). Les relations
  sont dérivées par analyse du code, jamais extraites par un LLM. Reconstruit hors ligne puis permuté
  atomiquement ; jamais modifié pendant une requête.

  Les addons OCA tiers sont rangés sous `odoo_addons/` selon la convention du projet, sans les considérer
  automatiquement installés. Le `addons_path` d'Odoo doit inclure le répertoire parent des répertoires de
  modules. Les addons natifs restent dans les chemins natifs Odoo ; les modules personnalisés, dont
  `miro_ai`, sont traités séparément lors de toute décision de déplacement.
- **État runtime** : valeurs, enregistrements, configuration. Temporel, lu par l'ORM au moment de la question,
  jamais indexé dans le graphe.

Cette séparation distingue la vérité structurelle (ce que le système est construit pour faire) de la vérité
courante (ce qui se passe maintenant). Une question peut exiger les deux ; le registre de faits les étiquette.

### 4.3. Lexique unique
Une seule table, dans les deux sens : terme utilisateur vers objet, objet vers libellé utilisateur. Chaque
entrée est liée à son objet exact (modèle, champ, menu, sélection), à sa source (traduction statique,
traduction runtime, surcharge), à son module et à sa langue. Un terme peut viser un objet restreint par un
discriminant (champ et valeur), pas seulement un modèle. Les surcharges manuelles sont une couche optionnelle,
visible et mesurable.

### 4.4. Routage des sources
Ordre de décision : mode explicite de l'utilisateur, formulation explicite, règles déterministes, contexte
d'écran transmis par Odoo, proposition du LLM. Sortie : intention de source, confiance, origine. Une intention
ambiguë déclenche une question de clarification ou une combinaison déclarée de sources, jamais un choix
silencieux.

### 4.5. Résolution métier
1. Mention technique exacte.
2. Lexique dérivé de l'instance, dans la langue de la requête.
3. Contexte d'écran actif transmis par Odoo.
4. Recherche floue puis sémantique, utilisées comme indices. Une panne du backend d'embeddings est signalée,
   jamais masquée.
5. **Proposer puis vérifier** : le LLM reçoit la question et le contexte d'instance (4.6), propose jusqu'à 3
   noms techniques à partir de sa connaissance d'Odoo ; seuls les noms existant dans le graphe sont conservés ;
   aucun nom valide signifie non résolu.

Sortie : objet (avec discriminant éventuel), confiance, origine (`lexicon`, `override`, `llm_proposal`),
candidats ou abstention explicite. Une question ambiguë (« commande ») n'est jamais résolue par défaut vers un
domaine.

### 4.6. Contexte d'instance
MIRO n'enseigne pas Odoo au LLM : il lui montre ce que cette instance ajoute ou change. Pour chaque candidat ou
objet résolu, un contexte compact, construit de façon déterministe à partir du graphe et du lexique : existence
dans le graphe, libellés dans la langue de l'utilisateur, menus et écrans, discriminants, modules qui le
touchent, champs et méthodes ajoutés ou surchargés par les modules non standard, sécurité applicable. Il sert à
valider les hypothèses du LLM, à planifier l'investigation et à rédiger. Il ne contient aucune documentation
générale d'Odoo, et sa taille est bornée par le budget.

### 4.7. Investigation
Un plan d'investigation explicite, à vocabulaire d'actions fermé, est produit avant tout appel d'outil, puis
validé par le moteur. Il porte les preuves requises, déduites de l'intention (par exemple, pour un
comportement de bouton : méthode appelée, overrides, ACL, règles, groupes, contraintes, actions serveur,
configuration, exception observée). Ces obligations sont génériques par intention, jamais propres à une
question.

Les collecteurs déterministes exécutent le plan (verrous de sécurité, chaîne d'overrides, accès et règles
d'enregistrement, actions serveur, workflow, héritage, navigation, chemin d'exécution des boutons, contraintes
de données) ; des outils d'approfondissement complètent si nécessaire. Chaque outil produit des observations
et des faits, pas seulement du texte. Après chaque action, les obligations sont réévaluées.

Invariant : outils exécutés ⊆ outils planifiés ⊆ outils autorisés, pour toutes les catégories d'intention. La
profondeur s'adapte à la longueur de la chaîne, sans règle propre à une question.

### 4.8. Budget d'investigation
Un seul objet `InvestigationBudget`, lu par tous les sites ; aucune limite en dur ailleurs, toutes les valeurs
viennent de la configuration. Dimensions : appels d'outils, durée runtime, lignes, octets, profondeur de
graphe, tokens de contexte, appels LLM, coût. Les limites de taille des observations (par outil, total, mode de
dégradation) dérivent de la fenêtre de contexte configurée.

Quand une observation dépasse son budget, elle est dégradée par priorité (minimum protégé par bloc, puis
répartition proportionnelle), jamais coupée en tête. Toute perte produit un signal structuré (outil, objet,
quantité omise) transmis au registre de faits et à la porte de suffisance : une réponse bâtie sur une
observation incomplète ne peut pas être déclarée suffisante sans le dire.

### 4.9. Registre de faits
Quatre niveaux, du brut à l'affirmation :

- **Observation** : résultat d'un outil tel que récupéré (outil, paramètres, instant, empreinte, utilisateur et
  société).
- **Evidence** : fragment vérifiable d'une observation, avec son localisateur (fichier et ligne, nœud AST,
  identifiant XML, identifiant d'enregistrement) et son hash de contenu.
- **Fact** : interprétation structurée, avec identifiant stable, affirmation, valeur, source, portée (société,
  utilisateur, instant de lecture), contexte **statique ou runtime**, niveau de preuve et indicateur de
  complétude.
- **Claim** : affirmation de la réponse finale, reliée aux faits qui la soutiennent.

Un mécanisme dérivé du code n'est jamais présenté comme un état lu en base. Un fait statique n'est émis que si
le graphe en apporte la preuve et que la question ne dépend pas de la configuration runtime. Un fait runtime
n'est jamais généralisé à d'autres utilisateurs ou sociétés sans preuve. Le registre exprime les conflits entre
deux sources.

La porte de suffisance compare les preuves requises aux preuves obtenues et rend le statut `suffisant`,
`insuffisant` ou `conflictuel`. Toute réponse est reconstructible : question, plan, outils, observations,
evidence, faits, prompt, réponse et vérification, rattachés à l'empreinte.

### 4.10. Filtrage d'habilitation
Toute observation traverse un filtre avant d'atteindre le LLM : les mécanismes de contournement sensibles sont
retirés si le demandeur n'a pas de droits élevés sur l'objet, ainsi que les champs inaccessibles et les
enregistrements hors périmètre. Chaque élément retenu ou retiré est consigné avec son motif.

### 4.11. Rédaction
Le LLM reçoit des faits déjà exprimés avec les libellés de l'utilisateur, dans sa langue, le contexte
d'instance, et les trois blocs du principe 1. Il produit une réponse en deux niveaux :
- **niveau utilisateur** : explication métier, sans identifiant technique ;
- **niveau vérification** (dépliable) : module, fichier, ligne, identifiant XML, domaine, preuves.

S'ajoute un niveau gouvernance : éléments retenus pour habilitation insuffisante, avec motif, lorsque
l'indiquer n'expose pas lui-même une donnée protégée. Toute affirmation issue de la connaissance générale est
présentée comme telle.

### 4.12. Vérification
Deux étages.

1. **Déterministe**, indépendant du LLM : montants, identifiants, groupes, conditions, messages d'exception,
   citations contre les passages réellement récupérés, portée, confusion statique/runtime, confusion
   instance/documentation générale, et chaîne `Claim -> Fact -> Evidence` pour chaque affirmation.
2. **Sémantique** : cohérence, nuance omise, formulation. Cet étage ne peut ajouter aucun fait.

Le `VerificationReport` liste les faits préservés, perdus, ajoutés et contredits. Une affirmation sans fait
support est retirée ou signalée comme non vérifiée. Ce mécanisme générique remplace les corrections propres à
un cas.

### 4.13. Données et runtime
Les questions « combien / qui / quand » passent par le même pipeline, avec les mêmes faits et le même
registre. Contrat de lecture : exécution par l'ORM sous l'identité du demandeur, périmètre de sociétés
explicite, ACL, règles et champs accessibles appliqués, lecture seule, plafond de lignes, budgets de temps et
de contexte, journalisation de chaque requête (utilisateur, société, but, volume, résultat), refus déclaré hors
périmètre pour ce que le demandeur ne peut pas voir. Les opérations passent par des outils typés ; le LLM ne
produit jamais de SQL.

### 4.14. Audit d'instance
Un rapport versionné, rattaché à l'empreinte : modules non indexés, extractions en échec, références non
résolues, traductions manquantes, domaines sans outil de preuve, termes ambigus. Chaque capacité est classée
`couverte`, `ambiguë`, `preuve_manquante` ou `non_supportée`, et alimente un backlog.

### 4.15. Branche documentaire
Limitée aux procédures et politiques non codées dans l'ERP, et, en option, à la documentation générale d'Odoo
pour orienter la compréhension. Recherche hybride (vectorielle et lexicale), citations obligatoires et
vérifiées contre les passages réellement récupérés. Une structuration de type GraphRAG est admise ici, parce
que le corpus est non structuré ; elle ne s'applique jamais au code. Cette branche ne fait jamais autorité sur
le comportement de l'installation : elle dit ce qu'Odoo ou l'entreprise prévoit, pas ce que l'instance fait.

## 5. Interfaces

- `InstanceFingerprint` : empreinte d'instance, attachée à tout artefact.
- `Fact` : seul format de sortie des outils vers la rédaction (précédé de `Observation` et `Evidence`).
- `InvestigationBudget` : seule source des limites.
- `LexiconEntry` : seule source des libellés, dans les deux sens.
- `RoutingResult` : intention de source, confiance, origine.
- `ResolutionResult` : objet, discriminant, confiance, origine, candidats, motif d'abstention.
- `InvestigationPlan` : actions fermées et preuves requises, vérifiable contre l'exécution.
- `VerificationReport` : faits préservés, perdus, ajoutés, contredits.
- `AssistantResponse` : réponse utilisateur, sources, preuves, éléments retenus, rapport de vérification,
  statut de suffisance (suffisant, insuffisant, conflictuel).

## 6. Évaluation

Un protocole gelé avant tout calibrage : cas figés (hash d'instance, utilisateur, société, langue, question,
intention et objets attendus, preuves acceptables, règle d'abstention), séparation par instance, module et
langue, jamais par tirage aléatoire de questions. Métriques : `accuracy_all_questions`,
`accuracy_answered_questions`, `coverage`, `unsupported_claim_rate`, `wrong_tool_rate`,
`technical_identifier_leak_rate`, `human_business_acceptance_rate`. Métriques par étage pour localiser
l'erreur : `resolution_recall_at_k`, `evidence_completeness`, `answer_faithfulness`. Aucun snapshot de
validation ne sert au calibrage.
