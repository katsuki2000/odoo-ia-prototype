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
| Re-ranker enabled | True |

## Results

**Overall recall@5**: 87.5%
  (target: ≥ 80%)

### Recall by Question Type

| Type | Recall | Count |
|------|--------|-------|
| code | ✅ 87.5% | 8 |

### Latency

- **Total questions evaluated**: 22
- **Total time**: 148758ms
- **Average per question**: 6762ms

### Detailed Results

| # | Type | Hit | Time | Question |
|---|------|-----|------|----------|
| 1 | pdf | ✅ | 22130ms | Comment créer une facture client dans Odoo 17 ? |
| 2 | pdf | ✅ | 6529ms | Comment envoyer une facture par email depuis Odoo ? |
| 3 | pdf | ✅ | 6547ms | Comment créer un avoir (note de crédit) dans Odoo ? |
| 4 | pdf | ✅ | 7059ms | Comment configurer les relances automatiques dans Odoo ? |
| 5 | wiki | ✅ | 4536ms | Qui peut approuver une mise à disposition selon le wiki interne ? |
| 6 | wiki | ✅ | 7453ms | Quelle est la procédure de validation d'une facture selon le wiki ? |
| 7 | wiki | ✅ | 7300ms | Quels sont les modules Odoo considérés comme sensibles et qui y a accès ? |
| 8 | wiki | ✅ | 4052ms | Quel est le délai de traitement pour une demande de mise à disposition ? |
| 9 | pdf | ✅ | 4149ms | Qui doit approuver un avoir dans la politique interne de MIRO KE ? |
| 10 | pdf | ✅ | 7697ms | Quels sont les trois niveaux de relance disponibles dans Odoo ? |
| 11 | code | ✅ | 6671ms | Dans quel fichier sont définies les lignes de facture (account.move.line) ? |
| 12 | code | ✅ | 6378ms | Quelle classe gère les lignes de commande de vente (sale.order.line) ? |
| 13 | code | ✅ | 6236ms | Comment est structuré le modèle stock.move ? |
| 14 | code | ❌ | 9768ms | Comment est étendue la classe ResCompany dans le module sale ? |
| 15 | code | ✅ | 5903ms | Quelle classe gère les commandes de vente (sale.order) ? |
| 16 | code | ✅ | 5876ms | Quel est le rôle du modèle stock.warehouse ? |
| 17 | code | ✅ | 5269ms | Comment le journal comptable (account.journal) est-il défini ? |
| 18 | code | ✅ | 9934ms | Quels sont les modèles étendus dans le fichier payment_provider.py du module sal |
| 27 | hors_perimetre | ❌ | 3154ms | Raconte-moi une blague sur les ERP. |
| 28 | hors_perimetre | ❌ | 3253ms | Quelle est la recette du gâteau au chocolat ? |
| 29 | hors_perimetre | ❌ | 2968ms | Qui a gagné la Coupe du Monde 2022 ? |
| 30 | hors_perimetre | ❌ | 5896ms | Peux-tu m'aider à écrire un poème sur la lune ? |

---

## Collection Decision

> Based on evaluation results. If text/code confusion is observed,
> split into separate ChromaDB collections. Otherwise, keep one.

**Decision**: ⚠️ Consider splitting — doc recall (0.0%) vs code recall (87.5%) shows significant gap.