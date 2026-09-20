# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-20 15:11:26

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 1 |
| p50 latence effective | `3.69s` |
| p90 latence effective | `3.69s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `3.69s` |
| Max | `3.69s` |

---

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 3.69s | Effectif: 3.685s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Peut‑t‑il créer et modifier des factures ?

Oui.  
Même si l’ACL *directe* de `account.group_account_manager` sur `account.move` ne donne que le droit de lecture, ce groupe hérite des droits du groupe `account.group_account_invoice`.  
Dans la matrice d’accès, on trouve :

- **WRITE** : `account.group_account_invoice`, `account.group_account_manager` (via `implied_ids <- account.group_account_invoice`), `account.group_account_user` (via `implied_ids <- account.group_account_invoice`), `group_purchase_user`  
- **CREATE** : idem que WRITE  
- **UNLINK** : idem que WRITE  

> **Source** : [Access Matrix for 'account.move': [WRITE] …](file:///media/donnee/projets/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L1-L22)

Ainsi, un utilisateur appartenant à `account.group_account_manager` possède les droits d’écriture, de création et de suppression sur les factures (`account.move`).  

Les règles de sécurité supplémentaires (record‑rules, locks) ne restreignent pas la création ou la modification ; elles ne concernent que des actions spécifiques (ex. validation d’un avoir > 5000 €).  

**Conclusion** : un « Billing Administrator » (group_account_manager) peut créer et modifier des factures.

[Source: Graphe de Connaissances Code Intelligence]
```

---