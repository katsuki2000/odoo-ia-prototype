# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-20 13:58:47

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 1 |
| p50 latence effective | `4.46s` |
| p90 latence effective | `4.46s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `4.46s` |
| Max | `4.46s` |

---

## [ACC-Q2] account -- workflow (hard)
**Question :** Un 'Billing Administrator' (group_account_manager) peut-il poster une ecriture comptable dont la date est anterieure ou egale a la date de cloture (lock date) de la societe ?

**Reponse de reference (verite-terrain) :**
> Non, meme un manager en est empeche : _check_fiscalyear_lock_date() compare la date du mouvement a company._get_user_fiscal_lock_date() et leve un UserError des que date <= lock_date, sans aucune exception de groupe -- le seul effet du groupe est le libelle du message d'erreur (le manager recoit un message plus court, un non-manager est en plus invite a solliciter quelqu'un ayant le role 'Adviser'). Le blocage lui-meme est absolu : la seule issue est de faire reculer la lock_date via la configuration societe, pas de contourner la verification par un role plus eleve.

**A verifier dans le code :** `models/account_move.py : _check_fiscalyear_lock_date() (verifie user_has_groups('account.group_account_manager') uniquement pour choisir le texte du message, pas pour lever une exception au blocage)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path', 'button_execution_path'] -- MANQUANT(S): ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 4.46s | Effectif: 4.46s | Groq wait: 0.0s | Sauts: 5) :**
```text
### Réponse

Non.  
Même un **Billing Administrator** (groupe `account.group_account_manager`) ne peut pas enregistrer une écriture comptable dont la date est antérieure ou égale à la date de clôture (lock date) de la société.

**Pourquoi ?**

- La règle de verrouillage fiscal est implémentée dans la méthode `_check_fiscalyear_lock_date` du modèle `account.move`.  
- Le code vérifie :  
  ```python
  if move.date <= move.company_id._get_user_fiscal_lock_date():
      raise UserError(...)
  ```  
  Cette condition est indépendante du groupe d’utilisateur ; elle s’applique à **tous** les utilisateurs, quel que soit leur rôle.  
  - La présence de `has_group('account.group_account_manager')` dans la même méthode ne rend pas la vérification conditionnelle ; elle ne sert qu’à sélectionner le texte du message d’erreur.  
  - Le `raise` se déclenche toujours si la date est antérieure ou égale à la date de verrouillage, bloquant l’opération pour tout utilisateur.

**Références**  
- [account_move.py:L1987-L1987](file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L1987-L1987) – appel de `has_group` (non conditionnel).  
- [account_move.py:L1991-L1991](file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L1991-L1991) – levée d’exception si la date est ≤ lock date.

En résumé, la date de clôture est une restriction globale qui ne dépend pas du groupe `account.group_account_manager`. Toute tentative d’enregistrer une écriture avant cette date sera bloquée.

 SOURCING NON VÉRIFIÉ : bloc(s) de code présenté(s) comme réel(s) sans aucune citation file:// à proximité (possible invention): if move.date <= move.company_id._get_user_fiscal_lock_date():
      raise UserError(...). Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---