# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-22 10:40:54

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 4 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `46.43s` |
| p90 latence effective | `74.91s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `45.11s` |
| Max | `74.91s` |

---

## [STK-Q2] stock -- workflow (hard)
**Question :** Que se passe-t-il quand on valide un transfert de stock (button_validate) dont les quantites traitees sont inferieures aux quantites demandees ?

**Reponse de reference (verite-terrain) :**
> button_validate() ignore les transferts deja 'done', confirme automatiquement ceux encore en 'draft', puis complete a la quantite demandee toute ligne dont la quantite traitee est nulle. Une verification de coherence (_sanity_check) s'execute ensuite sauf contexte skip_sanity_check. _pre_action_done_hook() marque picked=True des que des quantites existent. Vient ensuite la decision cle : les transferts sont scindes entre ceux dont picking_type_id.create_backorder=='never' (jamais de reliquat, executes avec cancel_backorder=True) et les autres (executes normalement, create_backorder='always' ou 'ask') -- c'est ce parametre du type d'operation, pas une valeur globale, qui determine si un bon de livraison partiel genere automatiquement un reliquat (backorder) pour les quantites restantes.

**A verifier dans le code :** `models/stock_picking.py : button_validate(), _pre_action_done_hook(), champ picking_type_id.create_backorder (stock_picking_type.py)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 74.91s | Effectif: 74.905s | Groq wait: 0.0s | Sauts: 5) :**
```text
Lorsque vous cliquez sur **button_validate** pour un *stock.picking*, la méthode `button_validate()` (voir `stock_picking.py:L1134-L1194`) exécute les étapes suivantes :

1. **Confirmation** – Si le picking est encore en brouillon, il est confirmé (`action_confirm()`).
2. **Ajustement des quantités** – Pour chaque mouvement dont la quantité traitée est nulle mais dont la quantité demandée (`product_uom_qty`) est non nulle, la quantité est mise à jour avec `move.quantity = move.product_uom_qty` (voir `L1138-L1141`).
3. **Vérifications de cohérence** – La méthode `_sanity_check()` est appelée (si le contexte ne désactive pas cette étape) pour s’assurer que les mouvements restent valides (`L1144-L1145`).
4. **Gestion des back‑orders** –  
   * Le picking est divisé en deux groupes :  
     * `pickings_not_to_backorder` : ceux dont `picking_type_id.create_backorder == 'never'` (`L1167-L1170`).  
     * `pickings_to_backorder` : le reste (`L1168-L1171`).  
   * Pour les pickings **à ne pas back‑order**, `_action_done()` est appelé avec `cancel_backorder=True` (`L1173-L1174`).  
   * Pour les pickings **à back‑order**, `_action_done()` est appelé avec `cancel_backorder=False` (`L1175-L1176`).  
   * Ainsi, si certaines quantités ne sont pas entièrement traitées, un nouveau picking (back‑order) est créé contenant les quantités restantes ; sinon, ces quantités sont annulées si `create_backorder` vaut « never » (`L139-L145`).

En résumé, **valider un transfert dont les quantités traitées sont inférieures aux quantités demandées entraîne la création d’un back‑order (ou l’annulation des quantités restantes si le type de picking est configuré pour ne jamais back‑order)**. Le picking original passe alors à l’état « done ».

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'button_execution_path']

**Reponse verbatim de l'agent (Total: 25.07s | Effectif: 25.071s | Groq wait: 0.0s | Sauts: 3) :**
```text
## Modèle : `stock.picking`

- **Nature** : *déclaration d’un nouveau modèle*  
  Le module **stock** crée le modèle `stock.picking` avec `_name = "stock.picking"`.  
  Il ne s’agit pas d’une extension d’un modèle natif existant (autre que les mixins).  
  - *Source* : [stock_picking.py:L382-L462](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L382-L462)

- **Mixins hérités**  
  Le modèle hérite de `mail.thread` et `mail.activity.mixin`, qui sont des mixins génériques pour la messagerie et les activités.  
  - *Source* : même extrait ci‑dessus (L384-L385)

