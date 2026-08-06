# Revue de code — mécanisme "chaîne de surcharge de méthode" (Bloc 8/9, 06/08/2026)

Revue faite à la demande de l'utilisateur, en lecture seule (`todo/real plan.md` non modifié).

## Priorité — à corriger en premier

**F5** (nouveau, ci-dessous) est le seul constat de cette revue qui est un bug
**confirmé en train de se produire**, pas une hypothèse : le benchmark de ce matin
(Q5.1, `todo/benchmark_run_bloc9_predispatch_v3_20260806_1145.log`) montre littéralement
la même action serveur analysée deux fois dans la réponse finale. F1 et F3 sont des
gaps réels mais pas (encore) observés en action ; F5 l'est.

## Appréciation générale

Le code est de bonne qualité, cohérent avec `todo/rules.md` : `try/except` systématique
autour des appels LLM et RPC, `.get()` défensif, docstrings qui expliquent le *pourquoi*
(pas juste le *quoi*) avec référence au bug réel trouvé et au test de non-régression
correspondant. La discipline "confiance FAIBLE fixe, jamais déduite par le LLM" pour
l'heuristique AST est bien respectée et bien documentée dans
`method_override_resolver.py`. Le garde structurel à deux étages
(`find_methods_with_override_cascade` puis `find_methods_with_unguarded_super`) pour
éviter d'exploser `CI_MAX_HOPS` est une bonne réponse à la régression déjà constatée
(17 hops) — c'est le genre de raisonnement en boucle courte (constat → fix → contre-test)
qui a produit F-06/F-08 plus tôt dans le plan.

---

## Élargissement (1) — mécanisme de chaîne de surcharge

Fichiers lus intégralement : `graph_builder.py`, `method_override_resolver.py`,
`ci_agent_tools.py`, `rag/graph.py` (le chemin complet : construction du graphe →
détection déterministe → pré-dispatch forcé → synthèse).

### F1 — Lecture de fichier non protégée dans deux outils composites (Rule 6)

**Où** :
- `method_override_resolver.py`, fonction `analyser_chaine_surcharge_methode`, boucle
  `for idx, site in enumerate(sites, start=1): ... source = p.read_text(encoding="utf-8")`
- `ci_agent_tools.py`, fonction `analyser_verrous_securite`, boucle
  `for fp in sorted(filepaths): ... code = p.read_text(encoding="utf-8")`

**Constat** : dans les deux cas, `p.read_text(...)` est appelé sans `try/except`, alors
que la même opération (lire un fichier source localisé via le graphe) EST protégée un
peu plus haut dans le même fichier, dans `find_methods_with_unguarded_super` :

```python
try:
    source = p.read_text(encoding="utf-8")
except OSError:
    continue
```

`rules.md` (Règle 6) demande d'encapsuler systématiquement "tout appel [...] hors base
de données" — la lecture de fichier en fait explicitement partie, et le projet applique
déjà cette règle à côté, dans la même fonction/fichier. C'est donc une incohérence
locale plutôt qu'un oubli général.

