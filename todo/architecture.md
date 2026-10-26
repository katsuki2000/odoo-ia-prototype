# Architecture cible de MIRO AI

## 1. Objectif

MIRO AI est un assistant privé destiné à expliquer le fonctionnement d'une instance Odoo 17 en langage métier, avec des réponses vérifiables et adaptées aux droits de la personne qui pose la question.

Le projet distingue deux sources principales :
- **Le système Odoo** : le code source et la structure de l'instance, ses configurations et, lorsque la question concerne des données métier, les données accessibles à l'utilisateur.
- **La documentation** : les documents internes qui décrivent les procédures et les règles de l'organisation.

Dans l'interface, l'utilisateur peut choisir « Selon le système » ou « D'après la documentation ». En l'absence de choix, MIRO détermine la source à interroger. Si l'intention est ambiguë et que l'incertitude empêche une investigation fiable, il demande une précision.

Le LLM aide à comprendre la question, planifier l'investigation et synthétiser les résultats. Il n'est pas la source de vérité sur le fonctionnement spécifique de l'instance : les affirmations propres à celle-ci doivent être étayées par le code, la configuration, les données ou les documents effectivement consultés. Si les preuves sont insuffisantes, MIRO l'indique au lieu d'inventer une réponse.

## 2. Périmètre fonctionnel du PoC

Le PoC ne cherche pas à répondre à toute question imaginable sur Odoo. Il vise à démontrer de façon fiable un ensemble prioritaire de capacités métier, sans imposer de liste fixe de modèles à l'architecture.

### 2.1 Code Intelligence : quatre familles de questions

1. **Droits et visibilité**
   - Qui peut consulter un objet métier et quelles restrictions d'accès s'appliquent ?
   - Quels groupes, droits d'accès, règles d'enregistrement ou restrictions d'interface expliquent qu'un utilisateur ne voie pas un document, un menu ou un bouton ?
   - Quelles sont les limites de l'analyse lorsque le contexte utilisateur requis n'est pas disponible ?

2. **Approbations et validations**
   - Qui approuve ou valide une opération, dans quel ordre et sous quelles conditions ?
   - Des seuils, exceptions, validations supplémentaires ou actions automatisées modifient-ils le processus ?
   - Où ces règles sont-elles configurées ou implémentées, lorsque le code disponible permet de le déterminer ?

3. **Saisie et remplissage des formulaires**
   - Quels champs, valeurs autorisées, domaines de sélection ou contraintes influencent la saisie ?
   - Quelles contraintes ou validations peuvent empêcher l'enregistrement ?
   - Pourquoi un champ ou une action semble-t-il indisponible, lorsqu'une explication est démontrable à partir des vues, configurations et sources analysées ?

4. **Déroulement des processus métier**
   - Quelles sont les étapes ou les états d'un processus ?
   - Quelles actions permettent de passer d'un état à un autre et quelles conditions ou vérifications contrôlent la transition ?
   - Pourquoi une opération reste-t-elle bloquée ou ne passe-t-elle pas à l'étape suivante ?

**L'explication des blocages est transversale à ces quatre familles.** MIRO doit croiser les mécanismes pertinents au lieu de déduire la cause d'un blocage à partir du seul nom d'un bouton, d'un champ ou d'une méthode.

Les questions sont formulées en langage métier : l'utilisateur n'a pas besoin de connaître les noms techniques des modèles ou des méthodes. En cas d'ambiguïté substantielle, MIRO demande une précision plutôt que de sélectionner arbitrairement une cible.

### 2.2 Données ERP

Les questions portant sur les valeurs présentes dans Odoo relèvent de la branche de consultation des données ERP. Le PoC privilégie la recherche, la consultation, le comptage et l'agrégation en lecture seule au moyen des capacités ORM déjà intégrées au projet.

Les lectures s'effectuent sous l'identité authentifiée du demandeur et dans son périmètre d'accès. L'utilisateur, les sociétés autorisées et le contexte d'exécution proviennent de la session, jamais d'une décision du LLM. Les opérations de création, de modification et de suppression sont hors périmètre.

### 2.3 Couverture du code source

L'indexation et l'exploration de Code Intelligence ne sont **pas limitées à quelques modèles Odoo**. Le graphe actif doit couvrir les modules déclarés installés par l'instance Odoo et dont le code source est accessible dans les répertoires d'addons configurés : modules standards, personnalisés et tiers. Les modules présents sur disque mais non installés doivent être distingués et ne doivent pas être présentés comme faisant partie de l'instance active.

