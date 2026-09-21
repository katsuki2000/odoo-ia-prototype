# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-20 17:22:59

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 2 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `29.22s` |
| p90 latence effective | `41.69s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `29.22s` |
| Max | `41.69s` |

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'button_execution_path']

**Reponse verbatim de l'agent (Total: 41.69s | Effectif: 41.693s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Modèle : `stock.picking`

- **Nature** : *déclaration d’un nouveau modèle*  
  Le fichier `stock_picking.py` du module `stock` contient la déclaration suivante :  

  ```python
  class Picking(models.Model):
      _name = "stock.picking"
      _inherit = ['mail.thread', 'mail.activity.mixin']
  ```  
  [stock_picking.py:L382-L384](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L382-L384)

  Ainsi, `stock.picking` n’est pas une extension d’un modèle natif existant (comme `stock.move` ou `stock.quant`). Il s’agit d’un modèle métier propre au module `stock`.

- **En réalité, ce module étend bien 12 modèle(s) hors de son propre périmètre : 'barcode.rule', 'ir.actions.report', 'product.category', 'product.label.layout', 'product.packaging', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.partner', 'res.users', 'uom.uom'.
  En réalité, ce module étend bien 12 modèle(s) hors de son propre périmètre : 'barcode.rule', 'ir.actions.report', 'product.category', 'product.label.layout', 'product.packaging', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.partner', 'res.users', 'uom.uom'. Aucun autre modèle natif n’est hérité ou modifié dans ce fichier.

- **Champs clés définis dans `stock.picking`**  
  Les champs les plus importants (utilisés pour l’identification, le suivi et la gestion des mouvements) sont :

  | Champ | Description | Ligne de référence |
  |-------|-------------|--------------------|
  | `name` | Référence de l’opération | [stock_picking.py:L397-L399](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L397-L399) |
  | `origin` | Référence du document source | [stock_picking.py:L400-L402](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L400-L402) |
  | `note` | Notes additionnelles | [stock_picking.py:L403-L404](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L403-L404) |
  | `backorder_id` / `backorder_ids` | Gestion des back‑orders | [stock_picking.py:L404-L410](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L404-L410) |
  | `return_id` / `return_ids` | Gestion des retours | [stock_picking.py:L410-L413](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L410-L413) |
  | `move_type` | Politique d’expédition (direct ou one) | [stock_picking.py:L415-L418](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L415-L418) |
  | `state` | Statut de l’opération (draft, waiting, assigned, done, cancel, …) | [stock_picking.py:L419-L426](file:///media/donnee/Programs/odoo-17.0/addons/stock/models/stock_picking.py#L419-L426) |

  Ces champs constituent la base de la logique métier de la gestion des transferts de stock dans Odoo.

---

**En résumé** :  
`stock.picking` est un **nouveau modèle** introduit par le module `stock`. En réalité, ce module étend bien 12 modèle(s) hors de son propre périmètre : 'barcode.rule', 'ir.actions.report', 'product.category', 'product.label.layout', 'product.packaging', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.partner', 'res.users', 'uom.uom'. Les champs clés mentionnés ci‑dessus sont ceux qui définissent l’identité, le suivi et le cycle de vie d’une opération de transfert de stock.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 16.74s | Effectif: 16.738s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Modèle `account.move`

- **Nature** : `account.move` est **déclaré** dans le module `account`.  
  - Le fichier `account/models/account_move.py` contient la déclaration `class AccountMove(models.Model):` avec `_name = "account.move"`.  
  - Source : [account/models/account_move.py:L81-L89](file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L81-L89).

- **Héritage** : il ne s’agit pas d’une extension d’un modèle natif existant (ex. `res.partner`).  
  - Il hérite uniquement de mixins internes à Odoo (`portal.mixin`, `mail.thread.main.attachment`, `mail.activity.mixin`, `sequence.mixin`).  
  - Source : [trace_full_inheritance](file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L81-L161).

- **Portée comptable** En réalité, ce module étend bien 25 modèle(s) hors de son propre périmètre : 'account.analytic.account', 'account.analytic.applicability', 'account.analytic.distribution.model', 'account.analytic.line', 'base.document.layout', 'base.partner.merge.automatic.wizard', 'decimal.precision', 'digest.digest', 'ir.actions.report', 'ir.attachment', 'ir.http', 'ir.module.module', 'kpi.provider', 'onboarding.onboarding', 'onboarding.onboarding.step', 'product.category', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.currency', 'res.groups', 'res.partner', 'res.partner.bank', 'uom.uom'.  
  - `account.move` est un modèle métier propre à la comptabilité, créé par le module `account`.  
  - Aucun autre module n’étend un modèle natif (ex. `res.partner`) dans le cadre de la comptabilité via `account.move`.

En résumé, **`account.move` est un nouveau modèle défini par le module `account`** En réalité, ce module étend bien 25 modèle(s) hors de son propre périmètre : 'account.analytic.account', 'account.analytic.applicability', 'account.analytic.distribution.model', 'account.analytic.line', 'base.document.layout', 'base.partner.merge.automatic.wizard', 'decimal.precision', 'digest.digest', 'ir.actions.report', 'ir.attachment', 'ir.http', 'ir.module.module', 'kpi.provider', 'onboarding.onboarding', 'onboarding.onboarding.step', 'product.category', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.currency', 'res.groups', 'res.partner', 'res.partner.bank', 'uom.uom'.

[Source: Graphe de Connaissances Code Intelligence]
```

---