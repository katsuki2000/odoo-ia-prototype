# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-20 10:10:47

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `81.33s` |
| p90 latence effective | `81.33s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `81.33s` |
| Max | `81.33s` |

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 81.34s | Effectif: 81.334s | Groq wait: 0.0s | Sauts: 3) :**
```text
**Réponse**

- **`account.move` est un modèle *déclaré* par le module `account`.**  
  Le fichier source qui le définit se trouve dans le module `account` :  
  `file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L81-L161`.

- **Il s’agit d’un nouveau modèle, pas d’une extension d’un modèle existant.**  
  Dans la chaîne d’héritage, le modèle est déclaré comme :  
  `class AccountMove(models.Model): _name = "account.move"` (voir `file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L81-L161`).

- **Le module `account` étend ce modèle en ajoutant des mixins génériques.**  
  La chaîne d’héritage montre que `account.move` hérite de :  
  - `mail.thread.main.attachment`  
  - `portal.mixin`  
  - `mail.activity.mixin`  
  - `sequence.mixin`  
  - `utm.mixin`  
  (voir `Inheritance Chain for 'account.move': Extensions (_inherit): [account.move, mail.activity.mixin, mail.thread.main.attachment, portal.mixin, sequence.mixin, utm.mixin]`).

- **Il n’étend pas un modèle natif hors de son périmètre comptable ;**  
  les seuls modèles hérités sont des mixins génériques (mail, portal, etc.) et non d’autres modèles métier spécifiques à un autre domaine.

En résumé, `account.move` est un modèle propre au module `account`, déclaré dans ce module, et il étend uniquement des mixins génériques pour ajouter des fonctionnalités de suivi, de portail, de séquence, etc. Aucun modèle natif d’un autre domaine n’est étendu par `account`.

[Source: Graphe de Connaissances Code Intelligence]
```

---