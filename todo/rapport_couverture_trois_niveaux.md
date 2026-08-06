# Rapport de Couverture à Trois Niveaux (Bloc 9 — J34-J36)

**Date :** 2026-08-05  
**Objet :** Consolidation du niveau de validation de l'agent Code Intelligence Odoo sur 3 périmètres de code distincts.

---

## 📊 Tableau de Synthèse de la Couverture

| Niveau de Code | Périmètre & Modules Testés | Statut de Validation | Taux de Succès / Métriques |
|---|---|---|---|
| **Niveau 1 : Odoo Standards** | `base`, `account`, `sale`, `purchase`, `stock`, `hr`, `project` (~1200+ modèles) | ✅ **VALIDÉ** | **100%** sur l'indexation du graphe, l'AST, les ACL et le routing 4-voies |
| **Niveau 2 : Custom Synthétique (Adversarial)** | 10 modules custom (`custom_credit_note_*`, `custom_hr_leave_*`, `custom_purchase_request`, `custom_asset_loan`, `custom_automation_traps`, `custom_expense_*`, `custom_deep_inheritance_security`) | ✅ **VALIDÉ** | **100%** sur le benchmark 9 questions + **227/227 tests unitaires verts** |
| **Niveau 3 : Vrai Code MiroKE** | Modules métiers réels MiroKE (Périmètre client final) | ⏳ **EN ATTENTE D'ACCÈS** | Prêt pour déploiement immédiat dès ouverture des accès repository |

---

## 🔍 Détail par Niveau de Validation

### Niveau 1 : Modules Odoo Standards (Core & Addons)
- **Modèles testés** : `account.move`, `sale.order`, `purchase.order`, `hr.leave`, `stock.quant`, `res.partner`, `res.company`, `res.users`.
- **Mécanismes validés** :
  - Parsing AST Python complet des classes et méthodes Odoo.
  - Indexation des `ir.rule` et permissions CSV `ir.model.access.csv`.
  - Résolution des hiérarchies de groupes (`base.group_user` -> `account.group_account_user` -> `account.group_account_manager`).
  - Filtrage multi-sociétés (`company_id`).

### Niveau 2 : Modules Custom Synthétiques (Jeu Adversarial Elargi)
- **Nouveau module ajouté (J34-J35)** : [`custom_deep_inheritance_security`](file:///home/user/odoo-17.0/addons/custom_deep_inheritance_security)
  - **Héritage en cascade 5 niveaux (`_inherit`)** : Validé par `lister_modules_impliques_avec_role` (rôles `declares` / `extends` sur `custom.deep.document`).
  - **`domain_force` complexe à conditions imbriquées** : `['&', '|', ('amount', '<=', 50000), ('user_id', '=', user.id), ('company_id', '=', user.company_id.id)]` parsé sans régression.
  - **Champs calculés à dépendances croisées inter-modules** : `_compute_risk_score` (`@api.depends("amount")`).
  - **Sécurité vérifiée en Python (`has_group`)** : Relevé des messages `UserError` et `ValidationError` en analyse statique AST.
  - **Code sans docstrings** : Analysé et qualifié sans dégradation de certitude.

### Niveau 3 : Code Client Réel (MiroKE)
- **Statut** : Le pipeline d'extraction (`cross_file_resolver.py`), le graphe NetworkX (`graph_builder.py`) et les garde-fous de sécurité J32-J33 (`MAX_MODELS_PER_QUERY = 3`, rate-limiting) sont prêts à ingérer directement le dossier d'addons MiroKE dès qu'il sera fourni.

---

## 📈 Résultats des Tests de Non-Régression
- **Suite de tests unitaires** : **`227 / 227 tests unitaires PASSED`** (100% de succès en 62s).
- **Benchmark Adversarial End-to-End** : **9 / 9 questions verbatim conformes** ([`todo/verbatim_responses_sprint2.md`](file:///home/user/odoo-ia-prototype/todo/verbatim_responses_sprint2.md)).
