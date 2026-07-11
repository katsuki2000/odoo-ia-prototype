# Rapport de Vérification RBAC et Filtrage Record-Level (Step 14)

**Date** : 11 Juillet 2026  
**Branche** : `phase-4`  
**Auteurs** : Équipe Prototype IA & Odoo 17  
**Statut** : ✅ **TOUS LES TESTS VALIDÉS (100% Succès)**

---

## 1. Vue d'Ensemble & Objectifs

L'Étape 14 (`Step 14: RBAC + access control`) a pour but de garantir que l'assistant conversationnel IA et ses outils ORM respectent rigoureusement les frontières de sécurité et les droits d'accès définis dans Odoo 17 via deux mécanismes complémentaires :
1. **Filtrage des Outils par Compétences (RBAC Tool Filtering - Day 1 & Day 3)** : Le backend interroge dynamiquement les groupes Odoo de l'utilisateur demandeur via XML-RPC (`res.users` → `groups_id`), fait correspondre ces groupes aux 4 catégories de compétences de l'IA (`ventes`, `stocks`, `comptabilite`, `tickets`), et n'expose à l'Agent LLM (via `.bind_tools()`) **que** les fonctions autorisées par son profil.
2. **Enforcement des Règles d'Enregistrement (`ir.rule` Record-Level Security - Day 2)** : Chaque requête ORM émise par l'IA est exécutée sous le `uid` exact de l'utilisateur demandeur (et non sous l'identité administrateur globale). Odoo applique automatiquement et nativement ses règles de sécurité sur les enregistrements (`ir.rule`) et le cloisonnement multi-sociétés (`res.company`).

---

## 2. Profils Utilisateurs et Cartographie des Compétences

Pour vérifier le comportement de bout en bout, l'environnement de test (`create_day2_setup.py`) a configuré les profils spécialisés suivants dans l'instance Odoo 17 Docker (`http://odoo:8069`) :

| Utilisateur Odoo | UID | Société (`res.company`) | Groupes Odoo Assignés | Compétences IA (`skills`) | Outils ORM Accessibles (`bind_tools`) |
| :--- | :---: | :---: | :--- | :--- | :--- |
| **Admin (`admin`)** | `2` | Toutes | Superuser / Tous Groupes | `ventes: True`<br>`stocks: True`<br>`comptabilite: True`<br>`tickets: True` | **Tous les 8 outils** (`obtenir_total_ventes`, `obtenir_stock_produit`, `obtenir_statut_commande`, `obtenir_total_factures`, `rechercher_client`, `obtenir_tickets_recents`, `lister_produits_en_rupture`, `obtenir_ca_periode`) |
| **Charlie Sales (`charlie@alpha.com`)** | `8` | Alpha (`2`) | `sales_team.group_sale_salesman` | `ventes: True`<br>`stocks: False`<br>`comptabilite: False`<br>`tickets: False` | `rechercher_client`, `obtenir_total_ventes`, `obtenir_statut_commande`, `obtenir_ca_periode` |
| **Diana Support (`diana@beta.com`)** | `11` | Beta (`3`) | `project.group_project_user` (Helpdesk) | `ventes: False`<br>`stocks: False`<br>`comptabilite: False`<br>`tickets: True` | `rechercher_client`, `obtenir_tickets_recents` |
| **Fiona Finance (`fiona@beta.com`)** | `9` | Beta (`3`) | `account.group_account_invoice` | `ventes: False`<br>`stocks: False`<br>`comptabilite: True`<br>`tickets: False` | `rechercher_client`, `obtenir_total_factures` |
| **Bob Stock (`bob@alpha.com`)** | `7` | Alpha (`2`) | `stock.group_stock_user` | `ventes: False`<br>`stocks: True`<br>`comptabilite: False`<br>`tickets: False` | `rechercher_client`, `obtenir_stock_produit`, `lister_produits_en_rupture` |
| **Alice CEO (`alice@alpha.com`)** *(Cas Multi-Groupes)* | `6` | Alpha (`2`) | `group_sale_salesman` + `group_project_user` | `ventes: True`<br>`stocks: False`<br>`comptabilite: False`<br>`tickets: True` | `rechercher_client`, `obtenir_total_ventes`, `obtenir_statut_commande`, `obtenir_ca_periode`, `obtenir_tickets_recents` |
| **Utilisateur Sans Groupe (`uid=9999`)** *(Cas Portail/Zéro Droit)* | `9999` | N/A | Aucun groupe ERP pertinent | `ventes: False`<br>`stocks: False`<br>`comptabilite: False`<br>`tickets: False` | `rechercher_client` (uniquement outil de base / général) |

