# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-20 14:41:18

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 1 |
| p50 latence effective | `5.56s` |
| p90 latence effective | `5.56s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `5.56s` |
| Max | `5.56s` |

---

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 15.51s | Effectif: 5.564s | Groq wait: 9.941s | Sauts: 4) :**
```text
Oui.  
L’ACL directe de **account.group_account_manager** sur le modèle **account.move** ne donne effectivement que le droit de lecture, mais le groupe obtient également les droits d’écriture, de création et de suppression grâce aux **implied_ids**.  

- Dans la matrice d’accès :  
  - **CREATE** et **UNLINK** : mêmes groupes que pour l’écriture.  

- Aucun **ir.rule** de groupe ne restreint l’accès à ce modèle ; les seules règles globales ne contiennent pas de condition de montant ou de portée supplémentaire.  

Ainsi, un utilisateur appartenant à **group_account_manager** (Billing Administrator) peut créer, modifier et supprimer des factures, même si l’ACL directe ne montre que le droit de lecture. (Les contrôles de workflow ou d’état ne sont pas examinés ici.)

[Source: Graphe de Connaissances Code Intelligence]
```

---