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

## État de l'art — positionnement par rapport à l'existant

**Le principe général n'est pas inédit, mais son application l'est.** Une catégorie active d'outils "code intelligence pour agents LLM" s'est développée en 2025-2026 autour du même principe que celui retenu ici : construire un graphe structurel du code et l'exposer à un agent LLM via des outils de haut niveau plutôt que par recherche par similarité. Deux travaux académiques publiés arrivent au même constat que le spike de ce projet : <cite index="27-1">la recherche par similarité manque de rappel pour le raisonnement multi-sauts — suivre des surcharges de méthodes, des dépendances inter-modules — tandis que les outils manuels sont conçus pour une tâche unique et manquent de généralisabilité.</cite> LocAgent (ACL 2025) formalise la même réponse que les outils composites de Sprint B : <cite index="22-1">unifier toute l'exploration, la recherche et la visualisation du code en quelques outils seulement, plutôt que de multiplier les outils spécialisés conçus pour la lisibilité humaine mais coûteux pour un agent LLM.</cite>

Côté outillage open-source, **CodeGraphContext** est l'équivalent générique le plus proche : <cite index="55-1">un outil Python, MIT, avec des backends de graphe interchangeables (FalkorDB Lite, KuzuDB, Neo4j), couvrant 22 langages.</cite> Aucun outil de cette catégorie, cependant, ne modélise de sémantique métier — permissions, rôles humains, workflow — <cite index="55-1">tous ces outils raisonnent en termes d'imports, d'appels de fonctions et de hiérarchies de classes pour aider un agent à éditer du code en toute sécurité, pas pour expliquer un système à un utilisateur non-développeur.</cite> Le vide que ce projet comble est donc précis : l'application d'une architecture publiée à un domaine — la gouvernance ERP pour utilisateurs métier — non couvert par l'existant.

Spécifiquement pour Odoo, **`odoo-analyse`** existe déjà (outil Python, initOS) mais reste un outil de visualisation de dépendances entre modules pour développeurs, sans LLM, sans sécurité ni workflow. Les modules IA officiels d'Odoo ("AI Chat Agent", "MCP Server") couvrent l'accès aux données via function calling avec contrôle d'accès — le même terrain que le Function Calling ERP déjà construit — mais aucun n'analyse le code source pour en extraire la structure de sécurité ou les processus.

**Sur la robustesse face au code custom**, l'analogie la plus utile ne vient pas du monde Odoo mais de SAP, qui affronte ce problème à grande échelle depuis deux décennies avec son parc de code ABAP custom ("code Z") — voir la taxonomie et le principe de scoping intégrés en A2.

**Sur le renommage de symboles** (limite identifiée en Sprint F), un outil existe et est publié spécifiquement pour Python : PyRef (SCAM 2021), qui <cite index="66-1">détecte le renommage de méthode et d'autres refactorings en convertissant le code en AST puis en appliquant des règles prédéfinies</cite>, avec des résultats mesurés (89,6% de précision, 76,1% de rappel) — voir Sprint F pour son intégration.

**Sur le mécanisme du filet de sécurité statique lui-même** (A1), plutôt qu'un visiteur AST fait main qu'il faudrait réécrire à chaque nouveau pattern custom rencontré, **Semgrep** est un outil mature et activement maintenu pour ce rôle : moteur d'analyse statique à règles déclaratives où les règles ressemblent au code qu'on écrit déjà — pas d'arbre syntaxique abstrait à manipuler ni de DSL pénible — écrites en YAML, avec support natif de Python et de JavaScript. Voir l'intégration détaillée dans l'annexe d'A1.

---

## Sprint A — Fondation : index structurel complet du code

### A1. Extraction structurelle — runtime en priorité, statique en filet de sécurité

**Détection de version — préalable à toute extraction**

Avant de lancer l'extraction, lire le champ `version` du `__manifest__.py` racine (ou, à défaut, du premier module trouvé) pour déterminer la génération Odoo du corpus — nécessaire pour monter une instance de la bonne version, et pour le branchement JS (seule partie encore purement statique, voir plus bas). Le pipeline reste **un seul outil générique paramétré par `(chemin_du_repo, version_odoo)`**, rejouable tel quel sur n'importe quel client ou n'importe quelle instance.

**Changement d'approche central : extraction runtime plutôt que reconnaissance de patterns.**

Le risque principal d'un extracteur statique (visiteur AST, parseur XML/CSV) est qu'il doit *reconnaître* des patterns Odoo dans le texte source — et qu'un module custom peut écrire ces patterns d'une façon jamais rencontrée, sans qu'on puisse garantir à l'avance que l'extracteur généralisera. Il existe un autre moyen d'obtenir la même information, qui ne dépend d'aucune reconnaissance de pattern : **charger le corpus dans une véritable instance Odoo de la version détectée (`odoo-bin shell -d <db> --addons-path=...`) et interroger l'état résolu directement via l'ORM et l'introspection Python**, plutôt que de re-parser le texte pour le deviner. C'est Odoo lui-même — pas une réimplémentation heuristique de sa logique de résolution — qui produit alors le résultat, avec la même fiabilité que pour n'importe quelle installation Odoo réelle, quel que soit le style d'écriture du module.

**Ce que le runtime donne directement, sans aucun parsing de texte :**
- **Héritage et délégation** : `env[model]._inherits` (dict) et la MRO Python (`__bases__`) donnent la résolution finale d'`_inherit`/`_inherits` — déjà calculée par Odoo, plus besoin de la déduire du texte source.
- **Champs et dépendances** : `model._fields[nom].depends`, `.relation`, `.compute`, `.store`, `.relation_field` (inverse_name) sont des attributs directement portés par l'objet `Field` déjà construit par Odoo.
- **Contraintes et onchange** : `@api.constrains`/`@api.onchange` stockent leurs arguments comme attributs sur la fonction elle-même (`method._constrains`, `method._onchange`), récupérables par introspection Python (`getattr`) plutôt que par lecture du décorateur dans le texte.
- **Sécurité** : `env['ir.rule']`, `env['ir.model.access']`, `env['res.groups']` donnent l'état de sécurité résolu — réutilisation du mécanisme déjà prévu pour la synchronisation live d'A4, mobilisé ici pour construire la structure elle-même, pas seulement pour détecter des divergences ultérieures.
- **Vues et navigation** : `env['ir.ui.view'].get_view()` retourne la vue finale composée après application de tous les héritages XPath (`inherit_id`) de tous les modules qui la modifient — résout d'un coup un cas très difficile à reconstituer statiquement (plusieurs modules qui étendent la même vue), avec les vrais labels de boutons et la structure de menu réelle.
- **Localisation dans le code** : `inspect.getsourcefile()` et `inspect.getsourcelines()` donnent fichier et numéro de ligne directement sur toute classe ou méthode déjà chargée — remplace le calcul manuel de position dans le texte pour l'attribut `DEFINED_IN`.
- **Ordre de chargement des modules** : déjà résolu par Odoo au moment du chargement de l'instance — la reconstruction manuelle de cet ordre depuis les manifests (nécessaire pour la voie statique, cf. A2) devient secondaire plutôt que centrale.

**Extraction statique — filet de sécurité résiduel, plus principe par défaut, structuré en trois niveaux.** Trois cas où elle reste nécessaire, avec un mécanisme différent pour chacun selon son degré de prévisibilité :

