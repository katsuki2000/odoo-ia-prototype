# Retrieval Configuration & Evaluation — Step 3

## Configuration

| Parameter | Value |
|-----------|-------|
| Vector search `top_k` | 12 |
| BM25 search `top_k` | 12 |
| Vector weight | 0.7 |
| BM25 weight | 0.3 |
| RRF constant `k` | 60 |
| Relevance threshold | 0.3 |
| Cross-encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Final `top_k` | 5 |
| Re-ranker enabled | False |

## Results

**Overall recall@5**: 100.0%
  (target: ≥ 80%)

### Recall by Question Type

| Type | Recall | Count |
|------|--------|-------|

### Latency

- **Total questions evaluated**: 14
- **Total time**: 6590ms
- **Average per question**: 471ms

### Detailed Results

| # | Type | Hit | Time | Question |
|---|------|-----|------|----------|
| 1 | pdf |  | 639ms | Comment créer une facture client dans Odoo 17 ? |
| 2 | pdf |  | 509ms | Comment envoyer une facture par email depuis Odoo ? |
| 3 | pdf |  | 659ms | Comment créer un avoir (note de crédit) dans Odoo ? |
| 4 | pdf |  | 570ms | Comment configurer les relances automatiques dans Odoo ? |
| 5 | wiki |  | 460ms | Qui peut approuver une mise à disposition selon le wiki interne ? |
| 6 | wiki |  | 422ms | Quelle est la procédure de validation d'une facture selon le wiki ? |
| 7 | wiki |  | 420ms | Quels sont les modules Odoo considérés comme sensibles et qui y a accès ? |
| 8 | wiki |  | 416ms | Quel est le délai de traitement pour une demande de mise à disposition ? |
| 9 | pdf |  | 411ms | Qui doit approuver un avoir dans la politique interne de MIRO KE ? |
| 10 | pdf |  | 407ms | Quels sont les trois niveaux de relance disponibles dans Odoo ? |
| 34 | hors_perimetre |  | 411ms | Raconte-moi une blague sur les ERP. |
| 35 | hors_perimetre |  | 414ms | Quelle est la recette du gâteau au chocolat ? |
| 36 | hors_perimetre |  | 420ms | Qui a gagné la Coupe du Monde 2022 ? |
| 37 | hors_perimetre |  | 433ms | Peux-tu m'aider à écrire un poème sur la lune ? |

---

## Scope

> Single `odoo_docs` collection, permanent (todo/contexte.txt sections 
> 349-354): Code Intelligence owns code questions exclusively, this 
> pipeline is a docs-only, last-resort RAG fallback. `code_source` 
> benchmark questions are excluded from evaluation above, not scored 
> as failures.
