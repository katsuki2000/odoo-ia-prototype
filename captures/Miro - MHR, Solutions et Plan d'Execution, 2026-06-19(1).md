

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

## 2\. Pourquoi le RAG plutôt que le Fine-tuning :

| Critère | RAG | Fine-tuning |
| ----- | ----- | ----- |
| Traçabilité des réponses | Native — chaque réponse cite sa source | Aucune — impossible de savoir d'où vient l'information |
| Mise à jour des connaissances | Immédiate, ajout d'un document suffit | Nécessite un réentraînement complet |
| Coût en calcul (GPU) | Inférence uniquement | Entraînement \+ inférence, nettement plus coûteux |
| Délai de mise en œuvre | Compatible avec un stage de 6 mois | Plus long, risque de dépasser le calendrier |
| Risque d'«oubli » du modèle | Aucun (le modèle reste figé, seul l'index change) | Réel — un réentraînement mal maîtrisé peut dégrader des capacités déjà acquises |

## 3\. Difficultés à anticiper

### 3.1. Difficultés techniques

**Matériel.** Un modèle de langage, même de taille modeste (7-8 milliards de paramètres), demande une carte graphique dédiée pour fonctionner à une vitesse acceptable. 

**Qualité des données sources.** Un RAG n'est jamais meilleur que les documents qu'il indexe. Du code source non commenté, des wikis mal structurés ou des PDF scannés de mauvaise qualité dégraderont directement la pertinence des réponses, indépendamment de la qualité du modèle choisi. Une partie du travail consistera donc à nettoyer et structurer les sources avant même de parler d'intelligence artificielle.

**Indexation du code source.** Contrairement à un document texte classique, le code source d'Odoo (Python, XML) a une structure logique propre (fonctions, classes, règles métier) qu'un découpage en texte brut ne respecte pas. Il faut un traitement spécifique pour que l'assistant puisse répondre correctement à une question comme "où est défini ce workflow ?".

**Interrogation des données métier structurées.** un modèle de langage qui tente de "deviner" une réponse chiffrée à partir de texte vectorisé produira des résultats faux sans que l'erreur soit visible. La solution consiste à donner au modèle un accès encadré à un ensemble prédéfini d'opérations sur l'ERP (consulter un stock, calculer un total sur une période), plutôt que de le laisser improviser une requête. 

### 3.2. Difficultés organisationnelles

**Isolation entre clients (multi-tenant).** aucune information d'un client ne doit jamais être accessible à un autre — y compris en cas d'erreur de configuration. C'est une exigence de sécurité non négociable qui doit être pensée dès l'architecture, pas ajoutée après coup.

**Cloisonnement des accès en interne.** Même au sein de MiroKE, un employé du support ne doit pas nécessairement avoir accès à toutes les informations consultées par un développeur, ou inversement.

**Adoption par les équipes.** Un outil, même techniquement excellent, échoue s'il n'est pas adopté. La qualité des premières réponses conditionnera la confiance des utilisateurs — d'où l'importance d'un jeu de test exigeant dès les premières semaines.

**Latence du pipeline complet.** Le temps de réponse perçu par l'utilisateur ne se limite pas au temps d'inférence du LLM : il inclut le routage de la question, la recherche vectorielle, le re-ranking éventuel, l'appel ORM si nécessaire, et la mise en forme de la réponse. Un budget de latence de bout en bout (objectif : ≤ 20 secondes pour le pipeline complet, contre ≤ 15 secondes pour le LLM seul mesuré en S4) doit être défini et suivi dès les premiers tests d'intégration.

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

Lorsqu'un utilisateur pose une question, le système analyse d'abord sa nature : s'agit-il d'une question documentaire (qui sera traitée par recherche sémantique dans la base vectorielle) ou d'une question portant sur une donnée chiffrée (qui sera traitée par l'appel d'une fonction du catalogue ERP) ? Dans les deux cas, le résultat — passages documentaires ou donnée ERP récupérée — est transmis au modèle de langage local, qui formule la réponse finale en citant sa source exacte : un document pour le premier cas, la donnée ERP interrogée pour le second.

Le routage est modélisé comme un graphe à arêtes conditionnelles (LangGraph), ce qui permet d'ajouter de nouvelles branches de traitement sans restructurer le pipeline existant.

### 1.4. Mémoire conversationnelle.

Un utilisateur posera naturellement des questions de suivi (ex. : « Et l'année dernière ? » après une question sur les ventes de l'année en cours). Sans mémoire conversationnelle, le système traiterait chaque message comme une question isolée et ne saurait pas résoudre les pronoms ou les références implicites.

Le système conserve les 5 derniers échanges (questions + réponses) de la session en cours. Ce contexte est injecté dans le prompt envoyé au LLM à chaque nouvelle question, lui permettant de résoudre les références implicites. La limite à 5 échanges est un compromis entre la qualité du suivi conversationnel et la taille de la fenêtre de contexte des modèles 7-8B (typiquement 8 192 à 32 768 tokens). Ce mécanisme est intégré nativement dans l'architecture LangGraph retenue (`MessagesState`).

### 1.5. Propagation de l'identité utilisateur (RBAC passthrough).

Le respect des droits d'accès Odoo (`res.groups`, `ir.rule`) est une exigence fondamentale du système. Pour qu'il soit effectif, l'identité de l'utilisateur courant doit traverser toute la chaîne de traitement, sans rupture :

| Étape | Donnée propagée |
| ----- | ----- |
| Module Odoo → API FastAPI | `uid` de l'utilisateur Odoo, transmis via le jeton d'authentification |
| API FastAPI → Outils ORM | Chaque appel XML-RPC utilise le `uid` de l'utilisateur, jamais un compte administrateur générique |
| API FastAPI → RAG documentaire | Le `uid` détermine quels documents sont accessibles (filtrage par collection client en multi-tenant) |

Si le backend utilisait un compte administrateur unique pour interroger l'ORM, il contournerait l'intégralité des règles d'accès Odoo — rendant le cloisonnement inopérant. Cette contrainte est intégrée dès la conception de l'API (S14), pas ajoutée après coup.

### 1.6. Comportement de repli (fallback).

Trois situations de repli sont identifiées et traitées explicitement :