1. **Patterns connus mais hors du modèle Python runtime — moteur à règles déclaratives (Semgrep), pas un visiteur AST fait main.** Le JS (`hasGroup`, OWL/legacy) et la lecture ciblée de méthodes déjà identifiées par le runtime (recherche d'un `has_group()` codé en dur dans le corps) sont des patterns récurrents et nommables — le bon outil pour ça n'est pas un visiteur AST qu'il faut réécrire à chaque nouvelle variante rencontrée, mais un **registre de règles Semgrep versionnées** (YAML, une règle = quelques lignes déclaratives). Avantage direct pour la généricité : quand un nouveau style d'écriture custom est rencontré chez un client (ou dans le jeu adversarial), on ajoute une règle au registre plutôt que de retoucher et retester du code Python — le registre devient l'artefact qui capitalise d'un corpus à l'autre.
2. **Patterns imprévisibles, fragment déjà localisé — lecture LLM bornée, jamais orchestrée.** Pour un fragment de code dont le style est trop irrégulier pour une règle déclarative (ex: le contenu du champ `code` d'un `ir.actions.server`), un LLM peut être utilisé pour une lecture ponctuelle et bornée ("ce texte contient-il une vérification de sécurité ? laquelle ?") — un usage étroit et donc fiable, sans rapport avec l'orchestration multi-sauts écartée en section 0. Le résultat est explicitement tagué **confiance faible / interprétation LLM** dans le graphe, jamais traité comme un fait structurel certain au même titre qu'une extraction runtime ou Semgrep.
3. **Modules qui ne s'installent pas isolément** (dépendance manquante, module cassé) — l'extraction statique (niveaux 1 et 2 ci-dessus) reste alors l'unique recours pour ce module, avec un statut de confiance "partiel" explicite, cohérent avec la taxonomie SAP ajoutée en A2.

**Score de couverture par module — rendre l'incertitude visible plutôt que de viser une exhaustivité illusoire.** Aucun système heuristique ne peut garantir une reconnaissance à 100% d'un style de code custom arbitraire — plutôt que de le nier ou de le cacher, le pipeline doit produire, pour chaque module, la proportion de constructions liées à la sécurité/au workflow effectivement reconnues par un mécanisme couvert (runtime, Semgrep) vs tombées en "pattern non reconnu" (niveau 2 ou échec complet). Ce score se propage jusqu'à la réponse de l'agent (cf. discipline de fidélité, Sprint C) : "voici ce que j'ai trouvé ; ce module contient aussi N constructions de sécurité que je n'ai pas pu classer avec certitude" plutôt qu'une réponse qui prétend implicitement à l'exhaustivité.

**Ce que ce changement ne résout pas** : il faut pouvoir réellement installer le code dans une instance Odoo de la bonne version — une contrainte déjà nécessaire pour A4, donc pas une infrastructure nouvelle à construire. Et il ne dispense pas de l'accès au vrai code de l'entreprise : il change la nature du risque une fois cet accès obtenu — d'un risque de reconnaissance heuristique incertaine à une garantie de résolution par Odoo lui-même, aussi fiable que n'importe quelle installation Odoo réelle.

---

**Annexe — extraction statique détaillée (filet de sécurité pour les trois cas ci-dessus)**

*Les patterns listés ci-dessous restent valides comme connaissance métier à extraire ; ce qui change, c'est le mécanisme d'implémentation. Pour tout ce qui est exprimable comme un pattern de code nommable (la majorité des cas Python/XML listés), l'implémentation cible est un **registre de règles Semgrep (YAML)**, pas un visiteur `ast.NodeVisitor` fait main — chaque puce ci-dessous correspond alors à une ou plusieurs règles déclaratives versionnées, plus faciles à auditer et à étendre qu'un visiteur Python. Le JS reste une exception (Semgrep supporte JS/OWL, mais le legacy Widget/QWeb pré-v14 est suffisamment irrégulier pour rester en partie du filet niveau 2 — lecture LLM bornée — plutôt qu'entièrement couvert par des règles).*

**Python — `jedi` + règles Semgrep (plutôt qu'un visiteur AST fait main)**

`jedi` couvre bien la résolution de définitions/références/héritage Python standard, mais échoue sur les patterns Odoo suivants, qu'il faut extraire séparément via des règles Semgrep dédiées :

- `_inherit` / `_name` — distinction cruciale entre **extension** (`_inherit` seul, sans `_name`, modifie un modèle existant) et **héritage classique** (`_name` + `_inherit`, crée un nouveau modèle qui hérite). Une troisième forme existe et est souvent oubliée : `_inherits` (avec un "s") qui est de la **délégation** (ex: `product.product` délègue à `product.template`) — sémantique complètement différente (accès aux champs du modèle parent via une clé étrangère, pas une fusion de classe). Les trois doivent être distingués dans le graphe avec des types d'arête différents.
- `@api.depends`, `@api.constrains`, `@api.onchange` — extraire non seulement le décorateur mais la **liste exacte des champs déclencheurs** passés en argument, y compris les chemins pointés (dépendance sur un champ d'un modèle lié via relation).
- `fields.Many2one`, `One2many`, `Many2many` — extraire `comodel_name` (ou premier argument positionnel), mais aussi `inverse_name` pour les One2many (nécessaire pour naviguer la relation dans les deux sens), `related` (champs calculés par délégation de chemin — une forme cachée de dépendance inter-modèle), `compute` (nom de la méthode qui calcule le champ), et `store` (un champ calculé non stocké n'apparaît pas en base, donc n'est pas requêtable via `read_group`).
- `@api.model`, `@api.model_create_multi` — contexte d'exécution (méthode de classe vs méthode d'instance), utile pour comprendre si une méthode a accès à `self.env.user` de façon fiable.
- Parsing des `__manifest__.py` de chaque module — champ `depends` (ordre de chargement des modules, qui détermine dans quel ordre les `_inherit` s'appliquent réellement) et champ `data` (liste des fichiers XML chargés — un fichier présent dans le dossier mais absent de `data` n'est jamais chargé par Odoo).

**Logique métier pure (helpers, fonctions non liées à l'ORM) — repo-map tree-sitter en complément.** Les patterns ci-dessus couvrent ce qui touche directement au framework ORM (décorateurs, champs, `_inherit`). Une partie de la logique métier réelle vit cependant dans du Python pur non capturé par ces patterns — fonctions utilitaires, calculs intermédiaires appelés depuis plusieurs méthodes, sans décorateur `@api.*` direct. Pour cette catégorie, l'outil de codage agentique Aider résout un problème voisin (donner à un LLM la structure d'un gros codebase sans tout charger en contexte) avec une technique différente, éprouvée à grande échelle en production : parser chaque fichier avec tree-sitter pour extraire définitions et références de symboles, construire un graphe où les fichiers sont des nœuds reliés par leurs dépendances, puis appliquer un PageRank pour faire remonter les fonctions les plus centrales/appelées. Une implémentation standalone de cette technique existe en open source (RepoMapper, basé sur le design d'Aider, licence permissive) et peut être adaptée en filet de sécurité complémentaire — spécifiquement pour la logique métier pure que ni l'introspection runtime ni le visiteur AST orienté-ORM ne couvrent. À évaluer en Sprint A comme extension optionnelle, pas comme prérequis bloquant.

**XML — règles Semgrep (support natif XML) plutôt que parseur tree-sitter dédié**

**Checklist de complétude — mécanismes officiels Odoo pouvant porter de la logique métier.** Odoo impose un nombre fini de points d'extension pour qu'un module fonctionne — cette fermeture du vocabulaire est justement ce qui rend l'extraction systématisable plutôt que devinée au cas par cas. Chaque ligne ci-dessous doit avoir un extracteur dédié en A1 ; celles marquées "à ajouter" ne sont pas couvertes par la version actuelle du plan et représentent un angle mort réel, pas hypothétique (voir le jeu de modules adversariaux, tests 5 et 6, qui les stressent concrètement) :

| Mécanisme | Statut | Risque si non couvert |
|---|---|---|
| Champs + décorateurs (`@api.depends`, `@api.constrains`, `@api.onchange`) | Couvert | — |
| `_inherit` / `_inherits` / mixins | Couvert (introspection runtime) | — |
| `ir.model.access.csv` + `ir.rule` (liste brute) | Couvert | — |
| **Algorithme de combinaison globale (ET) / groupe (OU) des `ir.rule`** | **À ajouter** | Le plus critique : une simple liste de règles sans reproduire cet algorithme peut donner une réponse inversée sur "qui voit quoi" (voir test adversarial 6) |
| `has_group()` / `sudo()` / `with_user()` en dur dans le code | Couvert (règle Semgrep) | — |
| `res.groups.implied_ids` (héritage implicite entre groupes) | Déjà dans le schéma (arête `IMPLIES`, A3) — à confirmer que l'extraction runtime la peuple systématiquement, pas seulement la voie statique | Sous-estimation des droits réels d'un utilisateur si l'extraction runtime ne la peuple pas |
| `ir.actions.server` / `base.automation` (logique en données) | À ajouter | Logique et bypass de sécurité invisibles à toute lecture de fichiers (voir test adversarial 5) |
| **`ir.cron`** (tâches planifiées) | À ajouter | Même angle mort que `base.automation` — code métier stocké en données, exécuté périodiquement |
| `_sql_constraints` (attribut de classe) | À ajouter | Règle métier écrite en SQL brut, invisible à un visiteur cherchant des `if`/`raise` |
| `domain=` sur un champ relationnel (Many2one/Many2many) | À ajouter | Règle métier encodée comme restriction de sélection, pas comme méthode |
| `default=`, `search=`, `inverse=` callables sur un champ | À vérifier | Logique cachée dans un paramètre de champ plutôt qu'une méthode nommée |
| `groups=` au niveau d'un champ (vs `ir.rule` au niveau enregistrement) | À vérifier | Mécanisme de sécurité différent, à ne pas confondre dans les réponses |
| Vues XML (`invisible=`/`readonly=` avec expression) | Partiellement couvert | Règle métier exprimée uniquement comme condition d'affichage |
| Rapports QWeb (`t-if` dans le template) | Watch-list, faible priorité vu le scope actuel | — |
| Contrôleurs HTTP (`@http.route`, `auth=`) | Watch-list, pertinent seulement si portail/webhook dans le scope | — |

Priorité concrète pour la suite immédiate : traiter l'algorithme de combinaison des `ir.rule` et `ir.cron` avant tout le reste de cette liste — ce sont les deux dont le risque de réponse silencieusement fausse est le plus élevé sur les processus déjà ciblés (avoirs, achats, congés).

- `<record model="ir.rule">` — `domain_force` (parsé comme expression de domaine Odoo, pas juste stocké en texte brut), `groups_id` (many2many vers `res.groups`), `model_id`, et `perm_read`/`perm_write`/`perm_create`/`perm_unlink` distincts (une règle peut s'appliquer uniquement en lecture, par exemple).
- `<record model="res.groups">` — `implied_ids` (hiérarchie de groupes, relation transitive à modéliser comme telle, pas une liste plate), `category_id` (catégorie fonctionnelle, utile pour le mapping nom technique → rôle humain).
- `<record model="ir.actions.act_window">` — permissions via `groups_id` directement sur l'action (distinctes des règles au niveau modèle — une action de menu peut être cachée à un groupe même si le modèle sous-jacent lui serait accessible).
- `<record model="ir.model.fields">` définis dynamiquement en XML, et `<menuitem>` avec leur `groups` (visibilité de menu, niveau de contrôle distinct des deux précédents).
- **Contenu des vues formulaire (`arch` des `ir.ui.view`)** — utile uniquement quand `get_view()` n'est pas disponible (module non installable isolément) : label exact des boutons de transition et chemin de menu, en filet de sécurité de ce que le runtime donne normalement directement.

**CSV — parser structuré de `ir.model.access.csv`**

Table stricte : `id, name, model_id:id, group_id:id, perm_read, perm_write, perm_create, perm_unlink`. Point d'attention : une ligne avec `group_id` **vide** signifie que la règle s'applique à **tous les utilisateurs authentifiés**, pas qu'elle est invalide — source d'erreur fréquente si le parser traite une cellule vide comme un cas à exclure.

**JS — extraction des contrôles côté client**

`this.env.user.hasGroup(...)`, et les patterns OWL (`useService("user")` combiné à `t-if="user.hasGroup(...)"`). Point à documenter explicitement dans le prompt système de l'agent : un contrôle côté client n'est jamais une garantie de sécurité (contournable en appelant l'API directement) — seuls `ir.rule`/`ir.model.access` sont réellement contraignants côté serveur.

**Branchement selon la version détectée** : si `version < 14`, le pattern OWL (`useService`) n'existe pas — utiliser à la place les patterns de l'ancien framework Widget/QWeb legacy (ex: vérifications de groupe dans les anciens `Widget.extend()`). Concrètement, une fonction `extraire_controles_js(fichier, version_odoo)` avec deux chemins de recherche selon le seuil v14, plutôt qu'un chemin unique qui suppose OWL partout et rate silencieusement les contrôles legacy sur les instances v11-v13 confirmées dans le parc.

### A2. Résolution des références croisées inter-fichiers

*Avec l'extraction runtime en méthode principale (A1), Odoo résout déjà lui-même l'ordre de chargement et la plupart des références croisées au moment où l'instance démarre — les points suivants restent nécessaires pour la voie statique de repli (modules non installables isolément) et pour le registre de traçabilité, mais ne sont plus le chemin critique de la résolution.*

- **Résolution en deux passes.** Passe 1 : indexer tous les symboles définis (par module, avec ordre de chargement issu des manifests). Passe 2 : résoudre les références selon cet ordre réel — une référence à un groupe non encore chargé au moment où le XML est lu (mais chargé plus tard dans la séquence) doit être résolue quand même, pas selon l'ordre d'apparition dans le corpus de fichiers.
- **Registre des références externes non résolues**, catégorisées : symbole absent du corpus indexé vs symbole appartenant au cœur Odoo hors périmètre indexé vs erreur de frappe probable. Cette distinction change la réponse de l'agent : "je ne sais pas" ≠ "hors de mon périmètre indexé".
- **Détection de cycles** dès A2 (`visited: set()` dès la première implémentation) — un résolveur naïf peut boucler à l'infini sur un héritage circulaire (rare mais possible via des modules tiers mal conçus).

**Boucle de correction humaine — fermer le registre plutôt que le laisser en collecte passive.** Le registre de références/patterns non résolus ne doit pas rester une simple liste consultée manuellement de loin en loin : chaque entrée non résolue mérite une revue courte (typiquement quelques minutes) qui tranche "ceci est bien une construction de sécurité/workflow, via tel mécanisme" ou "ceci est hors périmètre" — et cette décision doit se traduire en une nouvelle règle Semgrep versionnée (cf. A1) plutôt que rester une note isolée pour ce corpus. Concrètement, ce que la revue apprend sur un client profite à tous les corpus suivants, y compris les futurs modules OCA ou clients testés — le registre devient un mécanisme d'apprentissage cumulatif du pipeline, pas seulement un journal d'erreurs par projet.

**Classification du code custom — taxonomie à trois catégories, pas une distinction binaire standard/custom.** SAP affronte ce problème depuis deux décennies avec ses milliers de clients et leur code ABAP custom ("code Z"), et sa solution éprouvée classe systématiquement tout code custom rencontré en trois catégories : usage d'un objet standard, extension d'un objet standard (ajout de champs, enrichissement), ou modification directe d'un objet standard. Cette classification se transpose directement sur Odoo : `_inherit`/`_inherits` couvrent déjà l'extension et la délégation, mais A2 doit explicitement classer aussi le troisième cas — un pattern de sécurité ou de workflow codé "à la main" plutôt que via les mécanismes Odoo standard (`ir.rule`, `state` Selection) — avec un statut de confiance marqué (extraction certaine / partielle / non reconnue) plutôt qu'un échec silencieux ou un abandon total de l'extraction sur ce symbole.

**Scoping par fréquence d'usage — ne pas viser l'exhaustivité dès Sprint A.** Toujours par analogie avec la pratique SAP : avant d'extraire en profondeur *tout* le code custom rencontré, prioriser par fréquence d'usage réelle (un module custom appelé par de nombreux autres, ou impliqué dans beaucoup de workflows, vaut plus d'attention immédiate qu'un module custom isolé et rarement sollicité). Concrètement, un premier passage d'A1/A2 peut se limiter à une extraction "légère" (nœuds + relations directes) sur l'ensemble du corpus, puis une extraction approfondie priorisée sur les modules les plus référencés — plutôt qu'un seul passage exhaustif dont le coût croît avec chaque pattern non standard rencontré.

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

**Semaine 1 — A1 : extraction runtime via instance Odoo vivante**
- **Jour 1** : détection de version (lecture `version` du `__manifest__.py`) ; mise en place d'une instance Odoo de la version détectée (`odoo-bin shell -d <db> --addons-path=...`), installation du corpus de test ; validation que le shell s'ouvre avec accès à `env`.
- **Jour 2** : extraction runtime de l'héritage et de la délégation (`env[model]._inherits`, MRO Python) et des champs (`model._fields[nom].depends/.relation/.compute/.store/.relation_field`) sur l'ensemble des modèles installés.
- **Jour 3** : extraction runtime des contraintes/onchange (`method._constrains`, `method._onchange` via `getattr`) et de la sécurité (`env['ir.rule']`, `env['ir.model.access']`, `env['res.groups']`).
- **Jour 4** : extraction runtime des vues (`env['ir.ui.view'].get_view()` pour la vue composée finale — labels de boutons, structure de menu) et de la localisation (`inspect.getsourcefile()`/`getsourcelines()` pour chaque nœud extrait).
- **Jour 5** : tests d'intégration de l'extraction runtime sur le corpus complet ; mesure du taux de couverture (proportion de modèles/champs/règles effectivement extraits par cette voie) ; identification des cas nécessitant le filet de sécurité statique (modules non installables isolément).

**Semaine 2 — A1 : filet de sécurité statique (Semgrep + JS + LLM borné)**
- **Jour 1** : mise en place de Semgrep sur le corpus ; premières règles YAML pour `_inherit`/`_inherits`/`@api.depends` et `ir.rule`/`res.groups`/`ir.actions.act_window` — activées uniquement sur les modules identifiés en semaine 1 jour 5 comme non couverts par le runtime.
- **Jour 2** : règles Semgrep pour `ir.model.access.csv` (avec gestion du cas `group_id` vide) et pour l'extraction des vues (`arch`) en repli quand `get_view()` n'est pas disponible.
- **Jour 3** : règles Semgrep pour `has_group()`/`sudo()`/`with_user()` en dur dans le corps de méthodes déjà localisées par le runtime ; parsing des `__manifest__.py` (`depends`, `data`) pour la résolution d'ordre de repli.
- **Jour 4** : extraction JS avec branchement selon la version détectée (`hasGroup`/OWL si v14+ via règle Semgrep, patterns Widget/QWeb legacy sinon — nécessaire vu la présence confirmée de v11 dans le parc) ; mise en place du niveau 2 (lecture LLM bornée) pour les fragments hors de portée d'une règle déclarative (ex: contenu libre d'un champ `code=`), avec tag de confiance systématique sur ces résultats.
- **Jour 5** : test d'intégration bout en bout combinant runtime + Semgrep + LLM borné sur le corpus complet ; calcul du score de couverture par module ; bilan de fin de sprint A1 (cible : la grande majorité de la structure via runtime, Semgrep en exception documentée, LLM borné en dernier recours marginal).

**Semaine 3 — A2 : résolution des références croisées**
- **Jour 1** : passe 1 — indexation de tous les symboles définis, avec ordre de chargement des modules issu des manifests (dépend de la semaine 1, jour 5).
- **Jour 2** : passe 2 — résolution des références selon l'ordre de chargement réel, pas selon l'ordre d'apparition dans le corpus de fichiers.
- **Jour 3** : registre des références non résolues, avec catégorisation (absent du corpus / cœur Odoo hors périmètre / erreur de frappe probable).
- **Jour 4** : détection de cycles (`visited: set()`) ; test avec un cycle d'héritage artificiel injecté pour vérifier la détection dès cette étape (pas reportée en Sprint E).
- **Jour 5** : mise en place de la boucle de correction humaine (revue courte du registre → nouvelle règle Semgrep versionnée) ; test d'intégration A1+A2 sur le corpus réel ; bilan de fin de sprint A2.

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

**Sourcing de réponse — exigence, pas recommandation.** Ce n'est pas une bonne pratique parmi d'autres : **toute réponse produite par l'agent doit être accompagnée d'une source vérifiable** (fichier, module, nom de règle exact, ou identifiant XML), sans exception. Une réponse sans source citable est un défaut bloquant, au même titre qu'une réponse fausse — pas un manque de style à corriger plus tard. Concrètement, ça se traduit à deux niveaux :
- **Contrat de sortie des outils composites (Sprint B)** : chaque outil composite doit retourner un champ `source` structuré (fichier + ligne, ou identifiant XML de la règle/du groupe) pour chaque élément de sa réponse — pas seulement le résultat métier. Un outil qui ne peut pas fournir de source pour un élément doit le marquer explicitement plutôt que l'omettre silencieusement.
- **Contrat de sortie de l'agent (Sprint C)** : la réponse finale doit reprendre ces sources telles que retournées par les outils, jamais reformulées de façon à en perdre la traçabilité (ex: "d'après le fichier X, ligne Y" plutôt qu'une affirmation nue). Le vérificateur de fidélité (ci-dessous) doit explicitement rejeter toute réponse contenant une affirmation sans source rattachable — pas seulement les affirmations factuellement fausses.

**Synthèse de réponse — discipline de fidélité au graphe.** Tout ce qui précède garantit que la *recherche* est fiable (graphe déterministe, outils composites testés), mais rien ne garantit encore que la *réponse finale* du LLM reste fidèle à ce que la recherche a réellement trouvé — c'est un point de rupture distinct, aussi réel que ceux déjà traités, et non couvert par le reste du plan. Quatre exigences à poser explicitement dans le prompt système de `code_intelligence_agent_loop` :
- **Interdiction de compléter avec la connaissance générale du LLM.** La synthèse ne doit s'appuyer que sur les résultats d'outils reçus dans le tour en cours — jamais sur ce que le LLM "sait" par ailleurs d'Odoo ou des ERP en général, même quand la question invite à généraliser.
- **Propagation obligatoire du cas "non trouvé".** Si un outil composite renvoie `trouve: False`, la réponse finale doit le dire explicitement, et non produire une réponse plausible construite malgré l'absence de résultat.
- **Citation systématique de la source, sans exception (cf. exigence ci-dessus)** — pour qu'un consultant MiroKE puisse vérifier, et pour rendre visible tout écart entre la réponse et ce que le graphe a réellement retourné.
- **Surface du score de couverture (A1) quand il est pertinent.** Si le module interrogé a des constructions non classées avec certitude (niveau 2 du filet statique, cf. A1), la réponse doit le signaler explicitement plutôt que de présenter un résultat partiel comme exhaustif — cohérent avec la propagation du cas "non trouvé" ci-dessus, mais pour le cas plus nuancé d'une couverture partielle plutôt que d'une absence totale de résultat.

**Vérificateur de fidélité — mécanisme, pas seulement consigne de prompt.** Une simple instruction dans le prompt système ne suffit pas à garantir la fidélité — c'est un constat bien documenté dans la littérature sur les agents RAG/tool-calling : un modèle peut recevoir le bon contexte et tout de même l'ignorer, le mal interpréter, ou combler les manques par une supposition confiante. La pratique de production qui fonctionne consiste à ajouter une étape de vérification distincte de la génération, après elle : décomposer la réponse en affirmations atomiques, puis vérifier chacune contre les résultats d'outils réellement reçus (par inférence de langage naturel ou par un second appel LLM en juge), en signalant toute affirmation non supportée. Appliqué ici, ça donne une étape supplémentaire dans la boucle : après génération de la réponse par `code_intelligence_agent_loop`, un second appel (léger, un seul passage) vérifie **(a)** que chaque affirmation de la réponse est bien rattachable à un résultat d'outil du tour, et **(b)** que chaque affirmation porte une source citée valide — sans quoi la réponse est renvoyée pour reformulation stricte, ou explicitement marquée comme partiellement non vérifiée plutôt que présentée telle quelle.

### Planning détaillé — Sprint C (semaine 8)

- **Jour 1** : structure de la boucle `code_intelligence_agent_loop` dans LangGraph, branchement des 5 outils composites + 4 outils annexes.
- **Jour 2** : garde-fou anti-boucle (détection de rappel identique outil + arguments), aux côtés de la logique de recovery déjà présente dans `orm_agent_loop`.
- **Jour 3** : prompt système avec stratégie de navigation explicite (ex: scoper via `lister_modules_impliques` avant tout, comparer statique avant live) et discipline de fidélité (interdiction de compléter avec la connaissance générale, propagation du cas non trouvé, citation systématique de la source).
- **Jour 4** : compteur de sauts dans le state ; implémentation du vérificateur de fidélité (décomposition en affirmations atomiques, vérification contre les résultats d'outils du tour, signalement des affirmations non supportées).
- **Jour 5** : tests d'intégration bout en bout de l'agent complet (génération + vérification) sur quelques questions représentatives ; bilan de fin de Sprint C. *(La résolution de conflit inter-branches RAG/Function Calling/Code Intelligence reste hors périmètre ici — traitée dans le document séparé sur l'arbitrage.)*

---

## Sprint D — Jeu de test et validation

**Construction du jeu de gouvernance** : répartition par difficulté (1 saut / 2-3 sauts / 4+ sauts) et par type (sécurité pure, logique métier calculée, mapping technique→humain), pour mesurer où l'agent décroche précisément plutôt qu'un score global agrégé peu informatif.

**Langage des questions — exigence explicite.** Sauf pour la catégorie `tech_mapping` (dont le rôle est justement de tester la traduction technique → humain), toutes les questions du jeu de test doivent être formulées en **langage métier fonctionnel**, jamais en identifiants techniques Odoo. Une question comme *"Qui a accès au modèle sale.order en lecture ?"* teste la compréhension du graphe par l'agent, pas son utilité pour l'utilisateur final visé par ce projet (cf. Cadrage) ; la question équivalente à tester est *"Qui peut consulter les commandes de vente ?"*. De même, *"Quels champs dépendent du champ price_unit sur sale.order ?"* devient *"Si je change le prix unitaire d'un devis, qu'est-ce qui est recalculé ?"*. C'est à l'agent — via `resoudre_nom_technique_vers_role` et la résolution de noms dans les outils composites — de faire la correspondance vers les identifiants techniques, pas à la personne qui rédige la question de test de faire ce travail à l'avance.

**Ajustement de mesure** : avec les outils composites, le "saut" pertinent à mesurer n'est plus le nombre d'appels d'outils LLM (souvent réduit à 1 par question) mais la **profondeur de traversée interne** de la fonction composite appelée — à instrumenter en loggant la traversée réelle (nœuds/arêtes visités) à l'intérieur du code, indépendamment de la séquence d'appels LLM.

**Évaluation à deux niveaux** : grille de notation du chemin de raisonnement (chemin minimal réel vs détour valide mais inefficace, nœud non pertinent visité avant correction), pas seulement "bon/mauvais" — matière d'analyse pour la partie évaluation du mémoire.

**Test de sourcing systématique — critère d'acceptation à part entière, pas une note qualitative.** Pour chaque cas du jeu de test avec réponse trouvée (`trouve: True`), le harness doit vérifier mécaniquement que la réponse contient au moins une source citée (fichier, module, ou identifiant de règle) et que cette source correspond bien à un élément réellement retourné par l'outil appelé — pas seulement présente une chaîne de caractères plausible. Une réponse correcte sur le fond mais sans source vérifiable doit être comptée comme un échec du critère de sourcing, distinct du taux de succès global, pour que ce chiffre ne se noie pas dans la moyenne.

**Non-régression** : questions pièges ("information non trouvable dans le périmètre indexé") en proportion notable du jeu de test, pas juste 1-2 questions, pour mesurer séparément le taux de faux positifs (l'agent invente un chemin plausible mais faux) du taux de vrais positifs. Ces cas sont simples à tester proprement : c'est le comportement de chaque fonction composite sur un cas `trouve: False` qui doit être vérifié, indépendamment du LLM.

**Fiabilité du harness d'évaluation — garde-fous requis.** L'agent évalué n'est pas la seule source d'erreur possible : le script d'évaluation (`eval_harness.py` ou équivalent) doit lui-même être fiable, sous peine de produire un rapport dont les conclusions contredisent ses propres données sans que personne ne s'en aperçoive. Deux garde-fous à implémenter dès la construction du harness, pas après coup :
- **Assertion de cohérence interne avant génération du rapport** : le texte de synthèse ne doit jamais être écrit en dur — il doit être calculé dynamiquement à partir des chiffres du tableau. Si le taux de succès sur `trick_out_of_scope` est sous un seuil donné, le harness doit littéralement ne pas pouvoir écrire "interceptés sans hallucination" ; soit la phrase est générée depuis la donnée réelle, soit une vérification bloque explicitement la génération du rapport en cas d'incohérence détectée.
- **Vérification que la route loguée correspond à l'outil réellement exécuté** : un test de non-régression du harness lui-même, qui compare le nom de la branche enregistrée dans le log (`documentaire`/`code_intelligence`/`donnees_erp`) au nom de la fonction Python effectivement appelée pour produire la réponse. Ça évite qu'un bug d'ordre d'appel (ex: routeur invoqué sur un contexte vide avant la recherche vectorielle) fausse silencieusement toute la matrice de résultats sans qu'aucune anomalie ne remonte avant une relecture manuelle du rapport.

Cette exigence tient aussi comme point méthodologique pour le mémoire : l'évaluation automatisée d'un agent nécessite elle-même une validation, elle n'est pas une source de vérité par construction.

**Portée de la validation — modules standards vs modules custom.** Tant que l'accès au code de l'entreprise cible n'est pas accordé, le jeu de test et le corpus d'extraction reposent sur une instance Odoo fraîchement installée avec des modules standards (`sale`, `account`, `hr`...) et des données générées. Cette base valide réellement la partie générique du pipeline — extraction, résolution, graphe — puisque les modules standards sont strictement identiques chez tous les clients qui ne les modifient pas. Ce que cette validation **ne couvre pas** : le comportement de l'extracteur face aux modules custom/tiers spécifiques à l'entreprise cible, dont le style de code et les conventions restent inconnus. Le rapport d'évaluation doit distinguer explicitement ces deux niveaux de preuve (validé sur modules standards / à confirmer sur modules custom) plutôt que de présenter un taux de succès global comme s'il couvrait déjà le corpus réel final.

**Suite de régression vivante sur l'écosystème OCA — passer de 8 cas choisis à un échantillon large et continu.** Le jeu de modules adversariaux (8 modules construits à la main) donne un signal qualitatif précieux mais reste un échantillon restreint, écrit une fois. En complément, faire tourner le pipeline d'extraction en continu (CI, à chaque modification de l'extracteur ou du registre Semgrep) sur un échantillon large et croissant de vrais modules OCA (branche 17.0, dépôts choisis pour leur diversité — sécurité, workflow, vues) — pour détecter si une correction faite pour un pattern en casse un autre ailleurs, et mesurer un taux de couverture représentatif du monde réel plutôt qu'anecdotique. Ce n'est pas un remplacement de la validation finale sur le vrai corpus de l'entreprise, mais un signal continu bien plus robuste que 8 cas fixes en attendant cet accès.

### Planning détaillé — Sprint D (semaines 9-10)

**Semaine 9 — construction du jeu de test**
- **Jour 1** : définir la grille de répartition (1 saut / 2-3 sauts / 4+ sauts) × (sécurité pure, logique métier calculée, mapping technique→humain).
- **Jour 2-3** : rédaction des questions avec le maître de stage, **en langage métier fonctionnel** pour `security`/`business_logic` (identifiants techniques réservés à `tech_mapping`), réponses attendues documentées pour chaque question.
- **Jour 4** : rédaction des questions pièges ("non trouvable dans le périmètre indexé") en proportion notable.
- **Jour 5** : mise en place du harness de test (exécution automatisée des questions contre l'agent, capture des réponses et des traversées internes), avec dès cette étape les deux garde-fous de fiabilité (route loguée = route réellement exécutée ; conclusion générée dynamiquement à partir des chiffres, jamais en texte statique).

**Semaine 10 — exécution et évaluation**
- **Jour 1** : instrumentation du logging de la profondeur de traversée interne (nœuds/arêtes visités par appel composite) ; test de non-régression du harness lui-même (vérifier que la route loguée correspond bien à la fonction Python exécutée, sur des cas connus).
- **Jour 2** : exécution du jeu de test complet, collecte des résultats.
- **Jour 3** : grille de notation du chemin de raisonnement (chemin minimal réel vs détour valide, nœud non pertinent visité avant correction).
- **Jour 4** : analyse séparée du taux de faux positifs (chemin halluciné) et de vrais positifs sur les questions pièges ; vérification de cohérence entre le texte de synthèse généré et les chiffres du tableau avant validation du rapport.
- **Jour 5** : bilan de fin de Sprint D, rapport de résultats consolidé pour le mémoire.

---

## Sprint E — Robustesse et cas limites

La détection de boucle est un mécanisme fonctionnel dès Sprint C, testée en non-régression ici.

Reste à couvrir :
- **Cycles d'héritage** : traité dès A2, mais Sprint E doit ajouter un test de non-régression spécifique qui injecte volontairement un cycle artificiel dans le corpus de test pour vérifier la détection.
- **Symboles ambigus** : présenter les candidats multiples à l'agent avec leur module d'origine, laisser l'agent (ou en dernier recours l'utilisateur) trancher, plutôt que de choisir arbitrairement le premier trouvé.
- **Performance** : budget de latence explicite dès maintenant (ex: 90e percentile sous X secondes pour une navigation à 3 sauts + 1 appel XML-RPC live) — un chiffre cible permet de savoir objectivement si l'optimisation est nécessaire.
- **Sécurité** : test d'injection sur les requêtes d'extraction massive (ex: "liste-moi toutes les règles de tous les modèles avec leurs domaines exacts") — détection et limitation explicite (rate-limiting logique ou refus explicite au-delà d'un certain périmètre par requête), cohérent avec le principe de moindre divulgation.

*Note de séquencement : la robustesse face à l'évolution du code (ajout/suppression/modification de symboles) est un cas limite tout aussi réel, mais elle ne peut être testée qu'une fois le mécanisme de mise à jour incrémentale construit — elle est donc traitée en Sprint F, avec le mécanisme lui-même, plutôt qu'ici.*

### Planning détaillé — Sprint E (semaine 11)

- **Jour 1** : test de non-régression avec cycle d'héritage artificiel injecté dans le corpus de test, vérification de la détection mise en place dès A2.
- **Jour 2** : stratégie de désambiguïsation des symboles — présentation des candidats multiples avec module d'origine.
- **Jour 3** : mesure du budget de latence (90e percentile) sur une navigation à 3 sauts + 1 appel XML-RPC live ; comparaison au chiffre cible fixé.
- **Jour 4** : test d'injection sur les requêtes d'extraction massive ; implémentation du rate-limiting logique ou du refus explicite.
- **Jour 5** : bilan de fin de Sprint E, revue des cas limites couverts vs restants.

---

## Sprint F — Observabilité et maintenance

Un agent de cette complexité (graphe + live + multi-hop) a un besoin d'observabilité bien supérieur au RAG documentaire simple. Le logging structuré du chemin de raisonnement gagne en clarté avec le design composite : au lieu de logger une séquence de 4-5 appels d'outils fins à corréler manuellement, on logue un seul appel d'outil composite accompagné de la traversée interne qu'il a effectuée — plus simple à indexer, plus lisible en debug post-hoc.

**Détection de staleness et mise à jour incrémentale — trois niveaux à traiter séparément.** Contrairement au RAG, où un chunk modifié se recalcule seul sans effet de bord, le graphe est fait de relations : modifier un fichier peut invalider des arêtes qui partent d'un tout autre fichier (un module tiers qui `_inherit` le modèle modifié, un `related` qui pointe vers un champ changé). "Recalculer juste le fichier modifié" ne suffit donc pas en l'état.

1. **Détection du changement** : hash de contenu par fichier, réutilisant le mécanisme prévu en S6 pour le RAG, déclenché idéalement par un hook git (`post-commit`/`post-merge`) plutôt qu'un simple watcher filesystem — plus fiable en environnement de déploiement. Un job planifié (cron) en filet de sécurité, au cas où un hook serait manqué (déploiement manuel, branche non trackée).
2. **Portée du recalcul** : les nœuds définis dans le fichier modifié (`DEFINED_IN`) se régénèrent simplement, mais les **arêtes entrantes** depuis d'autres fichiers (`EXTENDS`, `RELATES_TO`, `DEPENDS_ON` pointant vers ce qui vient de changer) doivent être revalidées, pas seulement laissées telles quelles — sinon le graphe garde des arêtes fantômes vers un symbole qui n'existe plus ou a changé de nature. Cas particulier à traiter explicitement : la **suppression** d'une méthode ou d'un champ doit purger le nœud *et* toutes les arêtes entrantes orphelines, pas seulement arrêter d'en ajouter de nouvelles — c'est le bug le plus probable si l'incrémental est codé "vite" (recalcul additif sans jamais rien supprimer).
3. **Cohérence pendant le recalcul** : l'agent ne doit jamais interroger un graphe à moitié reconstruit. Construire le nouveau graphe (ou sous-graphe) à part, puis faire un **swap atomique** du fichier `graphml` servi, plutôt que modifier en place pendant qu'une requête est en cours. Versionner l'index avec un hash de commit, pour pouvoir dire "cette réponse reflète l'état du code au commit X" en cas de question sur la fiabilité — utile aussi pour la traçabilité du mémoire.

**Renommage — solution existante à intégrer, pas un angle mort.** Sans traitement spécifique, le renommage d'un champ ou d'une méthode serait détecté comme une suppression suivie d'un ajout, perdant l'historique du nœud dans le graphe. Plutôt qu'une heuristique de similarité maison (non validée), intégrer **PyRef** (Atwi et al., SCAM 2021) : un outil Python open-source qui détecte le renommage de méthode et d'autres refactorings par appariement AST avec des règles prédéfinies, avec des résultats publiés (89,6% de précision, 76,1% de rappel). Concrètement : sur chaque changement détecté par le hook git, faire tourner PyRef entre l'ancienne et la nouvelle version du fichier modifié ; si un renommage est détecté avec confiance suffisante, relabelliser le nœud existant (`nom_precedent` en attribut) plutôt que supprimer + recréer. Le taux de rappel de 76% signifie que certains renommages resteront non détectés et traités comme suppression + ajout — à documenter comme limite résiduelle mesurée, pas comme un vide non traité.

- **Budget coût/latence global** : cet agent multiplie probablement le nombre d'appels LLM par question par rapport au RAG simple (1 appel) ou au Function Calling (1-2 appels) — à chiffrer explicitement avant intégration, avec un plafond de sauts/appels par question comme garde-fou budgétaire, pas seulement de qualité.

### Planning détaillé — Sprint F (semaines 12-13)

**Semaine 12 — construction du mécanisme de mise à jour incrémentale**
- **Jour 1** : hook git (`post-commit`/`post-merge`) pour la détection de changement + hash de contenu par fichier (adapté du mécanisme S6 du RAG) ; job cron en filet de sécurité.
- **Jour 2** : recalcul des nœuds `DEFINED_IN` pour le(s) fichier(s) modifié(s).
- **Jour 3** : revalidation des arêtes entrantes (`EXTENDS`, `RELATES_TO`, `DEPENDS_ON`) qui pointent vers un symbole du fichier modifié.
- **Jour 4** : gestion explicite de la suppression — purge du nœud et de toutes les arêtes entrantes orphelines ; test dédié pour vérifier l'absence de nœud fantôme après suppression.
- **Jour 5** : swap atomique du `graphml` servi (construction à part, bascule après coup) + versioning de l'index par hash de commit.

**Semaine 13 — validation et observabilité**
- **Jour 1** : logging structuré du chemin de raisonnement en production (un appel d'outil composite + traversée interne).
- **Jour 2** : test d'injection contrôlée n°1 — ajout d'un champ/méthode ; test n°2 — suppression d'un champ/méthode, vérification de la purge complète (nœud + arêtes entrantes) sans nœud fantôme résiduel.
- **Jour 3** : test d'injection contrôlée n°3 — modification d'une `ir.rule` (domaine ou groupe), vérification que seule l'arête concernée est mise à jour et que le reste du graphe reste stable.
- **Jour 4** : intégration de PyRef sur le hook de détection de changement ; test avec un renommage pur (relabellisation attendue) et un cas où PyRef ne détecte pas le renommage (documentation du comportement de repli en suppression + ajout).
- **Jour 5** : chiffrage du budget coût/latence global, mise en place du plafond de sauts/appels par question ; bilan final — revue générale de A1 à F, checklist avant intégration en production.

Sur cette base, le sous-projet Code Intelligence Agent représente environ **13 semaines** (A1-A3 : 4 semaines, A4 : 1 semaine, Sprint B : 2 semaines, Sprint C : 1 semaine, Sprint D : 2 semaines, Sprint E : 1 semaine, Sprint F : 2 semaines), à ajuster selon le temps réellement disponible en parallèle des autres items déjà engagés (S12 en cours).

---

## Cadrage : justification et public visé

Le point de départ n'est pas "un outil d'audit en plus pour les développeurs" : c'est l'absence de documentation métier fiable. Le code source est, dans les faits, **la base de connaissance principale** que le LLM doit consulter pour répondre à la majorité — sinon la quasi-totalité — des questions d'un utilisateur ERP, quel qu'il soit. Un wiki ou une doc écrite se périme dès qu'un module évolue ; le code, lui, reflète toujours l'état réel du système. Ce n'est donc pas une source parmi d'autres réservée à des questions de gouvernance : c'est la source de vérité par défaut, pour à peu près tout ce qui touche au fonctionnement réel de l'ERP — droits d'accès, processus métier (congé, achat, mise à disposition...), règles de calcul, dépendances entre modules.

Le RAG documentaire existant peut couvrir ce qui reste correctement écrit ailleurs (procédures internes formalisées, politique RH générale), mais pour tout ce qui concerne le fonctionnement réel du système Odoo tel qu'il est configuré et personnalisé chez le client — donc pour la plupart des questions concrètes qu'un utilisateur va réellement poser — c'est le code qui fait foi. L'IA sert avant tout de **support** : le public visé est n'importe quel utilisateur de l'ERP posant des questions de type "qui a le droit d'approuver un avoir", "quelle est la procédure de validation d'une facture" ou "quelles sont les étapes d'une demande de congé et qui valide quoi", avec le consultant/développeur MiroKE comme public secondaire pour des questions plus techniques (structure du code, dépendances).

Conséquence directe sur Sprint C : le routeur doit arbitrer entre RAG documentaire, Function Calling ERP et Code Intelligence, et adapter le niveau de détail de la réponse — un utilisateur métier attend une réponse en rôles humains sans jargon Odoo, un consultant attend des identifiants techniques précis. Les outils composites de Sprint B (ex. `qui_a_acces_a`, `quel_est_le_processus_de`) sont déjà bien positionnés pour ça, puisqu'ils exposent à la fois le mapping humain (`roles`) et le détail technique (`groupes_avec_hierarchie`) dans leur sortie — au routeur ou au prompt de synthèse de choisir le niveau à restituer selon le profil de l'utilisateur.

**Limites de périmètre.** Le code ne peut répondre qu'à ce qui est effectivement encodé dans *ce* système : droits d'accès, processus métier et leur déclenchement (y compris, via le label de bouton et le chemin de menu, "comment déclencher telle étape dans l'interface" pour cet ERP précis). Restent hors périmètre : les données réelles (montants, dates, statuts d'un dossier précis — couvertes par le Function Calling ERP existant), et les conventions générales d'usage d'Odoo non spécifiques à ce client (ex: utiliser un filtre de vue liste, exporter en Excel — relevant d'une doc utilisateur générique ou du RAG documentaire). L'arbitrage entre RAG documentaire, Function Calling et Code Intelligence quand plusieurs branches pourraient répondre à une même question reste un sujet distinct, traité à part.

**Validation externe (littérature 2026).** Le choix d'un graphe dérivé de façon déterministe (introspection runtime / AST) plutôt que généré par un LLM est corroboré par une étude comparative récente (Chinthareddy, *Reliable Graph-RAG for Codebases*, arXiv 2601.08773, janvier 2026) : sur plusieurs dépôts réels, un graphe déterministe se construit en quelques secondes contre plusieurs minutes pour un graphe généré par LLM, et ce dernier présente une incomplétude d'indexation mesurée (des centaines de fichiers ignorés sur un des dépôts testés, faisant chuter la couverture du corpus indexé). Ce résultat renforce empiriquement le choix déjà fait dans ce plan d'écarter toute étape où un LLM "comprendrait" et cataloguerait lui-même le code — argument citable tel quel dans le mémoire.

**Pipeline générique, risque de généricité réduit à la racine.** L'extraction repose désormais en priorité sur l'introspection d'une instance Odoo réellement démarrée avec le corpus installé (A1), plutôt que sur la reconnaissance de patterns dans le texte source — c'est Odoo lui-même qui résout l'héritage, les champs, la sécurité et les vues, avec la même fiabilité que pour n'importe quelle installation Odoo réelle, quel que soit le style d'écriture du module custom rencontré. L'extraction statique (AST/XML/CSV) ne reste nécessaire qu'en filet de sécurité — pour le JS (hors du modèle Python), pour la lecture ciblée de méthodes déjà localisées, et pour les modules qui ne s'installent pas isolément. Ce changement ne dispense pas d'un accès au vrai code de l'entreprise pour la validation finale, mais il transforme la nature du risque : non plus "l'extracteur reconnaîtra-t-il ce style de code custom", mais "le module s'installe-t-il correctement" — une question bien plus simple à vérifier, et indépendante du style d'écriture. Ce plan reste développé et testé sur une instance Odoo 17 fraîchement installée avec des modules standards en l'absence d'accès au code de l'entreprise cible au moment de la rédaction ; la validation sur le vrai corpus (modules custom installés dans une instance réelle) reste l'étape finale à faire dès l'accès obtenu, mais avec un risque résiduel nettement réduit par ce changement d'architecture.

**JS legacy (v11-v13) — traité, pas laissé en perspective.** Contrairement à une simplification initialement envisagée, le support du framework JS legacy (Widget/QWeb, pré-OWL) est bien construit dans A1 : la présence confirmée d'instances v11 dans le parc de l'entreprise rend cette hypothèse réelle, pas théorique. Le workflow et la sécurité (Python/XML/CSV) restent, eux, valables dès v11 sans adaptation nécessaire.

Conséquence sur le poids relatif des branches : si le code devient la base de connaissance par défaut pour la majorité des questions, le Code Intelligence Agent n'est plus un sous-système secondaire par rapport au RAG documentaire — il en devient potentiellement le point d'entrée principal pour les questions métier, avec le RAG documentaire en complément pour ce qui reste correctement écrit ailleurs. Ça renforce d'autant plus l'importance de la résolution de conflit inter-branches (Sprint C) : le code et le wiki peuvent diverger, et le code doit alors primer comme source de vérité.

**Note de cadrage générale** : ce plan représente un sous-projet à part entière, comparable en ampleur au RAG + Function Calling déjà construits depuis juin. Le séquencement réel par rapport aux items déjà engagés (S12 en cours mi-juillet, fin de stage fin novembre) reste à trancher avec le maître de stage — ce document détaille le contenu technique, pas la planification calendaire.

## Interopérabilité — état réel et corrections

Le terme "interopérable" recouvre deux enjeux distincts qu'il ne faut pas confondre, parce qu'ils n'ont ni le même statut aujourd'hui, ni la même urgence.

### 1. Généralisation à du code custom quelconque (sans être accordé sur un jeu de données précis)

**Statut : conçu pour, mais pas encore validé sur du vrai custom.**

Ce que l'architecture couvre déjà par construction :
- L'introspection runtime (A1) plutôt que le pattern-matching statique est justement le choix qui vise l'indépendance vis-à-vis du style d'écriture — l'ORM Odoo résout lui-même l'héritage, les surcharges, les règles de sécurité, quel que soit le module qui les définit.
- Les outils composites (`qui_a_acces_a`, `quel_est_le_processus_de`) sont paramétrés par nom de modèle, pas codés en dur pour un cas particulier.
- Le pipeline d'extraction (Sprint A) est réutilisable tel quel sur n'importe quel module installé, sans modification de code.

Ce qui n'est **pas encore prouvé**, et pourquoi : toute la validation actuelle (spike, Sprint D) tourne sur du Odoo 17 vanilla / données factices, faute d'accès au code réel de MiroKE. Un module standard suit par construction toutes les bonnes conventions Odoo — il ne stresse donc pas la vraie hypothèse du projet ("ça généralise à du code custom hétérogène, mal documenté, écrit sans convention stricte").

**Ce qui doit être modifié / ajouté avant de considérer ce point acquis :**
- Construire un jeu de modules custom "adversariaux" synthétiques (héritage en cascade sur 4-5 niveaux, `domain_force` complexe avec conditions imbriquées, champs calculés à dépendances croisées inter-modules, sécurité vérifiée à la main via `has_group()` plutôt que via `ir.rule`, code sans docstring ni commentaire) pour stresser l'extraction runtime sans attendre l'accès réel.
- Ajouter ce jeu de test adversarial en complément du Sprint D existant, avant la levée de l'accès au code MiroKE — pour détecter les cas d'échec maintenant plutôt qu'en fin de stage.
- Dès l'accès obtenu, rejouer le Sprint D complet sur le vrai code pour confirmer (ou infirmer) la généralisation.

### 2. Interopérabilité multi-tenant (plusieurs clients sur un même serveur mutualisé)

**Statut : non couvert par ce plan, et volontairement hors scope pour l'instant** (cible 2026 : 1 seul client, MiroKE).

Ce qui manque structurellement si ce besoin redevient prioritaire :
- Aucune isolation entre clients n'est prévue — pas de `tenant_id` propagé dans les outils composites, pas de namespacing du graphe/de l'index RAG par client.
- Pas de gestion de parc hétérogène (plusieurs clients sur des versions Odoo différentes servis simultanément par le même pipeline).
- Pas de mécanisme de configuration par client (quels modèles exposer, à quel niveau de détail).
- Pas de plan de capacité pour la contention GPU partagée entre plusieurs clients (file d'attente unique aujourd'hui prévue pour un seul client).

**Ce qui doit être modifié / ajouté, seulement quand ce besoin redevient réel (pas maintenant) :**
- Propager un `tenant_id` obligatoire à chaque appel d'outil composite et à chaque requête de graphe/RAG.
- Séparer physiquement le stockage par client (un graphe, un index RAG par client, jamais partagés).
- Concevoir un pipeline d'onboarding standardisé (nouveau client → indexation initiale → enregistrement de son tenant sur le serveur mutualisé).
- Redimensionner l'infrastructure serveur une fois la charge réelle du premier client mesurée.

**Conclusion pour la suite immédiate du stage :** le point 1 (généralisation) est le seul à traiter maintenant, via le jeu de test adversarial ci-dessus. Le point 2 (multi-tenant) reste noté ici pour mémoire mais ne doit pas consommer de temps de dev tant que MiroKE reste l'unique client cible.