**Pourquoi c'est plus qu'un style nitpick** : une méthode surchargée dans 3 modules
(le cas réel VIP) est composée de 3 "sites" lus en boucle. Si UN SEUL site lève une
exception (permission, fichier supprimé entre la construction du graphe et l'exécution
de la requête, encodage non-UTF-8, etc.), l'exception remonte, sort de `_impl`, et est
interceptée de façon générique par l'appelant (`code_intelligence_agent` dans
`rag/graph.py`, `except Exception as te: logger.error(...)`) — ce qui fait perdre
**toute** l'analyse pour les 3 modules, y compris les 2 sites qui se seraient lus sans
problème. Le comportement voulu (cohérent avec `find_methods_with_unguarded_super` et
avec l'esprit défensif du reste du projet) est de sauter le site en échec et de
continuer avec les autres, pas de faire échouer tout l'outil pour un seul fichier
capricieux. Même remarque pour `analyser_verrous_securite`, qui boucle sur plusieurs
fichiers Python d'un même modèle.

**Correctif suggéré** (même style que le code existant) :

```python
# method_override_resolver.py, analyser_chaine_surcharge_methode
p = Path(site.filepath)
if not p.exists():
    continue
try:
    source = p.read_text(encoding="utf-8")
except OSError as e:
    _logger.warning("Could not read %s for override-chain analysis: %s", site.filepath, e)
    continue
```

```python
# ci_agent_tools.py, analyser_verrous_securite
for fp in sorted(filepaths):
    p = Path(fp)
    if not p.exists():
        continue
    try:
        code = p.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning("Could not read %s for security lock analysis: %s", fp, e)
        continue
    analysis = analyze_python_security_locks(code, fp)
    summaries.append(analysis.summary_text)
```

### F2 — Constante dupliquée dans `ci_agent_tools.py`

**Où** : `WILDCARD_MODEL_ERROR_MSG` est défini deux fois, mot pour mot, à environ
30 lignes d'écart (une fois avant `_is_wildcard_model`, une fois juste avant la section
"COMPOSITE TOOLS").

**Impact** : aucun bug fonctionnel (la seconde définition écrase la première avec une
valeur identique), mais ça viole la règle "clean code" du projet et crée un risque de
divergence silencieuse si quelqu'un modifie une occurrence sans repérer l'autre lors
d'une future revue de sécurité J32-J33 (le message concerne justement la politique de
sécurité sur l'extraction massive — pas l'endroit idéal pour une incohérence qui passe
inaperçue).

**Correctif suggéré** : supprimer la deuxième définition, garder la première.

### Points vérifiés et jugés corrects (pas d'action requise)