---

## 3. Résultats de Validation : Enforcement `ir.rule` & Requêtes ORM (Day 2)

La suite de test dédiée `tests/test_ir_rule_enforcement_profiles.py` vérifie 15 requêtes réelles (5 par profil : Admin, Sales User Charlie, Support User Diana) sous l'identité XML-RPC `_get_password_for_uid(uid)` :

| # | Profil Demandeur | Type de Requête & Modèle | Résultat Attendu par `ir.rule` / RBAC | Statut Test | Observation & Moteur |
| :-: | :--- | :--- | :--- | :-: | :--- |
| **Q1** | Admin (`uid=2`) | `sale.order` (Statut commande Alpha) | Accès complet, retourne le statut S00001 | ✅ **PASSED** | L'administrateur peut lire toutes les commandes |
| **Q2** | Admin (`uid=2`) | `account.move` (CA Société Alpha) | Accès complet, retourne le montant total CA | ✅ **PASSED** | Agrégation financière multi/inter-sociétés fonctionnelle |
| **Q3** | Admin (`uid=2`) | `stock.quant` (Disponibilité Bureaux) | Accès complet, retourne la quantité en stock | ✅ **PASSED** | Lecture directe des stocks multi-entrepôts |
| **Q4** | Admin (`uid=2`) | `account.move` (Factures Impayées) | Accès complet, retourne le total des factures ouvertes | ✅ **PASSED** | Accès sans restriction aux pièces comptables |
| **Q5** | Admin (`uid=2`) | `helpdesk.ticket` (Tickets Récents) | Accès complet, retourne la liste des tickets | ✅ **PASSED** | Accès aux tickets du support ou `project.task` |
| **Q6** | Sales Charlie (`uid=8`) | `sale.order` (Statut commande Alpha) | Accès autorisé (Société Alpha, Groupe Ventes) | ✅ **PASSED** | `ir.rule` autorise la lecture du bon de commande |
| **Q7** | Sales Charlie (`uid=8`) | `res.partner` (Recherche Client) | Accès autorisé (Répertoire partenaires partagé/autorisé) | ✅ **PASSED** | `search_read` sur `res.partner` retourne les coordonnées |
| **Q8** | Sales Charlie (`uid=8`) | `account.move` (Société Beta - Factures) | **Blocage / Restriction** (`ir.rule` / `skills["comptabilite"]=False`) | ✅ **PASSED** | `obtenir_total_factures` exclu de l'IA ; ORM direct sur Company Beta `account.move` retourne `len == 0` ou lève `Access Denied` |
| **Q9** | Sales Charlie (`uid=8`) | `stock.quant` (Outils Stocks) | **Restriction Outil** (`skills["stocks"]=False`) | ✅ **PASSED** | `obtenir_stock_produit` non exposé au LLM pour un commercial |
| **Q10** | Sales Charlie (`uid=8`) | `helpdesk.ticket` (Outils Support) | **Restriction Outil** (`skills["tickets"]=False`) | ✅ **PASSED** | `obtenir_tickets_recents` non exposé au LLM pour un commercial |
| **Q11** | Support Diana (`uid=11`)| `helpdesk.ticket` (Tickets Beta) | Accès autorisé (Société Beta, Groupe Helpdesk/Projet) | ✅ **PASSED** | Diana peut lire les tickets de support ou tâches projets |
| **Q12** | Support Diana (`uid=11`)| `res.partner` (Recherche Client) | Accès autorisé (`rechercher_client` / `res.partner`) | ✅ **PASSED** | Lecture du carnet d'adresses client |
| **Q13** | Support Diana (`uid=11`)| `sale.order` (Commandes Alpha) | **Blocage / Restriction** (`skills["ventes"]=False`) | ✅ **PASSED** | `obtenir_statut_commande` exclu des outils pour le support |
| **Q14** | Support Diana (`uid=11`)| `account.move` (Comptabilité) | **Blocage / Restriction** (`skills["comptabilite"]=False`) | ✅ **PASSED** | `obtenir_total_factures` exclu ; accès `account.move` restreint par `ir.rule` |
| **Q15** | Support Diana (`uid=11`)| `stock.quant` (Stocks / Quantités) | **Blocage / Restriction** (`skills["stocks"]=False`) | ✅ **PASSED** | `obtenir_stock_produit` non accessible à l'utilisateur support |