| Situation | Comportement du système |
| ----- | ----- |
| La question ne relève ni du RAG documentaire ni du function calling (ex. : « Raconte-moi une blague ») | Le système indique poliment qu'il est spécialisé dans les questions relatives à l'ERP et invite l'utilisateur à reformuler |
| Le RAG documentaire ne trouve aucun passage au-dessus du seuil de pertinence | Le système indique qu'il n'a pas trouvé de source fiable pour répondre, plutôt que d'inventer une réponse |
| Un appel ORM échoue (serveur Odoo indisponible, erreur de droits) | Le système retourne un message d'erreur explicite (ex. : « Impossible de contacter le serveur Odoo ») sans tenter de deviner la réponse |

Dans tous les cas, le système ne fabrique jamais une réponse sans source vérifiable.

### 1.7. Garde-fous de sécurité.

**Politique strictement en lecture seule.** Le catalogue de fonctions ERP n'expose que des opérations de lecture (`search_read`, `read_group`, `fields_get`). Aucune fonction de création, modification ou suppression (`create`, `write`, `unlink`) n'est accessible à l'agent, même en cas d'injection de prompt malveillante.

**Liste blanche de modèles Odoo.** Seuls les modèles Odoo explicitement autorisés (ex. : `sale.order`, `account.move`, `stock.quant`, `helpdesk.ticket`) peuvent être interrogés par les outils. Toute tentative d'accès à un modèle non autorisé (ex. : `res.users`, `ir.module.module`) est bloquée avant l'exécution de la requête.

**Limite d'itérations de l'agent.** Le cycle de raisonnement de l'agent (réflexion → action → observation) est limité à 6 itérations maximum. Si l'agent n'a pas produit de réponse après 6 cycles, il s'arrête et retourne un message d'erreur explicite, évitant toute boucle infinie et toute consommation excessive de ressources.

### 1.8. Format de sortie structuré.

Pour garantir la citation systématique des sources — exigence centrale du système — la réponse du LLM est contrainte par un schéma de sortie structuré (Pydantic), et non par simple instruction dans le prompt :

```python
class SourceReference(BaseModel):
    type: Literal["document", "code", "erp_data"]
    source: str          # ex. : "account/models/account_move.py"
    detail: str          # ex. : "lignes 45-89, méthode _post()"

class AssistantResponse(BaseModel):
    answer: str
    sources: List[SourceReference]
    confidence: Literal["high", "medium", "low"]
```

Ce format est plus fiable que le prompt engineering seul, en particulier avec des modèles de 7-8B paramètres qui ne suivent pas toujours les consignes de formatage libre.

## 2\. Stack technique
| Couche | Outil retenu | Pourquoi ce choix |
| ----- | ----- | ----- |
| **Modèle de langage (RAG documentaire)** | Mistral 7B (Q4) | Particulièrement performant en français, léger (6 Go VRAM), bien adapté à la génération de réponses textuelles sourcées |
| **Modèle de langage (function calling)** | Hermes 3 8B (Q4) | Fine-tuné spécifiquement pour le tool-use et le function calling structuré — capacité critique pour le routage et l'appel ORM ; les deux modèles tiennent simultanément en VRAM sur une RTX 3060 (12 Go), ou un seul modèle peut être retenu si les tests comparatifs (S4) montrent qu'il couvre les deux usages |
| **Modèle d'embedding** | nomic-ai/nomic-embed-text-v1.5 | Multilingue (bon support du français), supporte le texte et le code dans un même espace vectoriel, léger (~550 Mo), fonctionne sur CPU et GPU ; un seul modèle d'embedding pour les deux types de contenu (documents et code) simplifie l'architecture — la séparation en deux collections distinctes sera envisagée uniquement si les tests de recherche (S7) montrent une dégradation mesurable |
| **Orchestration** | LangChain + LangGraph | LangChain fournit les abstractions de base (prompts, retrievers, outils) ; LangGraph modélise le flux de requête comme un graphe à arêtes conditionnelles (routage documentaire / ERP), gère nativement la mémoire conversationnelle (`MessagesState`) et la limite d'itérations de l'agent — choix préféré à LlamaIndex car mieux documenté pour le function calling et le routage conditionnel |
| **Base vectorielle** | ChromaDB en développement → Qdrant en production | ChromaDB est rapide à mettre en place pour les tests ; Qdrant prend le relais en production car il supporte nativement l'isolation entre plusieurs clients (multi-tenant) |
| **Serveur d'inférence** | Ollama en développement → vLLM en production | Ollama permet de tester rapidement plusieurs modèles ; vLLM est conçu pour tenir la charge avec plusieurs utilisateurs simultanés |
| **Interface utilisateur** | Application web interne \+ module Odoo dédié | Un seul point d'entrée technique (API), deux façades différentes selon que l'utilisateur est interne à MiroKE ou employé d'un client |
| **Interrogation ERP structuré** | Function calling sur l'ORM Odoo (catalogue de fonctions prédéfinies, lecture seule) | Respecte nativement les droits Odoo (res.groups, ir.rule), évite la génération libre de requêtes risquées ; politique strictement en lecture seule (search_read, read_group) — aucune opération d'écriture n'est exposée à l'agent |

### Métadonnées d'extensibilité
Chaque chunk indexé dans la base vectorielle porte une métadonnée `odoo_version: "17"`. Ce champ, inutilisé dans le prototype, prépare l'extension future du système à d'autres versions d'Odoo sans réindexation complète — un argument commercial pour la proposition de valeur à long terme auprès des clients MiroKE.

### Infrastructure et coûts

| Composant | Développement (Codespaces) | Production (machine MiroKE) |
| ----- | ----- | ----- |
| **LLM** | API Groq (gratuit, tier free — Llama 3.1 8B) | Ollama / vLLM sur GPU local |
| **GPU** | Aucun (inférence cloud) | 1× RTX 3060 12 Go (déjà identifiée) |
| **Embedding** | CPU Codespaces (~550 Mo RAM) | GPU local ou CPU serveur |
| **Base vectorielle** | ChromaDB (fichier local) | Qdrant (conteneur Docker) |
| **Coût récurrent** | 0 € (Groq free tier + GitHub Codespaces gratuit) | Électricité serveur uniquement |

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

## 3\. Détail jour par jour

> **Convention** : chaque journée est décrite par sa tâche principale. Les tâches transversales (rédaction du mémoire, résolution de bugs rencontrés la veille) sont implicites et occupent les temps morts. Le vendredi de chaque semaine inclut systématiquement un temps de revue, consolidation et documentation de ce qui a été produit.

---

