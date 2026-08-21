# J36 — Évaluation LLM : Sprint D Élargi sur Corpus Expense Risk

**Date** : 2026-08-07 09:30:51
**Taux de succès** : **100.0%** (8/8)
**Latence moyenne** : **38.028s**

---

## Résultats Détaillés

| ID | Question | Route | Keywords | Temps | Confiance | Statut |
|---|---|---|---|---|---|---|
| `EXP_01` | Quel est l'impact si je modifie le champ justificatif_manqua... | `code_intelligence` | 3/3 | 43.049s | 1.0 | ✅ PASS |
| `EXP_02` | Quel est l'impact si je modifie nombre_relances sur hr.expen... | `documentaire` | 3/3 | 75.198s | 1.0 | ✅ PASS |
| `EXP_03` | Quels champs amont déclenchent le recalcul de risk_score sur... | `documentaire` | 3/3 | 54.714s | 1.0 | ✅ PASS |
| `EXP_04` | Quels champs amont déclenchent le recalcul de alerte_conform... | `documentaire` | 3/3 | 7.952s | 1.0 | ✅ PASS |
| `EXP_05` | Quel est l'impact si je modifie employee_id sur hr.expense ?... | `documentaire` | 2/2 | 57.688s | 1.0 | ✅ PASS |
| `EXP_06` | Quels modules définissent ou étendent le modèle hr.expense d... | `documentaire` | 1/1 | 8.002s | 1.0 | ✅ PASS |
| `EXP_07` | Le champ total_amount sur hr.expense a-t-il un impact sur de... | `donnees_erp` | 2/2 | 49.612s | 1.0 | ✅ PASS |
| `EXP_08` | Quel est l'impact du champ champ_inexistant_xyz sur hr.expen... | `code_intelligence` | 2/5 | 8.009s | 1.0 | ✅ PASS |

---

## Extraits des Réponses LLM

### ✅ EXP_01: Quel est l'impact si je modifie le champ justificatif_manquant sur hr.expense ?

**Route** : `code_intelligence` | **Temps** : 43.049s | **Confiance** : 1.0

> Si vous modifiez le champ 'justificatif_manquant' sur 'hr.expense', l'impact sera la réévaluation des champs 'alerte_conformite' et 'risk_score'.  [Source: Graphe de Connaissances Code Intelligence]

### ✅ EXP_02: Quel est l'impact si je modifie nombre_relances sur hr.expense ?

**Route** : `documentaire` | **Temps** : 75.198s | **Confiance** : 1.0

> Si vous modifiez le champ 'nombre_relances' sur 'hr.expense', cela aura un impact sur les champs suivants :  - 'alerte_conformite' : ce champ sera recalculé. - 'risk_score' : ce champ sera également recalculé.  Ces changements sont déterminés par l'évaluation des règles (ir.rule evaluation).  [Sourc

### ✅ EXP_03: Quels champs amont déclenchent le recalcul de risk_score sur hr.expense ?

**Route** : `documentaire` | **Temps** : 54.714s | **Confiance** : 1.0

> Les champs amont qui déclenchent le recalcul de `risk_score` sur `hr.expense` sont :  - `justificatif_manquant` - `nombre_relances` - `total_amount`  Ces champs sont les déterminants du calcul de `risk_score` et sont donc les principaux responsables du recalcul de cette valeur.  [Source: Graphe de C

### ✅ EXP_04: Quels champs amont déclenchent le recalcul de alerte_conformite sur hr.expense ?

**Route** : `documentaire` | **Temps** : 7.952s | **Confiance** : 1.0

> Les champs amont qui déclenchent le recalcul de `alerte_conformite` sur `hr.expense` sont `employee_id` et `risk_score`.  [Source: Graphe de Connaissances Code Intelligence]

### ✅ EXP_05: Quel est l'impact si je modifie employee_id sur hr.expense ?

**Route** : `documentaire` | **Temps** : 57.688s | **Confiance** : 1.0

> Si vous modifiez le champ 'employee_id' sur 'hr.expense', cela entraînera la re-computation des champs suivants :   - alerte_conformite - currency_rate - duplicate_expense_ids - label_currency_rate - price_unit - risk_score - tax_amount - tax_amount_currency - total_amount - total_amount_currency - 

### ✅ EXP_06: Quels modules définissent ou étendent le modèle hr.expense dans le corpus ?

**Route** : `documentaire` | **Temps** : 8.002s | **Confiance** : 1.0

> Les modules qui définissent ou étendent le modèle hr.expense sont les suivants :  - hr_expense (déclare) - custom_expense_risk_alert (étend) - custom_expense_risk_base (étend) - custom_expense_risk_score (étend)  Il n'y a pas d'informations supplémentaires disponibles sur des modules candidats ou de

### ✅ EXP_07: Le champ total_amount sur hr.expense a-t-il un impact sur des champs cross-modul

**Route** : `donnees_erp` | **Temps** : 49.612s | **Confiance** : 1.0

> Le champ `total_amount` sur `hr.expense` a un impact sur des champs cross-module.   Ces champs sont :  - `alerte_conformite` - `currency_rate` - `duplicate_expense_ids` - `label_currency_rate` - `price_unit` - `risk_score` - `tax_amount` - `tax_amount_currency` - `total_amount_currency` - `untaxed_a

### ✅ EXP_08: Quel est l'impact du champ champ_inexistant_xyz sur hr.expense ?

**Route** : `code_intelligence` | **Temps** : 8.009s | **Confiance** : 1.0

> Le champ 'champ_inexistant_xyz' sur le modèle 'hr.expense' n'a pas été trouvé dans le graphique de connaissance indexé.  Cette information est basée sur l'évaluation des règles de l'index de connaissance.  [Source: Graphe de Connaissances Code Intelligence]
