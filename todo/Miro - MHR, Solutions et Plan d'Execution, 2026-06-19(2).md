# I. Solutions envisagées et difficultés à anticiper

## 1\. Les options envisagées

### Option A — API cloud (OpenAI, Claude, Gemini)

**Principe :** envoyer les questions et le contexte documentaire à un service IA hébergé chez un tiers, via une API.

**Avantages :** mise en œuvre rapide, qualité de réponse généralement excellente, aucune infrastructure à gérer.

**Verdict : éliminée.**

### Option B — RAG local sur modèle open source

**Principe :** faire tourner un modèle de langage open source (Mistral, Llama 3...) entièrement en local, et lui injecter à chaque question les passages pertinents de la documentation interne, sans jamais réentraîner le modèle.

**Avantages :** aucune donnée ne quitte l'infrastructure MiroKE, chaque réponse peut être sourcée précisément, et l'ajout d'un nouveau document met à jour le système immédiatement, sans réentraînement.

**Verdict : retenue.**

### Option C — Fine-tuning d'un modèle open source

**Principe :** réentraîner un modèle existant sur un jeu de données propre à MiroKE, pour qu'il "absorbe" les connaissances métier directement dans ses paramètres.

**Avantages :** des réponses potentiellement plus "naturelles", sans avoir besoin d'aller chercher un document à chaque requête.

**Verdict : option complémentaire à envisager à plus long terme (12-18 mois), une fois le RAG validé.**

### Option D — Hybride RAG \+ Fine-tuning

**Principe :** combiner les deux approches une fois que la première est opérationnelle et éprouvée.

**Verdict : à reconsidérer après le pilote.**

### Option E — Modules IA packagés du marketplace Odoo

**Principe** : Odoo propose, en natif (offre Enterprise) ou via des modules tiers du marketplace (ex. : suites de "copilots" spécialisés par métier), des fonctionnalités IA déjà intégrées à l'ERP — scoring prédictif, OCR de documents, recherche sémantique, agents conversationnels configurables.

**Pourquoi** cette option semble séduisante : aucune infrastructure à construire, mise en service rapide, interface déjà intégrée à Odoo.

Pourquoi elle ne résout pas le problème posé : ces modules, qu'ils soient natifs ou tiers, s'appuient systématiquement sur des modèles de langage hébergés en externe (GPT, Gemini ou équivalent) — l'agent IA configurable d'Odoo impose explicitement de choisir un fournisseur cloud au moment de la configuration.

Au-delà de la question de confidentialité, la qualité des modules tiers du marketplace Odoo reste inégale. Plusieurs retours d'intégrateurs spécialisés indiquent qu'une large majorité des modules IA tiers proposés sur la marketplace sont peu aboutis, et qu'une partie significative est abandonnée par leurs éditeurs peu après leur sortie.

**Verdict : éliminée,**

### Alternatives envisagées pour l'interrogation des données ERP structurées

Au-delà du choix du RAG documentaire (Option B), une décision technique distincte concerne la façon d'interroger les données chiffrées de l'ERP (ventes, stocks, factures). Deux alternatives au function calling retenu ont été étudiées avant de trancher.

#### Alternative 1 — Text-to-SQL (ou Text-to-ORM)

**Principe :** plutôt que de limiter le modèle à un catalogue de fonctions prédéfinies, on lui fournit directement le plan de la base de données (tables, colonnes, relations) et on le laisse rédiger lui-même la requête technique. Pour la question "Quel est le total facturé pour le Client 2 ?", le modèle générerait directement une requête du type `SELECT SUM(amount) FROM account_move WHERE partner_name = 'Client 2'`, exécutée telle quelle sur la base.

**Avantage :** une flexibilité quasi illimitée — aucune fonction à coder à l'avance pour chaque cas d'usage, le modèle peut en théorie croiser des données de façon inédite face à une question imprévue.

> **Verdict : écartée.** Le risque d'erreur silencieuse sur une donnée chiffrée et le risque de sécurité sur l'exécution de requêtes générées dynamiquement sont disproportionnés par rapport au bénéfice de flexibilité.

#### Alternative 2 — Code Interpreter (agent d'analyse de données)

