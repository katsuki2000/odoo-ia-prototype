# Rapport Verbatim — Test Adversarial (End-to-End Benchmark)

**Date d'exécution :** 2026-09-12 05:58:42

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim et la latence après instrumentation J30-J31.

---
## Synthèse Latence & Performance 

| Métrique | Temps Effectif (Algorithmique) | Budget Target | Statut |
|---|---|---|---|
| **p50 (Médiane)** | `55.35s` | — | — |
| **p90 (90e Percentile)** | `79.33s` | `12.0s` |  DÉPASSÉ |
| **p95 (95e Percentile)** | `79.33s` | — | — |
| **Moyenne** | `55.35s` | — | — |
| **Max** | `79.33s` | — | — |

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (Total: 79.33s | Effectif: 79.329s | Groq wait: 0.0s | Sauts: 4) :**
```text
Le moteur de règles ne peut pas déterminer avec certitude si l'utilisateur peut voir cet enregistrement pour ce montant (voir le fait déterministe ci-dessous).

**Pourquoi l’accès reste indéterminé**

- Les règles d’enregistrement (`ir.rule`) pour le modèle `account.move` contiennent deux règles de groupe qui s’appliquent aux avoirs :
  - `custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale` : `[['|', ('move_type', '!=', 'out_refund'), ('amount_total', '<=', 50000)]]` (xml_id: custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale)
  - `custom_credit_note_visibility_rules.rule_avoir_visibilite_nationale` : `[[ (1, '=', 1) ]]` (xml_id: custom_credit_note_visibility_rules.rule_avoir_visibilite_nationale)

  Ces règles sont combinées en **OU**. La règle nationale est toujours vraie, mais la règle régionale impose une restriction lorsqu`amount_total <= 50000`.  
- Les règles globales (`account.account_move_comp_rule` et `custom_credit_note_visibility_rules.rule_avoir_multi_societe`) imposent un filtre sur `company_id` et `user.company_id.id`.  
- Le moteur de règles ne peut pas déterminer l’accès pour un montant de 80 000 € car il doit évaluer simultanément les conditions dépendant de `user`, `company_id`, `company_ids` et `amount_total`.  
  - Observation : “Pour un montant de 80000€, le moteur de règles NE PEUT PAS déterminer si l'utilisateur peut voir cet enregistrement (can_view_amount_v2() = indeterminate)”.  

En l’absence d’une règle explicite qui autorise ou refuse l’accès pour un avoir de 80 000 € lorsqu’un utilisateur appartient aux deux groupes, le résultat reste indéterminé.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (Total: 31.36s | Effectif: 31.363s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Peut‑il voir l’avoir de 80 000 € ?

Oui, **s’il appartient à la même société** que l’avoir.  
Les règles d’enregistrement qui s’appliquent à un avoir (`move_type = 'out_refund'`) sont :

| Type de règle | Condition | Groupe ciblé | Résultat pour un utilisateur sans groupe régional ni national |
|---------------|-----------|--------------|-------------------------------------------------------------|
| **Globale** – *Account Entry* | `company_id in company_ids` | Aucun | Appliquée à tous les utilisateurs de la société |
| **Globale** – *Avoirs – cantonnement société* | `| ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)` | Aucun | Appliquée à tous les utilisateurs de la société |
| **Groupe** – *Avoirs – visibilite par département* | … | `custom_credit_note_approval.rule_avoir_visibilite_departement` | Ignorée (l’utilisateur n’appartient à aucun groupe ciblé) |
| **Groupe** – *Avoirs – plafond visibilite régionale* | `| ('move_type', '!=', 'out_refund'), ('amount_total', '<=', 50000)` | `custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale` | Ignorée |
| **Groupe** – *Avoirs – visibilite nationale* | `[(1, '=', 1)]` | `custom_credit_note_visibility_rules.rule_avoir_visibilite_nationale` | Ignorée |

> **Source** : [Évaluation des règles d'enregistrement (ir.rule) pour 'account.move'](file:///media/donnee/projets/odoo-ia-prototype/odoo_addons/custom_credit_note_approval_regional/models/account_move.py#L1-L21)

Comme l’utilisateur ne fait partie d’aucun des groupes ciblés par les règles de groupe, celles‑ci sont ignorées. Seules les règles globales restent actives, et elles ne contiennent aucune restriction de montant. Elles ne font intervenir que la condition `company_id = user.company_id.id`.  

- Si l’avoir appartient à la même société que l’utilisateur, il est visible.  
- Si l’avoir appartient à une autre société, il n’est pas visible.

En résumé, **l’absence de groupe régional ou national ne bloque pas la visibilité** tant que l’utilisateur partage la même société que l’avoir.

[FAIT DÉTERMINISTIQUE] Pour un montant de 80000€, le moteur de règles NE PEUT PAS déterminer si l'utilisateur peut voir cet enregistrement (can_view_amount_v2() = indeterminate) : au moins une règle applicable dépend de company_id, company_ids, user, qui ne sont pas connus dans ce contexte. Ne pas affirmer que l'accès est autorisé ou refusé -- signaler explicitement cette incertitude à l'utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---