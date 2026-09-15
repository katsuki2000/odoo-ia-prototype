# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-15 10:34:33

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `2.68s` |
| p90 latence effective | `2.68s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `2.68s` |
| Max | `2.68s` |

---

## [MNT-Q4] maintenance -- ui (easy)
**Question :** Pourquoi le champ 'cost' (cout) d'un equipement n'est-il pas visible pour tous les utilisateurs ayant acces en lecture a sa fiche ?

**Reponse de reference (verite-terrain) :**
> Le champ cost porte groups='maintenance.group_equipment_manager' dans la vue formulaire -- reserve aux managers, independamment du droit de lecture sur la fiche elle-meme : un utilisateur simple qui suit un equipement (et le voit donc via equipment_rule_user) ne voit pas ce champ precis dans le formulaire.

**A verifier dans le code :** `views/maintenance_views.xml, <field name="cost" groups="maintenance.group_equipment_manager"/>`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 2.68s | Effectif: 2.679s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi le champ **cost** n’est pas visible ?

Le champ **cost** (coût) est déclaré dans la vue `maintenance.equipment` avec un filtre de groupe :

- **Déclaration** : `<field name="cost" groups="maintenance.group_equipment_manager"/>`  
  **Source** : [maintenance_views.xml:L445-L451](file:///home/user/odoo-17.0/addons/maintenance/views/maintenance_views.xml#L445-L451)

Cette balise `groups="maintenance.group_equipment_manager"` signifie que **seuls les utilisateurs appartenant au groupe `maintenance.group_equipment_manager`** peuvent voir ce champ, même s’ils disposent d’un droit de lecture sur le modèle `maintenance.equipment`.  

En Odoo, les droits d’accès au modèle (via `ir.model.access`) contrôlent l’accès aux enregistrements, tandis que les attributs `groups` dans les vues contrôlent la visibilité des champs. Le champ reste invisible pour les autres groupes, même si ces derniers peuvent lire l’enregistrement.

**Solution**  
Si vous souhaitez que d’autres utilisateurs voient ce champ, vous devez :

1. Ajouter ces utilisateurs au groupe `maintenance.group_equipment_manager`, ou
2. Modifier la vue pour enlever ou ajuster l’attribut `groups` sur le champ `cost`.

---

[Source: Graphe de Connaissances Code Intelligence]
```

---