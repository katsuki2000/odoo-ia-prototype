# Retrieval Configuration & Evaluation — Step 3

## Configuration

| Parameter | Value |
|-----------|-------|
| Vector search `top_k` | 12 |
| BM25 search `top_k` | 12 |
| Vector weight | 0.6 |
| BM25 weight | 0.4 |
| RRF constant `k` | 60 |
| Relevance threshold | 0.3 |
| Cross-encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Final `top_k` | 5 |
| Re-ranker enabled | False |

## Results

**Overall recall@5**: 61.1%
  (target: ≥ 80%)

### Recall by Question Type

| Type | Recall | Count |
|------|--------|-------|
| code | ⚠️ 25.0% | 8 |

### Latency

- **Total questions evaluated**: 22
- **Total time**: 25070ms
- **Average per question**: 1140ms

### Detailed Results

| # | Type | Hit | Time | Question |
|---|------|-----|------|----------|
| 1 | pdf | ✅ | 1330ms | Comment créer une facture client dans Odoo 17 ? |
| 2 | pdf | ✅ | 1172ms | Comment envoyer une facture par email depuis Odoo ? |
| 3 | pdf | ✅ | 1126ms | Comment créer un avoir (note de crédit) dans Odoo ? |
| 4 | pdf | ✅ | 1208ms | Comment configurer les relances automatiques dans Odoo ? |
| 5 | wiki | ✅ | 1123ms | Qui peut approuver une mise à disposition selon le wiki interne ? |
| 6 | wiki | ✅ | 1139ms | Quelle est la procédure de validation d'une facture selon le wiki ? |
| 7 | wiki | ✅ | 1113ms | Quels sont les modules Odoo considérés comme sensibles et qui y a accès ? |
| 8 | wiki | ✅ | 1132ms | Quel est le délai de traitement pour une demande de mise à disposition ? |
| 9 | pdf | ❌ | 1120ms | Qui doit approuver un avoir dans la politique interne de MIRO KE ? |
| 10 | pdf | ✅ | 1138ms | Quels sont les trois niveaux de relance disponibles dans Odoo ? |
| 11 | code | ❌ | 1140ms | Dans quel fichier sont définies les lignes de facture (account.move.line) ? |
| 12 | code | ❌ | 1122ms | Quelle classe gère les lignes de commande de vente (sale.order.line) ? |
| 13 | code | ✅ | 1108ms | Comment est structuré le modèle stock.move ? |
| 14 | code | ❌ | 1082ms | Comment est étendue la classe ResCompany dans le module sale ? |
| 15 | code | ❌ | 1108ms | Quelle classe gère les commandes de vente (sale.order) ? |
| 16 | code | ✅ | 1114ms | Quel est le rôle du modèle stock.warehouse ? |
| 17 | code | ❌ | 1143ms | Comment le journal comptable (account.journal) est-il défini ? |
| 18 | code | ❌ | 1087ms | Quels sont les modèles étendus dans le fichier payment_provider.py du module sal |
| 27 | hors_perimetre | ❌ | 1171ms | Raconte-moi une blague sur les ERP. |
| 28 | hors_perimetre | ❌ | 1131ms | Quelle est la recette du gâteau au chocolat ? |
| 29 | hors_perimetre | ❌ | 1108ms | Qui a gagné la Coupe du Monde 2022 ? |
| 30 | hors_perimetre | ❌ | 1156ms | Peux-tu m'aider à écrire un poème sur la lune ? |

---

## Collection Decision

> Based on evaluation results. If text/code confusion is observed,
> split into separate ChromaDB collections. Otherwise, keep one.

**Decision**: ⚠️ Consider splitting — doc recall (90.0%) vs code recall (25.0%) shows significant gap.