- `resoudre_chaine_surcharge_methode` : l'inversion `list(reversed(sites))` pour passer
  de l'ordre de chargement manifest à l'ordre d'exécution réel est correcte et bien
  justifiée en docstring (MRO Odoo : le module le plus dépendant s'exécute en premier).
- `_UnguardedSuperVisitor` : heuristique volontairement étroite (une seule forme de
  bug), limites explicitement documentées plutôt que présentées comme une détection
  générale — cohérent avec la discipline "confiance FAIBLE" du reste du projet.
- Le garde à deux étages dans `rag/graph.py`
  (`find_methods_with_override_cascade` → `find_methods_with_unguarded_super`) est
  bien la bonne réponse structurelle à la régression 17-hops mentionnée dans le
  commentaire : le filtre coûteux (lecture de fichier + AST) n'est déclenché que sur
  les candidats déjà réduits par le filtre gratuit (graphe seul).
- Le `gate_observation` (Bloc 7) est appliqué de façon cohérente sur les 3 dispatches
  forcés (`analyser_verrous_securite`, `analyser_actions_serveur`,
  `analyser_chaine_surcharge_methode`) — aucun des trois ne contourne le gating comme
  l'ancien bug de bloc-entier le permettait.
- La signature de `find_methods_with_unguarded_super(G, model_name, method_names)` dans
  `method_override_resolver.py` correspond exactement à l'appel fait depuis
  `rag/graph.py` — pas de dérive d'API entre les deux fichiers créés/modifiés le même
  jour.

---

## Élargissement (2) — `authorization_gate.py`, `semgrep_locks_analyzer.py`,
## `server_action_analyzer.py`, `deterministic_tools.py`, `utils.py`

### Bon point à signaler d'abord

`authorization_gate.py` protège déjà correctement sa lecture de fichier
(`_extract_has_group_xmlids_from_source`) :

```python
try:
    code = p.read_text(encoding="utf-8")
except Exception:
    continue
```

C'est exactement le patron manquant dans F1 — la preuve que le bon réflexe existe déjà
ailleurs dans le projet, ce qui renforce l'idée que F1 est un oubli localisé plutôt
qu'un choix délibéré.

### F3 — `semgrep_locks_analyzer.py` : le "fallback regex" ne renforce jamais l'AST, contrairement à ce que dit le commentaire

**Où** : `analyze_python_security_locks`, section "2. Regex fallback / reinforcement".

**Constat** : les trois blocs de secours (`hardcoded_logins`, `dynamic_dispatch_types`,
`exception_messages`) sont chacun gardés par `if not result.X:` — c'est-à-dire qu'ils ne
s'exécutent QUE si l'AST n'a RIEN trouvé du tout pour cette catégorie. Le commentaire dit
pourtant "fallback **/ reinforcement**", ce qui suggère une intention de renforcer les
résultats de l'AST, pas seulement de compenser un `SyntaxError`.

Concrètement, pour les emails/logins en dur : `visit_Assign` ne détecte que les emails
présents dans une liste/tuple/set littéral assigné à une variable
(`_VALIDATEURS_EXCEPTIONNELS = ["a@b.com", ...]`). Un email codé en dur comme simple
constante scalaire (`ADMIN_OVERRIDE_EMAIL = "a@b.com"`) n'est jamais visité par
`visit_Assign` (qui filtre sur `ast.List/Tuple/Set`). Le seul filet de sécurité pour ce
cas est le fallback regex `_EMAIL_PATTERN.findall(code)` — mais celui-ci ne se déclenche
que si `result.hardcoded_logins` est encore vide. Si le même fichier contient à la fois
une liste de logins privilégiés (détectée par l'AST) ET, ailleurs, une constante scalaire
avec un autre email privilégié, ce second email ne sera **jamais** signalé.

**Pourquoi c'est plus qu'un détail** : c'est l'analyseur qui alimente
`SENSITIVE_BYPASS_MARKER` (Bloc 7) — le mécanisme qui décide quoi montrer ou cacher selon
les droits du demandeur repose sur ce que cet analyseur détecte. Un email privilégié
raté silencieusement n'est pas juste une réponse incomplète : c'est un contournement de
sécurité réel qui reste invisible même pour un demandeur habilité à le voir.

**Correctif suggéré** : faire tourner le fallback regex sur les emails de façon
inconditionnelle et fusionner (dédupliquer) avec les résultats AST, plutôt que de le
sauter dès que l'AST a trouvé quelque chose :

```python
# 2. Regex reinforcement (toujours exécuté, fusionné avec l'AST plutôt que
# de le remplacer -- un email en dur en dehors d'une liste/tuple/set
# littéral, ex. une simple constante scalaire, n'est jamais vu par
# visit_Assign, qui ne visite que les collections littérales).
emails = _EMAIL_PATTERN.findall(code)
for e in emails:
    if e not in result.hardcoded_logins:
        result.hardcoded_logins.append(e)
```

(Les fallbacks `dynamic_dispatch_types` et `exception_messages` sont moins critiques :
l'AST couvre déjà de façon quasi exhaustive les formes syntaxiquement valides pour ces
deux catégories, donc le gain d'un passage "reinforcement" y est plus faible — mais la
même correction de fond s'applique si on veut que le commentaire du code reste honnête.)

### F4 — `deterministic_tools.py`, `_user_belongs_to_rule_group` : étape 3 redondante (pas un bug, juste du travail inutile)

**Où** : `evaluer_regles_enregistrement._user_belongs_to_rule_group`, "Step 3: fuzzy
match against display name".

**Constat** :

```python
for rule_group in rule_groups:
    if resolve_group_identifier(G, next(iter(user_groups_set), ""), [rule_group]) or any(
        _group_fuzzy_matches_display_name(G, ug, rule_group) for ug in user_groups_set
    ):
        return True
```

`resolve_group_identifier(...)` re-teste en interne le match exact et le match par nom
court (Steps 1 et 2), déjà écartés juste au-dessus dans la même fonction — donc à ce
stade ce sont deux vérifications mortes. Pire, il ne le fait que sur **un seul** groupe
de l'utilisateur pris arbitrairement (`next(iter(user_groups_set), "")`, un `set` n'a pas
d'ordre garanti), alors que le `any(...)` juste après teste bien TOUS les groupes de
l'utilisateur par fuzzy matching. Le résultat final n'est pas faux — le `any(...)` à
droite du `or` couvre tous les cas — mais l'appel à `resolve_group_identifier` ne sert à
rien d'autre qu'à consommer du temps de calcul et à rendre la lecture du code plus
confuse (on croirait qu'il teste quelque chose que le `any()` ne teste pas).

**Correctif suggéré** : simplifier en gardant uniquement le `any(...)`, qui est déjà
suffisant et correct :

```python
for rule_group in rule_groups:
    if any(_group_fuzzy_matches_display_name(G, ug, rule_group) for ug in user_groups_set):
        return True
```

### Point à faire confirmer par l'équipe (pas un bug tranché) — `can_view_amount`

Dans `RuleEvaluationResult.can_view_amount`, quand une règle de groupe APPLICABLE a un
`domain_force` qui ne correspond à aucun des formats reconnus (ni le motif `<=`, ni les
littéraux "illimité" codés en dur `[(1,'=',1)]` / `[('id','!=',False)]`), le code retourne
`True` par défaut ("Group rule with no numeric limit ... allows access"). C'est cohérent
avec la sémantique OU d'Odoo entre règles de groupe SI cette règle ne porte vraiment pas
sur le montant (une règle sur le département, par exemple, ne restreint pas la
*visibilité par montant*). Mais si un jour une règle de groupe combine un seuil de
montant avec une syntaxe que le regex ne reconnaît pas (ex. `'<'` strict au lieu de
`'<='`, ou un seuil exprimé autrement), le comportement actuel serait de l'autoriser par
défaut plutôt que de refuser par défaut — l'inverse de la discipline "fail closed"
appliquée ailleurs dans le projet (`_resolve_user_group_xmlids`, `authorization_gate.py`).
Je ne le classe pas comme un bug confirmé (je n'ai pas de cas réel du jeu adversarial qui
le déclenche), mais ça vaut la peine de le signaler comme un point à vérifier avec le
maître de stage, vu que Bloc 1 est sécurité-critique et que "fail closed" y est un
principe explicite ailleurs dans le projet.

### Autres fichiers de ce lot, jugés corrects

- `server_action_analyzer.py` : même discipline que `method_override_resolver.py`
  (confiance FAIBLE fixe, couche LLM bornée avec set de confiance fermé, dégradation
  systématique vers `None` sur toute réponse malformée). `SENSITIVE_BYPASS_MARKER`
  appliqué de façon cohérente (sudo() et IDs en dur marqués, has_group() et incertitude
  dynamique explicitement non marqués, avec commentaire justifiant chaque choix).
- `utils.py` : `format_file_link` et `resolve_model_xmlref` corrects sur tous les cas
  couverts par leurs docstrings. Limite théorique mineure sur `resolve_model_xmlref` :
  un nom de modèle technique déjà pointé (pas un xmlref) qui contiendrait littéralement
  "model_" après un point (cas très improbable en pratique dans Odoo) serait mal
  interprété comme un xmlref -- non bloquant, juste une note pour info.

---

## Élargissement (3) — `business_resolver.py`, `cross_file_resolver.py`, `atomic_graph_swap.py`, `sourcing_guard.py`

### F5 — Le bug F-08 (J7) n'a été corrigé QUE pour les Rules ; le même défaut existe encore pour les ServerActions, et se manifeste DÉJÀ dans le benchmark d'aujourd'hui

**Où** :
- Racine : `cross_file_resolver.py`, `build_module_symbol_registry`, Pass 1. Pour
  `groups`, `rules`, `actions`, `server_actions`, `base_automations`, `menuitems`,
  `views`, le même patron est répété partout :
  ```python
  registry.server_actions[full_xml_id] = sa
  registry.server_actions[sa.xml_id] = sa   # même objet, sous une DEUXIÈME clé (courte, non qualifiée)
  ```
  C'est exactement le mécanisme qui causait F-08 pour les `rules` (déjà corrigé, J7).
- Côté consommateur non protégé : `graph_builder.py`, `_add_security_group_nodes`,
  section 4 (Server Actions) :
  ```python
  for full_xml_id, sa in self.registry.server_actions.items():
      sa_node_id = f"server_action:{full_xml_id}"
      self.G.add_node(sa_node_id, node_type="ServerAction", ...)
  ```
  Aucun filtre `if "." not in full_xml_id: continue` ici, contrairement à la boucle
  `rules` juste au-dessus dans la même méthode (le filtre qui a corrigé F-08). Résultat :
  **deux** nœuds `ServerAction` sont créés pour la même action réelle — un sous
  `server_action:{module}.{xml_id}` et un sous `server_action:{xml_id}` (sans préfixe de
  module) — tous deux avec une arête `TARGETS_MODEL` vers le même modèle.
- Côté impact observable : `ci_agent_tools.py`, `find_server_action_nodes` scanne
  **tous** les nœuds `ServerAction` du graphe (`for node, attrs in G.nodes(data=True): if
  attrs.get("node_type") == "ServerAction"`) et retourne les deux doublons. L'outil
  `analyser_actions_serveur` boucle ensuite sur cette liste et analyse (et rapporte) la
  même action deux fois.

**Preuve dans le benchmark d'aujourd'hui** (`benchmark_run_bloc9_predispatch_v3_20260806_1145.log`,
Q5.1, "Est-ce que tous les avoirs fournisseurs passent par les mêmes règles
d'approbation ?") :

> - L'analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' indique que cet action serveur automatise la validation d'avoirs reçus de trois fournisseurs spécifiques, en contournant les règles d'accès et les ACL via sudo().
> - L'analyse du code de l'action serveur 'ir_action_server_avoir_fournisseur_privilegie' est similaire à celle du précédent.

C'est la MÊME action serveur, analysée deux fois, une fois avec la clé qualifiée, une
fois avec la clé courte -- exactement le mécanisme décrit ci-dessus. Ce n'est donc pas
une hypothèse : c'est visible dans la sortie brute d'aujourd'hui.

**Pourquoi c'est plus gênant qu'un doublon cosmétique** : ça gaspille un hop de contexte
(le texte dupliqué compte double dans la limite de troncature à 1200 caractères des
dispatches forcés, dans `rag/graph.py`), ça peut faire dépasser `CI_MAX_HOPS` plus vite
sur une question qui touche plusieurs actions serveur, et surtout ça peut semer le doute
côté synthèse LLM ("est-ce que ce sont deux actions différentes qui font la même
chose, ou vraiment la même ?") -- un risque de confusion pour une information
sécurité-critique (contournement sudo()).

**Correctif suggéré** : reproduire exactement le fix J7 (F-08), déjà appliqué à `rules`,
sur les `server_actions` (et, par cohérence/hygiène, sur `groups` et `base_automations`,
qui ont le même défaut structurel même si je n'ai pas trouvé de consommateur qui les
scanne exhaustivement aujourd'hui -- donc bug latent, pas encore observé) :

```python
# graph_builder.py, _add_security_group_nodes, section 4
for full_xml_id, sa in self.registry.server_actions.items():
    if "." not in full_xml_id:
        continue
    sa_node_id = f"server_action:{full_xml_id}"
    ...

for full_xml_id, ba in self.registry.base_automations.items():
    if "." not in full_xml_id:
        continue
    ba_node_id = f"automation:{full_xml_id}"
    ...
```

Et, même section, groupes :
```python
for full_xml_id, grp in self.registry.groups.items():
    if "." not in full_xml_id:
        continue
    grp_node_id = f"group:{full_xml_id}"
    ...
```

### Autres fichiers de ce lot, jugés corrects

- `business_resolver.py` (cœur du Bloc 0) : l'ordre alias statique → fuzzy → arbitrage
  LLM borné est bien respecté (conforme à la note de régression du plan sur J1/J2). La
  pénalité de longueur dans `_fuzzy_match_graph` ne s'applique qu'aux labels plus courts
  que la requête, jamais aux labels plus longs -- cohérent avec le docstring. L'arbitrage
  LLM est bien borné à une liste fermée de candidats, avec dégradation propre vers
  "unresolved" si le LLM répond `NONE`, une valeur hors-liste, ou échoue. Note pour
  info (pas un bug nouveau, juste une reconnaissance de portée) : le cas 1-token/1-token
  sans pénalité de longueur qui a causé le bug originel (`avoirs` vs label de champ)
  reste possible pour un terme métier qui n'est PAS encore dans `BUSINESS_ALIASES` --
  la table d'alias traite les cas connus au coup par coup, elle ne corrige pas la
  vulnérabilité structurelle sous-jacente pour un terme futur non répertorié. C'est un
  compromis déjà assumé par le plan (alias = liste courte maintenue à la main), pas une
  régression de ma part.
- `_build_fuzzy_index` (même fichier) met en cache l'index par `id(G)` (identité mémoire
  de l'objet graphe). Aujourd'hui sans impact (le graphe est un singleton construit une
  fois par processus, jamais remplacé en mémoire), mais ça deviendra un piège latent dès
  que le Bloc 10 (staleness / swap, `atomic_graph_swap.py`) sera branché sur le chemin de
  requête en direct : `atomic_graph_swap.py` fait aujourd'hui un swap **fichier**
  (`os.replace` sur le JSON servi), pas un swap d'objet Python en mémoire -- donc tant que
  personne n'ajoute un rechargement du graphe en cours de vie du processus, ce n'est pas
  un problème actif. Mais le jour où `get_code_intelligence_graph()` (rag/graph.py)
  recharge un nouveau graphe après un swap, l'ancien objet peut être garbage-collecté et
  son `id()` réutilisé par le nouvel objet -- `_FUZZY_INDEX_CACHE` servirait alors un
  index fuzzy PÉRIMÉ pour le nouveau graphe, silencieusement. À garder en tête pour
  Bloc 10 (J40-41), pas à corriger maintenant.
- `sourcing_guard.py` (Bloc 4 / J14) : vérification mécanique correcte -- la citation
  de fichier est considérée vérifiée si son intervalle de lignes est un SOUS-ensemble
  d'un intervalle réellement produit par un outil (pas une égalité stricte, ce qui est
  le bon choix : le LLM peut légitimement citer un sous-extrait). Les xml_id non
  préfixés par `xml_id:` sont correctement exclus de la vérification (vocabulaire
  normal, pas une revendication de sourcing) -- évite les faux positifs.

---

## Non couvert par cette revue

Fichiers encore non lus : `xml_extractor.py`, `python_extractor.py`, `csv_extractor.py`,
`manifest_parser.py`, `semgrep_runner.py`, `live_rule_validator.py`,
`graph_staleness_detector.py`, `graph_symbol_refactor.py`, `incremental_event_logger.py`,
`reasoning_trace_logger.py`, `odoo_rpc_client.py`, ainsi que tout `miro-rag/tools/` (les
outils ORM) et `miro-rag/api/`. Dites-moi si vous voulez que je continue -- notamment sur
`python_extractor.py`/`xml_extractor.py` puisque ce sont les fichiers qui produisent les
données brutes dont dépend tout le reste (une erreur d'extraction s'y propagerait
silencieusement partout en aval).
