# 🧠 Plan d'implémentation — Step 4b : Routeur Hybride + Outil Data

> **Objectif :** Résoudre les 11 questions en échec du benchmark (63.3% → ≥90%) en ajoutant un routeur intelligent et un outil d'agrégation de données structurées au pipeline LangGraph existant.

---

## Diagnostic des échecs actuels

| Catégorie | Échecs | Cause racine |
|-----------|--------|--------------|
| **ERP (ventes)** | 6/8 | Le LLM ne peut pas sommer/compter/filtrer des données numériques depuis du texte brut |
| **ERP (tickets)** | 2/8 | `top_k=5` insuffisant + LLM ne sait pas compter des enregistrements |
| **Code source** | 3/8 | Réponses correctes mais terminologie légèrement différente (ex: `sale.order` vs `saleorder`) — problème d'éval, pas de pipeline |

> [!IMPORTANT]
> Les 3 échecs CODE sont des **faux négatifs** du script d'éval (le LLM répond correctement mais avec des mots légèrement différents). On corrigera l'éval, pas le pipeline.

---

## Architecture cible

```
START → retrieve → route → ─┬─ [documentaire] → generate → format_output → END
                             │
                             └─ [données_erp]  → data_query → format_output → END
```

### Nouveau nœud : `route`
Après la récupération des chunks, un classifieur léger (basé sur les métadonnées des chunks) décide :
- **Si ≥50% des chunks ont `type` = `sale` ou `ticket`** → branche `data_query`
- **Sinon** → branche `generate` (pipeline actuel)

### Nouveau nœud : `data_query`
Un outil Python qui :
1. Charge les fichiers JSON bruts (`sales.json`, `tickets.json`)
2. Utilise le LLM pour générer une **intention structurée** (filtre + agrégation)
3. Exécute l'opération en Python pur (pas de code LLM exécuté)
4. Retourne le résultat formaté dans un `AssistantResponse`

---

## Plan d'implémentation détaillé

### Day 1 : Routeur + Intent Schema

**Fichiers modifiés :**
- `rag/schemas.py` — ajouter `DataQueryIntent` et `QueryRoute`
- `rag/graph.py` — ajouter le nœud `route` et le branchement conditionnel

**Tâches :**

1. **Créer `QueryRoute` enum** dans `schemas.py` :
   ```python
   class QueryRoute(str, Enum):
       DOCUMENTAIRE = "documentaire"
       DONNEES_ERP = "donnees_erp"
   ```

2. **Créer `DataQueryIntent`** dans `schemas.py` :
   ```python
   class DataQueryIntent(BaseModel):
       data_source: str  # "sales" | "tickets"
       operation: str    # "sum" | "count" | "filter" | "list" | "max" | "min"
       filters: dict     # ex: {"client": "Société Dupont", "statut": "facturé"}
       target_field: str  # ex: "montant"
   ```

3. **Implémenter le nœud `route`** dans `graph.py` :
   - Analyser les métadonnées des chunks récupérés
   - Si la majorité des chunks sont de type `sale` ou `ticket` → `QueryRoute.DONNEES_ERP`
   - Sinon → `QueryRoute.DOCUMENTAIRE`
   - Stocker la route dans le state

4. **Modifier `RAGState`** pour inclure `route: Optional[str]`

5. **Modifier `build_graph()`** pour ajouter le branchement conditionnel :
   ```python
   workflow.add_conditional_edges("route", route_decision, {
       "documentaire": "generate",
       "donnees_erp": "data_query"
   })
   ```

**Règles `rules.md` appliquées :**
- `.get()` pour tous les accès dict (Règle 4)
- `try/except` autour du routage (Règle 6)
- Logging exhaustif à chaque décision (Partie 3, §2)

---

### Day 2 : Outil Data Query

**Fichiers créés :**
- `rag/data_tool.py` — moteur d'exécution des requêtes structurées

**Tâches :**

1. **Créer `DataQueryEngine`** dans `rag/data_tool.py` :
   - Méthode `load_data(source: str) -> list[dict]` : charge `sales.json` ou `tickets.json`
   - Méthode `execute(intent: DataQueryIntent) -> str` : applique filtres + agrégation
   - Opérations supportées :
     - `sum` : somme d'un champ numérique (ex: montant total)
     - `count` : nombre d'enregistrements filtrés
     - `filter` : liste d'enregistrements matchant les critères
     - `list` : liste tous les enregistrements (avec limite)
     - `max` / `min` : valeur extrême d'un champ