**Exécution Pytest (`test_ir_rule_enforcement_profiles.py`)** :
```text
tests/test_ir_rule_enforcement_profiles.py::TestIRRuleEnforcementProfiles::test_q01_admin_order_status PASSED
tests/test_ir_rule_enforcement_profiles.py::TestIRRuleEnforcementProfiles::test_q02_admin_total_ca PASSED
...
tests/test_ir_rule_enforcement_profiles.py::TestIRRuleEnforcementProfiles::test_q15_diana_unauthorized_stock_tools_and_rules PASSED
============================= 15 passed in 24.22s =============================
```

---

## 4. Résultats de Validation : Vérification Assistant IA & Cas aux Limites (Day 3)

La suite de test dédiée `tests/test_rbac_assistant_queries.py` valide la chaîne de décision complète dans le graphe LangGraph (`query_graph`) lors de requêtes en langage naturel :

### A. Commercial vs Comptabilité (Scénario Comparatif)
- **Requête commercial Charlie (`uid=8`)** : *"Quel est le montant total des factures pour Azure Interior ?"*
  - **Comportement IA** : Le nœud `build_graph()` et le middleware RBAC interceptent `skills["comptabilite"] == False`. L'outil `obtenir_total_factures` n'est pas lié au LLM (`bind_tools`).
  - **Réponse Générée** : *"Désolé, je ne dispose pas des permissions ni des outils de comptabilité nécessaires pour accéder au total de vos factures."* (Aucune tentative d'appel d'outil ni fuite de donnée).
- **Requête Administrateur (`uid=2`)** : *"Quel est le montant total des factures pour Azure Interior ?"*
  - **Comportement IA** : `skills["comptabilite"] == True`. L'outil `obtenir_total_factures` est lié, appelé avec succès, et retourne la donnée financière.
  - **Réponse Générée** : *"Le total des factures payées pour Azure Interior s'élève à 4 500.00 Ar."*

### B. Cas aux Limites (Multi-Groupes & Utilisateur Sans Groupe)
- **Utilisateur Multi-Groupes Alice (`uid=6`, CEO Alpha)** :
  - Détectée dans `res.users` avec `group_sale_salesman` ET `group_project_user`.
  - Reçoit simultanément `obtenir_statut_commande`, `obtenir_total_ventes`, `obtenir_tickets_recents`, etc. (Accès multi-domaines vérifié sans conflit de routage).
- **Utilisateur Sans Groupe ERP (`uid=9999` ou portail)** :
  - `skills` se résout à `{'ventes': False, 'stocks': False, 'comptabilite': False, 'tickets': False}`.
  - L'IA ne reçoit aucun outil ORM de domaine (`obtenir_total_factures`, `obtenir_ca_periode`, `obtenir_statut_commande` sont absents).
  - Face à une question ERP, l'assistant formule un refus poli ou indique son absence de données sans générer d'exception technique ni planter la boucle de conversation.

**Exécution Pytest (`test_rbac_assistant_queries.py`)** :
```text
tests/test_rbac_assistant_queries.py::TestRBACAssistantQueries::test_01_sales_user_asks_accounting_question_refused PASSED
tests/test_rbac_assistant_queries.py::TestRBACAssistantQueries::test_02_admin_asks_same_accounting_question_answered PASSED
tests/test_rbac_assistant_queries.py::TestRBACAssistantQueries::test_03_edge_case_user_with_multiple_groups PASSED
tests/test_rbac_assistant_queries.py::TestRBACAssistantQueries::test_04_edge_case_user_with_no_relevant_groups PASSED
================== 4 passed in 76.15s (0:01:16) ===================
```

---

## 5. Synthèse & Validation Technique

1. **Zéro Fuite de Données Inter-Profils ou Inter-Sociétés** :
   Les utilisateurs commerciaux ne peuvent ni voir ni interroger les outils comptables ou les tickets de support d'une autre société, tant au niveau du prompt/LLM qu'au niveau du noyau ORM XML-RPC (`ir.rule`).
2. **Robustesse d'Authentification** :
   L'implémentation de `_get_password_for_uid` garantit que chaque requête ORM émanant de l'assistant s'exécute authentifiée sous l'identité propre du demandeur, appliquant la stricte granularité des droits Odoo sans requérir l'injection du mot de passe admin.
3. **Résilience et Pas de Crash** :
   Les cas aux limites (utilisateurs sans droits ou aux droits mixtes) sont gérés de manière élégante par la boucle ReAct (`ChatGroq`), assurant une expérience utilisateur sécurisée et compréhensible.

**Conclusion : L'Étape 14 (`Step 14: RBAC + access control`) est 100% complétée, testée et documentée.**
