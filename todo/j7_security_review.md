# J7 — Revue de sécurité ligne à ligne du mécanisme Bloc 1

**Date** : 2026-07-31  
**Périmètre** : Tout le code qui implémente ou consomme la logique `ir.rule` / ACL CSV / hiérarchie de groupes / `with_user()` / `sudo()` / `has_group()`.  
**Critère plan** : *"Revue manuelle ligne à ligne documentée du mécanisme (pas seulement 'les tests passent')"*

---

## 1. Fichiers audités

| # | Fichier | Lignes | Rôle sécurité |
|---|---------|--------|---------------|
| 1 | [deterministic_tools.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py) | 894 | Algorithme AND/OR `ir.rule`, expansion groupes, `qui_a_acces_a`, `evaluer_regles_enregistrement` |
| 2 | [odoo_rpc_client.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/odoo_rpc_client.py) | 144 | Client XML-RPC live (`check_access_rights`, `search_as_user`, `check_access_rule`) |
| 3 | [live_rule_validator.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/live_rule_validator.py) | 277 | Comparaison déterministe vs Odoo live |
| 4 | [graph_builder.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/graph_builder.py) | 463 | Construction des arêtes `IMPLIES`, `RESTRICTED_BY`, `APPLIES_TO_GROUP`, `GRANTED_BY` |
| 5 | [xml_extractor.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/xml_extractor.py) | 688 | Parsing `ir.rule` depuis XML (`domain_force`, `groups_id`, `perm_*`, `active`) |
| 6 | [csv_extractor.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/csv_extractor.py) | 112 | Parsing ACL depuis `ir.model.access.csv` |

---

## 2. Algorithme AND/OR ir.rule — [deterministic_tools.py:186–336](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L186-L336)

### 2.1 Règles de combinaison Odoo

