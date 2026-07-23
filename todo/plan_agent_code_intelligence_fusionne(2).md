# Plan — Agent de Code Intelligence (Odoo)

---

## 0. Choix architectural : traversée du graphe en code, pas orchestrée par le LLM

**Approche écartée** : le LLM orchestre lui-même chaque saut du graphe via une boucle ReAct ouverte sur 10 à 12 outils fins (`trouver_definition`, `lire_regles_securite_statique`, `lire_groupes_dune_regle`, `lire_hierarchie_groupe`, `resoudre_nom_technique_vers_role`, etc.).

**Approche retenue** : la traversée du graphe est effectuée en **code Python déterministe** (NetworkX). Le LLM ne choisit qu'**un outil composite de haut niveau** correspondant à l'intention de la question ; toute la mécanique multi-sauts (règles → groupes → hiérarchie → rôles) est encapsulée à l'intérieur de la fonction Python appelée, invisible pour le LLM.

### Justification (empirique)

Un spike contrôlé a comparé les deux approches sur les mêmes questions, avec le même modèle (Llama 3.1 8B via Groq) :

| Approche | Résultat | Défaillances observées |
|---|---|---|
| Outils fins + ReAct ouvert | 0/3 séquences correctes, sur deux runs successifs | Mauvaise extraction d'identifiants entre étapes (le modèle passe une description en langage naturel au lieu d'un ID exact) ; hallucination d'un outil jamais bindé (`brave_search`) ; non-reconnaissance d'un cul-de-sac — le modèle a comblé l'absence de données en inventant une hiérarchie de groupes Odoo standard tirée de ses connaissances générales plutôt que du graphe réel indexé, jusqu'à épuiser la limite d'itérations |
| Outils composites | 2/3 exact | Le seul écart est un appel redondant au même outil avec les mêmes arguments — résultat correct, aucune hallucination, intercepté proprement par un garde-fou anti-boucle |

**Conclusion** : ce n'est pas une limite générale du modèle 8B en tant que tel, mais la profondeur d'orchestration multi-étapes qui le fait décrocher. Un modèle de cette taille reste fiable pour *choisir* le bon outil parmi quelques options claires ; il devient peu fiable dès qu'on lui demande d'*enchaîner* plusieurs appels avec extraction et réinjection d'identifiants entre chaque étape. En déplaçant cette orchestration dans du code testable, le risque disparaît sans rien sacrifier sur la richesse du graphe sous-jacent.

Ce résultat structure directement la conception de Sprint B, et par ricochet les sprints C à F.

---

## Sprint A — Fondation : index structurel complet du code

### A1. Extraction structurelle multi-langage

**Python — `jedi` + AST manuel**

`jedi` couvre bien la résolution de définitions/références/héritage Python standard, mais échoue sur les patterns Odoo suivants, qu'il faut extraire séparément via un visiteur AST (`ast.NodeVisitor`) dédié :

- `_inherit` / `_name` — distinction cruciale entre **extension** (`_inherit` seul, sans `_name`, modifie un modèle existant) et **héritage classique** (`_name` + `_inherit`, crée un nouveau modèle qui hérite). Une troisième forme existe et est souvent oubliée : `_inherits` (avec un "s") qui est de la **délégation** (ex: `product.product` délègue à `product.template`) — sémantique complètement différente (accès aux champs du modèle parent via une clé étrangère, pas une fusion de classe). Les trois doivent être distingués dans le graphe avec des types d'arête différents.
- `@api.depends`, `@api.constrains`, `@api.onchange` — extraire non seulement le décorateur mais la **liste exacte des champs déclencheurs** passés en argument, y compris les chemins pointés (dépendance sur un champ d'un modèle lié via relation).
- `fields.Many2one`, `One2many`, `Many2many` — extraire `comodel_name` (ou premier argument positionnel), mais aussi `inverse_name` pour les One2many (nécessaire pour naviguer la relation dans les deux sens), `related` (champs calculés par délégation de chemin — une forme cachée de dépendance inter-modèle), `compute` (nom de la méthode qui calcule le champ), et `store` (un champ calculé non stocké n'apparaît pas en base, donc n'est pas requêtable via `read_group`).
- `@api.model`, `@api.model_create_multi` — contexte d'exécution (méthode de classe vs méthode d'instance), utile pour comprendre si une méthode a accès à `self.env.user` de façon fiable.
- Parsing des `__manifest__.py` de chaque module — champ `depends` (ordre de chargement des modules, qui détermine dans quel ordre les `_inherit` s'appliquent réellement) et champ `data` (liste des fichiers XML chargés — un fichier présent dans le dossier mais absent de `data` n'est jamais chargé par Odoo).