### S3 (22/06 – 26/06) — Installation de l'environnement

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 22/06 | Installation d'Ubuntu Server sur le matériel validé. Partitionnement disque, configuration réseau, accès SSH. | Machine accessible en SSH depuis le réseau MiroKE |
| Mar 23/06 | Installation des drivers GPU NVIDIA (CUDA toolkit) et vérification avec `nvidia-smi`. Installation de Docker et Docker Compose. | `nvidia-smi` affiche la RTX 3060, Docker fonctionne |
| Mer 24/06 | Installation d'Ollama. Téléchargement des modèles candidats : Mistral 7B Q4, Hermes 3 8B Q4, Llama 3.1 8B Q4, Phi-3.5 Mini Q4. | `ollama run mistral` répond sans erreur |
| Jeu 25/06 | Installation de l'environnement Python (3.11+, venv). Installation des dépendances du projet (`requirements.txt` : LangChain, LangGraph, ChromaDB, FastAPI, etc.). | `python -c "import langchain; import chromadb"` passe sans erreur |
| Ven 26/06 | Test de fumée : script Python qui appelle chaque modèle via Ollama et mesure le temps de réponse brut. Documentation de la configuration dans le README. | Chaque modèle répond en < 30 s. README mis à jour |

Livrable de la semaine : environnement local opérationnel, les 4 modèles candidats se lancent sans erreur.

---

