# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-15 17:05:43

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `59.02s` |
| p90 latence effective | `59.02s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `59.02s` |
| Max | `59.02s` |

---

## [STK-Q5] stock -- constraints (medium)
**Question :** Quelles contraintes empechent la creation d'un stock.quant invalide, et quelle regle distincte garantit l'unicite d'un numero de serie ?

**Reponse de reference (verite-terrain) :**
> Trois @api.constrains independantes sur stock.quant : check_product_id interdit un quant pour un produit qui n'est pas de type 'product' (consommable/service exclus) ; check_location_id interdit un emplacement de type 'view' (emplacement structurel, non physique) ; check_lot_id interdit qu'un lot/numero de serie soit rattache a un produit different de celui du quant. Independamment, sur stock.lot, _check_unique_lot (@api.constrains sur name/product_id/company_id) verifie via _read_group (pas une contrainte SQL unique) qu'aucune combinaison produit+societe+nom de lot n'est dupliquee -- une verification applicative, pas une contrainte de base de donnees.

**A verifier dans le code :** `models/stock_quant.py : check_product_id, check_location_id, check_lot_id (@api.constrains) ; models/stock_lot.py : _check_unique_lot (@api.constrains('name','product_id','company_id'))`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 59.08s | Effectif: 59.019s | Groq wait: 0.0s | Sauts: 1) :**
```text
**Contraintes empêchant la création d’un `stock.quant` invalide**

1. **Contrôle du type de produit**  
   ```python
   @api.constrains('product_id')
   def check_product_id(self):
       if any(elem.product_id.type != 'product' for elem in self):
           raise ValidationError(_('Quants cannot be created for consumables or services.'))
   ```
   (voir `stock_quant.py#L615-L618`)  
   Cette contrainte empêche la création de quants pour des produits de type « consommable » ou « service ».

2. **Messages d’erreur explicites**  
   - `raise UserError(_('Operation not supported'))` (`stock_quant.py#L241-L241`)  
   - `raise UserError(_('You cannot duplicate stock quants.'))` (`stock_quant.py#L251-L251`)  
   - `raise UserError(_("Quant's creation is restricted, you can't do this operation."))` (`stock_quant.py#L268-L268`)  
   - `raise UserError(_("Quant's editing is restricted, you can't do this operation."))` (`stock_quant.py#L372-L372`)  
   - `raise UserError(_("Quants are auto‑deleted when appropriate. If you must manually delete them, please ask a stock manager to do it."))` (`stock_quant.py#L379-L379`)  

   Ces messages bloquent explicitement certaines opérations (création, duplication, édition ou suppression manuelle) lorsqu’elles ne respectent pas les règles métier.

3. **Contrôle de la quantité positive et de la localisation**  
   ```python
   raise UserError(_('You can only move positive quantities stored in locations used by a single company per relocation.'))
   ```
   (`stock_quant.py#L506-L506`)  
   Cette règle empêche le déplacement de quantités négatives ou de quantités stockées dans des emplacements multi‑entreprises.

---

**Règle distincte garantissant l’unicité d’un numéro de série**

Dans les extraits fournis (`stock_quant.py`), aucune contrainte ou règle n’est explicitement mentionnée pour assurer l’unicité d’un numéro de série (`lot_id`).  
Si une telle règle existe, elle ne figure pas dans les observations ci‑dessus.  

En résumé :

- La création d’un `stock.quant` invalide est bloquée par la contrainte de type de produit, les messages d’erreur explicites et le contrôle de la quantité/location.
- L’unicité d’un numéro de série n’est pas détaillée dans les données présentées.

[Source: Graphe de Connaissances Code Intelligence]
```

---