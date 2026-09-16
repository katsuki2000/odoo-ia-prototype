# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-16 15:38:00

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 3 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 1 |
| p50 latence effective | `20.18s` |
| p90 latence effective | `26.11s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `20.03s` |
| Max | `26.11s` |

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'button_execution_path']

**Reponse verbatim de l'agent (Total: 20.18s | Effectif: 20.181s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Modèle : `stock.picking`

- **Nature** : *déclaré* dans le module **stock** (pas une extension d’un modèle natif existant).  
  - Le fichier `stock_picking.py` contient la déclaration :  
    ```python
    class Picking(models.Model):
        _name = "stock.picking"
        _inherit = ['mail.thread', 'mail.activity.mixin']
    ```  
    Source : [stock_picking.py:L382-L386](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L382-L386)

- **Héritage** :  
  - Il hérite de `mail.thread` et `mail.activity.mixin` (mixins de suivi et d’activité).  
  - Aucun héritage d’un modèle natif hors du périmètre du module stock.

- **Champs clés** (extraits du début du fichier) :  
  - `name` – référence du picking.  
  - `origin` – référence du document source.  
  - `note` – notes.  
  - `backorder_id`, `backorder_ids` – lien vers les back‑orders.  
  - `return_id`, `return_ids` – lien vers les retours.  
  - `return_count` – nombre de retours (calculé).  
  - `move_type` – politique d’expédition (`direct` ou `one`).  
  - `state` – statut du picking (`draft`, `waiting`, `assigned`, `done`, `cancel`, etc.).  
  Source : [stock_picking.py:L397-L425](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L397-L425)

En résumé, `stock.picking` est un **nouveau modèle** introduit par le module `stock`, qui ne modifie pas un modèle natif existant mais s’appuie sur les mixins de suivi et d’activité. Les champs ci‑dessus constituent les principaux attributs utilisés pour gérer les transferts de stock.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q2] account -- workflow (hard)
**Question :** Un 'Billing Administrator' (group_account_manager) peut-il poster une ecriture comptable dont la date est anterieure ou egale a la date de cloture (lock date) de la societe ?

**Reponse de reference (verite-terrain) :**
> Non, meme un manager en est empeche : _check_fiscalyear_lock_date() compare la date du mouvement a company._get_user_fiscal_lock_date() et leve un UserError des que date <= lock_date, sans aucune exception de groupe -- le seul effet du groupe est le libelle du message d'erreur (le manager recoit un message plus court, un non-manager est en plus invite a solliciter quelqu'un ayant le role 'Adviser'). Le blocage lui-meme est absolu : la seule issue est de faire reculer la lock_date via la configuration societe, pas de contourner la verification par un role plus eleve.

**A verifier dans le code :** `models/account_move.py : _check_fiscalyear_lock_date() (verifie user_has_groups('account.group_account_manager') uniquement pour choisir le texte du message, pas pour lever une exception au blocage)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path', 'button_execution_path'] -- MANQUANT(S): ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 26.11s | Effectif: 26.112s | Groq wait: 0.0s | Sauts: 5) :**
```text
**Réponse synthétique**

Les mécanismes d’accès et de sécurité que nous avons examinés (ACL, `ir.rule`, verrouillage Python) ne contiennent aucune restriction qui empêche un utilisateur appartenant au groupe `account.group_account_manager` de créer ou de modifier une écriture comptable dont la date est antérieure ou égale à la date de clôture (« lock date ») de la société.  

- **ACL**  
  - `WRITE` sur le modèle `account.move` est autorisé pour `account.group_account_manager` (voir *Access Matrix for 'account.move'*).  
  - Aucun autre groupe n’est requis pour cette opération.

- **Règles `ir.rule`**  
  - Les règles globales et celles spécifiques aux groupes ne filtrent pas les écritures en fonction de la date.  
  - Aucune règle ne mentionne la « lock date » ou impose une restriction temporelle.

- **Verrouillage Python**  
  - L’analyse de `account_move.py` (L1‑22) ne contient que des messages liés à la validation de crédits supérieurs à 5000 € et ne fait aucune référence à la date de clôture.  
  - Aucun autre fichier lié à la création d’écritures n’indique de contrôle sur la date.

**Conclusion**

À partir des données d’accès et de verrouillage que nous avons pu analyser, il n’existe pas de restriction explicite empêchant un « Billing Administrator » (group_account_manager) de poster une écriture comptable dont la date est antérieure ou égale à la date de clôture de la société.  

Cependant, cette conclusion ne tient pas compte des éventuelles vérifications métier ou des règles de workflow qui pourraient être implémentées ailleurs (par exemple dans un module personnalisé, un workflow Odoo, ou une logique métier non couverte par les outils d’analyse utilisés). Si une telle restriction existe, elle ne se trouve pas dans les mécanismes d’accès et de verrouillage examinés.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 13.81s | Effectif: 13.808s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Modèle : `account.move`

- **Nature** : *déclaré*  
  Le module **account** crée le modèle `account.move` lui‑même.  
  Il ne s’agit pas d’une extension d’un modèle déjà existant hors de son périmètre comptable.

- **Héritage**  
  `account.move` hérite de plusieurs mixins métier (mail.thread.main.attachment, mail.activity.mixin, portal.mixin, sequence.mixin, utm.mixin) mais ne s’étend pas sur un modèle natif provenant d’un autre module.  
  Voir la chaîne d’héritage complète :  
  `portal.mixin → mail.thread.main.attachment → mail.activity.mixin → sequence.mixin → utm.mixin`  
  (source : [account_move.py:L5-L22](file:///home/user/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L5-L22))

- **Conclusion**  
  Le module **account** ne « étend pas en parallèle un modèle natif hors de son propre périmètre comptable » ; il introduit simplement le modèle `account.move` et l’enrichit via des mixins.

[Source: Graphe de Connaissances Code Intelligence]
```

---