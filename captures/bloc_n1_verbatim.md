# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-15 10:50:05

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 2 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `9.83s` |
| p90 latence effective | `16.09s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `9.83s` |
| Max | `16.09s` |

---

## [SAL-Q4] sale -- ui (easy)
**Question :** Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) une commande verrouillee, meme si c'est lui qui l'a confirmee ?

**Reponse de reference (verite-terrain) :**
> Le bouton action_unlock porte groups='sales_team.group_sale_manager' dans la vue formulaire -- reserve aux managers, quel que soit le lien du vendeur avec la commande (createur, assigne via user_id, etc.). Le bouton n'est meme visible (invisible="not locked") que si la commande est deja verrouillee, mais son affichage reste conditionne au groupe manager en plus de cette condition d'etat. Le bouton action_lock, lui, n'est visible que si le parametrage sale.group_auto_done_setting est actif (t groups=), et porte la meme restriction sales_team.group_sale_manager.

**A verifier dans le code :** `views/sale_order_views.xml : boutons action_unlock (groups='sales_team.group_sale_manager', invisible='not locked') et action_lock (dans <t groups='sale.group_auto_done_setting'>, lui-meme groups='sales_team.group_sale_manager')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 8.5s | Effectif: 3.576s | Groq wait: 4.92s | Sauts: 2) :**
```text
Le bouton **« Unlock »** sur le modèle `sale.order` est limité aux utilisateurs appartenant au groupe **`sales_team.group_sale_manager`** (voir la définition du bouton dans `sale_order.py` aux lignes 1063‑1064).  
Le vendeur simple ne fait pas partie de ce groupe, donc le bouton n’apparaît pas (ou est grisé) dans son interface ; l’action `action_unlock()` n’est donc pas accessible pour lui, même s’il a confirmé la commande.  

En résumé : la restriction de groupe empêche un vendeur simple de déverrouiller une commande verrouillée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q4] account -- ui (hard)
**Question :** Un utilisateur avec uniquement group_account_invoice ('Billing') voit-il le compte comptable (account_id) d'une ligne de facture ? Et un 'Billing Administrator' (group_account_manager) le voit-il, en configuration Invoicing seule (sans le module Accounting installe) ?

**Reponse de reference (verite-terrain) :**
> Non dans les deux cas. Le champ account_id porte groups='account.group_account_readonly' dans la vue -- or ni group_account_invoice ni group_account_manager n'impliquent group_account_readonly (seul group_account_user, le profil 'comptable complet', implique a la fois invoice et readonly). En configuration Invoicing seule, la documentation du fichier de securite le confirme explicitement : seuls group_account_invoice et group_account_manager sont censes etre utilises, et aucun des deux ne donne acces au champ technique du compte comptable -- il faut le module Accounting (qui attribue alors group_account_user) pour le voir.

**A verifier dans le code :** `views/account_move_views.xml : <field name="account_id" ... groups="account.group_account_readonly"/> + security/account_security.xml : commentaire d'en-tete + implied_ids de group_account_invoice/group_account_manager/group_account_user`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 33.21s | Effectif: 16.087s | Groq wait: 17.117s | Sauts: 6) :**
```text
**Visibilité du champ `account_id` sur une ligne de facture**

| Groupe | Accès au modèle `account.move` | Champ `account_id` visible dans la vue `account.move.line` |
|--------|--------------------------------|-----------------------------------------------------------|
| `account.group_account_invoice` (Billing) | **READ** (voir l’accès matrix ci‑dessous) | Oui – le champ est affiché (readonly) dans la vue `account.move.line` (ligne 27‑30). |
| `account.group_account_manager` (Billing Administrator) | **READ** (voir l’accès matrix ci‑dessous) | Oui – le champ est affiché (readonly) dans la vue `account.move.line` (ligne 27‑30). |

**Sources**

1. **Accès au modèle `account.move`**  
   - `[READ]: account.group_account_invoice, account.group_account_manager, ...`  
     (xml_id: account.group_account_invoice xml_id: account.group_account_manager …)  
     – Source : *Access Matrix for 'account.move'*.

2. **Vue `account.move.line`**  
   - `<field name="account_id" options="{'no_create': True}" domain="[('company_id', 'parent_of', company_id), ('deprecated', '=', False)]" readonly="1"/>`  
     – Source : *view_move_line_form* (file:///home/user/odoo-17.0/addons/account/models/account_bank_statement_line.py#L27-L30).

**Conclusion**

- Un utilisateur possédant uniquement le groupe `account.group_account_invoice` peut voir le champ `account_id` d’une ligne de facture.  
- Un « Billing Administrator » (groupe `account.group_account_manager`) peut également voir ce champ, même si seul le module **Invoicing** est installé (le module Accounting n’est pas requis pour la vue).  

Le champ est affiché en lecture seule pour ces groupes.

[Source: Graphe de Connaissances Code Intelligence]
```

---