- **En réalité, ce module étend bien 12 modèle(s) hors de son propre périmètre : 'barcode.rule', 'ir.actions.report', 'product.category', 'product.label.layout', 'product.packaging', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.partner', 'res.users', 'uom.uom'.
  Le module ne fait pas d’`_inherit` sur un modèle natif comme `res.partner` ou `product.product`.  
  Il ne « étend » que les mixins mentionnés ci‑dessus.

- **Champs clés (extraits)**  
  | Champ | Description | Source |
  |-------|-------------|--------|
  | `name` | Référence de l’opération | [stock_picking.py:L397-L399](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L397-L399) |
  | `origin` | Référence du document source | [stock_picking.py:L400-L402](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L400-L402) |
  | `note` | Notes internes | [stock_picking.py:L403-L404](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L403-L404) |
  | `backorder_id` / `backorder_ids` | Gestion des back‑orders | [stock_picking.py:L404-L410](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L404-L410) |
  | `return_id` / `return_ids` | Gestion des retours | [stock_picking.py:L410-L416](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L410-L416) |
  | `move_type` | Politique d’expédition | [stock_picking.py:L415-L418](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L415-L418) |
  | `state` | Statut de l’opération | [stock_picking.py:L419-L426](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L419-L426) |

Ces champs constituent les colonnes les plus souvent utilisées pour identifier, suivre et gérer les mouvements de stock dans Odoo.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q4] stock -- ui (medium)
**Question :** Pourquoi les champs 'From'/'To' (emplacement source/destination) n'apparaissent-ils pas sur un transfert de stock pour la plupart des utilisateurs ?

**Reponse de reference (verite-terrain) :**
> Ces champs portent groups='stock.group_stock_multi_locations' dans la vue -- mais ce n'est pas un groupe de role (comme user/manager), c'est un groupe active par un parametre de configuration (implied_group sur le champ booleen group_stock_multi_locations dans res.config.settings, 'Storage Locations'). Tant que la fonctionnalite multi-emplacements n'est pas activee en configuration, aucun utilisateur -- meme stock.group_stock_manager -- ne voit ces champs, car le groupe technique lui-meme n'est attribue a personne.

**A verifier dans le code :** `views/stock_picking_views.xml : champs location_id/location_dest_id groups='stock.group_stock_multi_locations' + models/res_config_settings.py : champ group_stock_multi_locations (implied_group='stock.group_stock_multi_locations')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 12.66s | Effectif: 12.664s | Groq wait: 0.0s | Sauts: 2) :**
```text
Les champs **« From »** et **« To »** (`location_id` et `location_dest_id`) ne sont visibles que pour les utilisateurs appartenant au groupe **`stock.group_stock_multi_locations`**.  
Dans la vue `view_picking_form`, ces champs sont déclarés avec l’attribut `groups="stock.group_stock_multi_locations"`, ce qui les masque aux autres utilisateurs :

- **Déclaration dans la vue**  
  ```xml
  <field name="location_id" … groups="stock.group_stock_multi_locations" …/>
  <field name="location_dest_id" … groups="stock.group_stock_multi_locations" …/>
  ```
  [stock_picking_views.xml:L91-L97](file:///home/user/odoo-17.0/addons/stock/views/stock_picking_views.xml#L91-L97)

Ainsi, la plupart des utilisateurs ne voient pas ces champs parce qu’ils ne font pas partie de ce groupe.  
Pour les rendre visibles, il faut :

1. Ajouter l’utilisateur au groupe **`stock.group_stock_multi_locations`** (via *Settings → Users & Companies → Users → Groups*), ou  
2. Modifier la vue pour retirer l’attribut `groups` (ou le remplacer par un groupe plus large).

En résumé, la restriction d’affichage est due à la condition de groupe définie dans la vue.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q5] stock -- constraints (medium)
**Question :** Quelles contraintes empechent la creation d'un stock.quant invalide, et quelle regle distincte garantit l'unicite d'un numero de serie ?

