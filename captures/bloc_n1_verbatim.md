# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-15 14:46:28

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `3.44s` |
| p90 latence effective | `3.44s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `3.44s` |
| Max | `3.44s` |

---

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 3.44s | Effectif: 3.437s | Groq wait: 0.0s | Sauts: 6) :**
```text
**Ce qui distingue un simple acheteur d’un manager sur une commande d’achat :**

1. **Capacité d’approbation**  
   - Le bouton **« Confirm Order »** (méthode `button_confirm()`) passe la commande à l’état `to approve` si la condition `_approval_allowed()` n’est pas satisfaite.  
   - Cette condition est vraie :  
     - Si la société a activé la double validation en **une étape** (`po_double_validation == 'one_step'`).  
     - Ou si la double validation est en **deux étapes** et que le montant total de la commande est **inférieur** au seuil `po_double_validation_amount`.  
     - **Ou** si l’utilisateur appartient au groupe `purchase.group_purchase_manager`.  
   - Ainsi, un **manager** peut approuver immédiatement les commandes qui dépassent le seuil de double validation ou qui sont soumises à la double validation en deux étapes.  
   - Un **acheteur** (membre de `group_purchase_user` mais pas de `purchase.group_purchase_manager`) ne peut pas approuver ces commandes ; il doit attendre l’approbation d’un manager.

2. **Fonctionnalité de déverrouillage**  
   - Le bouton **« Unlock »** (méthode `button_unlock()`) est disponible uniquement pour le groupe `purchase.group_purchase_manager` (xml_id : `purchase.group_purchase_manager`).  
   - Un manager peut donc déverrouiller une commande qui a été verrouillée, ce qui n’est pas possible pour un acheteur.

3. **Accès global**  
   - Les ACL donnent les mêmes droits de lecture, écriture, création et suppression aux deux groupes.  
   - Les règles globales (`purchase.purchase_order_comp_rule`) ne restreignent pas l’accès en fonction du groupe.  
   - Aucun `ir.rule` spécifique ne différencie les deux groupes pour ce modèle.

En résumé, la différence principale réside dans la **capacité d’approbation** des commandes dépassant le seuil de double validation et dans la **possibilité de déverrouiller** une commande, fonctions réservées aux membres du groupe `purchase.group_purchase_manager`. Les droits d’accès de base (lecture, écriture, création, suppression) restent identiques pour les deux groupes.

[Source: Graphe de Connaissances Code Intelligence]
```

---