Les outils doivent pouvoir naviguer entre les modèles, champs, méthodes, héritages, vues, boutons, groupes, droits d'accès, règles d'enregistrement et actions automatisées, dans la mesure où ces éléments sont présents et pris en charge par l'indexeur et les outils d'analyse.

La couverture fonctionnelle du PoC est limitée aux quatre familles ci-dessus ; la couverture de l'indexation, elle, n'est pas artificiellement limitée à une liste de 3 à 5 modules parmi les modules installés et accessibles. Les tests peuvent se concentrer sur un ensemble représentatif de modules et de scénarios, sans que cet ensemble devienne une restriction de l'architecture.

La couverture n'est toutefois pas supposée exhaustive : un module qui n'est pas présent dans les répertoires indexés, un fichier non analysé ou un comportement dynamique que les outils ne savent pas inspecter ne constitue pas une preuve disponible. MIRO doit signaler cette limite.

## 3. Hors périmètre du PoC

- Générer, modifier, installer ou déployer automatiquement du code Odoo.
- Remplir, valider, approuver ou soumettre réellement des formulaires ou des opérations métier.
- Exécuter des écritures ORM ou contourner les contrôles d'accès d'Odoo.
- Réaliser un audit exhaustif de sécurité, un test d'intrusion ou une analyse générale des performances.
- Garantir une réponse à toute question technique ou métier, indépendamment des sources disponibles.
- Déduire un comportement spécifique à l'instance lorsque le code, la configuration, les données et la documentation ne permettent pas de l'établir.

Ces exclusions décrivent le périmètre de livraison du PoC et ne constituent pas nécessairement des interdictions pour une évolution future de l'architecture.

## 4. Principes d'architecture

1. **Les preuves avant les affirmations.** Le LLM peut employer ses connaissances générales pour comprendre les concepts Odoo et organiser l'investigation, mais ne présente pas un comportement spécifique à l'instance comme un fait sans éléments observés.
2. **Le routage des sources est explicite.** Le choix de l'utilisateur est prioritaire ; à défaut, MIRO choisit la source la plus pertinente. Une incertitude importante déclenche une clarification plutôt qu'une supposition.
3. **Respect des droits Odoo.** Les données métier sont lues sous l'identité du demandeur, sans élévation implicite de privilèges. L'analyse du code et la consultation des données runtime sont deux opérations distinctes : l'existence d'un droit dans le code ne prouve pas, à elle seule, l'accès effectif d'une personne donnée.
4. **Déploiement privé.** Les prompts, secrets, extraits de code et données restent dans l'infrastructure approuvée pour l'environnement concerné.
5. **Réutiliser l'existant avant d'ajouter des couches.** Réutiliser le RAG, les embeddings, les outils d'analyse, le graphe de code et les intégrations déjà présents, ainsi que les mécanismes natifs d'Odoo (ORM, RPC, ACL, règles d'enregistrement, groupes, modules et contexte utilisateur), avant d'ajouter une bibliothèque, un service ou un nouveau moteur.
6. **Lecture seule pour le PoC.** Code Intelligence lit et analyse les sources ; l'agent ERP consulte les données sans les modifier.
7. **Une couverture extensible.** Les outils sont conçus pour découvrir et explorer les modèles et modules effectivement indexés, plutôt que d'enfermer l'architecture dans des correspondances codées en dur entre questions et une petite liste de modèles.

## 5. Évaluation et critères de livraison

La validation doit mesurer le comportement réel du PoC, et non la seule présence de composants dans l'architecture.

- Rejouer les tests unitaires ciblés de classification, d'outillage et de non-régression du routage.
- Rejouer le protocole d'évaluation gelé sans changer ses cas ni ses seuils pour masquer les échecs.
- Couvrir les quatre familles de questions Code Intelligence avec des scénarios représentatifs comprenant, lorsque les sources de test le permettent, des modules standards et personnalisés.
- Vérifier que les réponses importantes sont étayées par des observations réelles et que les conclusions non démontrées sont signalées comme telles.
- Vérifier les cas de refus ou d'incertitude, les fichiers absents ou non indexés, les identifiants introuvables et les limites des outils.
- Tester la consultation ORM sur des questions représentatives tout en vérifiant le respect de l'identité, des droits d'accès et des limites de lecture.

Le PoC sera jugé sur les familles fonctionnelles et les scénarios effectivement évalués. La validation sur un échantillon représentatif ne doit pas être présentée comme une garantie de compatibilité parfaite avec toutes les instances, personnalisations ou questions Odoo 17.