**Reponse de reference (verite-terrain) :**
> Trois @api.constrains independantes sur stock.quant : check_product_id interdit un quant pour un produit qui n'est pas de type 'product' (consommable/service exclus) ; check_location_id interdit un emplacement de type 'view' (emplacement structurel, non physique) ; check_lot_id interdit qu'un lot/numero de serie soit rattache a un produit different de celui du quant. Independamment, sur stock.lot, _check_unique_lot (@api.constrains sur name/product_id/company_id) verifie via _read_group (pas une contrainte SQL unique) qu'aucune combinaison produit+societe+nom de lot n'est dupliquee -- une verification applicative, pas une contrainte de base de donnees.

**A verifier dans le code :** `models/stock_quant.py : check_product_id, check_location_id, check_lot_id (@api.constrains) ; models/stock_lot.py : _check_unique_lot (@api.constrains('name','product_id','company_id'))`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 67.78s | Effectif: 67.78s | Groq wait: 0.0s | Sauts: 2) :**
```text
## Contraintes empêchant la création d’un **stock.quant** invalide

| Type de contrainte | Description | Lignes de code concernées |
|--------------------|-------------|---------------------------|
| **`check_product_id`** | Empêche la création d’un quant pour un produit de type *consommable* ou *service*. | [stock_quant.py:L615-L618](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L615-L618) |
| **`check_location_id`** | Empêche de prendre ou livrer depuis une localisation de type *view* (exemple : “Vue”). | [stock_quant.py:L638-L642](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L638-L642) |
| **`check_lot_id`** | Vérifie que le lot/numéro de série référencé appartient bien au même produit que le quant. | [stock_quant.py:L644-L648](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L644-L648) |
| **`check_quantity_or_reserved_quantity`** | S’assure que la quantité ou la quantité réservée est renseignée. | [stock_quant.py:L1091](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L1091) |
| **`only_stock_manager_can_validate_inventory`** | Restreint la validation d’un ajustement de stock aux utilisateurs disposant du rôle *stock manager*. | [stock_quant.py:L1052](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L1052) |
| **`lot_movement_location_check`** | Autorise le déplacement d’un lot/numéro de série uniquement s’il existe dans une seule localisation. | [stock_lot.py:L149](file:///home/user/odoo-17.0/addons/stock/models/stock_lot.py#L149) |
| **`company_change_forbidden`** | Empêche de changer la société d’un lot/numéro de série après sa création. | [stock_lot.py:L161](file:///home/user/odoo-17.0/addons/stock/models/stock_lot.py#L161) |
| **`product_change_forbidden`** | Empêche de modifier le produit lié à un lot/numéro de série si des mouvements de stock existent déjà. | [stock_lot.py:L165-L169](file:///home/user/odoo-17.0/addons/stock/models/stock_lot.py#L165-L169) |

> **Remarque** : ces contraintes sont implémentées sous forme de méthodes décorées `@api.constrains` dans le modèle `stock.quant` (et `stock.lot` pour les contraintes liées aux lots). Elles lèvent une `ValidationError` ou un `UserError` lorsqu’une règle est violée, bloquant ainsi la création ou la modification du quant.

---

## Règle distincte garantissant l’unicité d’un numéro de série

| Règle | Description | Lignes de code concernées |
|-------|-------------|---------------------------|
| **`_check_unique_lot`** (dans `stock.lot`) | Vérifie que la combinaison *(numéro de série, produit, société)* est unique. Si des doublons sont détectés, une `ValidationError` est levée avec un message détaillé. | [stock_lot.py:L91-L102](file:///home/user/odoo-17.0/addons/stock/models/stock_lot.py#L91-L102) |

Cette règle est **distincte** des contraintes de `stock.quant`. Elle s’applique au modèle `stock.lot` et assure que chaque numéro de série ne peut être attribué qu’une seule fois à un produit donné dans une société donnée. Elle est déclenchée à chaque création ou modification d’un lot/numéro de série.

[Source: Graphe de Connaissances Code Intelligence]
```

---