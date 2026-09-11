# Rapport Verbatim — Test Adversarial (End-to-End Benchmark)

**Date d'exécution :** 2026-09-11 16:42:24

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim et la latence après instrumentation J30-J31.

---
## Synthèse Latence & Performance 

| Métrique | Temps Effectif (Algorithmique) | Budget Target | Statut |
|---|---|---|---|
| **p50 (Médiane)** | `39.27s` | — | — |
| **p90 (90e Percentile)** | `90.61s` | `12.0s` |  DÉPASSÉ |
| **p95 (95e Percentile)** | `90.61s` | — | — |
| **Moyenne** | `42.4s` | — | — |
| **Max** | `90.61s` | — | — |

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (Total: 90.61s | Effectif: 90.61s | Groq wait: 0.0s | Sauts: 4) :**
```text
**Qui peut valider un avoir de 25 000 € ?**

| Observation | Explication | Source |
|-------------|-------------|--------|
| **Verrou Python dans `custom_credit_note_approval`** – “Seul un responsable comptable peut valider un avoir de plus de 5000 €.” (condition : `rec.amount_total > 5000` et `not self.env.user.has_group('account.group_account_manager')`) | Pour tout avoir dont le montant dépasse 5 000 €, la validation est autorisée uniquement aux utilisateurs appartenant au groupe **account.group_account_manager**. Le montant de 25 000 € dépasse ce seuil, donc seul un responsable comptable peut l’approuver. | xml_id: account.group_account_manager (file:///home/user/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L1-L22) |
| **Module `custom_credit_note_approval_vip`** – condition `rec.partner_id.avoir_vip_exempt` | Cette règle ne s’applique que pour les clients VIP. Le client est « normal » (pas VIP), donc la clause n’est pas activée et n’affecte pas l’autorisation. | file:///home/user/odoo-ia-prototype/odoo_addons/custom_credit_note_approval_vip/models/account_move.py#L7-L14 |
| **Chaîne de surcharge `custom_credit_note_approval_regional`** – “CHAINE RELATIONNELLE NON VÉRIFIÉE” (condition `rec.amount_total > 20000` → notification au directeur via `env.user.employee_id.parent_id.parent_id.user_id`) | Cette règle ajoute un risque de notification silencieuse si la chaîne hiérarchique est incomplète, mais elle ne modifie pas l’autorité requise pour la validation. Le responsable comptable reste le seul à pouvoir valider. | file:///home/user/odoo-ia-prototype/odoo_addons/custom_credit_note_approval_regional/models/account_move.py#L1-L21 |

**Conclusion**  
Pour un avoir de 25 000 € destiné à un client normal, **seul un utilisateur appartenant au groupe `account.group_account_manager` (responsable comptable) a le droit de l’approuver**. Les autres modules (VIP ou régional) ne changent pas cette autorité, bien qu’ils introduisent des risques de notification ou d’exemption qui ne concernent pas la validation elle‑même.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (Total: 83.04s | Effectif: 83.044s | Groq wait: 0.0s | Sauts: 4) :**
```text
**Qui peut valider un avoir pour un client VIP ?**

| Condition | Autorité requise | Source |
|-----------|------------------|--------|
| **Montant > 5 000 €** | Seul un utilisateur appartenant au groupe `account.group_account_manager` peut valider l’avoir. | `xml_id: account.group_account_manager` – message de verrou dans `custom_credit_note_approval/models/account_move.py` (L13‑L22) |
| **Montant ≤ 5 000 €** | Aucun groupe particulier n’est requis ; tout utilisateur peut valider. | Même verrou, mais la condition `rec.amount_total > 5000` n’est pas satisfaite. |

### Pourquoi le module « VIP » ne supprime pas cette restriction ?

Le module `custom_credit_note_approval_vip` contient une surcharge de `action_valider_avoir` :

```
def action_valider_avoir(self):
    for rec in self:
        if rec.partner_id.avoir_vip_exempt:
            # client VIP : validation directe, pas de seuil
            rec.avoir_valide_par_id = self.env.user
            rec.avoir_niveau_appro = 'n1'
            continue
    return super().action_valider_avoir()
```

Cette surcharge est suivie d’un appel `super().action_valider_avoir()` **inconditionnel** (voir `SUPER() NON GARDÉ` dans la chaîne de surcharge).  
En pratique, même si le client est VIP et que la branche conditionnelle est exécutée, l’appel `super()` réapplique la logique du module parent (`custom_credit_note_approval`). Ainsi, pour les montants supérieurs à 5 000 €, la restriction du groupe `account.group_account_manager` reste en vigueur.

