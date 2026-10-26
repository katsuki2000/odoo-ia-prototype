# Architecture cible de MIRO AI

## 1. Objectif

MIRO AI est un assistant privé qui aide les utilisateurs métier à comprendre le fonctionnement réel d'une instance Odoo 17 et à consulter les données auxquelles ils ont accès. Les réponses doivent être compréhensibles, vérifiables et fondées sur les sources effectivement consultées.

Le PoC distingue deux modes :
- **Selon le système Odoo** : investiguer le code, la configuration et, lorsque la question le demande, les données runtime de l'instance.
- **D'après la documentation** : chercher dans les documents internes indexés et répondre à partir des passages retrouvés.

L'utilisateur peut choisir le mode dans l'interface. Sans choix explicite, MIRO sélectionne la source la plus probable. Si la source reste incertaine, il demande une précision au lieu de choisir silencieusement.

Le LLM aide à classer la question, choisir les outils et rédiger une explication. Il ne constitue pas une preuve du comportement spécifique de l'instance. Une information générale sur Odoo doit être clairement présentée comme générale, et jamais comme un fait confirmé sur l'installation analysée.

## 2. Périmètre fonctionnel du PoC

Le PoC se concentre sur les capacités suivantes. Elles délimitent les familles de questions à évaluer ; elles ne constituent pas une liste fixe de modèles Odoo.

### 2.1 Code Intelligence : quatre familles prioritaires

1. **Droits et visibilité**
   - Expliquer les droits d'accès, groupes, règles d'enregistrement et restrictions d'interface pertinents.
   - Analyser pourquoi un utilisateur ne voit pas un document, un menu ou un bouton, lorsque les informations disponibles permettent de l'établir.
   - Distinguer les permissions déclarées dans le code du verdict runtime applicable à un utilisateur précis.

2. **Approbations et validations**
   - Identifier les étapes de validation, les gardes applicatives, les seuils, exceptions et automatisations.
   - Examiner les boutons et méthodes qui déclenchent une validation, ainsi que leurs surcharges entre modules.
   - Identifier où une règle est définie ou configurée lorsque les sources disponibles le démontrent.

3. **Saisie et remplissage des formulaires**
   - Expliquer les champs, valeurs autorisées, domaines de sélection et contraintes qui influencent la saisie.
   - Déterminer quelles validations peuvent empêcher l'enregistrement et expliquer les blocages établis par le code ou les observations.
   - Décrire l'interface et les actions disponibles sans prétendre remplir ou soumettre le formulaire à la place de l'utilisateur.

4. **Déroulement des processus métier**
   - Décrire les états, transitions et actions d'un processus.
   - Identifier les conditions qui permettent ou empêchent le passage à l'étape suivante.
   - Croiser le workflow, les méthodes, les droits et les actions automatisées lorsque la question l'exige.

**L'explication des blocages est transversale** : MIRO doit rechercher la cause pertinente au lieu de déduire le comportement à partir du seul nom d'un bouton, d'un champ ou d'une méthode.

### 2.2 Données ERP

Les questions portant sur des valeurs actuelles — statut, nombre, liste ou agrégation — doivent utiliser les outils ORM existants en lecture seule. Les opérations de création, modification et suppression sont hors périmètre du PoC.

La lecture d'une donnée métier s'effectue sous l'identité authentifiée du demandeur, avec le contexte de société correspondant. L'identité et les permissions ne proviennent jamais du LLM. L'accès technique utilisé pour lire des métadonnées ne doit pas servir de raccourci pour lire des données métier à la place de l'utilisateur.

### 2.3 Documentation interne

La branche documentaire utilise le RAG déjà présent dans le projet. Une réponse doit être fondée sur les passages récupérés et signaler les limites lorsque ces passages ne suffisent pas. La documentation interne peut décrire une procédure prévue ; elle ne prouve pas à elle seule que le code de l'instance applique cette procédure.

## 3. Couverture du code source

L'indexation ne doit pas être limitée à une poignée de modèles. Le graphe actif vise les modules qu'Odoo déclare installés et dont le code source est disponible dans les répertoires d'addons configurés : modules standards, personnalisés et tiers.

La recherche de Code Intelligence doit également pouvoir retrouver, au sein des modules chargés, les fichiers source utiles qui ne correspondent pas eux-mêmes à un nœud du graphe — par exemple certains helpers Python, vues XML, contrôleurs et fichiers JavaScript. Le graphe fournit les relations structurelles ; l'inventaire des fichiers source complète la découverte.

La couverture doit rester honnête :
- un module installé dont le code source est absent des chemins configurés constitue un écart ;
- un module ou un fichier qui n'a pas pu être chargé ou inventorié doit être signalé ;
- si l'inventaire runtime des modules installés est indisponible, le graphe de repli ne doit pas être présenté comme exhaustif ;
- un résultat de recherche vide n'est pas une preuve d'absence si la couverture est incomplète, la recherche tronquée ou les métadonnées obsolètes.

Les tests peuvent porter sur un ensemble représentatif de modules natifs et personnalisés. Cet échantillon limite l'évaluation du PoC, pas la portée de l'indexation lorsque les sources sont disponibles.

## 4. Architecture du PoC

Le PoC conserve les composants existants et privilégie le chemin le plus simple.