**Principe :** l'approche popularisée par les fonctionnalités d'analyse de données avancée de certains assistants IA grand public. Plutôt que du SQL ou des fonctions simples, le modèle écrit un véritable script Python (typiquement avec Pandas), exécuté dans un environnement isolé et temporaire ("bac à sable"), dont le résultat est ensuite récupéré et présenté.

**Avantage :** la solution la plus puissante des trois — capable de calculs complexes, de nettoyage de données à la volée, et même de corriger ses propres erreurs en relisant le résultat de son script.

> **Verdict : écartée.** Complexité de déploiement et de maintenance disproportionnée par rapport à la nature des questions métier visées (consultation de stock, de ventes, de statut de commande).

#### Tableau comparatif des trois approches

| Critère | Text-to-SQL | Code Interpreter | Function calling (retenu) |
|---|---|---|---|
| Précision sur les calculs chiffrés | Risque d'erreur silencieuse (jointures, colonnes erronées) | Élevée, mais coûteuse à obtenir | Élevée — seules des opérations validées à l'avance sont exécutées |
| Sécurité | Faible sans garde-fous réseau extrêmes | Élevée (environnement isolé), mais complexe à sécuriser | Élevée — le modèle ne peut appeler que des fonctions explicitement codées par l'équipe technique |
| Complexité de mise en œuvre | Modérée | Élevée (infrastructure d'exécution dédiée) | Faible à modérée — un catalogue de fonctions à définir et étendre progressivement |
| Flexibilité face à une question imprévue | Très élevée en théorie | Très élevée | Limitée au catalogue de fonctions défini |
| Latence | Faible | Élevée (création d'un environnement à chaque requête) | Faible |
| Cohérence avec les droits d'accès Odoo existants | Difficile à garantir (le SQL contourne la couche applicative) | Difficile à garantir | Native — l'appel passe par l'ORM, qui respecte les permissions Odoo |

#### Pourquoi le function calling reste le choix retenu

Le function calling occupe un point d'équilibre que les deux alternatives n'atteignent pas simultanément :

- **Précision** : contrairement au Text-to-SQL, il est fiable sur les calculs chiffrés, puisque seules des opérations déjà vérifiées et validées par l'équipe technique peuvent être exécutées — aucune requête n'est inventée à la volée.
- **Sécurité** : contrairement au Text-to-SQL, le modèle ne peut utiliser que les fonctions explicitement codées et exposées par l'équipe technique, ce qui élimine le risque d'accès non maîtrisé à la base de données.
- **Légèreté** : contrairement au Code Interpreter, aucun environnement d'exécution complexe n'est créé à chaque requête, ce qui garantit une réponse rapide et une infrastructure simple à maintenir sur la durée du stage.

La contrepartie assumée est une flexibilité plus restreinte : une question portant sur un type de donnée non couvert par le catalogue de fonctions ne pourra pas être traitée tant que la fonction correspondante n'aura pas été ajoutée — un compromis jugé raisonnable au regard du gain en fiabilité et en sécurité, pour un usage où l'exactitude d'un chiffre prime sur la flexibilité de la question posée.


## 2\. Difficultés à anticiper

### 2.1. Difficultés techniques

**Matériel.** Un modèle de langage, même de taille modeste (7-8 milliards de paramètres), demande une carte graphique dédiée pour fonctionner à une vitesse acceptable. 

**Qualité des données sources.** Un RAG n'est jamais meilleur que les documents qu'il indexe. Du code source non commenté, des wikis mal structurés ou des PDF scannés de mauvaise qualité dégraderont directement la pertinence des réponses, indépendamment de la qualité du modèle choisi. Une partie du travail consistera donc à nettoyer et structurer les sources avant même de parler d'intelligence artificielle.

**Indexation du code source.** Contrairement à un document texte classique, le code source d'Odoo (Python, XML) a une structure logique propre (fonctions, classes, règles métier) qu'un découpage en texte brut ne respecte pas. Il faut un traitement spécifique pour que l'assistant puisse répondre correctement à une question comme "où est défini ce workflow ?".

**Interrogation des données métier structurées.** un modèle de langage qui tente de "deviner" une réponse chiffrée à partir de texte vectorisé produira des résultats faux sans que l'erreur soit visible. La solution consiste à donner au modèle un accès encadré à un ensemble prédéfini d'opérations sur l'ERP (consulter un stock, calculer un total sur une période), plutôt que de le laisser improviser une requête. 

### 2.2. Difficultés organisationnelles

**Isolation entre clients (multi-tenant).** aucune information d'un client ne doit jamais être accessible à un autre — y compris en cas d'erreur de configuration. C'est une exigence de sécurité non négociable qui doit être pensée dès l'architecture, pas ajoutée après coup.

**Cloisonnement des accès en interne.** Même au sein de MiroKE, un employé du support ne doit pas nécessairement avoir accès à toutes les informations consultées par un développeur, ou inversement.

**Adoption par les équipes.** 

# II. Choix de la solution

## 1\. Architecture cible

Le système repose désormais sur deux mécanismes distincts selon la nature de la question posée, en plus du flux d'indexation qui s'exécute en continu.

[![architecture-cible-v2.png](https://i.postimg.cc/bY0Xq7js/architecture-cible-v2.png)](https://postimg.cc/F1KCZnz4)

### 1.1.Flux d'indexation documentaire (en amont).

Les documents sources (PDF, wikis, code source) sont extraits, découpés, vectorisés et stockés dans la base vectorielle. Ce flux tourne en arrière-plan et se déclenche à chaque ajout ou modification de document.

**Exemple concret de question documentaire :**

| Élément | Détail |
| ----- | ----- |
| Question utilisateur | "Qui peut approuver une mise à disposition ?" |
| Nature de la réponse | Une règle métier écrite dans le code (condition, groupe de permission, workflow), pas une donnée qui change en continu |
| Traitement | Recherche sémantique dans l'index du code source Odoo, qui retrouve la fonction ou la règle exacte définissant cette permission |
| Réponse attendue | Le rôle ou le groupe habilité, avec la référence précise du fichier et de la fonction où cette règle est définie |
| Ce que ça remplace | La pratique actuelle, où un développeur doit ouvrir le code source manuellement pour retrouver cette information |

### 1.2.Catalogue de fonctions ERP (en amont, défini une fois).

Plutôt que de laisser le modèle improviser une requête sur les données métier structurées (ventes, stocks, commandes), un ensemble fermé de fonctions est défini à l'avance — par exemple "obtenir le stock d'un produit" ou "calculer un total de ventes sur une période" — chacune s'appuyant directement sur l'ORM d'Odoo en lecture seule.

**Exemple concret de fonction du catalogue :**

| Élément | Détail |
| ----- | ----- |
| Question utilisateur | "Combien de ventes a fait \[Client X\] cette année ?" |
| Fonction déclenchée | `obtenir_total_ventes(client, periode)` |
| Résolution du paramètre `client` | Le nom donné en langage naturel est recherché dans la table clients d'Odoo (`res.partner`) pour retrouver l'identifiant exact ; en cas de plusieurs correspondances, le système demande une précision plutôt que de choisir au hasard |
| Résolution du paramètre `periode` | "Cette année" est traduit en plage de dates (01/01 au 31/12 de l'année en cours) |
| Appel ORM correspondant | Lecture des commandes (`sale.order`) filtrées par client et par date, agrégées en montant total |
| Contrôle d'accès appliqué | Un employé MiroKE peut interroger n'importe quel client ; un utilisateur connecté depuis le module Odoo d'un client ne peut interroger que ses propres données, quel que soit le nom saisi |

### 1.3.Flux de requête (au moment de la question).

Lorsqu'un utilisateur pose une question, le système analyse d'abord sa nature : s'agit-il d'une question documentaire (qui sera traitée par recherche sémantique dans la base vectorielle) ou d'une question portant sur une donnée chiffrée (qui sera traitée par l'appel d'une fonction du catalogue ERP) ? Dans les deux cas, le résultat — passages documentaires ou donnée ERP récupérée est transmis au modèle de langage local, qui formule la réponse finale en citant sa source exacte : un document pour le premier cas, la donnée ERP interrogée pour le second.

## 2\. Stack technique
| Couche | Outil retenu | Pourquoi ce choix |
| ----- | ----- | ----- |
| **Modèle de langage** | Mistral 7B (ou Llama 3 8B selon les tests) | Mistral est particulièrement performant en français et reste léger ; Llama 3 8B est une alternative plus polyvalente si la puissance disponible le permet |
| **Orchestration RAG** | LangChain ou LlamaIndex | Frameworks matures, large communauté, intégration directe avec les bases vectorielles courantes |
| **Base vectorielle** | ChromaDB en développement → Qdrant en production | ChromaDB est rapide à mettre en place pour les tests ; Qdrant prend le relais en production car il supporte nativement l'isolation entre plusieurs clients (multi-tenant) |
| **Serveur d'inférence** | Ollama en développement → vLLM en production | Ollama permet de tester rapidement plusieurs modèles ; vLLM est conçu pour tenir la charge avec plusieurs utilisateurs simultanés |
| **Interface utilisateur** | Application web interne \+ module Odoo dédié | Un seul point d'entrée technique (API), deux façades différentes selon que l'utilisateur est interne à MiroKE ou employé d'un client |
| **Interrogation ERP structuré** | Function calling sur l'ORM Odoo (catalogue de fonctions prédéfinies) | Respecte nativement les droits Odoo (res.groups, ir.rule), évite la génération libre de requêtes risquées |

# III. Plan d'exécution
#### Avancement à date

| Semaine | Période | Contenu |
| ----- | ----- | ----- |
| Semaine 1 | 08/06 – 12/06/2026 | Terminé — Analyse du problème : contexte, problématique, objectifs |
| Semaine 2 | 15/06 – 19/06/2026 | Terminé — Solutions envisagées, choix de la solution, plan d'exécution initial |


## 1\. Calendrier

| Semaines | Période | Phase |
| ----- | ----- | ----- |
| S1 – S4 | 08/06 – 03/07/2026 | Analyse, étude des besoins, infrastructure |
| S5 – S9 | 06/07 – 07/08/2026 | Pipeline RAG documentaire (PDF, wikis, code source) |
| S10 – S13 | 10/08 – 04/09/2026 | Interrogation des données ERP structurées (function calling ORM Odoo) |
| S14 – S17 | 07/09 – 02/10/2026 | Interface, intégration Odoo, sécurité |
| S18 – S20 | 05/10 – 23/10/2026 | Cloisonnement multi-tenant, droits d'accès |
| S21 – S22 | 26/10 – 06/11/2026 | Tests de charge, évaluation qualité |
| S23 – S25 | 09/11 – 27/11/2026 | Documentation, formation, restitution |

## 2\. Rédaction du mémoire

La rédaction du mémoire de fin de stage n'est pas une tâche isolée en fin de calendrier : elle s'effectue en continu, en parallèle du développement, chapitre par chapitre, au fur et à mesure que chaque partie du système est conçue ou livrée.

## 3\. Détail semaine par semaine

### S3 (22/06 – 26/06) — Installation de l'environnement

* Installation du système hôte (Ubuntu Server) sur le matériel validé  
* Installation d'Ollama et téléchargement des modèles candidats (Mistral 7B, Llama 3 8B, Phi-3 mini) en version quantifiée GGUF

Livrable : environnement local opérationnel, les modèles candidats se lancent sans erreur.

### S4 (29/06 – 03/07) — Tests comparatifs des modèles

* Constitution d'un jeu de 20 questions métier représentatives  
* Mesure du temps de réponse, des tokens par seconde, de la consommation mémoire et d'un score qualitatif pour chaque modèle

Livrable — Jalon J1 : modèle sélectionné sur preuve mesurée (score ≥ 3,5/5, réponse ≤ 15 secondes).

### S5 (06/07 – 10/07) — Extraction des documents et chunking

* Constitution d'un jeu de documents de test fixe et représentatif (quelques PDF, quelques pages wiki, un échantillon de code source), volontairement stable pendant toute la phase de développement du pipeline qu'une fois le pipeline validé  
* Mise en place de ChromaDB en environnement de développement  
* Scripts d'extraction pour PDF, wikis et code source  
* Paramétrage du chunking (512 tokens, chevauchement de 50 tokens)

Livrable : pipeline d'extraction fonctionnel sur un échantillon de documents.

### S6 (13/07 – 17/07) — Vectorisation et indexation

* Intégration du modèle d'embedding (bge-m3 pour le texte, embedding spécialisé pour le code)
* Génération des embeddings et stockage dans la base vectorielle
* Réindexation incrémentale par hash de contenu  
* Validation du mécanisme de réindexation en modifiant volontairement un ou deux documents du jeu de test, pour vérifier que seuls les chunks concernés sont régénérés

Livrable : corpus de test indexé sans erreur, réindexation ciblée vérifiée.

### S7 (20/07 – 24/07) — Recherche sémantique

* Recherche par similarité cosinus (top-k \= 12\)  
* Recherche hybride (similarité \+ mots-clés, fusion pondérée)  
* Re-ranking par cross-encoder

Livrable : recherche hybride fonctionnelle sur le jeu de questions test.

### S8 (27/07 – 31/08) — Indexation spécifique du code source

* Parsing structuré du code Python/XML d'Odoo (tree-sitter)  
* Découpage par unité logique (fonction, classe, vue)  
* Tests de récupération sur des questions touchant au code

Livrable : au moins 80 % des recherches retournent un passage pertinent dans les 5 premiers résultats.

### S9 (03/08 – 07/08) — Génération de réponses sourcées

* Construction du gabarit de prompt avec contexte référencé
* Extraction et citation des sources dans la réponse générée
* Mécanisme de repli si aucun passage ne dépasse le seuil de pertinence

Livrable — Jalon J2 : au moins 90 % de réponses correctement sourcées sur le jeu de test documentaire.

### S10 (10/08 – 14/08) — Cadrage de l'interrogation ERP structurée

* Inventaire des questions métier portant sur des données chiffrées (stocks, ventes, commandes)

* Définition d'un catalogue de fonctions prédéfinies sur l'ORM Odoo (ex. : obtenir un niveau de stock, obtenir un total de ventes sur une période, obtenir le statut d'une commande)

* Spécification du format d'appel de chaque fonction (paramètres attendus, modèle Odoo concerné)

Livrable : catalogue de fonctions validé avec le maître de stage avant développement.

### S11 (17/08 – 21/08) — Function calling, première implémentation

* Implémentation du mécanisme de function calling : le modèle identifie qu'une question porte sur une donnée structurée et sélectionne la fonction appropriée dans le catalogue  
* Connexion de chaque fonction à l'ORM Odoo (search, read\_group) en lecture seule  
* Tests sur des questions simples (ex. : stock d'un produit donné)

Livrable : une question simple sur une donnée ERP structurée obtient une réponse correcte issue de l'ORM, pas du RAG documentaire.

### S12 (24/08 – 28/08) — Extension du catalogue de fonctions

* Ajout des fonctions d'agrégation (totaux, moyennes, filtres par période)  
* Gestion des cas où la question combine donnée structurée et contexte documentaire (ex. : "quel est le stock du produit décrit dans cette fiche technique ?")  
* Tests sur un jeu de 15 questions ERP représentatives

Livrable : couverture des principaux types de questions métier chiffrées identifiées en S10.

### S13 (31/08 – 04/09) — Validation de l'interrogation ERP

* Tests de non-régression sur le RAG documentaire (vérifier que l'ajout du function calling ne dégrade pas les réponses déjà validées en S9)  
* Mesure du taux de réponses correctes sur le jeu de questions ERP  
* Présentation des résultats au maître de stage

Livrable — Jalon J2bis : au moins 85 % de réponses correctes sur les questions ERP structurées, sans régression sur le RAG documentaire.

### S14 (07/09 – 11/09) — Backend API unifié

* Développement du backend FastAPI avec point d'entrée unique, orchestrant à la fois le RAG documentaire et le function calling ERP  
* Documentation API (OpenAPI)

Livrable : API backend capable de router une question vers le bon mécanisme (recherche documentaire ou appel ORM) selon sa nature.

### S15 (14/09 – 18/09) — Interface web interne

* Développement de l'interface web (champ de question, indicateur de chargement, affichage de la réponse et de sa provenance — document source ou donnée ERP)  
* Connexion à l'API backend

Livrable : un utilisateur interne peut poser indifféremment une question documentaire ou une question chiffrée et recevoir une réponse cohérente.

### S16 (21/09 – 25/09) — Module Odoo, structure de base

* Création de la structure standard du module Odoo  
* Mise en place du menu d'accès à l'assistant

Livrable : module Odoo installable sur une instance de test.

### S17 (28/09 – 02/10) — Intégration Odoo / Backend

* Connexion du contrôleur Odoo à l'API backend, authentification par jeton applicatif  
* Récupération automatique de l'utilisateur Odoo courant

Livrable : un utilisateur Odoo accède à l'assistant depuis le menu sans ressaisir d'identifiants.

### S18 (05/10 – 09/10) — Cloisonnement multi-tenant

* Migration vers Qdrant, une collection par client pour le RAG documentaire  
* Restriction du function calling ERP au périmètre Odoo du client courant (chaque appel ORM est exécuté dans le contexte de l'instance Odoo de l'utilisateur, jamais sur une autre instance)

Livrable : chaque client de test dispose d'un périmètre isolé, à la fois documentaire et ERP.

### S19 (12/10 – 16/10) — Droits d'accès et journalisation

* Synchronisation des droits Odoo (res.groups, ir.rule) vers le backend, appliqués aux deux mécanismes (RAG et function calling)  
* Journalisation systématique de chaque requête, qu'elle soit documentaire ou ERP

Livrable : un utilisateur avec des droits restreints dans Odoo a les mêmes restrictions dans l'assistant, sur les deux canaux.

### S20 (19/10 – 23/10) — Tests d'intrusion et stabilisation

* Tests d'intrusion volontaires sur l'isolation multi-tenant (documentaire et ERP)
* Corrections des anomalies identifiées

Livrable — fin du développement principal : 0 fuite de donnée observée sur les tentatives d'accès croisé, système stable.

### S21 (26/10 – 30/11) — Tests de charge

* Migration vers vLLM pour la phase de charge  
* Simulation de charge (1 à 10 utilisateurs simultanés), mesure du temps de réponse et du taux d'erreur sur les deux mécanismes

Livrable : temps de réponse maintenu sous un seuil acceptable à 5 utilisateurs simultanés.

### S22 (02/11 – 06/11) — Évaluation qualité globale

* Évaluation RAGAS pour le RAG documentaire (faithfulness, context precision/recall)  
* Évaluation du taux d'exactitude pour le function calling ERP sur un jeu de questions élargi

Livrable — Jalon J3 : scores consolidés sur les deux mécanismes, présentés au maître de stage.

### S23 (09/11 – 13/11) — Documentation technique

* Rédaction de la documentation d'architecture (RAG documentaire \+ function calling ERP)  
* Procédure d'installation, de réindexation, et d'ajout d'une nouvelle fonction au catalogue ERP

Livrable : documentation technique complète couvrant les deux mécanismes.

### S24 (16/11 – 20/11) — Guide utilisateur et formation

* Rédaction du guide utilisateur illustré  
* Session de formation pratique avec l’ équipe

Livrable : équipes formées sur l'usage des deux types de questions (documentaire et ERP).

### S25 (23/11 – 27/11) — Restitution finale

* Consolidation de l'ensemble des livrables  
* Présentation finale et clôture du stage

Livrable — Jalon J4 : système jugé prêt pour un déploiement pilote chez un client.

## 4\. Jalons de validation — récapitulatif

| Jalon | Semaine | Critère mesurable |
| ----- | ----- | ----- |
| J1 | S4 | Modèle sélectionné : score ≥ 3,5/5, réponse ≤ 15 s |
| J2 | S9 | ≥ 90 % de réponses correctement sourcées (RAG documentaire) |
| J2bis | S13 | ≥ 85 % de réponses correctes sur questions ERP structurées, sans régression documentaire |
| J3 | S22 | Scores de charge et de qualité consolidés sur les deux mécanismes |
| J4 | S25 | Validation finale pour déploiement pilote |