2. **Implémenter le nœud `data_query`** dans `graph.py` :
   - Utiliser le LLM avec `with_structured_output(DataQueryIntent)` pour extraire l'intention
   - Passer l'intention au `DataQueryEngine`
   - Construire un `AssistantResponse` avec le résultat formaté
   - En cas d'erreur → fallback vers le nœud `generate` classique

3. **Prompt spécialisé pour l'extraction d'intention** dans `rag/prompts.py` :
   ```
   Tu dois analyser la question et extraire l'intention de requête.
   Sources disponibles : "sales" (ventes), "tickets" (support).
   Champs sales : id, client, produit, montant, devise, date, statut
   Champs tickets : id, titre, client, description, solution, statut, date
   ```

**Règles `rules.md` appliquées :**
- Division par zéro protégée sur les agrégations (Règle 1)
- `if/elif/else` exhaustif pour chaque opération (Règle 5)
- `try/except` sur le chargement JSON (Règle 6)

---

### Day 3 : Tests + Correction de l'éval

**Fichiers modifiés :**
- `tests/test_graph.py` — nouveaux tests pour le routeur et le data tool
- `tests/eval_rag.py` — corriger les faux négatifs CODE

**Tâches :**

1. **Tests unitaires pour `DataQueryEngine`** :
   - `test_sum_sales_by_client()` — vérifier la somme pour Société Dupont
   - `test_count_tickets_by_status()` — vérifier le compte des tickets résolus
   - `test_filter_sales_en_cours()` — vérifier le filtrage par statut
   - `test_empty_filter_returns_all()` — vérifier le cas sans filtre

2. **Tests unitaires pour le routeur** :
   - `test_route_erp_chunks()` — chunks de type sale → route données_erp
   - `test_route_doc_chunks()` — chunks de type pdf/wiki → route documentaire
   - `test_route_mixed_chunks()` — chunks mixtes → route majoritaire

3. **Corriger `eval_rag.py`** pour les faux négatifs CODE :
   - Rendre la vérification des keywords case-insensitive ET flexible :
     - Accepter `sale.order` OU `saleorder` OU `SaleOrder`
     - Accepter `stock.warehouse` OU `stockwarehouse` OU `StockWarehouse`
   - Accepter un match partiel sur les mots composés (ex: `res.company` matche `rescompany`)

4. **Relancer le benchmark complet** et viser ≥ 90%

---

### Day 4 : Polish + Edge Cases

**Tâches :**

1. **Gérer les cas limites du routeur** :
   - Question mixte (ex: "Quelle est la procédure de facturation et combien de factures avons-nous ?")
   - Question ERP mais aucun chunk trouvé → fallback gracieux
   - Question avec filtre ambigu (ex: "les ventes récentes" → définir "récent" = 3 derniers mois)

2. **Ajouter un cache** pour `DataQueryEngine.load_data()` :
   - Ne pas recharger le JSON à chaque requête
   - Utiliser `functools.lru_cache` ou un singleton

3. **Enrichir les réponses data** avec le contexte :
   - Ajouter "Détail :" avec la liste des enregistrements individuels
   - Format monétaire correct : `5 300 000 Ar` (avec espaces)

4. **Mettre à jour la documentation** :
   - Mettre à jour le README avec l'architecture hybride
   - Documenter les opérations supportées par le `DataQueryEngine`

---

## Critères de succès

| Métrique | Avant | Cible |
|----------|-------|-------|
| Score global benchmark | 63.3% (19/30) | ≥ 90% (27/30) |
| Questions documentaires | 10/10 ✅ | 10/10 |
| Questions code source | 5/8 | 8/8 (après fix eval) |
| Questions ERP | 0/8 | ≥ 7/8 |
| Questions hors périmètre | 4/4 ✅ | 4/4 |

---

## Fichiers impactés

| Fichier | Action |
|---------|--------|
| `rag/schemas.py` | Ajouter `QueryRoute`, `DataQueryIntent` |
| `rag/graph.py` | Ajouter nœuds `route`, `data_query` + branchement conditionnel |
| `rag/data_tool.py` | **Nouveau** — moteur d'exécution des requêtes structurées |
| `rag/prompts.py` | Ajouter prompt d'extraction d'intention |
| `tests/test_graph.py` | Nouveaux tests routeur + data tool |
| `tests/eval_rag.py` | Corriger faux négatifs CODE |