### Risque supplémentaire (module régional)

Le module `custom_credit_note_approval_regional` ajoute une notification de directeur pour les montants > 20 000 € (`CHAINE RELATIONNELLE NON VÉRIFIÉE`).  
Cette règle ne change pas l’autorité d’approbation, mais elle peut entraîner

[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode contient une condition supplémentaire déclenchée au-delà de 20000€, distincte du groupe requis ci-dessus. Fait extrait directement de l'analyse statique du code.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (Total: 34.55s | Effectif: 34.554s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Pourquoi votre demande de congé ne peut pas être validée malgré l’option « Urgente » ?

Le code de validation de la demande de congé contient une **verrou** (security lock) qui empêche la validation lorsqu’une demande urgente dépasse le solde de congés restant **et** que l’utilisateur n’est ni le N+2 (le supérieur hiérarchique direct du supérieur de l’employé) ni un responsable RH.

> **Message d’erreur**  
> “Une demande urgente depassant le solde doit etre validee par le N+2 ou un responsable RH.”  
> (condition : `rec.conge_urgence and rec.number_of_days > rec.employee_id.remaining_leaves and self.env.user != rec.employee_id.parent_id.parent_id.user_id and (not self.env.user.has_group('hr_holidays.group_hr_holidays_manager'))”)  
> [hr_leave.py:L1-L28](file:///home/user/odoo-ia-prototype/odoo_addons/custom_hr_leave_workflow/models/hr_leave.py#L1-L28)

#### Ce qui se passe dans votre cas

| Condition | Ce qui se passe | Résultat |
|-----------|-----------------|----------|
| `rec.conge_urgence` | Vous avez coché « Urgente » | Vrai |
| `rec.number_of_days > rec.employee_id.remaining_leaves` | Votre demande dépasse le solde de congés restant | Vrai |
| `self.env.user != rec.employee_id.parent_id.parent_id.user_id` | Vous n’êtes **pas** le N+2 (le supérieur hiérarchique du supérieur de votre manager) | Vrai |
| `not self.env.user.has_group('hr_holidays.group_hr_holidays_manager')` | Vous n’avez pas le groupe **Responsable RH** | Vrai |

Comme toutes les conditions sont vraies, le verrou s’active et la validation est bloquée.

#### Que faire ?

1. **Vérifiez votre position hiérarchique**  
   - Si vous êtes le N+2 (le supérieur direct du manager de votre manager), vous pourrez valider la demande.  
   - Sinon, vous devez demander à votre N+2 ou à un responsable RH de valider la demande.

2. **Contactez le responsable RH**  
   - Le groupe `hr_holidays.group_hr_holidays_manager` est requis pour contourner ce verrou.  
   - Demandez à un membre de ce groupe de valider votre demande urgente.

3. **Si vous pensez être le N+2**  
   - Vérifiez que votre compte utilisateur est bien lié à la bonne personne dans la hiérarchie (champ `parent_id` de votre manager).  
   - Si la hiérarchie est correcte, le verrou ne devrait plus s’activer.

En résumé, la validation échoue parce que votre demande dépasse le solde de congés restant et que vous n’êtes ni le N+2 ni un responsable RH. Vous devrez donc faire valider la demande par l’un de ces deux rôles.

[FAIT DÉTERMINISTIQUE] Court-circuit ET (déterministe) : l'analyse statique du code montre que la condition dépend de 'rec.conge_urgence', 'conflicting_holidays' en première position d'un `and` -- si ce champ est vide ou absent (aucun enregistrement lié), toute la condition est FAUSSE par court-circuit Python, et la règle correspondante NE S'APPLIQUE PAS, quel que soit le reste de la condition (montant, etc.). Fait extrait directement de l'analyse statique du code, indépendant de toute reformulation en langage naturel.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (Total: 23.93s | Effectif: 23.929s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Qui peut approuver une demande d’achat de 15 000 € ?

- **Seule la Direction** (groupe : `purchase.group_purchase_manager`) peut valider une demande dont le montant estimé dépasse 10 000 €.  
- Les utilisateurs figurant dans la liste d’exceptions `rec._VALIDATEURS_EXCEPTIONNELS` sont également autorisés à valider, même si le montant est supérieur à 10 000 €.

> **Source** : analyse des verrous Python – `purchase_request.py` (L1‑L33)  
> [purchase_request.py:L1-L33](file:///home/user/odoo-ia-prototype/odoo_addons/custom_purchase_request/models/purchase_request.py#L1-L33)

[FAIT DÉTERMINISTIQUE] Le verrou de sécurité contient une condition supplémentaire déclenchée au-delà de 10000€, distincte du groupe requis ci-dessus. Fait extrait directement de l'analyse statique du code.

[Source: Graphe de Connaissances Code Intelligence]

[ACCES RESTREINT] ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION:
  - Logins/Emails privilégies en dur (custom.purchase.request) : Élément omis pour raison d'autorisation (ELEMENT OMITTED FOR AUTHORIZATION REASON) : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'custom.purchase.request'.
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (Total: 27.6s | Effectif: 27.599s | Groq wait: 0.0s | Sauts: 2) :**
```text
Pour demander la mise à disposition d’un matériel, il faut créer un enregistrement dans le modèle **custom.asset.loan** (le formulaire « Demande de mise à disposition »).  

**Condition particulière**  
- Si la demande est liée à une demande d’achat (`demande_achat_liee_id`) dont le montant estimé dépasse **2000 €**, alors le bénéficiaire du matériel doit être différent du demandeur initial.  
  - Cette règle est définie dans le code Python (asset_loan.py:L1-L30) et porte la mention :  
    > *Separation des rôles requise : le bénéficiaire d'un matériel de plus de 2000 euros doit être différent du demandeur initial.*  
    [Confiance: ÉLEVÉE]  

**Aucune autre restriction**  
- Aucune règle de groupe (`ir.rule`) ne s’applique à ce modèle pour l’utilisateur concerné.  
- Il n’y a donc pas de limitation supplémentaire liée à la compagnie ou à un groupe d’utilisateurs.

En résumé, vous pouvez soumettre votre demande de mise à disposition tant que vous respectez la condition ci‑dessus (si le montant estimé dépasse 2000 €). Aucune autre contrainte n’est imposée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (Total: 39.34s | Effectif: 39.341s | Groq wait: 0.0s | Sauts: 4) :**
```text
**Réponse :**

Non, les avoirs fournisseurs ne passent pas tous par exactement les mêmes règles d’approbation ; la règle de base est partagée, mais certains modules ajoutent ou modifient le comportement.

| Observation | Source | Détail | Impact |
|-------------|--------|--------|--------|
| **Règle de base** | Analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L1-L22)) | `Seul un responsable comptable peut valider un avoir de plus de 5000€.` (condition : `rec.amount_total > 5000` et `not self.env.user.has_group('account.group_account_manager')`) | Cette règle s’applique à tous les avoirs fournisseurs dont le montant dépasse 5000 €, exigeant l’approbation d’un membre du groupe `account.group_account_manager`. [Confiance: ÉLEVÉE] |
| **Module régional** | Analyse des verrous Python ([account_move.py:L1-L21](file:///home/user/odoo-ia-prototype/odoo_addons/custom_credit_note_approval_regional/models/account_move.py#L1-L21)) | Aucun verrou spécifique détecté | Le module régional ne modifie pas la règle de base ; il hérite donc de la condition > 5000 € et du besoin d’un responsable comptable. [Confiance: ÉLEVÉE] |
| **Module VIP** | Analyse des verrous Python ([account_move.py:L1-L14](file:///home/user/odoo-ia-prototype/odoo_addons/custom_credit_note_approval_vip/models/account_move.py#L1-L14)) | Aucun verrou spécifique détecté | Le module VIP ne modifie pas la règle de base ; il hérite également de la condition > 5000 € et du besoin d’un responsable comptable. [Confiance: ÉLEVÉE] |
| **Automation pour fournisseurs privilégiés** | Analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' (xml_id: custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie) | Condition de déclenchement : `rec.move_type == 'in_refund'` et `rec.partner_id.id in FOURNISSEURS_PRIVILEGIES` | Cette action serveur ne constitue pas une règle d’approbation stricte, mais elle peut déclencher des automatisations supplémentaires (ex. notifications) pour les fournisseurs figurant dans la liste `FOURNISSEURS_PRIVILEGIES`. [Confiance: FAIBLE] |

### Conclusion

- **Tous les avoirs fournisseurs** sont soumis à la règle de base : si le montant dépasse 5000 €, l’approbation doit être effectuée par un membre du groupe `account

[Source: Graphe de Connaissances Code Intelligence]

[ACCES RESTREINT] ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION:
  - SUDO détecté (account.move) : Élément omis pour raison d'autorisation (ELEMENT OMITTED FOR AUTHORIZATION REASON) : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'account.move'.
  - IDs en dur (account.move) : Élément omis pour raison d'autorisation (ELEMENT OMITTED FOR AUTHORIZATION REASON) : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'account.move'.
  - Interprétation LLM [confiance (account.move) : Élément omis pour raison d'autorisation (ELEMENT OMITTED FOR AUTHORIZATION REASON) : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'account.move'.
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (Total: 42.75s | Effectif: 42.748s | Groq wait: 0.0s | Sauts: 3) :**
```text
**Réponse :**  
Le moteur d’évaluation des règles ne peut pas déterminer de façon certaine si un utilisateur qui appartient à la fois au groupe régional et au groupe national pourra voir un avoir de 80 000 €.  

**Pourquoi l’accès est indéterminé ?**

1. **Règles de groupe applicables**  
   - `custom_credit_note_visibility_rules.rule_avoir_visibilite_regionale` : `[['|', ('move_type', '!=', 'out_refund'), ('amount_total', '<=', 50000)]]`  
   - `custom_credit_note_visibility_rules.rule_avoir_visibilite_nationale` : `[[ (1, '=', 1) ]]`  

   La règle nationale est sans condition (1 = 1), ce qui, en principe, autoriserait la visualisation sans limite de montant. Cependant, l’évaluation finale dépend également des règles globales et de la configuration de l’entreprise.

2. **Règles globales**  
   - `account.account_move_comp_rule` : `[['company_id', 'in', company_ids]]`  
   - `custom_credit_note_visibility_rules.rule_avoir_multi_societe` : `[['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]]`  

   Ces règles imposent des contraintes liées à l’`company_id` de l’en

[FAIT DÉTERMINISTIQUE] Pour un montant de 80000€, le moteur de règles NE PEUT PAS déterminer si l'utilisateur peut voir cet enregistrement (can_view_amount_v2() = indeterminate) : au moins une règle applicable dépend de company_id, company_ids, user, amount_total, qui ne sont pas connus dans ce contexte. Ne pas affirmer que l'accès est autorisé ou refusé -- signaler explicitement cette incertitude à l'utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (Total: 39.27s | Effectif: 39.269s | Groq wait: 0.0s | Sauts: 3) :**
```text
**Réponse :**  
Le moteur de règles ne peut pas déterminer avec certitude si l'utilisateur peut voir cet enregistrement pour ce montant (voir le fait déterministe ci-dessous).  

**Pourquoi ?**

1. **Aucune règle de groupe applicable** – l’utilisateur n’appartient à aucun des groupes ciblés par les règles de groupe (voir la section *Règles de Groupe applicables*).  
2. **Seules les règles globales s’appliquent** – les règles globales (ex. `account.account_move_comp_rule`, `custom_credit_note_visibility_rules.rule_avoir_multi_societe`) ne contiennent pas de condition sur le montant ou la portée qui exclurait explicitement un avoir de 80 000 €.  
3. **Conditions dépendantes de paramètres inconnus** – ces règles globales dépendent de champs tels que `company_id`, `company_ids` et `user`, dont les valeurs ne sont pas connues dans le contexte d’évaluation. En l’absence de ces informations, le moteur ne peut pas conclure à l’accès.

En résumé, il n’existe aucune restriction explicite qui empêche l’utilisateur d’accéder à l’avoir de 80 000 €, mais le moteur d’accès ne peut pas confirmer cette possibilité sans connaître les valeurs de `company_id` et d’autres paramètres contextuels.

[FAIT DÉTERMINISTIQUE] Pour un montant de 80000€, le moteur de règles NE PEUT PAS déterminer si l'utilisateur peut voir cet enregistrement (can_view_amount_v2() = indeterminate) : au moins une règle applicable dépend de company_id, company_ids, user, qui ne sont pas connus dans ce contexte. Ne pas affirmer que l'accès est autorisé ou refusé -- signaler explicitement cette incertitude à l'utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (Total: 0.52s | Effectif: 0.521s | Groq wait: 0.0s | Sauts: 3) :**
```text
Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. Ne pas présenter cette validation comme autorisée ou refusée de manière certaine. Source à revoir : [reimbursement.py:L1-L39](file:///home/user/odoo-ia-prototype/odoo_addons/custom_expense_reimbursement_indirect/models/reimbursement.py#L1-L39).

[Source: Graphe de Connaissances Code Intelligence]
```

---