# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-21 23:49:47

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `13.97s` |
| p90 latence effective | `13.97s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `13.97s` |
| Max | `13.97s` |

---

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'analyze_method_override_chain', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules', 'describe_workflow']

**Reponse verbatim de l'agent (Total: 28.74s | Effectif: 13.974s | Groq wait: 14.765s | Sauts: 6) :**
```text
Dans le modèle **purchase.order**, les ACL donnent effectivement les mêmes droits de lecture, écriture, création et suppression aux groupes **group_purchase_user** et **group_purchase_manager**.  
La distinction entre un acheteur « simple » et un manager ne vient donc pas des ACL mais d’autres mécanismes de contrôle :

| Mécanisme | Action différenciée | Groupe requis | Référence |
|-----------|---------------------|---------------|-----------|
| **Vérification d’approbation** | La méthode `_approval_allowed()` est appelée lorsqu’un utilisateur clique sur le bouton **Confirm Order** (workflow : *draft → sale*). Cette méthode contient un test `has_group('purchase.group_purchase_manager')` qui autorise l’approbation uniquement si l’utilisateur appartient à **group_purchase_manager**. | `purchase.group_purchase_manager` | `purchase_order.py:L969-L969` (Confiance : ÉLEVÉE) |
| **Envoi de rappels** | La méthode `_send_reminder_mail()` est utilisée pour envoyer des rappels aux fournisseurs. Elle contient un test `has_group('purchase.group_send_reminder')`, qui n’est activé que pour les managers. | `purchase.group_send_reminder` | `purchase_order.py:L768-L768` (Confiance : ÉLEVÉE) |

**En pratique**

* Un utilisateur du groupe **group_purchase_user** peut créer, modifier et supprimer des commandes d’achat, mais il ne peut pas **confirmer** (approver) une commande ni envoyer de rappels.  
* Un utilisateur du groupe **group_purchase_manager** possède les mêmes droits de base, **plus** la capacité d’approbation (bouton *Confirm Order*) et d’envoi de rappels, grâce aux vérifications explicites dans `_approval_allowed()` et `_send_reminder_mail()`.

Aucune règle `ir.rule` supplémentaire ne restreint ces actions, et les ACL ne font pas de distinction. La différence réelle réside donc dans les contrôles de méthode Python décrits ci‑dessus.

[Source: Graphe de Connaissances Code Intelligence]
```

---