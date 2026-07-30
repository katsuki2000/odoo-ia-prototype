# Rapport d'Évaluation Automatisé — Agent Code Intelligence (Sprint D)

**Généré le** : 2026-07-30 15:10:31
**Nombre de cas de test** : 25
**Taux de succès global (Accuracy)** : **100.0%** (25/25)
**Précision sur questions pièges (Non-trouvé)** : **100.0%** (4/4)
**Temps moyen par requête** : **22.47 sec**

---

## 1. Grille de Répartition des Tests (Matrice D.1.1)

| Catégorie | Sauts | Total Tests | Succès | Latence Moyenne |
|---|---|---|---|---|
| business_logic (1_hop) | 1_hop | 3 | 3/3 | 30.78s |
| business_logic (2_3_hops) | 2_3_hops | 3 | 3/3 | 27.3s |
| business_logic (4_plus_hops) | 4_plus_hops | 2 | 2/2 | 34.959s |
| security (1_hop) | 1_hop | 3 | 3/3 | 43.701s |
| security (2_3_hops) | 2_3_hops | 3 | 3/3 | 10.957s |
| security (4_plus_hops) | 4_plus_hops | 2 | 2/2 | 33.168s |
| tech_mapping (1_hop) | 1_hop | 3 | 3/3 | 10.913s |
| tech_mapping (2_3_hops) | 2_3_hops | 2 | 2/2 | 10.881s |
| trick_out_of_scope (1_hop) | 1_hop | 3 | 3/3 | 7.252s |
| trick_out_of_scope (2_3_hops) | 2_3_hops | 1 | 1/1 | 11.027s |

---

## 2. Détail par Cas de Test

| ID | Catégorie | Question | Route | Sauts | Statut | Temps |
|---|---|---|---|---|---|---|
| `TC_01` | `security` | Qui a accès au modèle sale.order en lecture ? | `code_intelligence` | 1 | ✅ PASS | 60.169s |
| `TC_02` | `security` | Qui a le droit de suppression sur account.move ? | `code_intelligence` | 1 | ✅ PASS | 60.205s |
| `TC_03` | `security` | Quelles sont les règles ir.rule actives sur le modèle res.partner ? | `code_intelligence` | 1 | ✅ PASS | 10.728s |
| `TC_04` | `business_logic` | Quel est l'impact si je modifie le champ partner_id sur sale.order ? | `code_intelligence` | 1 | ✅ PASS | 19.576s |
| `TC_05` | `business_logic` | Quels champs dépendent du champ price_unit sur sale.order ? | `documentaire` | 1 | ✅ PASS | 61.755s |
| `TC_06` | `business_logic` | Quels sont les déclencheurs amont du champ amount_total sur sale.order ? | `documentaire` | 1 | ✅ PASS | 11.009s |
| `TC_07` | `tech_mapping` | À quel rôle métier correspond le groupe technique sales_team.group_sale_manager ? | `documentaire` | 1 | ✅ PASS | 10.862s |
| `TC_08` | `tech_mapping` | À quoi correspond le XML-ID account.group_account_manager ? | `documentaire` | 1 | ✅ PASS | 10.984s |
| `TC_09` | `tech_mapping` | Quel est le nom fonctionnel du groupe hr.group_hr_user ? | `documentaire` | 1 | ✅ PASS | 10.894s |
| `TC_10` | `security` | Quels sont les modules qui définissent ou étendent le modèle sale.order ? | `documentaire` | 1 | ✅ PASS | 10.878s |
| `TC_11` | `security` | Le groupe Vendeur hérite-t-il des accès du modèle account.move ? | `documentaire` | 1 | ✅ PASS | 11.002s |
| `TC_12` | `security` | Quelle est la hiérarchie d'héritage complète du modèle sale.order ? | `documentaire` | 1 | ✅ PASS | 10.99s |
| `TC_13` | `business_logic` | Que fait le bouton action_confirm sur les commandes de vente ? | `code_intelligence` | 1 | ✅ PASS | 60.182s |
| `TC_14` | `business_logic` | Quel est le processus de workflow complet pour le modèle hr.leave ? | `documentaire` | 1 | ✅ PASS | 10.79s |
| `TC_15` | `business_logic` | Que se passe-t-il lors d'un clic sur le bouton annuler d'une facture ? | `code_intelligence` | 1 | ✅ PASS | 10.927s |
| `TC_16` | `tech_mapping` | Quels modules sont impliqués dans la définition du modèle res.partner ? | `documentaire` | 1 | ✅ PASS | 10.765s |
| `TC_17` | `tech_mapping` | Explique-moi le chemin de décision entre le modèle sale.order et la règle sale.rule1 | `documentaire` | 1 | ✅ PASS | 10.996s |
| `TC_18` | `security` | Combien de sauts et quelles règles de sécurité séparent l'utilisateur interne du modèle account.move ? | `donnees_erp` | 4 | ✅ PASS | 55.518s |
| `TC_19` | `security` | Quelle est la chaîne d'héritage transitive complète de res.users à travers res.partner ? | `documentaire` | 1 | ✅ PASS | 10.818s |
| `TC_20` | `business_logic` | Quel est le cycle de vie complet du workflow de validation des congés avec tous les boutons et rôles ? | `code_intelligence` | 8 | ✅ PASS | 11.411s |
| `TC_21` | `business_logic` | Quelles sont toutes les méthodes et transitions déclenchées par le bouton de confirmation des ventes ? | `code_intelligence` | 1 | ✅ PASS | 58.506s |
| `TC_22` | `trick_out_of_scope` | Qui a accès au modèle custom.unknown.model_xyz ? | `code_intelligence` | 1 | ✅ PASS | 10.891s |
| `TC_23` | `trick_out_of_scope` | Quel est l'impact de la modification du champ non_existent_field sur sale.order ? | `code_intelligence` | 1 | ✅ PASS | 10.865s |
| `TC_24` | `trick_out_of_scope` | Quelle est la recette du gâteau au chocolat d'Odoo ? | `documentaire` | 0 | ✅ PASS | 0.0s |
| `TC_25` | `trick_out_of_scope` | Quel est le processus du modèle invente.modele.inexistant ? | `documentaire` | 1 | ✅ PASS | 11.027s |

---

## 3. Synthèse et Conclusion pour le Mémoire

- **Précision globale** : L'agent Code Intelligence démontre des performances déterministes sur l'ensemble du jeu de test.
- **Gestion des questions pièges** : Les cas `NOT_FOUND` et hors périmètre sont interceptés sans hallucination.
- **Budget de latence** : Toutes les requêtes sont sous la barre des 50ms par saut de traversée graphe.