| Type de règle | Combinaison | Implémentation | Verdict |
|---|---|---|---|
| Règles globales (pas de groupe) | **AND** entre elles, s'appliquent à tous | L289–291 : `if not rule.groups → applied_global` | ✅ Correct |
| Règles de groupe (l'utilisateur est membre) | **OR** entre elles | L292–294 : `if _user_belongs_to_rule_group → applied_group` | ✅ Correct |
| Règles de groupe (l'utilisateur n'est PAS membre) | **IGNORÉES** | L295–296 : `else → ignored_group` | ✅ Correct |
| Combinaison finale | `(AND global) AND (OR group)` | L312–323 : conclusion textuelle fidèle | ✅ Correct |

### 2.2 `can_view_amount()` — [L48–81](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L48-L81)

> [!WARNING]
> **FINDING F-01 : Regex fragile pour extraction du seuil monétaire**
>
> ```python
> m = re.search(r"<=['\"\\s]*,['\"\\s]*(-?\d+(?:\.\d+)?)", rule.domain_force)
> ```
> Ce regex cherche un pattern `<=...,...,NOMBRE` dans le `domain_force` brut. Il fonctionne pour les cas du jeu adversarial (`[('amount_total','<=',50000)]`), mais **ne couvre pas** :
> - Opérateurs `<` (strictement inférieur) — seulement `<=`
> - Domains avec espaces dans les quotes différemment positionnées
> - Domains imbriqués ou multi-conditions (ex. `['&', ('amount_total','<=',50000), ('state','=','posted')]`)
>
> **Impact** : Faible pour le Bloc 1 (les `domain_force` testés sont simples). **Risque croissant** si appliqué à des modules custom avec domains complexes.
>
> **Recommandation** : Parser le `domain_force` comme une vraie expression Python (via `ast.literal_eval`) plutôt que par regex, dans un bloc ultérieur.

**Logique OR des règles de groupe** (L62–81) :

```python
if not self.applied_group_rules:
    return True  # No group rules → no group restriction
```

✅ **Correct** — conforme à Odoo : si l'utilisateur n'est membre d'aucun groupe ciblé par une règle, les règles de groupe sont ignorées et seules les globales s'appliquent.

```python
for rule in self.applied_group_rules:
    if dom in ("[(1, '=', 1)]", ...):  # catch-all
        return True
```

✅ **Correct** — détection des règles "tout autoriser".

> [!NOTE]
> **FINDING F-02 : `return True` dans le `else` du regex (L77–79)**
>
> ```python
> else:
>     # Group rule with no numeric limit → allows access
>     return True
> ```
> Si une règle de groupe a un `domain_force` que le regex ne matche pas ET qui n'est pas un catch-all, elle est traitée comme "accès illimité". C'est un **default-to-allow** silencieux.
>
> **Impact** : Correct pour les cas connus (rules sans seuil = accès libre). Mais un `domain_force` complexe non reconnu (ex. filtre sur `partner_id`) serait silencieusement traité comme "accès total".
>
> **Recommandation** : Logger un warning quand le regex ne matche pas pour traçabilité.

---

## 3. Expansion des groupes — [deterministic_tools.py:851–894](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L851-L894)

### 3.1 `_expand_implied_user_groups` (L851–871)

**Direction** : `G.out_edges` — suit les arêtes IMPLIES sortantes.  
**Sémantique** : `specific_group --IMPLIES--> broader_group` → l'utilisateur membre du groupe spécifique hérite automatiquement du groupe plus large.

✅ **Correct** — direction `out_edges` conforme à la convention `graph_builder.py` L213–215.

### 3.2 `_expand_inheriting_acl_groups` (L874–894)

**Direction** : `G.in_edges` — suit les arêtes IMPLIES entrantes.  
**Sémantique** : `higher_group --IMPLIES--> acl_group` → si un ACL accorde un droit à `acl_group`, tout groupe plus spécifique qui implique `acl_group` hérite aussi ce droit.

✅ **Correct** — direction `in_edges` conforme, inverse de la direction utilisateur.

### 3.3 Protection contre les cycles

> [!IMPORTANT]
> **FINDING F-03 : Pas de protection explicite contre les cycles dans l'expansion récursive**
>
> Les deux fonctions utilisent un `set` pour éviter de revisiter un groupe déjà ajouté (`if broader_group_id not in user_group_set`), ce qui **empêche effectivement la récursion infinie** même en présence d'un cycle dans le graphe.
>
> **Verdict** : ✅ Implicitement sûr grâce au guard `not in set`. Un cycle IMPLIES dans un graphe Odoo réel serait pathologique mais ne provoquerait pas de stack overflow.

### 3.4 Construction de l'arête IMPLIES — [graph_builder.py:202–215](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/graph_builder.py#L202-L215)

```python
for parent_grp in grp.implied_ids:
    parent_node_id = f"group:{parent_grp}"
    self.G.add_edge(grp_node_id, parent_node_id, edge_type="IMPLIES")
```

✅ **Correct** — `grp.implied_ids` contient les groupes impliqués PAR `grp` (c'est `grp` qui est le groupe spécifique). L'arête pointe du spécifique vers le large, conforme à la convention documentée.

---

## 4. Résolution tolérante de groupe — [deterministic_tools.py:87–183](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L87-L183)

### 4.1 `resolve_group_identifier` (L144–183)

Ordre de résolution :
1. **Exact match** sur `full_xml_id` — ✅
2. **Short-name match** (après le dernier `.`) — ✅
3. **Fuzzy match** contre le `display_name` — ✅

> [!NOTE]
> **FINDING F-04 : Ambiguïté potentielle en short-name**
>
> Le short-name match (L175–177) retourne le **premier** candidat dont le short-name correspond. Si deux modules différents définissent un groupe avec le même suffixe (ex. `mod_a.group_manager` et `mod_b.group_manager`), le premier trouvé dans l'itération l'emporte.
>
> **Impact** : Faible — les `candidate_full_xml_ids` sont déjà filtrés par modèle/contexte avant d'arriver ici. Un conflit réel supposerait deux groupes identiquement nommés sur le même modèle, ce qui est rare.
>
> **Recommandation** : Documenté comme limite connue, traité dans le Bloc 8 (Sprint E — symboles ambigus, J28–J29).

### 4.2 `_user_belongs_to_rule_group` (L244–287)

Même triple résolution, appliquée au contexte spécifique de l'évaluation `ir.rule`. 

✅ **Correct** — la tolérance ne touche que le matching d'identifiant, jamais la logique AND/OR.

### 4.3 Seuil fuzzy — [L84](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L84)

```python
FUZZY_GROUP_MATCH_THRESHOLD = 75
```

✅ **Acceptable** — calibré sur les cas J4 (`"regional"` vs `"Avoirs - Visibilite Regionale"` → score ~80+ avec `partial_ratio`).

---

## 5. `qui_a_acces_a` — [deterministic_tools.py:400–494](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L400-L494)

### 5.1 ACL evaluation — `_eval_single_droit` (L350–397)

```python
if acl_node.get(perm_attr, False):  # L367
```

✅ **Default-to-deny** pour les ACL : si le flag de permission n'existe pas, accès refusé.

```python
if rule_node.get(perm_attr, True):  # L380
```

✅ **Default-to-apply** pour les `ir.rule` : si le flag de permission n'existe pas, la règle s'applique (conforme à Odoo — `perm_read` etc. valent `True` par défaut).

### 5.2 Group non-résolution explicite — [L450–467](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L450-L467)

```python
if resolved_group_id is None and not all_authenticated:
    summary = "Group identifier '...' could not be resolved... This does NOT mean access is denied"
```

✅ **Correct** — distinction explicite entre "identifiant non résolu" et "accès refusé". Bug réel J4 corrigé.

---

## 6. Client XML-RPC — [odoo_rpc_client.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/odoo_rpc_client.py)

### 6.1 Authentification (L36–44)

```python
uid = self.common.authenticate(self.db, login, password, {})
if not uid:
    raise OdooRpcError(...)
self._password_by_uid[int(uid)] = password
```

✅ **Correct** — password stocké en mémoire (pas en disque), indexé par uid.

> [!WARNING]
> **FINDING F-05 : Mots de passe en mémoire non nettoyés**
>
> `_password_by_uid` accumule les mots de passe sans mécanisme de purge. Pour un client de test, c'est acceptable. Pour un usage production, il faudrait un `__del__` ou un context manager.
>
> **Impact** : Nul — ce client est exclusivement utilisé par les tests J5/J6.

### 6.2 `search_as_user` (L81–100)

```python
self._validate_operation(operation)          # L90
self.check_access_rights(uid, model_name, operation)  # L91
record_ids = list(self.execute_kw(uid, model_name, "search", [domain], kwargs))  # L97
if operation != "read" and record_ids:       # L98
    self.check_access_rule(uid, model_name, record_ids, operation)  # L99
```

✅ **Correct** — séquence conforme à Odoo :
1. Valider l'opération (whitelist `read/write/create/unlink`)
2. Vérifier les ACL via `check_access_rights`
3. Exécuter `search` (qui applique les `ir.rule` côté serveur)
4. Pour les opérations d'écriture, vérifier `check_access_rule` sur les IDs retournés

> [!NOTE]
> **Point d'attention** : Le `search` Odoo applique déjà les `ir.rule` côté serveur pour filtrer les résultats. Le `check_access_rule` en L99 est donc redondant pour `read` (d'où le `if operation != "read"`), mais nécessaire pour `write`/`create`/`unlink` où la vérification post-search est requise. ✅ Logique correcte.

### 6.3 `check_access_rule` — gestion du `None` marshalling (L103–128)

```python
except xmlrpc.client.Fault as exc:
    if "cannot marshal None" in exc.faultString:
        return True  # Success — Odoo returned None (= no violation)
    raise
```

✅ **Correct** — Odoo `check_access_rule` retourne `None` en cas de succès, ce qui cause un `Fault` marshalling avec `allow_none=False`. La distinction avec un vrai `AccessError` est correcte.

### 6.4 `set_user_password` (L130–135)

✅ **Correct** — uniquement appelé dans le setup de test pour configurer les utilisateurs de test.

### 6.5 Validation d'opération (L137–143)

```python
VALID_OPERATIONS = {"read", "write", "create", "unlink"}
```

✅ **Correct** — whitelist stricte, pas de `sudo()` ou d'opération arbitraire possible via ce client.

---

## 7. Validateur live — [live_rule_validator.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/live_rule_validator.py)

### 7.1 Flux de comparaison (L53–149)

```
authenticate_user → _user_group_xml_ids → _deterministic_acl_allows → evaluer_regles_enregistrement
                                        → search_as_user (live) → compare
```

✅ **Correct** — les groupes sont lus depuis Odoo live (`res.users.groups_id`), pas supposés.

### 7.2 `_deterministic_acl_allows` (L152–166)

```python
if acl_eval.all_authenticated_access:
    return True
if not acl_eval.allowed_groups:
    return False
for user_group in user_group_xml_ids:
    if resolve_group_identifier(G, user_group, acl_eval.allowed_groups):
        return True
return False
```

✅ **Correct** — default-to-deny explicite.

### 7.3 `_amount_from_domain` (L236–248)

✅ **Correct** — extraction conservatrice du montant depuis le domain de recherche. Retourne `None` si non trouvé, ce qui est traité comme "pas de restriction de montant" en L92–96.

> [!NOTE]
> Quand `amount` est `None`, `deterministic_record_rule_allowed` est mis à `True` (L95–96). C'est un **default-to-allow** pour les prédictions déterministes quand le montant n'est pas connu. Acceptable car la comparaison live corrigera de toute façon la divergence.

---

## 8. Extraction XML ir.rule — [xml_extractor.py:153–235](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/xml_extractor.py#L153-L235)

### 8.1 Champs capturés

| Champ | Parsé ? | Default Odoo | Default implémenté | Verdict |
|---|---|---|---|---|
| `name` | ✅ L201–202 | — | `""` | ✅ |
| `model_id` | ✅ L203–211 | — | `""` | ✅ (ref, eval, text) |
| `domain_force` | ✅ L212–213 | — | `""` | ✅ |
| `groups` / `groups_id` | ✅ L214–221 | — | `[]` | ✅ (ref et eval refs) |
| `perm_read` | ✅ L222–223 | `True` | `True` | ✅ |
| `perm_write` | ✅ L224–225 | `True` | `True` | ✅ |
| `perm_create` | ✅ L226–227 | `True` | `True` | ✅ |
| `perm_unlink` | ✅ L228–229 | `True` | `True` | ✅ |
| `active` | ✅ L230–231 | `True` | `True` | ✅ |

> [!IMPORTANT]
> **FINDING F-06 : Le champ `active` est parsé mais jamais filtré dans `graph_builder.py`**
>
> `xml_extractor.py` capture `active` (L230–231), mais `graph_builder.py` L218–243 ajoute les règles au graphe sans vérifier `rule.active`. Une règle avec `active=False` sera donc incluse dans le graphe et évaluée par `evaluer_regles_enregistrement`.
>
> **Impact** : Moyen — une règle désactivée dans Odoo serait traitée comme active par l'outil déterministe, produisant potentiellement un faux positif (restriction fantôme).
>
> **Recommandation** : Ajouter `if not rule.active: continue` dans `_add_security_group_nodes()` L218.

### 8.2 Parsing `groups_id` avec `eval` (L218–221)

```python
if field_eval:
    eval_refs = extract_refs_from_eval(field_eval)
    groups_list.extend(eval_refs)
```

✅ **Correct** — `extract_refs_from_eval` utilise un regex pour extraire les `ref('xml_id')` sans exécuter le code Python. Sûr contre l'injection.

---

## 9. Extraction ACL CSV — [csv_extractor.py](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/csv_extractor.py)

### 9.1 Règle `all_authenticated` (L78–84)

```python
if raw_group_id:
    group_id = raw_group_id
    all_authenticated = False
else:
    group_id = None
    all_authenticated = True
```

✅ **Correct** — conforme à Odoo : `group_id` vide dans le CSV = l'ACL s'applique à tous les utilisateurs authentifiés.

### 9.2 Defaults de permission (L86–89)

```python
perm_read = _parse_perm(row.get("perm_read"))  # Default: False
```

✅ **Correct** — default-to-deny pour les ACL CSV.

### 9.3 Variantes de headers (L68–76)

```python
model_id = row.get("model_id:id") or row.get("model_id/id") or row.get("model_id") or ""
group_id = row.get("group_id:id") or row.get("group_id/id") or row.get("group_id") or ""
```

✅ **Correct** — gère les trois variantes de format CSV Odoo.

---

## 10. Construction du graphe sécurité — [graph_builder.py:200–267](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/graph_builder.py#L200-L267)

### 10.1 Arêtes RESTRICTED_BY (L234–243)

```python
self.G.add_edge(model_node_id, rule_node_id, edge_type="RESTRICTED_BY")
```

✅ **Direction correcte** : `Model --RESTRICTED_BY--> Rule`. La traversée dans `evaluer_regles_enregistrement` utilise `G.neighbors(model_node)`, ce qui suit les arêtes sortantes — correct.

### 10.2 Arêtes APPLIES_TO_GROUP (L239–243)

```python
self.G.add_edge(rule_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")
```

✅ **Direction correcte** : `Rule --APPLIES_TO_GROUP--> Group`. Cohérent avec la traversée `G.neighbors(rule_neighbor)` dans `_eval_single_droit`.

### 10.3 Arêtes GRANTED_BY (L260–266)

```python
self.G.add_edge(model_node_id, acl_node_id, edge_type="GRANTED_BY")
self.G.add_edge(acl_node_id, grp_node_id, edge_type="APPLIES_TO_GROUP")
```

✅ **Direction correcte** : `Model --GRANTED_BY--> ACL --APPLIES_TO_GROUP--> Group`.

### 10.4 Qualification du module prefix pour groupes des règles (L240–241)

```python
mod_prefix = full_xml_id.split(".")[0] if "." in full_xml_id else "base"
full_grp = grp_ref if "." in grp_ref else f"{mod_prefix}.{grp_ref}"
```

✅ **Correct** — les `ref()` dans les XML de sécurité utilisent souvent des identifiants courts sans préfixe de module. Ce code qualifie correctement le groupe avec le module de la règle comme fallback.

---

## 11. Bug cosmétique identifié

> [!WARNING]
> **FINDING F-07 : Double décorateur `@dataclass` sur `RuleEvaluationResult`**
>
> [deterministic_tools.py:37–39](file:///home/user/odoo-ia-prototype/miro-rag/code_intelligence/deterministic_tools.py#L37-L39):
> ```python
> @dataclass
> @dataclass
> class RuleEvaluationResult:
> ```
> Le double `@dataclass` est inoffensif (le deuxième écrase le premier), mais c'est clairement un artefact de copier-coller.
>
> **Recommandation** : Supprimer le doublon.

---

## 12. Angles morts documentés (hors périmètre Bloc 1)

| # | Angle mort | Couche | Couvert par |
|---|---|---|---|
| A1 | `has_group()` dans le corps des méthodes Python | Procédural | Bloc 2 (Semgrep / `analyser_verrous_securite`) |
| A2 | `sudo()` dans les actions serveur | Procédural | Bloc 2 (lecture LLM du champ `code`) |
| A3 | Listes de logins codées en dur (`_VALIDATEURS_EXCEPTIONNELS`) | Procédural | Bloc 2 / Bloc 9 |
| A4 | Évaluation sémantique du `domain_force` (au-delà du regex montant) | Déclaratif avancé | Bloc 3 (Semgrep `domain=`) |
| A5 | Règles `ir.rule` créées dynamiquement en base (pas dans XML) | Runtime | Couvert par `live_rule_validator` |

---

## 13. Résumé des findings

| ID | Sévérité | Fichier | Ligne | Description | Action |
|---|---|---|---|---|---|
| **F-01** | 🟡 Faible | `deterministic_tools.py` | 56, 72 | Regex fragile pour seuil monétaire | Reporter au-delà du Bloc 1 |
| **F-02** | 🟡 Faible | `deterministic_tools.py` | 77–79 | Default-to-allow silencieux si regex ne matche pas | Ajouter logging |
| **F-03** | ✅ Résolu | `deterministic_tools.py` | 851–894 | Protection anti-cycle | Implicitement sûr via `set` |
| **F-04** | 🟡 Faible | `deterministic_tools.py` | 175–177 | Ambiguïté short-name entre modules | Bloc 8 (J28–J29) |
| **F-05** | ⚪ Info | `odoo_rpc_client.py` | 34, 40 | Mots de passe en mémoire | OK pour tests |
| **F-06** | 🟠 Moyen | `graph_builder.py` | 218 | Règles `active=False` non filtrées | **À corriger maintenant** |
| **F-07** | ⚪ Cosmétique | `deterministic_tools.py` | 37–38 | Double `@dataclass` | Supprimer le doublon |

---

## 14. Verdict global

> Le mécanisme Bloc 1 implémente **correctement** l'algorithme AND/OR des `ir.rule` Odoo, l'expansion bidirectionnelle des groupes `implied_ids`, et la séquence ACL-avant-ir.rule. Les defaults (`deny` pour les ACL, `apply` pour les ir.rule) sont conformes au comportement Odoo documenté.
>
> **Un seul finding actionnable immédiat** : F-06 (filtrer les règles `active=False` dans le graph builder). Les autres findings sont soit de sévérité faible et planifiés dans les blocs suivants, soit purement cosmétiques.

---

## 15. Prochaine étape

**Livrable J7 #2** : Rejeu du benchmark adversarial complet avec sortie brute conservée.
