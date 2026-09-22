# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-22 16:44:35

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective | `48.19s` |
| p90 latence effective | `48.19s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `48.19s` |
| Max | `48.19s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 48.25s | Effectif: 48.188s | Groq wait: 0.0s | Sauts: 2) :**
```text
## Résumé des droits d’un utilisateur « simple » (base.group_user)

| Action | Autorisation | Détails |
|--------|--------------|---------|
| **Lire** une fiche équipement (`maintenance.equipment`) | **Oui** | Le groupe `base.group_user` possède le droit de lecture sur le modèle. La règle globale `maintenance.maintenance_equipment_comp_rule` limite l’accès aux équipements de la même société, mais ne restreint pas davantage les utilisateurs simples. |
| **Modifier** une fiche équipement | **Non** | Seul le groupe `group_equipment_manager` a le droit d’écriture (`WRITE`). Les utilisateurs simples n’ont pas ce droit. |
| **Consulter** quels équipements | **Tous les équipements de la société** | La règle globale impose le filtre `company_id` (les équipements de la même société). Il n’y a pas de règle de groupe supplémentaire qui restreint davantage les utilisateurs simples. |

### Conclusion

- Un utilisateur simple **ne peut pas modifier** aucune fiche équipement.  
- Il peut **consulter** toutes les fiches équipements appartenant à sa société, sans restriction supplémentaire.  

> **Note** : aucune règle de groupe ne limite la visibilité des équipements pour les utilisateurs simples, donc ils voient l’ensemble des équipements de leur société.

[Source: Graphe de Connaissances Code Intelligence]
```

---