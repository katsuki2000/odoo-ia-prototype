# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-18 16:02:20

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `25.84s` |
| p90 latence effective | `25.84s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `25.84s` |
| Max | `25.84s` |

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 25.84s | Effectif: 25.842s | Groq wait: 0.0s | Sauts: 3) :**
```text
**Réponse**

- **`account.move` est un modèle déclaré dans le module `account`.**  
  Le fichier `account_move.py` du module `account` contient la déclaration :  
  `class AccountMove(models.Model): _name = "account.move"` (voir `file:///home/user/odoo-17.0/addons/account/models/account_move.py#L5-L22`).  
  Il ne s’agit donc pas d’une extension d’un modèle déjà existant, mais d’un nouveau modèle introduit par `account`.

- **Il ne s’agit pas d’une extension d’un modèle natif hors de son périmètre comptable.**  
  L’héritage de `account.move` se fait uniquement sur des mixins métier (et non sur un modèle « natif » comme `res.partner`, `res.company`, etc.).  
  La chaîne d’héritage est la suivante :  
  `portal.mixin → mail.thread.main.attachment → mail.activity.mixin → sequence.mixin → utm.mixin` (voir `file:///home/user/odoo-17.0/addons/account/models/account_move.py#L5-L22`).  
  Aucun modèle natif hors du domaine comptable n’est étendu par `account.move`.

En résumé, `account.move` est un modèle **déclaré** dans le module `account` et ne repose que sur des mixins métier ; il n’étend pas de modèle natif en dehors de son périmètre comptable.

[Source: Graphe de Connaissances Code Intelligence]
```

---