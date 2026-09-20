# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-20 09:50:17

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `3.66s` |
| p90 latence effective | `3.66s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `3.66s` |
| Max | `3.66s` |

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 3.66s | Effectif: 3.662s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Modèle `account.move`

- **Nature** : `account.move` est **déclaré** dans le module `account`.  
  - Source : [account_move.py:L5-L22](file:///media/donnee/projets/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L5-L22)  
  - Il n’est pas une extension d’un modèle existant, mais un nouveau modèle métier.

- **Héritage** : il hérite de plusieurs mixins génériques (mail, portal, sequence, UTM) mais **ne dérive pas d’un modèle natif hors de l’écosystème comptable**.  
  - Source : [account_move.py:L5-L22](file:///media/donnee/projets/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L5-L22)  
  - Les mixins (`mail.thread.main.attachment`, `mail.activity.mixin`, `portal.mixin`, `sequence.mixin`, `utm.mixin`) sont des modèles génériques, pas des modèles comptables.

### Extension du module `account`

- Le module `account` **n’étend pas** un modèle natif qui ne fait pas partie de son périmètre comptable.  
  - Il ne modifie pas, par exemple, `res.partner` ou d’autres modèles métier non liés à la comptabilité.  
  - Les seules extensions sont vers des mixins génériques, ce qui est normal pour ajouter des fonctionnalités transversales (notifications, portail, séquences, etc.).

En résumé, `account.move` est un nouveau modèle créé par le module `account`, et le module ne s’étend pas sur des modèles natifs hors de son domaine comptable.

[Source: Graphe de Connaissances Code Intelligence]
```

---