```text
Question utilisateur
        |
        v
Choix explicite de la source, sinon classification avec confiance
        |
        +-------------------------+
        |                         |
        v                         v
Documentation                Système Odoo
RAG existant                  Agent système unique
ChromaDB + recherche          - recherche dans le graphe et les sources
lexicale/vectorielle          - outils Code Intelligence
        |                     - outils ORM typés en lecture seule
        |                         |
        +------------+------------+
                     |
                     v
         Dossier de preuves existant
                     |
                     v
         Vérification et réponse
```

En mode système, le PoC conserve **un agent unique** qui dispose des outils d'analyse du code et des outils ORM typés. La distinction entre analyse statique et lecture runtime est maintenue dans les preuves, sans exiger deux agents séparés ni une nouvelle couche d'orchestration.

Pour rester proportionné au PoC, l'agent ne présente au LLM qu'un ensemble limité d'outils :
- **Découverte et inspection du code** : `search_system` et `read_source_fragment`.
- **Droits et visibilité** : `who_has_access_to`, `evaluate_record_rules`, `describe_navigation_path`, `button_execution_path` et `analyze_security_locks`.
- **Approbations et processus** : `describe_workflow`, `analyze_method_override_chain` et `analyze_server_actions`.
- **Saisie et validations** : `analyze_data_constraints`.
- **Données actuelles** : les outils ORM typés en lecture seule déjà existants.

Les utilitaires d'inspection générale ou d'impact qui ne font pas partie de ce périmètre ne sont pas exposés à l'agent. Leurs implémentations restent provisoirement dans le dépôt pour éviter une suppression avant l'audit des références et des tests. Cette limitation du choix d'outils simplifie le raisonnement du LLM sans remplacer les sources par sa mémoire.

Le routage est réalisé avant l'accès à la source. Le choix explicite de l'utilisateur est prioritaire. Lorsque le modèle de classification est indisponible ou que la confiance est insuffisante, MIRO demande une clarification au lieu de choisir une source par défaut. Le score de confiance du classifieur est un signal de routage, pas une probabilité de justesse calibrée.

## 5. Principes d'implémentation

1. **Réutiliser avant d'ajouter.** Conserver le graphe, les extracteurs, les outils d'analyse, le résolveur, le RAG, le collecteur de preuves et le vérificateur existants. Ne créer une nouvelle couche que si un échec mesuré le justifie.
2. **Résoudre les cibles de façon prudente.** Exploiter les libellés et objets de l'instance. Une cible ambiguë doit déclencher une clarification plutôt qu'un choix arbitraire. Le terme résolu et la cible effectivement analysée doivent rester cohérents pendant une même requête.
3. **Ne pas confondre code statique et état runtime.** Le code montre les mécanismes déclarés ; le runtime montre les données et l'effet applicable au contexte d'exécution. Les deux peuvent être nécessaires pour expliquer un blocage.
4. **Respecter les limites d'accès.** Le LLM ne choisit ni l'utilisateur ni la société et ne peut pas élever ses privilèges. Les outils ORM restent en lecture seule et sous l'identité du demandeur.
5. **Traiter les sorties d'outils comme des observations.** Les résultats de recherche servent à découvrir des éléments ; une affirmation doit être fondée sur une inspection ou une lecture adaptée, pas uniquement sur un résultat de recherche.
6. **Signaler l'incertitude et les limites de couverture.** Une erreur d'outil, une source inaccessible, une analyse tronquée ou un graphe incomplet ne doivent jamais être transformés en affirmation qu'une règle ou un comportement n'existe pas.
7. **Préserver la confidentialité.** Les prompts, secrets, extraits de code et données restent dans l'infrastructure approuvée par la configuration de déploiement.

## 6. Hors périmètre du PoC

- Génération, modification, installation ou déploiement automatique de code Odoo.
- Remplissage, confirmation, validation, approbation ou soumission effective d'opérations métier.
- Écriture ORM ou contournement des contrôles d'accès d'Odoo.
- Audit exhaustif de sécurité, tests d'intrusion ou optimisation générale des performances.
- Garantie de répondre à toute question, même lorsque les sources ou les capacités d'analyse ne permettent pas d'établir la réponse.

Ces exclusions limitent la livraison du PoC ; elles ne préjugent pas des évolutions futures.

## 7. Évaluation avant livraison

L'évaluation doit séparer les tests logiciels, les tests d'intégration et la qualité métier.

- Exécuter les tests unitaires et de non-régression du routage, du résolveur, des outils et de la construction du graphe.
- Vérifier que la couverture des modules et des fichiers source est rapportée correctement, y compris les cas où l'inventaire runtime ou certaines sources sont indisponibles.
- Tester les quatre familles Code Intelligence sur des scénarios vérifiés couvrant des modules natifs et personnalisés.
- Tester des questions ambiguës ou sans réponse étayée et vérifier que MIRO demande une précision ou signale la limite.
- Vérifier que les affirmations sont soutenues par les observations effectivement collectées et que les limites de lecture ORM sont respectées.
- Rejouer le protocole d'évaluation gelé sans modifier ses cas ni ses seuils pour masquer un échec.

Un test logiciel réussi ne prouve pas une précision métier de 80 % sur toutes les instances Odoo 17. Tout objectif chiffré doit être confirmé par une évaluation reproductible sur les instances et les cas de test définis.
