# Plan d'implémentation J5 — Validation `ir.rule` & ACL (Live Odoo + Modèle Déterministe Enrichi)

## Objectif
Acter l'évaluation exacte d'Odoo 17 sur le contrôle d'accès (`ir.model.access` / ACL) et la combinaison des règles de sécurité (`ir.rule`) via `with_user().search()`.

---

## Principes & Règles d'exécution

1. **TDD strict** : Les tests d'abord (`test_j5_live_validation.py`) encodent les 2 divergences constatées comme assertions qui échouent avant d'être résolues.
2. **Support multi-opérations** : Prise en compte explicite de la granularité d'accès (`read`, `write`, `create`, `unlink`) dans la vérification des ACL et ir.rules.
3. **Périmètre étanche (Pas de Scope Creep J6)** : J5 se focalise exclusivement sur `ir.model.access` + `ir.rule`. La gestion fine du contexte système (`company_id`, `lang`, `date`) reste réservée à J6.
4. **Validation DoD complète** : Rejeu obligatoire du benchmark adversarial end-to-end complet (25 cas de test) avant de valider J5.

---

## Étapes d'Implémentation

### Étape 1 : Client RPC Dédié (`odoo_rpc_client.py`)
- Wrapper XML-RPC réutilisable pour interroger l'instance Odoo en direct.
- Proposer :
  - `authenticate_user(login, password)`
  - `check_access_rights(uid, model_name, operation='read')` -> vérifie les ACL (`ir.model.access`).
  - `search_as_user(uid, model_name, domain, operation='read')` -> exécute la recherche sous l'identité de l'utilisateur.

### Étape 2 : Tests TDD d'abord (`code_intelligence/tests/test_j5_live_validation.py`)
- Écrire la suite de tests unitaires/intégration :
  - `test_no_group_user_blocked_by_acl()` : Vérifie que `test_no_group_2026` subit une interdiction ACL d'abord (AccessError).
  - `test_regional_user_override_by_billing_group()` : Reproduit l'invalidation du plafond 50k lorsque le groupe Billing est actif (combinaison OR en Odoo).
  - `test_both_groups_user_access()` : Valide l'accès aux montants illimités.
  - Paramétrage explicite de l'opération (`read`, `write`, etc.).

### Étape 3 : Interpréteur & Enrichissement Déterministe (`deterministic_tools.py` & `live_rule_validator.py`)
- Enrichir `qui_a_acces_a` et `evaluer_regles_enregistrement` :
  - Intégrer un contrôle ACL préalable (`ir.model.access`) selon l'opération demandée (`read`/`write`/`create`/`unlink`). Si l'ACL est absente pour l'utilisateur/ses groupes, rejeter immédiatement sans évaluer les `ir.rule`.
  - Charger/Considérer l'ensemble des règles `ir.rule` (y compris les règles d'origine Odoo comme `(1, '=', 1)`) dans la résolution déterministe si le graphe est complet.

### Étape 4 : Validateur d'Écart Live (`live_rule_validator.py`)
- Un outil de diagnostic croisé qui compare la prédiction déterministe avec `with_user().search()` en direct et signale tout écart fonctionnel (ex: sur-autorisation par une règle OR résiduelle).

### Étape 5 : Rejeu du Benchmark Adversarial End-to-End
- Exécuter `python3 -m code_intelligence.evaluation.eval_harness`.
- Conserver le rapport `eval_report_sprint_d.md` (DoD).