**XML — extension du parseur tree-sitter existant**

- `<record model="ir.rule">` — `domain_force` (parsé comme expression de domaine Odoo, pas juste stocké en texte brut), `groups_id` (many2many vers `res.groups`), `model_id`, et `perm_read`/`perm_write`/`perm_create`/`perm_unlink` distincts (une règle peut s'appliquer uniquement en lecture, par exemple).
- `<record model="res.groups">` — `implied_ids` (hiérarchie de groupes, relation transitive à modéliser comme telle, pas une liste plate), `category_id` (catégorie fonctionnelle, utile pour le mapping nom technique → rôle humain).
- `<record model="ir.actions.act_window">` — permissions via `groups_id` directement sur l'action (distinctes des règles au niveau modèle — une action de menu peut être cachée à un groupe même si le modèle sous-jacent lui serait accessible).
- `<record model="ir.model.fields">` définis dynamiquement en XML, et `<menuitem>` avec leur `groups` (visibilité de menu, niveau de contrôle distinct des deux précédents).
- **Contenu des vues formulaire (`arch` des `ir.ui.view`)** — au-delà des droits, extraire le label exact des boutons de transition (`<button name="action_confirm" string="Confirmer"/>`) et le chemin de menu complet jusqu'à la vue (`<menuitem>` parent → enfant). Ce n'est plus seulement "qui peut déclencher cette transition" mais "sur quel bouton, à quel endroit de l'interface" — nécessaire pour que l'agent puisse répondre à des questions de navigation ("comment je fais pour...") propres à la personnalisation de cet ERP, pas seulement à des questions de droits ou de structure.

**CSV — parser structuré de `ir.model.access.csv`**

Table stricte : `id, name, model_id:id, group_id:id, perm_read, perm_write, perm_create, perm_unlink`. Point d'attention : une ligne avec `group_id` **vide** signifie que la règle s'applique à **tous les utilisateurs authentifiés**, pas qu'elle est invalide — source d'erreur fréquente si le parser traite une cellule vide comme un cas à exclure.

**JS — extraction des contrôles côté client**

`this.env.user.hasGroup(...)`, et les patterns OWL (`useService("user")` combiné à `t-if="user.hasGroup(...)"`). Point à documenter explicitement dans le prompt système de l'agent : un contrôle côté client n'est jamais une garantie de sécurité (contournable en appelant l'API directement) — seuls `ir.rule`/`ir.model.access` sont réellement contraignants côté serveur.

### A2. Résolution des références croisées inter-fichiers

- **Résolution en deux passes.** Passe 1 : indexer tous les symboles définis (par module, avec ordre de chargement issu des manifests). Passe 2 : résoudre les références selon cet ordre réel — une référence à un groupe non encore chargé au moment où le XML est lu (mais chargé plus tard dans la séquence) doit être résolue quand même, pas selon l'ordre d'apparition dans le corpus de fichiers.
- **Registre des références externes non résolues**, catégorisées : symbole absent du corpus indexé vs symbole appartenant au cœur Odoo hors périmètre indexé vs erreur de frappe probable. Cette distinction change la réponse de l'agent : "je ne sais pas" ≠ "hors de mon périmètre indexé".
- **Détection de cycles** dès A2 (`visited: set()` dès la première implémentation) — un résolveur naïf peut boucler à l'infini sur un héritage circulaire (rare mais possible via des modules tiers mal conçus).

### A3. Stockage — graphe complet

**Schéma de graphe explicite** (à définir avant tout code) :

**Types de nœuds** : `Model`, `Field`, `Method`, `Group`, `Rule`, `Module`, `AccessEntry`, `WorkflowState`

**Types d'arêtes** (typées, pas génériques) :
- `EXTENDS` (Model → Model, via `_inherit`)
- `DELEGATES_TO` (Model → Model, via `_inherits`)
- `HAS_FIELD` (Model → Field)
- `RELATES_TO` (Field → Model, via `comodel_name`, avec attribut `relation_type` = many2one/one2many/many2many)
- `COMPUTED_BY` (Field → Method)
- `DEPENDS_ON` (Method → Field, via `@api.depends`)
- `RESTRICTED_BY` (Model → Rule)
- `APPLIES_TO_GROUP` (Rule → Group)
- `IMPLIES` (Group → Group, hiérarchie transitive)
- `GRANTED_BY` (Model → AccessEntry)
- `DEFINED_IN` (tout nœud → Module, avec chemin de fichier et numéro de ligne en attribut)
- `TRANSITIONS_VIA` (WorkflowState → Method → WorkflowState suivant, avec attribut `label_bouton` si un bouton de vue déclenche cette méthode)

Ce schéma explicite permet des requêtes de traversée typées (ex: "tous les chemins `RESTRICTED_BY` puis `APPLIES_TO_GROUP` puis `IMPLIES*` partant de `account.move`") au lieu d'une traversée générique sur un graphe non typé, beaucoup plus sujette à erreur d'interprétation par l'agent.

**Workflow et processus métier.** Le graphe couvre "qui a le droit d'accéder à quoi" (sécurité statique), mais aussi "quelles sont les étapes d'un processus et qui déclenche laquelle" — un axe distinct, complémentaire à la sécurité. En Odoo, un processus (demande de congé, demande d'achat, mise à disposition de matériel...) est presque toujours encodé de la même façon :
- un champ `state = fields.Selection([...])` qui énumère les étapes possibles (ex: `draft → confirm → validate1 → validate → refuse` pour `hr.leave`) ;
- des méthodes de transition (`action_approve`, `action_confirm`, `button_validate`...) qui font passer d'un état à l'autre — ces méthodes sont extraites en A1 comme les autres méthodes, puis reliées au nœud `WorkflowState` correspondant via `TRANSITIONS_VIA` ;
- ces méthodes de transition sont elles-mêmes protégées par des groupes de sécurité (souvent le même mécanisme que `RESTRICTED_BY`/`APPLIES_TO_GROUP`, parfois une simple vérification `has_group()` dans le corps de la méthode plutôt qu'une `ir.rule`) — donc chaque `TRANSITIONS_VIA` porte, comme attribut, le groupe requis pour déclencher la transition ;
- des seuils conditionnels fréquents (ex: montant d'achat au-delà duquel un niveau d'approbation supplémentaire est requis) — logique explicite dans le code, jamais correctement documentée ailleurs, à capturer comme attribut de la transition plutôt que comme un fait séparé ;
- le **label du bouton** qui déclenche la méthode dans la vue formulaire (`string="Confirmer"`, `string="Envoyer pour approbation"`...), et le **chemin de menu** pour y accéder — cette information transforme une réponse technique ("la méthode `action_confirm` fait passer l'état de draft à confirm") en instruction actionnable pour l'utilisateur final ("clique sur le bouton **Confirmer**").

**Choix NetworkX**, avec précisions :
- Sérialisation via `graphml` (recommandée) plutôt que `pickle` — plus portable et inspectable manuellement, utile en phase de debug/mémoire, vu l'importance de la traçabilité pour un stage évalué.
- Benchmark à faire concrètement sur le volume réel du corpus (2682 chunks vus dans les logs d'ingestion RAG donnent un ordre de grandeur : le graphe structurel sera probablement d'un ordre de grandeur comparable en nœuds, mais avec beaucoup plus d'arêtes du fait des relations croisées). Mesurer explicitement le temps de traversée pour un chemin à 5 sauts sur un graphe de cette taille, avant de valider NetworkX en prod — sinon la recommandation reste une hypothèse non vérifiée.

### Planning détaillé — A1 à A3 (4 semaines, 5 jours/semaine)

Hypothèse de base : un développeur à temps plein, journées de travail effectif dédiées à ce sous-projet. À ajuster selon la disponibilité réelle et le rythme déjà en cours (S12).

**Semaine 1 — A1 : extraction Python (jedi + AST)**
- **Jour 1** : intégration de `jedi` sur le corpus réel ; test de résolution de définitions/références standard ; identification concrète des limites de `jedi` sur les patterns Odoo (ce que le visiteur AST devra combler).
- **Jour 2** : visiteur AST dédié — distinction `_inherit` seul (extension) / `_name`+`_inherit` (héritage classique) / `_inherits` (délégation), avec type d'arête différent pour chacun.
- **Jour 3** : extraction `@api.depends`/`@api.constrains`/`@api.onchange` — liste exacte des champs déclencheurs, y compris chemins pointés inter-modèles.
- **Jour 4** : extraction des champs relationnels (`comodel_name`, `inverse_name`, `related`, `compute`, `store`) et du contexte `@api.model` vs méthode d'instance.
- **Jour 5** : parsing des `__manifest__.py` (`depends`, `data`) ; tests unitaires sur l'ensemble de la semaine ; revue avant de passer au XML/CSV/JS.

**Semaine 2 — A1 : XML, CSV, JS**
- **Jour 1** : extension tree-sitter pour `ir.rule` (`domain_force` parsé comme expression de domaine, `groups_id`, `model_id`, `perm_read`/`write`/`create`/`unlink` distincts).
- **Jour 2** : `res.groups` (`implied_ids`, `category_id`) + `ir.actions.act_window` (permissions au niveau action).
- **Jour 3** : `ir.model.fields` définis en XML, `<menuitem>` (`groups`), et extraction du contenu des vues formulaire (`arch` : labels de boutons, chemin de menu — nécessaire pour `quel_est_le_processus_de` en Sprint B).
- **Jour 4** : parser CSV `ir.model.access.csv`, avec gestion explicite du cas `group_id` vide (tous les utilisateurs authentifiés, pas une ligne à ignorer) ; tests dédiés à ce cas.
- **Jour 5** : extraction JS (`hasGroup`, patterns OWL) ; test d'intégration bout en bout de A1 sur un module réel complet ; bilan de fin de sprint A1.

**Semaine 3 — A2 : résolution des références croisées**
- **Jour 1** : passe 1 — indexation de tous les symboles définis, avec ordre de chargement des modules issu des manifests (dépend de la semaine 1, jour 5).
- **Jour 2** : passe 2 — résolution des références selon l'ordre de chargement réel, pas selon l'ordre d'apparition dans le corpus de fichiers.
- **Jour 3** : registre des références non résolues, avec catégorisation (absent du corpus / cœur Odoo hors périmètre / erreur de frappe probable).
- **Jour 4** : détection de cycles (`visited: set()`) ; test avec un cycle d'héritage artificiel injecté pour vérifier la détection dès cette étape (pas reportée en Sprint E).
- **Jour 5** : test d'intégration A1+A2 sur le corpus réel ; bilan de fin de sprint A2.

**Semaine 4 — A3 : schéma de graphe et stockage**
- **Jour 1** : finalisation du schéma de graphe (types de nœuds et d'arêtes, y compris `WorkflowState`/`TRANSITIONS_VIA`) comme document de design validé avant tout code — évite de redéfinir le schéma en cours d'implémentation.
- **Jour 2** : implémentation NetworkX — construction du graphe à partir des sorties A1/A2 (nœuds `Model`/`Field`/`Method`/`Group`/`Rule`/`Module`/`AccessEntry`).
- **Jour 3** : sérialisation `graphml` ; inspection manuelle du graphe produit sur un sous-ensemble du corpus.
- **Jour 4** : extraction et intégration du sous-graphe `WorkflowState` (champ `state`, méthodes de transition, groupe requis, seuils conditionnels, label de bouton et chemin de menu extraits en semaine 2, jour 3).
- **Jour 5** : benchmark de traversée à 5 sauts sur le volume réel du corpus ; bilan de fin de Sprint A (A1 à A3) avant d'attaquer A4/Sprint B.

Ce découpage suppose que chaque semaine se termine avec un livrable testable (pas seulement du code en cours) : à la fin de la semaine 4, le graphe complet — sécurité statique + workflow — doit être navigable en NetworkX sur le corpus réel, avant de passer à la synchronisation live (A4) et aux outils composites (Sprint B).

### A4. Synchronisation avec le contenu réel Odoo

- **Cache TTL court** (ex: 5 minutes) pour les requêtes live plutôt qu'un appel XML-RPC à chaque question — coût observé de ~100-300ms par appel. Invalidation manuelle possible, utile en phase de test quand des droits sont modifiés volontairement pour observer la détection de divergence. Un appel redondant au même outil composite peut se produire (appel dupliqué avec résultat correct, intercepté par le garde-fou anti-boucle) ; avec cache, cette redondance devient gratuite plutôt que coûteuse en latence.
- **Logique de fusion/priorité** : `comparer_regles_statique_vs_live` ne doit jamais renvoyer un simple booléen "divergence: true/false", mais la nature précise de la divergence (groupe ajouté en base mais absent du code, domaine de règle modifié avec les deux valeurs affichées côte à côte, règle désactivée en base — `active: False` — mais toujours présente et active dans le XML source). Ce niveau de détail est ce qui rend l'outil réellement utile à un consultant MiroKE en intervention chez un client, pas juste un signal binaire.

### Planning détaillé — A4 (semaine 5)

- **Jour 1** : connexion XML-RPC ; requêtes live sur `ir.model.access`, `ir.rule`, `res.groups` ; mesure du coût réel par appel (~100-300ms attendu, à confirmer).
- **Jour 2** : cache TTL (5 minutes) avec invalidation manuelle ; tests de non-régression du cache (données périmées, invalidation forcée).
- **Jour 3** : logique de détection de divergence dans `comparer_regles_statique_vs_live` (groupe ajouté/absent, domaine modifié, règle `active: False` mais toujours dans le XML).
- **Jour 4** : format de sortie détaillé (jamais un booléen) ; tests avec des droits modifiés volontairement en base pour valider chaque type de divergence.
- **Jour 5** : tests d'intégration A1 à A4 sur le corpus réel ; bilan de fin de Sprint A complet avant d'attaquer les outils composites.

---

## Sprint B — Outils composites

Le graphe est exposé au LLM via **5 outils composites**, chacun encapsulant une traversée complète en Python :

```python
@tool
def qui_a_acces_a(modele_odoo: str, action: str = "write") -> str:
    """Traverse règles → groupes → hiérarchie → rôles métier en une fois,
    retourne directement les rôles ayant accès à un modèle."""

@tool
def modules_et_regles_dun_modele(modele_odoo: str) -> str:
    """Modules qui étendent un modèle + ses règles de sécurité, en un appel."""

@tool
def comparer_regles_statique_vs_live(modele_odoo: str) -> str:
    """Détecte et détaille les divergences code/base (nature précise, pas un booléen)."""

@tool
def suivre_heritage_complet(modele_odoo: str) -> str:
    """Chaîne d'héritage complète, _inherit ET _inherits distingués (délégation
    toujours incluse par défaut — pas de paramètre à activer séparément)."""

@tool
def quel_est_le_processus_de(modele_odoo: str) -> str:
    """Traverse le graphe de workflow (WorkflowState → TRANSITIONS_VIA → WorkflowState)
    et retourne la séquence d'étapes du processus, avec pour chaque transition
    la méthode qui l'exécute, le groupe/rôle requis pour la déclencher, le label
    du bouton associé dans la vue et le chemin de menu pour y accéder
    (ex: étapes d'une demande de congé ou d'achat, qui approuve chaque étape,
    et sur quel bouton cliquer à chaque étape)."""
```

Un ensemble d'outils fins (`trouver_definition`, `trouver_references`, `lire_regles_securite_statique`, `lire_regles_securite_live`, `suivre_chemin_dependance`, `lister_declencheurs`, etc.) existe en interne comme fonctions appelées *par* les outils composites, mais n'est jamais exposé directement au LLM. Ils restent utiles pour Sprint D (tester la logique de traversée indépendamment du LLM) et pour un mode de navigation libre résiduel, traité en exception plutôt qu'en cas général.

**Outils annexes**, déjà atomiques et n'impliquant aucune traversée à orchestrer :
- `resoudre_nom_technique_vers_role(nom_technique)` — traduit un identifiant technique Odoo vers un rôle métier MiroKE, via la table de correspondance documentée.
- `lister_modules_impliques(modele_odoo)` — scoping en amont d'une question complexe, avant navigation détaillée.
- `expliquer_chemin_de_decision(chemin)` — reformule une séquence de nœuds/arêtes déjà trouvée en langage naturel étape par étape ; sépare recherche et explication, pour que l'agent puisse vérifier son propre raisonnement avant de le présenter (lien direct avec Sprint D).
- `lire_code_source_precis(fichier, ligne_debut, ligne_fin)` — lecture ciblée avec garde-fou sur la taille max de plage.

**Justification** : chaque saut orchestré par le LLM est un point de rupture potentiel — extraction d'ID, choix du bon outil suivant, reconnaissance d'un résultat vide. Réduire le nombre de décisions du LLM par question à 1 élimine mécaniquement une bonne part de la surface d'erreur.

**Gestion d'erreur à trois niveaux** (résultat trouvé / résultat vide — le symbole existe mais n'a pas ce qui est cherché / symbole introuvable — erreur de nom probable) implémentée *à l'intérieur* de la fonction composite — donc fiable en code plutôt que dépendante de l'interprétation du LLM à chaque étape intermédiaire. Un LLM qui reçoit un texte générique "aucun résultat" pour ces trois cas très différents va halluciner une explication pour combler le vide plutôt que de distinguer correctement les cas — cohérent avec le principe de "Codage Défensif" déjà présent dans la documentation interne.

### Planning détaillé — Sprint B (semaines 6-7)

**Semaine 6 — outils composites principaux**
- **Jour 1** : `qui_a_acces_a` — traversée règles → groupes → hiérarchie → rôles métier.
- **Jour 2** : `modules_et_regles_dun_modele`.
- **Jour 3** : `comparer_regles_statique_vs_live` (wrapper autour de la logique déjà validée en A4) + `suivre_heritage_complet`.
- **Jour 4** : `quel_est_le_processus_de` — traversée du sous-graphe workflow, avec label de bouton et chemin de menu en sortie.
- **Jour 5** : gestion d'erreur à trois niveaux implémentée dans chacun des 5 outils composites ; tests unitaires dédiés à chaque cas (trouvé/vide/introuvable).

**Semaine 7 — outils annexes et consolidation**
- **Jour 1** : `resoudre_nom_technique_vers_role`.
- **Jour 2** : `lister_modules_impliques`.
- **Jour 3** : `expliquer_chemin_de_decision`.
- **Jour 4** : `lire_code_source_precis` avec garde-fou sur la taille de plage.
- **Jour 5** : tests unitaires complets sur les 5 outils composites + 4 outils annexes ; bilan de fin de Sprint B avant intégration dans la boucle agent.

---

## Sprint C — Intégration routeur et agent

**Boucle `code_intelligence_agent_loop`** : conçue pour 1-2 itérations par question (contre 4-6 pour une orchestration à outils fins), limitant le risque de dérive sur la limite de récursion. Prompt système structuré en stratégie explicite de navigation (ex: toujours commencer par `lister_modules_impliques` pour scoper, puis comparer statique avant live).

**Garde-fou anti-boucle** (détection de rappel identique outil + arguments) à porter directement dans cette boucle de production, aux côtés de la logique de recovery de tool calls malformés déjà présente dans `orm_agent_loop`.

**Routeur étendu et résolution de conflit inter-branches** (RAG documentaire vs Code Intelligence) : problème ouvert de conception, à traiter avec un jeu d'exemples few-shot couvrant les cas ambigus à la frontière RAG/Function-Calling/Code-Intelligence (ex: "Qui peut approuver un avoir de plus de 500 000 Ar ?" est à la fois une question de gouvernance — nécessite le graphe — ET potentiellement documentée dans le wiki RAG existant, avec risque de redondance/contradiction si les deux divergent). Le routeur doit avoir une politique explicite de résolution de conflit, pas seulement de sélection de branche.

**Profondeur de navigation** : compteur de sauts explicite dans le state LangGraph — ce compteur se situe naturellement à l'intérieur des fonctions de traversée elles-mêmes, pour pouvoir indiquer précisément à quel saut l'agent s'est arrêté en cas de réponse partielle.

### Planning détaillé — Sprint C (semaine 8)

- **Jour 1** : structure de la boucle `code_intelligence_agent_loop` dans LangGraph, branchement des 5 outils composites + 4 outils annexes.
- **Jour 2** : garde-fou anti-boucle (détection de rappel identique outil + arguments), aux côtés de la logique de recovery déjà présente dans `orm_agent_loop`.
- **Jour 3** : prompt système avec stratégie de navigation explicite (ex: scoper via `lister_modules_impliques` avant tout, comparer statique avant live).
- **Jour 4** : compteur de sauts dans le state, pour tracer précisément où l'agent s'arrête en cas de réponse partielle.
- **Jour 5** : tests d'intégration bout en bout de l'agent complet sur quelques questions représentatives ; bilan de fin de Sprint C. *(La résolution de conflit inter-branches RAG/Function Calling/Code Intelligence reste hors périmètre ici — traitée dans le document séparé sur l'arbitrage.)*

---

## Sprint D — Jeu de test et validation

**Construction du jeu de gouvernance** : répartition par difficulté (1 saut / 2-3 sauts / 4+ sauts) et par type (sécurité pure, logique métier calculée, mapping technique→humain), pour mesurer où l'agent décroche précisément plutôt qu'un score global agrégé peu informatif.

**Ajustement de mesure** : avec les outils composites, le "saut" pertinent à mesurer n'est plus le nombre d'appels d'outils LLM (souvent réduit à 1 par question) mais la **profondeur de traversée interne** de la fonction composite appelée — à instrumenter en loggant la traversée réelle (nœuds/arêtes visités) à l'intérieur du code, indépendamment de la séquence d'appels LLM.

**Évaluation à deux niveaux** : grille de notation du chemin de raisonnement (chemin minimal réel vs détour valide mais inefficace, nœud non pertinent visité avant correction), pas seulement "bon/mauvais" — matière d'analyse pour la partie évaluation du mémoire.

**Non-régression** : questions pièges ("information non trouvable dans le périmètre indexé") en proportion notable du jeu de test, pas juste 1-2 questions, pour mesurer séparément le taux de faux positifs (l'agent invente un chemin plausible mais faux) du taux de vrais positifs. Ces cas sont simples à tester proprement : c'est le comportement de chaque fonction composite sur un cas `trouve: False` qui doit être vérifié, indépendamment du LLM.

### Planning détaillé — Sprint D (semaines 9-10)

**Semaine 9 — construction du jeu de test**
- **Jour 1** : définir la grille de répartition (1 saut / 2-3 sauts / 4+ sauts) × (sécurité pure, logique métier calculée, mapping technique→humain).
- **Jour 2-3** : rédaction des questions avec le maître de stage, réponses attendues documentées pour chaque question.
- **Jour 4** : rédaction des questions pièges ("non trouvable dans le périmètre indexé") en proportion notable.
- **Jour 5** : mise en place du harness de test (exécution automatisée des questions contre l'agent, capture des réponses et des traversées internes).

**Semaine 10 — exécution et évaluation**
- **Jour 1** : instrumentation du logging de la profondeur de traversée interne (nœuds/arêtes visités par appel composite).
- **Jour 2** : exécution du jeu de test complet, collecte des résultats.
- **Jour 3** : grille de notation du chemin de raisonnement (chemin minimal réel vs détour valide, nœud non pertinent visité avant correction).
- **Jour 4** : analyse séparée du taux de faux positifs (chemin halluciné) et de vrais positifs sur les questions pièges.
- **Jour 5** : bilan de fin de Sprint D, rapport de résultats consolidé pour le mémoire.

---

## Sprint E — Robustesse et cas limites

La détection de boucle est un mécanisme fonctionnel dès Sprint C, testée en non-régression ici.

Reste à couvrir :
- **Cycles d'héritage** : traité dès A2, mais Sprint E doit ajouter un test de non-régression spécifique qui injecte volontairement un cycle artificiel dans le corpus de test pour vérifier la détection.
- **Symboles ambigus** : présenter les candidats multiples à l'agent avec leur module d'origine, laisser l'agent (ou en dernier recours l'utilisateur) trancher, plutôt que de choisir arbitrairement le premier trouvé.
- **Performance** : budget de latence explicite dès maintenant (ex: 90e percentile sous X secondes pour une navigation à 3 sauts + 1 appel XML-RPC live) — un chiffre cible permet de savoir objectivement si l'optimisation est nécessaire.
- **Sécurité** : test d'injection sur les requêtes d'extraction massive (ex: "liste-moi toutes les règles de tous les modèles avec leurs domaines exacts") — détection et limitation explicite (rate-limiting logique ou refus explicite au-delà d'un certain périmètre par requête), cohérent avec le principe de moindre divulgation.

### Planning détaillé — Sprint E (semaine 11)

- **Jour 1** : test de non-régression avec cycle d'héritage artificiel injecté dans le corpus de test, vérification de la détection mise en place dès A2.
- **Jour 2** : stratégie de désambiguïsation des symboles — présentation des candidats multiples avec module d'origine.
- **Jour 3** : mesure du budget de latence (90e percentile) sur une navigation à 3 sauts + 1 appel XML-RPC live ; comparaison au chiffre cible fixé.
- **Jour 4** : test d'injection sur les requêtes d'extraction massive ; implémentation du rate-limiting logique ou du refus explicite.
- **Jour 5** : bilan de fin de Sprint E, revue des cas limites couverts vs restants.

---

## Sprint F — Observabilité et maintenance

Un agent de cette complexité (graphe + live + multi-hop) a un besoin d'observabilité bien supérieur au RAG documentaire simple. Le logging structuré du chemin de raisonnement gagne en clarté avec le design composite : au lieu de logger une séquence de 4-5 appels d'outils fins à corréler manuellement, on logue un seul appel d'outil composite accompagné de la traversée interne qu'il a effectuée — plus simple à indexer, plus lisible en debug post-hoc.

- **Détection de staleness de l'index** : le graphe structurel devient obsolète dès que le code source évolue (nouveau module, modification d'une règle). Réutiliser le mécanisme de réindexation incrémentale par hash de contenu prévu en S6 pour le RAG, étendu au graphe structurel, avec calcul du sous-graphe à recalculer plutôt que tout le graphe à chaque modification.
- **Budget coût/latence global** : cet agent multiplie probablement le nombre d'appels LLM par question par rapport au RAG simple (1 appel) ou au Function Calling (1-2 appels) — à chiffrer explicitement avant intégration, avec un plafond de sauts/appels par question comme garde-fou budgétaire, pas seulement de qualité.

### Planning détaillé — Sprint F (semaine 12)

- **Jour 1** : logging structuré du chemin de raisonnement en production (un appel d'outil composite + traversée interne, pas 4-5 appels fins à corréler).
- **Jour 2** : détection de staleness de l'index — adaptation du mécanisme de hash de contenu déjà prévu en S6 pour le RAG.
- **Jour 3** : calcul du sous-graphe à recalculer lors d'une modification (pas tout le graphe à chaque changement) ; tests sur une modification ciblée.
- **Jour 4** : chiffrage du budget coût/latence global ; mise en place du plafond de sauts/appels par question.
- **Jour 5** : bilan final — revue générale de A1 à F, checklist avant intégration en production.

Sur cette base, le sous-projet Code Intelligence Agent représente environ **12 semaines** (A1-A3 : 4 semaines, A4 : 1 semaine, Sprint B : 2 semaines, Sprint C : 1 semaine, Sprint D : 2 semaines, Sprint E : 1 semaine, Sprint F : 1 semaine), à ajuster selon le temps réellement disponible en parallèle des autres items déjà engagés (S12 en cours).

---

## Cadrage : justification et public visé

Le point de départ n'est pas "un outil d'audit en plus pour les développeurs" : c'est l'absence de documentation métier fiable. Le code source est, dans les faits, **la base de connaissance principale** que le LLM doit consulter pour répondre à la majorité — sinon la quasi-totalité — des questions d'un utilisateur ERP, quel qu'il soit. Un wiki ou une doc écrite se périme dès qu'un module évolue ; le code, lui, reflète toujours l'état réel du système. Ce n'est donc pas une source parmi d'autres réservée à des questions de gouvernance : c'est la source de vérité par défaut, pour à peu près tout ce qui touche au fonctionnement réel de l'ERP — droits d'accès, processus métier (congé, achat, mise à disposition...), règles de calcul, dépendances entre modules.

Le RAG documentaire existant peut couvrir ce qui reste correctement écrit ailleurs (procédures internes formalisées, politique RH générale), mais pour tout ce qui concerne le fonctionnement réel du système Odoo tel qu'il est configuré et personnalisé chez le client — donc pour la plupart des questions concrètes qu'un utilisateur va réellement poser — c'est le code qui fait foi. L'IA sert avant tout de **support** : le public visé est n'importe quel utilisateur de l'ERP posant des questions de type "qui a le droit d'approuver un avoir", "quelle est la procédure de validation d'une facture" ou "quelles sont les étapes d'une demande de congé et qui valide quoi", avec le consultant/développeur MiroKE comme public secondaire pour des questions plus techniques (structure du code, dépendances).

Conséquence directe sur Sprint C : le routeur doit arbitrer entre RAG documentaire, Function Calling ERP et Code Intelligence, et adapter le niveau de détail de la réponse — un utilisateur métier attend une réponse en rôles humains sans jargon Odoo, un consultant attend des identifiants techniques précis. Les outils composites de Sprint B (ex. `qui_a_acces_a`, `quel_est_le_processus_de`) sont déjà bien positionnés pour ça, puisqu'ils exposent à la fois le mapping humain (`roles`) et le détail technique (`groupes_avec_hierarchie`) dans leur sortie — au routeur ou au prompt de synthèse de choisir le niveau à restituer selon le profil de l'utilisateur.

**Limites de périmètre.** Le code ne peut répondre qu'à ce qui est effectivement encodé dans *ce* système : droits d'accès, processus métier et leur déclenchement (y compris, via le label de bouton et le chemin de menu, "comment déclencher telle étape dans l'interface" pour cet ERP précis). Restent hors périmètre : les données réelles (montants, dates, statuts d'un dossier précis — couvertes par le Function Calling ERP existant), et les conventions générales d'usage d'Odoo non spécifiques à ce client (ex: utiliser un filtre de vue liste, exporter en Excel — relevant d'une doc utilisateur générique ou du RAG documentaire). L'arbitrage entre RAG documentaire, Function Calling et Code Intelligence quand plusieurs branches pourraient répondre à une même question reste un sujet distinct, traité à part.

Conséquence sur le poids relatif des branches : si le code devient la base de connaissance par défaut pour la majorité des questions, le Code Intelligence Agent n'est plus un sous-système secondaire par rapport au RAG documentaire — il en devient potentiellement le point d'entrée principal pour les questions métier, avec le RAG documentaire en complément pour ce qui reste correctement écrit ailleurs. Ça renforce d'autant plus l'importance de la résolution de conflit inter-branches (Sprint C) : le code et le wiki peuvent diverger, et le code doit alors primer comme source de vérité.

**Note de cadrage générale** : ce plan représente un sous-projet à part entière, comparable en ampleur au RAG + Function Calling déjà construits depuis juin. Le séquencement réel par rapport aux items déjà engagés (S12 en cours mi-juillet, fin de stage fin novembre) reste à trancher avec le maître de stage — ce document détaille le contenu technique, pas la planification calendaire.