### S4 (29/06 – 03/07) — Tests comparatifs des modèles et constitution du jeu de test

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 29/06 | Rédaction du jeu de test : 10 questions documentaires (PDF, wikis) + 8 questions code source. Pour chaque question : réponse attendue, source de référence, type de traitement. | Fichier `tests/benchmark_questions.json` — 18 premières questions |
| Mar 30/06 | Rédaction du jeu de test (suite) : 8 questions ERP chiffrées + 4 questions hors périmètre (repli). Revue complète des 30 questions pour cohérence. | `benchmark_questions.json` complet — 30 questions |
| Mer 01/07 | Benchmark Mistral 7B et Hermes 3 8B : chaque modèle répond aux 30 questions. Mesure : temps de réponse, tokens/s, VRAM consommée, score qualitatif (1-5) noté manuellement. | Tableau comparatif Mistral vs Hermes 3 rempli |
| Jeu 02/07 | Benchmark Llama 3.1 8B et Phi-3.5 Mini : même protocole. Test spécifique Hermes 3 sur le function calling (capacité à produire un appel d'outil structuré). | Tableau comparatif complet, 4 modèles |
| Ven 03/07 | Analyse des résultats, sélection du ou des modèles retenus. Rédaction du rapport de benchmark (tableau + justification). Versionnement du jeu de test dans Git. | **Jalon J1** livré |

Livrable de la semaine — **Jalon J1** : modèle(s) sélectionné(s) sur preuve mesurée (score ≥ 3,5/5, réponse ≤ 15 s). Jeu de test de référence versionné.

---

### S5 (06/07 – 10/07) — Extraction des documents et chunking

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 06/07 | Constitution du jeu de documents de test : sélection de 3-4 PDF représentatifs, 2-3 pages wiki (texte brut), 1 module Odoo complet (Python + XML). Copie dans `fake_data/`. | Dossier `fake_data/` complet et stable |
| Mar 07/07 | Installation et configuration de ChromaDB. Création de la collection unique. Écriture de `vectorstore/chroma_manager.py` : initialisation de la collection, fonctions `add_chunks()` et `get_collection_stats()`. | `chroma_manager.py` fonctionnel, collection créée |
| Mer 08/07 | Écriture de `ingestion/pdf_loader.py` : chargement des PDF via `pypdf`, chunking avec `RecursiveCharacterTextSplitter` (512 tokens, chevauchement 50 tokens). Extraction des métadonnées (source, type, module, odoo_version, content_hash). | PDFs chunkés avec métadonnées complètes |
| Jeu 09/07 | Écriture du chunking code Python : `RecursiveCharacterTextSplitter.from_language(Language.PYTHON)`. Extraction des métadonnées enrichies (class, function, lines). Écriture du chunking XML : découpage par `<record>` et `<template>`. | Code Python et XML chunkés correctement |
| Ven 10/07 | Écriture du loader wiki (texte brut / HTML). Test d'intégration : ingestion complète du jeu de test dans ChromaDB. Vérification que `get_collection_stats()` retourne le bon nombre de chunks avec les bonnes métadonnées. | Pipeline d'extraction complet, tous les documents ingérés |

Livrable de la semaine : pipeline d'extraction fonctionnel sur l'échantillon de documents, avec métadonnées complètes sur chaque chunk.

---

### S6 (13/07 – 17/07) — Vectorisation et indexation

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 13/07 | Intégration de `nomic-ai/nomic-embed-text-v1.5` : téléchargement du modèle, configuration dans `chroma_manager.py` comme fonction d'embedding par défaut. Test unitaire : vérifier que deux phrases similaires en français ont une similarité cosinus > 0.8. | Modèle d'embedding fonctionnel, test unitaire passe |
| Mar 14/07 | Génération des embeddings pour l'ensemble du corpus de test. Stockage dans ChromaDB. Mesure du temps d'indexation et de la taille résultante sur disque. | Corpus complet indexé, métriques notées |
| Mer 15/07 | Implémentation de la réindexation incrémentale : comparaison par `content_hash` — si le hash d'un chunk existe déjà, il n'est pas réindexé. Écriture de la fonction `reindex_if_changed()`. | Fonction de réindexation incrémentale opérationnelle |
| Jeu 16/07 | Validation de la réindexation : modifier 2 documents du jeu de test, relancer l'ingestion, vérifier que seuls les chunks modifiés sont régénérés (les autres restent intacts). Logs détaillés. | Test de réindexation documenté, logs montrant la sélectivité |
| Ven 17/07 | Écriture de tests automatisés pour l'indexation (`tests/test_indexation.py`). Documentation du pipeline d'indexation dans le README. | Tests automatisés passent, documentation à jour |

Livrable de la semaine : corpus de test indexé sans erreur, réindexation ciblée vérifiée.

---

### S7 (20/07 – 24/07) — Recherche sémantique

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 20/07 | Implémentation de la recherche par similarité cosinus dans `rag/pipeline.py` : fonction `retrieve(query, top_k=12)` qui interroge ChromaDB et retourne les chunks les plus proches. Test sur 5 questions du jeu de test. | Recherche vectorielle de base fonctionnelle |
| Mar 21/07 | Implémentation de la recherche par mots-clés (BM25) en parallèle de la recherche vectorielle. Écriture de la fusion pondérée (Reciprocal Rank Fusion) combinant les deux scores. | Recherche hybride fonctionnelle |
| Mer 22/07 | Intégration d'un cross-encoder pour le re-ranking des résultats fusionnés. Choix du modèle cross-encoder (ex. : `cross-encoder/ms-marco-MiniLM-L-6-v2`). Mesure de l'impact sur la précision. | Re-ranking fonctionnel, amélioration mesurée |
| Jeu 23/07 | Évaluation systématique sur les 18 questions documentaires et code du jeu de test : pour chaque question, noter si le passage pertinent apparaît dans le top-5. Calcul du recall@5. | Rapport de recall@5, identification des cas d'échec |
| Ven 24/07 | Ajustement des paramètres (top-k, poids de fusion, seuil de pertinence) pour maximiser le recall@5. Documentation des paramètres retenus. | Paramètres optimisés, recall@5 ≥ 80 % |

Livrable de la semaine : recherche hybride fonctionnelle sur le jeu de questions test.

---

### S8 (27/07 – 31/07) — Indexation spécifique du code source

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 27/07 | Enrichissement des métadonnées code : script qui parcourt chaque chunk Python et extrait automatiquement le nom de classe, le nom de fonction et le docstring via l'AST Python (`ast.parse`). Mise à jour des chunks dans ChromaDB. | Métadonnées code enrichies dans ChromaDB |
| Mar 28/07 | Optimisation de l'indexation XML Odoo : découpage par `<record>` et `<template>`, extraction de l'attribut `id` et du modèle cible comme métadonnées. Indexation des fichiers `__manifest__.py`. | Chunks XML avec métadonnées structurées |
| Mer 29/07 | Indexation des fichiers de sécurité Odoo (`security/ir.model.access.csv`) et des fichiers de données (`data/*.xml`). Ces fichiers contiennent les règles d'accès — essentiels pour les questions de type "qui peut faire quoi ?". | Fichiers de sécurité et de données indexés |
| Jeu 30/07 | Tests de récupération sur les 8 questions code du jeu de test. Pour chaque question : le bon fichier et la bonne fonction apparaissent-ils dans le top-5 ? Identification des confusions entre chunks texte et chunks code. | Rapport de recall@5 spécifique au code |
| Ven 31/07 | Décision empirique : si confusion texte/code constatée → créer deux collections ChromaDB séparées et retester. Sinon, documenter le résultat et conserver la collection unique. | Décision documentée, recall@5 code ≥ 80 % |

Livrable de la semaine : au moins 80 % des recherches code retournent un passage pertinent dans les 5 premiers résultats.

---

### S9 (03/08 – 07/08) — Génération de réponses sourcées

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 03/08 | Construction du graphe LangGraph linéaire : nœud d'entrée → nœud de recherche (appelle la recherche hybride de S7) → nœud de génération (envoie contexte + question au LLM) → nœud de sortie. Test de bout en bout sur 3 questions. | Pipeline LangGraph linéaire fonctionnel |
| Mar 04/08 | Implémentation du schéma de sortie structuré Pydantic (`AssistantResponse` + `SourceReference`, cf. section 1.8). Le nœud de génération produit une réponse JSON structurée au lieu de texte libre. | Sortie structurée avec sources citées |
| Mer 05/08 | Intégration de la mémoire conversationnelle : ajout de `MessagesState` au graphe LangGraph. Les 5 derniers échanges sont automatiquement injectés dans le contexte. Test avec des questions de suivi (ex. : "Et l'année dernière ?"). | Mémoire conversationnelle fonctionnelle |
| Jeu 06/08 | Implémentation du mécanisme de repli : si aucun chunk ne dépasse le seuil de pertinence (score < 0.3), le système retourne un message explicite ("Je n'ai pas trouvé de source fiable pour répondre à cette question"). Test sur les 4 questions hors périmètre. | Repli fonctionnel, pas de réponse inventée |
| Ven 07/08 | Évaluation sur les 18 questions documentaires/code + 4 questions de repli du jeu de test. Pour chaque réponse : vérifier la présence d'au moins un `SourceReference` vérifiable. Calcul du taux de réponses sourcées. | **Jalon J2** : ≥ 90 % de réponses correctement sourcées |

Livrable de la semaine — **Jalon J2** : au moins 90 % de réponses correctement sourcées sur le jeu de test documentaire.

---

### S10 (10/08 – 14/08) — Cadrage de l'interrogation ERP structurée

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 10/08 | Inventaire des questions métier ERP à partir des 8 questions chiffrées du jeu de test + discussion avec l'équipe MiroKE pour identifier les questions les plus fréquentes des clients. | Liste de 15-20 questions ERP classées par fréquence |
| Mar 11/08 | Regroupement des questions en catégories fonctionnelles : ventes (`sale.order`), factures (`account.move`), stocks (`stock.quant`), tickets (`helpdesk.ticket`). Pour chaque catégorie, identifier les opérations ORM nécessaires. | Matrice questions → modèles Odoo → opérations ORM |
| Mer 12/08 | Rédaction du catalogue de fonctions : pour chaque fonction, spécifier le nom, la description en français, les paramètres (nom, type, description), le modèle Odoo cible, et l'opération ORM (`search_read` ou `read_group`). Maximum 10-12 fonctions. | Catalogue de fonctions au format JSON/YAML |
| Jeu 13/08 | Rédaction de la liste blanche de modèles Odoo autorisés. Définition de la politique de sécurité : quels modèles, quelles opérations, quels champs. Rédaction des garde-fous (aucune opération d'écriture, blocage des modèles non autorisés). | Politique de sécurité documentée |
| Ven 14/08 | Présentation du catalogue au maître de stage. Ajustements selon retours. Versionnement du catalogue dans Git. | Catalogue validé par le maître de stage |

Livrable de la semaine : catalogue de fonctions validé avec le maître de stage avant développement.

---

### S11 (17/08 – 21/08) — Function calling, première implémentation

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 17/08 | Écriture des 3-4 premières fonctions ORM dans `tools/odoo_tools.py` : `obtenir_stock_produit()`, `obtenir_total_ventes()`, `obtenir_statut_commande()`. Chaque fonction est décorée en outil LangChain (`@tool`) avec description en français et ≤ 3 paramètres. | 3-4 outils LangChain fonctionnels |
| Mar 18/08 | Connexion des outils à l'ORM Odoo via XML-RPC (`xmlrpc.client`). Test unitaire : chaque outil retourne des données correctes depuis l'instance Odoo de test. Vérification que seuls `search_read` et `read_group` sont utilisés (lecture seule). | Outils connectés à Odoo, tests unitaires passent |
| Mer 19/08 | Ajout de l'arête conditionnelle dans le graphe LangGraph : le nœud de routage dirige vers le nœud d'appel ORM si la question porte sur une donnée chiffrée. Binding des outils au LLM via `llm.bind_tools()`. Configuration de `recursion_limit=6`. | Routage RAG/ORM fonctionnel dans le graphe |
| Jeu 20/08 | Implémentation de la résolution de paramètres : le nom naturel du client ("Rakoto") est recherché dans `res.partner` pour retrouver l'ID exact. En cas d'ambiguïté (plusieurs correspondances), le système demande une précision. | Résolution de paramètres fonctionnelle |
| Ven 21/08 | Tests sur les 8 questions ERP du jeu de test. Vérification que le routage est correct (question ERP → outils ORM, question documentaire → RAG). Mesure du taux de réponses correctes. | Routage correct, premières réponses ERP justes |

Livrable de la semaine : une question simple sur une donnée ERP structurée obtient une réponse correcte issue de l'ORM, pas du RAG documentaire.

---

### S12 (24/08 – 28/08) — Extension du catalogue de fonctions

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 24/08 | Ajout des fonctions d'agrégation : `obtenir_total_factures()` (via `read_group` sur `account.move`), `obtenir_moyenne_ventes()`. Vérification que PostgreSQL effectue le calcul, pas le LLM. | Fonctions d'agrégation opérationnelles |
| Mar 25/08 | Ajout des fonctions de filtrage temporel : chaque outil accepte un paramètre `periode` ("ce mois", "ce trimestre", "cette année") traduit en plage de dates. Écriture de la fonction utilitaire `parse_period()`. | Filtrage temporel fonctionnel |
| Mer 26/08 | Gestion des questions hybrides (donnée structurée + contexte documentaire) : le graphe LangGraph peut chaîner un appel RAG puis un appel ORM si nécessaire. Test : "Quel est le stock du produit décrit dans cette fiche technique ?" | Chaînage RAG + ORM fonctionnel |
| Jeu 27/08 | Constitution d'un jeu de 15 questions ERP élargi (au-delà des 8 initiales). Tests systématiques : chaque question doit obtenir une réponse chiffrée correcte vérifiable manuellement. | 15 questions ERP testées, résultats documentés |
| Ven 28/08 | Revue du catalogue complet : nombre total d'outils ≤ 15, descriptions en français relues, paramètres simplifiés. Ajustements si le LLM choisit mal certaines fonctions. | Catalogue stabilisé, ≤ 15 outils |

Livrable de la semaine : couverture des principaux types de questions métier chiffrées identifiées en S10.

---

### S13 (31/08 – 04/09) — Validation de l'interrogation ERP

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 31/08 | Tests de non-régression sur le RAG documentaire : relancer les 18 questions documentaires/code du jeu de test et comparer les résultats à ceux obtenus en S9. Aucune dégradation acceptable. | Rapport de non-régression RAG |
| Mar 01/09 | Tests d'exactitude ERP : pour chaque question ERP, comparer la réponse de l'agent au résultat obtenu par requête ORM manuelle. Calcul du taux d'exactitude. | Taux d'exactitude ERP mesuré |
| Mer 02/09 | Tests de routage : pour les 30 questions du jeu de test, vérifier que chaque question est dirigée vers le bon mécanisme (RAG, ORM, repli). Calcul du taux de routage correct. | Taux de routage mesuré (objectif ≥ 90 %) |
| Jeu 03/09 | Tests de la mémoire conversationnelle avec des scénarios ERP : "Combien de ventes pour Rakoto cette année ?" → "Et l'année dernière ?" → "Quel est son plus gros achat ?". 5 scénarios multi-tours. | 5 scénarios multi-tours documentés |
| Ven 04/09 | Consolidation des résultats, rédaction du rapport de validation. Présentation au maître de stage. | **Jalon J2bis** livré, résultats présentés |

Livrable de la semaine — **Jalon J2bis** : au moins 85 % de réponses correctes sur les questions ERP structurées, sans régression sur le RAG documentaire.

---

### S14 (07/09 – 11/09) — Backend API unifié

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 07/09 | Structure de base de `api/main.py` : application FastAPI, endpoint `POST /api/v1/ask` acceptant `{question, session_id, user_uid}`. Connexion au graphe LangGraph comme moteur de traitement. | Endpoint `/ask` fonctionnel en local |
| Mar 08/09 | Propagation du `uid` : le middleware FastAPI extrait le `uid` du jeton d'authentification et l'injecte dans le contexte LangGraph. Chaque appel ORM utilise ce `uid` — vérification qu'un `uid` non-admin ne voit pas les données admin. | RBAC passthrough vérifié |
| Mer 09/09 | Mesure et journalisation de la latence : chaque requête est chronométrée (routage, recherche, génération, total). Log structuré au format JSON. Endpoint `GET /api/v1/health` pour le monitoring. | Logs de latence, health check fonctionnel |
| Jeu 10/09 | Gestion des erreurs : codes HTTP appropriés (400 question vide, 401 uid invalide, 503 Odoo indisponible). Réponses d'erreur au format `AssistantResponse` avec `confidence: "low"`. | Gestion d'erreurs complète |
| Ven 11/09 | Documentation API automatique (OpenAPI/Swagger). Tests d'intégration : 10 questions via `curl` ou Postman, vérification des réponses et de la latence (objectif ≤ 20 s). | Documentation OpenAPI, latence ≤ 20 s |

Livrable de la semaine : API backend opérationnelle avec propagation de l'identité utilisateur et respect du budget de latence.

---

### S15 (14/09 – 18/09) — Interface web interne

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 14/09 | Maquette de l'interface : champ de saisie, zone de réponse, indicateur de chargement, panneau latéral pour les sources citées. Design sobre adapté à un usage professionnel interne. | Maquette validée (HTML/CSS statique) |
| Mar 15/09 | Implémentation du frontend : formulaire de question, appel `fetch()` vers `POST /api/v1/ask`, affichage de la réponse. Indicateur de chargement pendant l'attente. | Interface fonctionnelle, réponses affichées |
| Mer 16/09 | Affichage structuré des sources : chaque `SourceReference` est affiché sous la réponse avec un lien cliquable (fichier, lignes, type). Indicateur de confiance visuel (high/medium/low). | Sources cliquables, confiance affichée |
| Jeu 17/09 | Historique conversationnel : affichage des messages précédents dans un fil de discussion. Le `session_id` est maintenu côté client pour la mémoire conversationnelle. | Historique de conversation visible |
| Ven 18/09 | Tests utilisateur internes : 2-3 collègues testent l'interface avec des questions libres. Collecte des retours, corrections des irritants majeurs. | Retours utilisateurs collectés, corrections appliquées |

Livrable de la semaine : un utilisateur interne peut poser indifféremment une question documentaire ou chiffrée et recevoir une réponse cohérente.

---

### S16 (21/09 – 25/09) — Module Odoo, structure de base

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 21/09 | Création de la structure standard du module Odoo : `__manifest__.py`, `__init__.py`, `models/`, `controllers/`, `views/`, `security/`, `static/`. Déclaration du module dans le manifest. | Structure de module Odoo valide |
| Mar 22/09 | Création du modèle `miro.ai.settings` : champs de configuration (URL de l'API backend, jeton d'authentification, booléens d'activation des compétences). Vue formulaire dans les paramètres Odoo. | Page de configuration dans Odoo |
| Mer 23/09 | Création du menu d'accès à l'assistant dans Odoo. Vue initiale : un simple champ de texte et un bouton "Demander". Pour l'instant, pas de connexion au backend — juste l'UI. | Menu et vue accessibles dans Odoo |
| Jeu 24/09 | Installation du module sur l'instance Odoo de test (Docker). Vérification que le module s'installe sans erreur, que le menu apparaît, et que la page de configuration est accessible. | Module installé sur Odoo de test |
| Ven 25/09 | Tests de base : vérifier les droits d'accès (`ir.model.access.csv`) — seuls les utilisateurs du groupe "MIRO AI User" voient le menu. Documentation de la procédure d'installation. | Droits d'accès configurés, documentation écrite |

Livrable de la semaine : module Odoo installable sur une instance de test.

---

### S17 (28/09 – 02/10) — Intégration Odoo / Backend

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 28/09 | Écriture du contrôleur Odoo (`controllers/main.py`) : endpoint interne qui reçoit la question de l'utilisateur et appelle l'API FastAPI via `requests.post()`. Transmission du `uid`, `groups` et `company_id`. | Contrôleur Odoo → API FastAPI fonctionnel |
| Mar 29/09 | Authentification : le contrôleur Odoo génère un jeton applicatif (JWT ou token simple) contenant le `uid` et les groupes de l'utilisateur courant. Le backend FastAPI valide ce jeton avant de traiter la requête. | Authentification par jeton opérationnelle |
| Mer 30/09 | Contrôle granulaire des compétences : lecture des booléens de configuration (`activer_ventes`, `activer_stocks`, `activer_comptabilite`, `activer_tickets`). Transmission au backend, qui filtre les outils passés à `llm.bind_tools()` en conséquence. | Activation/désactivation des compétences fonctionnelle |
| Jeu 01/10 | Conversion Markdown → HTML : écriture d'une fonction utilitaire qui convertit la réponse Markdown du LLM en HTML compatible Odoo Discuss (gras, italique, listes, blocs de code). Protection XSS via `html.escape`. | Réponses formatées correctement dans Odoo |
| Ven 02/10 | Tests d'intégration de bout en bout : un utilisateur Odoo pose une question depuis le module, reçoit une réponse formatée avec sources, le tout sans ressaisir d'identifiants. Test avec compétences activées/désactivées. | Intégration Odoo complète, démo fonctionnelle |

Livrable de la semaine : un utilisateur Odoo accède à l'assistant depuis le menu sans ressaisir d'identifiants, avec un contrôle administrateur sur les compétences activées.

---

### S18 (05/10 – 09/10) — Cloisonnement multi-tenant

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 05/10 | Installation de Qdrant (conteneur Docker). Migration de la logique `chroma_manager.py` vers un nouveau `qdrant_manager.py` : mêmes interfaces, backend différent. | Qdrant opérationnel, manager écrit |
| Mar 06/10 | Création d'une collection par client de test (ex. : `client_alpha`, `client_beta`). Réingestion des documents de test dans les collections séparées. | Collections par client créées et remplies |
| Mer 07/10 | Modification du pipeline LangGraph : le `company_id` de l'utilisateur courant détermine quelle collection Qdrant est interrogée. Vérification qu'un utilisateur de `client_alpha` ne voit jamais les documents de `client_beta`. | Isolation documentaire vérifiée |
| Jeu 08/10 | Restriction du function calling : chaque appel ORM est exécuté dans le contexte de l'instance Odoo du client courant. Si le client n'a pas d'instance Odoo distincte, filtrage par `company_id` dans les requêtes ORM. | Isolation ERP vérifiée |
| Ven 09/10 | Tests croisés : avec deux utilisateurs de clients différents, poser les mêmes questions et vérifier que chacun ne voit que ses données. Documentation du mécanisme d'isolation. | Tests croisés passent, 0 fuite |

Livrable de la semaine : chaque client de test dispose d'un périmètre isolé, à la fois documentaire et ERP.

---

### S19 (12/10 – 16/10) — Droits d'accès et journalisation

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 12/10 | Synchronisation des groupes Odoo (`res.groups`) : le backend récupère les groupes de l'utilisateur via le `uid` et détermine quelles fonctions ORM sont accessibles. Ex. : un utilisateur du groupe "Ventes / Utilisateur" ne peut pas accéder aux fonctions comptables. | Filtrage par groupes fonctionnel |
| Mar 13/10 | Synchronisation des règles d'accès (`ir.rule`) : les règles de domaine Odoo sont appliquées automatiquement via l'ORM (puisque l'appel utilise le `uid` de l'utilisateur). Vérification avec un utilisateur restreint. | Règles d'accès effectives |
| Mer 14/10 | Implémentation de la journalisation : chaque requête est loguée dans une table dédiée (`miro.ai.log`) avec : timestamp, `uid`, question posée, mécanisme utilisé (RAG/ORM/repli), temps de réponse, résumé de la réponse. | Table de logs créée, logs enregistrés |
| Jeu 15/10 | Vue liste des logs dans le module Odoo : un administrateur peut consulter l'historique des questions posées à l'assistant, filtrées par utilisateur, par date, par mécanisme. | Vue des logs accessible dans Odoo |
| Ven 16/10 | Tests avec 3 profils utilisateurs distincts (admin, commercial, support) : vérifier que chacun a accès uniquement aux données autorisées par ses groupes et règles Odoo. | 3 profils testés, restrictions respectées |

Livrable de la semaine : un utilisateur avec des droits restreints dans Odoo a les mêmes restrictions dans l'assistant, sur les deux canaux.

---

### S20 (19/10 – 23/10) — Tests d'intrusion et stabilisation

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 19/10 | Tests d'intrusion multi-tenant (RAG) : tenter d'accéder aux documents d'un autre client en manipulant le `company_id` dans la requête API, en forgeant un jeton, en injectant des métadonnées dans la question. | Rapport d'intrusion RAG, 0 fuite attendue |
| Mar 20/10 | Tests d'intrusion multi-tenant (ORM) : tenter d'interroger les données d'un autre client en modifiant les paramètres d'un outil ORM. Tenter d'appeler un modèle non autorisé (ex. : `res.users`). | Rapport d'intrusion ORM, 0 fuite attendue |
| Mer 21/10 | Tests d'injection de prompt : soumettre des questions malveillantes tentant de faire ignorer les instructions système, d'appeler des fonctions d'écriture, ou de révéler le prompt système. Documenter les résultats. | Rapport d'injection de prompt |
| Jeu 22/10 | Correction des anomalies identifiées lors des tests d'intrusion. Renforcement des garde-fous si nécessaire (validation supplémentaire côté backend, filtrage plus strict). | Anomalies corrigées |
| Ven 23/10 | Relance complète de tous les tests (régression, intrusion, isolation). Rédaction du rapport de sécurité final. | Rapport de sécurité final, système stable |

Livrable de la semaine — fin du développement principal : 0 fuite de donnée observée sur les tentatives d'accès croisé, système stable.

---

### S21 (26/10 – 30/10) — Tests de charge

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 26/10 | Installation et configuration de vLLM sur la machine de production. Migration de la configuration LLM : remplacer Ollama par vLLM comme backend d'inférence. Vérification que le pipeline fonctionne identiquement. | vLLM opérationnel, pipeline inchangé |
| Mar 27/10 | Test de charge à 1 utilisateur : mesure de la latence du pipeline complet (routage + recherche + génération + mise en forme) sur 30 questions. Objectif : ≤ 20 secondes par question. | Latence à 1 utilisateur mesurée |
| Mer 28/10 | Test de charge à 3 utilisateurs simultanés (via `locust` ou script parallèle) : mesure du temps de réponse moyen, du p95, et du taux d'erreur. | Métriques à 3 utilisateurs |
| Jeu 29/10 | Test de charge à 5 et 10 utilisateurs simultanés. Identification du point de saturation (VRAM, CPU, latence). Objectif : ≤ 30 secondes à 5 utilisateurs. | Métriques à 5 et 10 utilisateurs |
| Ven 30/10 | Analyse des résultats, identification des goulots d'étranglement. Optimisations si nécessaire (batch inference, cache des embeddings, ajustement de la taille du contexte). Rédaction du rapport de charge. | Rapport de charge complet |

Livrable de la semaine : temps de réponse maintenu sous un seuil acceptable à 5 utilisateurs simultanés.

---

### S22 (02/11 – 06/11) — Évaluation qualité globale

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 02/11 | Extension du jeu de test à 50+ questions : ajout de 20 nouvelles questions couvrant des cas limites, des reformulations, et des questions ambiguës identifiées pendant le développement. | Jeu de test étendu (50+ questions) |
| Mar 03/11 | Évaluation RAGAS sur les questions documentaires : calcul automatisé de Faithfulness, Context Precision, Context Recall, Answer Relevancy via la bibliothèque `ragas`. | Scores RAGAS calculés et documentés |
| Mer 04/11 | Évaluation du function calling ERP : pour chaque question chiffrée, comparaison de la réponse de l'agent avec le résultat obtenu par requête ORM manuelle. Calcul du taux d'exactitude. | Taux d'exactitude ERP documenté |
| Jeu 05/11 | Évaluation du routage (% de questions correctement dirigées) et de la mémoire conversationnelle (10 scénarios multi-tours). Identification des cas d'échec restants. | Taux de routage et résultats mémoire |
| Ven 06/11 | Consolidation de tous les scores dans un rapport unique. Présentation au maître de stage. Identification des axes d'amélioration pour le mémoire. | **Jalon J3** livré, rapport présenté |

Livrable de la semaine — **Jalon J3** : scores consolidés sur les quatre dimensions (RAG, function calling, routage, mémoire), présentés au maître de stage.

---

### S23 (09/11 – 13/11) — Documentation technique

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 09/11 | Documentation de l'architecture globale : schéma mis à jour (architecture cible v3 intégrant LangGraph, mémoire, RBAC), description de chaque composant et de leurs interactions. | Schéma d'architecture final |
| Mar 10/11 | Procédure d'installation complète : de la machine vierge au système opérationnel (Ubuntu, CUDA, Docker, Qdrant, vLLM, module Odoo). Testée sur une machine propre si possible. | Guide d'installation pas à pas |
| Mer 11/11 | Procédure de réindexation : comment ajouter un nouveau document, comment réindexer après une mise à jour du code source Odoo, comment purger et reconstruire l'index. | Guide de réindexation |
| Jeu 12/11 | Procédure d'ajout d'une nouvelle fonction au catalogue ERP : modèle à suivre, description à rédiger, tests à écrire, déploiement. | Guide d'extension du catalogue |
| Ven 13/11 | Revue complète de la documentation. Vérification que chaque procédure est exécutable par un développeur MiroKE sans assistance. | Documentation technique complète |

Livrable de la semaine : documentation technique complète couvrant les deux mécanismes.

---

### S24 (16/11 – 20/11) — Guide utilisateur et formation

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 16/11 | Rédaction du guide utilisateur : captures d'écran de l'interface Odoo, exemples de questions pour chaque type (documentaire, code, ERP, suivi conversationnel). | Guide utilisateur illustré (brouillon) |
| Mar 17/11 | Rédaction de la FAQ : "Pourquoi l'assistant dit qu'il ne sait pas ?", "Comment reformuler une question pour un meilleur résultat ?", "Comment signaler une réponse incorrecte ?". | FAQ intégrée au guide |
| Mer 18/11 | Rédaction du guide administrateur : configuration des compétences (on/off), consultation des logs, gestion des collections multi-tenant, ajout d'un nouveau client. | Guide administrateur |
| Jeu 19/11 | Session de formation pratique avec l'équipe MiroKE : démonstration en direct, exercices guidés (chaque participant pose 5 questions et évalue les réponses). Collecte des retours. | Formation réalisée, retours collectés |
| Ven 20/11 | Corrections post-formation : ajustements de l'interface, du wording, ou des prompts en fonction des retours de l'équipe. | Corrections appliquées |

Livrable de la semaine : équipes formées sur l'usage des deux types de questions (documentaire et ERP).

---

### S25 (23/11 – 27/11) — Restitution finale

| Jour | Tâche | Livrable du jour |
| ----- | ----- | ----- |
| Lun 23/11 | Consolidation de l'ensemble des livrables : code source nettoyé et commenté, documentation à jour, rapports d'évaluation finalisés, jeu de test complet. | Dépôt Git propre et complet |
| Mar 24/11 | Préparation de la présentation finale : slides couvrant le problème, la solution, l'architecture, les résultats mesurés, les perspectives. Démonstration en direct préparée. | Présentation prête |
| Mer 25/11 | Répétition de la présentation. Vérification que la démonstration en direct fonctionne sans accroc (instance Odoo, API, LLM). Plan B en cas de panne (captures vidéo). | Répétition réalisée, plan B prêt |
| Jeu 26/11 | **Présentation finale** au maître de stage et à l'équipe MiroKE. Démonstration en direct. Questions-réponses. | Présentation finale réalisée |
| Ven 27/11 | Clôture du stage : transfert des accès, documentation des éléments restant à faire (perspectives), archivage du projet. | Stage clôturé |

Livrable de la semaine — **Jalon J4** : système jugé prêt pour un déploiement pilote chez un client.  - **Answer Relevancy** : la réponse est-elle pertinente par rapport à la question ?
* Évaluation du taux d'exactitude pour le function calling ERP : chaque réponse chiffrée est comparée au résultat obtenu par requête ORM manuelle
* Évaluation du routage : pourcentage de questions correctement dirigées vers le bon mécanisme (RAG vs function calling vs repli)
* Évaluation de la mémoire conversationnelle : les questions de suivi sont-elles correctement résolues ?

Livrable — Jalon J3 : scores consolidés sur les quatre dimensions (RAG, function calling, routage, mémoire), présentés au maître de stage.

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

## 5\. Perspectives hors périmètre du stage

Les fonctionnalités suivantes ont été identifiées et étudiées pendant la phase d'analyse, mais sont explicitement exclues du périmètre du stage. Elles sont documentées ici comme perspectives d'évolution à moyen terme :

| Fonctionnalité | Description | Prérequis |
| ----- | ----- | ----- |
| **Création proactive de tickets** | L'agent détecte un problème dans la conversation et crée automatiquement un ticket Helpdesk dans Odoo | Nécessite de lever la politique read-only — à envisager uniquement après validation de la sécurité multi-tenant (post-S20), avec un workflow d'approbation humaine |
| **OCR pour PDF scannés** | Les PDF scannés (images, pas de texte extractible) sont prétraités par Tesseract OCR avant chunking. Détection automatique du type de PDF, extraction du texte avec support français/anglais, métadonnée `ocr_quality` pour signaler les sources de moindre fiabilité | Les documents de test sont en texte natif — l'OCR n'est utile qu'en production réelle où les clients fournissent des scans. Intégration via `pytesseract`, ajout d'un flag de qualité dans les métadonnées du chunk |
| **Ingestion automatisée continue** | Un processus en arrière-plan surveille les répertoires de documents et de code source. À chaque ajout, modification ou suppression de fichier, le système re-chunke, ré-embedde et met à jour la base vectorielle automatiquement, sans intervention manuelle | Nécessite un mécanisme de surveillance de fichiers (`watchdog`), une réindexation incrémentale par `content_hash`, un endpoint API `POST /reindex` pour le déclenchement manuel, et un scan planifié périodique comme filet de sécurité |
| **Multi-canal (WhatsApp, Telegram)** | L'API FastAPI étant indépendante du frontend, d'autres interfaces (webhooks Telegram, API WhatsApp Business) peuvent s'y connecter | L'architecture le permet déjà (l'API est le « cerveau », le module Odoo n'est qu'une « bouche » parmi d'autres) — mais chaque canal apporte ses contraintes d'authentification et de formatage |
| **Découverte dynamique de schéma** | L'agent utilise `fields_get()` pour découvrir les champs disponibles sur un modèle Odoo à l'exécution, au lieu de s'appuyer sur un schéma statique | Améliore la portabilité entre clients (champs personnalisés `x_`), mais introduit une complexité au moment du function calling — les descriptions d'outils ne sont plus statiques, ce qui peut déstabiliser les modèles 7-8B |
| **Fine-tuning complémentaire** | Réentraîner le modèle retenu sur un corpus de questions/réponses MiroKE validées, pour améliorer la qualité des réponses sans contexte RAG | Nécessite un volume significatif de données d'entraînement (~500+ paires Q/R), un budget GPU dédié, et une validation que le fine-tuning ne dégrade pas les capacités existantes (catastrophic forgetting) |
| **Sélecteur de fournisseur IA depuis Odoo** | Un menu déroulant dans les paramètres du module Odoo permettant de basculer entre plusieurs backends LLM (Groq cloud, Ollama local, vLLM) | Actuellement géré par variable d'environnement dans `settings.py` — la création d'une interface Odoo dédiée est un développement UI complet sans valeur ajoutée immédiate |

## 6\. Jalons de validation — récapitulatif

| Jalon | Semaine | Critère mesurable |
| ----- | ----- | ----- |
| J1 | S4 | Modèle(s) sélectionné(s) : score ≥ 3,5/5, réponse ≤ 15 s. Jeu de test de référence constitué (30+ questions) |
| J2 | S9 | ≥ 90 % de réponses correctement sourcées (RAG documentaire), mémoire conversationnelle fonctionnelle |
| J2bis | S13 | ≥ 85 % de réponses correctes sur questions ERP structurées, sans régression documentaire, routage correct ≥ 90 % |
| J3 | S22 | Scores RAGAS consolidés, latence pipeline ≤ 20 s (1 utilisateur), ≤ 30 s (5 utilisateurs), 0 fuite multi-tenant |
| J4 | S25 | Validation finale pour déploiement pilote |

