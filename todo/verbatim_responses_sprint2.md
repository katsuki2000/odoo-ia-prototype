# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-03 08:56:31

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (86.45s) :**
```text
En fonction des analyses effectuées, il semble que le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) soit déterminé par la présence d'un verrou spécifique dans le module `custom_credit_note_approval`. Ce verrou est défini dans le fichier `account_move.py` (file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L12-L25) et indique que "Seul un responsable comptable peut valider un avoir de plus de 5000€.".

Ainsi, en fonction de cette analyse, seul un responsable comptable a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) [Confiance: HIGH].

⚠️ SOURCING NON VÉRIFIÉ (J14): citation(s) fichier non retrouvée(s) dans les données produites: home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L12-L25. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (91.05s) :**
```text
En réponse à votre question, il semble que les règles d'enregistrement (ir.rule) pour le modèle 'account.move' ne contiennent aucune restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour l'utilisateur en question. [Confiance: FAIBLE]

Cependant, il est important de noter que l'utilisateur n'appartient à aucun groupe cible par une règle sur ce modèle, ce qui signifie que seules les règles globales s'appliquent. [Confiance: FAIBLE]

En outre, lors de l'analyse des groupes, il n'a pas été possible de résoudre l'identifiant 'client_vip' contre n'importe quel groupe avec des règles d'écriture ou des ACLs sur le modèle 'account.move'. [Confiance: FAIBLE]

Il est donc impossible de déterminer avec certitude qui a le droit d'approuver un avoir pour un client VIP en fonction des informations fournies. [Confiance: FAIBLE]

Cependant, il est possible que les règles globales s'appliquent, comme indiqué ci-dessus. [Confiance: FAIBLE]

Référence : 
- ir.rule évaluation pour 'account.move' : 
  - Règles Globales (ET pour tous) : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]] 
  - Règles de Groupe applicables : Aucune (l'utilisateur n'appartient à aucun des groupes visés)
  - Règles de Groupe ignorées (non-membre) : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee)
  -> CONCLUSION : Aucune regle de groupe applicable (l'utilisateur n'appartient a aucun groupe cible par une regle sur ce modele). Seules les regles globales ci-dessus s'appliquent -- il n'y a AUCUNE restriction supplementaire de montant ou de portee provenant d'une regle de groupe pour cet utilisateur.
- Analyse des groupes : 
  - Group identifier 'client_vip' could not be resolved against any group with WRITE rules or ACLs on 'account.move'. This does NOT mean access is denied -- it means the identifier itself could not be matched. Try lister_modules_impliques or resoudre_nom_technique to find the exact group xml_id.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (87.18s) :**
```text
Réponse :

Je comprends que vous rencontrez des difficultés pour valider votre demande de congé malgré avoir coché 'urgente'. Voici quelques observations qui pourraient expliquer ce problème :

1. **Analyse des verrous Python** : [hr_leave.py](file:///home/user/odoo-17.0/addons/custom_hr_leave_workflow/models/hr_leave.py) [Confiance: HIGH] : Il semble que vous ayez atteint votre solde de congés restant. Le système vous avertit que vous devez cocher 'Demande urgente' pour soumettre une demande exceptionnelle de validation du N+2. Cependant, même avec 'urgente' cochée, vous devez avoir suffisamment de congés restants pour valider votre demande.

2. **Évaluation des règles d'enregistrement (ir.rule)** : Aucune règle de groupe applicable [Confiance: MÉDI] : Vous n'appartenez à aucun groupe cible par une règle sur le modèle 'hr.leave'. Les règles globales ne sont pas applicables dans ce cas.

3. **Model 'hr.leave' [WRITE]** : Aucune règle de groupe applicable [Confiance: MÉDI] : Comme mentionné précédemment, vous n'appartenez à aucun groupe cible par une règle sur le modèle 'hr.leave'.

4. **Erreur de fichier** : File 'hr/models/hr_leave.py' does not exist [Confiance: ÉLEVÉ] : Il semble qu'il y ait une erreur de fichier liée au modèle 'hr_leave.py'. Cependant, cela n'affecte pas directement votre demande de congé.

En résumé, il semble que vous ayez atteint votre solde de congés restant, ce qui empêche la validation de votre demande. Vous devez cocher 'Demande urgente' et avoir suffisamment de congés restants pour valider votre demande.

⚠️ SOURCING NON VÉRIFIÉ (J14): lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): home/user/odoo-17.0/addons/custom_hr_leave_workflow/models/hr_leave.py. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (27.41s) :**
```text
En analysant les verrous Python, nous constatons que les logins/emails privilégiés en dur sont ['direction@societe.com', 'daf@societe.com'] [Confiance: HIGH]. Cela signifie que ces utilisateurs ont le droit d'approuver une demande d'achat.

De plus, les messages de verrous indiquent que "Vous n'avez pas le droit de valider cette demande d'achat." et "Au-delà de 10 000 euros, seule la Direction peut valider (liste restreinte)." [Confiance: HIGH]. Cependant, il est important de noter que ces messages ne sont pas liés à la demande d'achat de 15 000€, mais plutôt à des conditions générales.

L'évaluation des règles d'enregistrement (ir.rule) pour 'custom.purchase.request' n'a pas révélé de règles globales ou de règles de groupe applicables [Confiance: MEDIUM]. Cela signifie que les utilisateurs n'ont pas de restrictions supplémentaires de montant ou de portée provenant d'une règle de groupe pour cet utilisateur.

Enfin, l'analyse des modules impliqués pour le modèle 'custom.purchase.request' n'a pas révélé de restrictions supplémentaires [Confiance: MEDIUM].

En conclusion, en fonction des verrous Python, les utilisateurs 'direction@societe.com' et 'daf@societe.com' ont le droit d'approuver une demande d'achat de 15 000€ [Confiance: HIGH].

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (11.75s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez suivre les étapes suivantes :

1. Vérifiez si vous avez les droits nécessaires pour effectuer cette action. Selon l'analyse des verrous Python, il est nécessaire de séparer les rôles : le bénéficiaire d'un matériel de plus de 2000 euros doit être différent du demandeur initial. (asset_loan.py#L12-L25)
2. Vérifiez si vous appartenez à un groupe qui a des règles d'enregistrement spécifiques pour le modèle 'custom.asset.loan'. Selon l'évaluation des règles d'enregistrement, il n'y a aucune règle de groupe applicable pour cet utilisateur. (ir.rule)
3. Vérifiez si vous avez accès à une action de serveur pour le modèle 'custom.asset.loan'. Selon l'analyse des actions de serveur, il n'y a aucune action de serveur disponible pour ce modèle. (ir.actions.server)
4. Vérifiez si vous avez des contraintes SQL ou des domaines relationnels définis pour le modèle 'custom.asset.loan'. Selon l'analyse des contraintes SQL et des domaines relationnels, il n'y a aucune contrainte ou domaine défini pour ce modèle. (Confiance: HIGH -- static pattern match, deterministic)
5. Vérifiez si vous avez des transitions d'état de workflow définies pour le modèle 'custom.asset.loan'. Selon l'analyse des transitions d'état de workflow, il n'y a aucune transition d'état définie pour ce modèle.

Une fois ces étapes vérifiées, vous pouvez effectuer la demande de mise à disposition de matériel en utilisant la fonction 'custom_asset_loan_mise_disposition' du modèle 'custom.asset.loan'. (custom_asset_loan_mise_disposition 'custom_asset_loan_mise_disposition' --[CONNECTED_TO]--> custom_asset_loan 'custom_asset_loan'.)

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (62.89s) :**
```text
En analysant les données fournies, il est clair que les avoirs fournisseurs ne passent pas tous par les mêmes règles d'approbation. 

D'une part, l'analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] révèle que cet action serveur automatise la validation d'avoirs reçus de trois fournisseurs spécifiques, en contournant les règles d'accès et les ACL via sudo(), ce qui implique que ces avoirs sont traités de manière privilégiée et non conforme aux règles d'approbation habituelles [1].

D'autre part, l'évaluation des règles d'enregistrement (ir.rule) pour 'account.move' révèle que seules les règles globales s'appliquent, sans aucune règle de groupe applicable pour l'utilisateur en question [2]. Cela signifie que les avoirs reçus de fournisseurs autres que ceux spécifiques traités par l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' sont soumis aux règles globales d'approbation, sans contournement des droits d'accès.

En conclusion, les avoirs fournisseurs ne passent pas tous par les mêmes règles d'approbation, car certains sont traités de manière privilégiée et non conforme aux règles d'approbation habituelles, tandis que d'autres sont soumis aux règles globales d'approbation.

Références :
[1] Analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution]
[2] Évaluation des règles d'enregistrement (ir.rule) pour 'account.move'

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (47.5s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour 'account.move', l'utilisateur membre à la fois du groupe régional et du groupe national peut voir un avoir de 80 000€, mais avec certaines restrictions.

Les règles globales (ET pour tous) indiquent que l'utilisateur peut voir les avoirs, sauf en cas de remboursement (out_refund) et si la société n'est pas la même que celle de l'utilisateur (company_id != user.company_id.id).

Les règles de groupe applicables (combinées en OU) sont les suivantes :

- Avoirs - plafond visibilité régionale (50000e) : l'utilisateur peut voir les avoirs si le montant total est inférieur ou égal à 50 000€.
- Avoirs - visibilité nationale (illimitée) : l'utilisateur peut voir les avoirs sans aucune restriction.

Cependant, les règles de groupe ignorées (non-membre) ne sont pas pertinentes pour cette situation, car l'utilisateur est membre des groupes régionaux et nationaux.

En conclusion, l'utilisateur peut voir un avoir de 80 000€, mais il doit satisfaire les conditions des règles de groupe applicables. 

[Confiance: MÉDI]

Référence : 
- Règles d'enregistrement (ir.rule) pour 'account.move' (file:///path#L12-L25)

⚠️ SOURCING NON VÉRIFIÉ (J14): citation(s) fichier non retrouvée(s) dans les données produites: path#L12-L25. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (57.26s) :**
```text
En réponse à votre question, l'utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut voir l'avoir de 80 000€, [Confiance: FAIBLE]. 

En effet, lors de l'évaluation des règles d'enregistrement (ir.rule) pour 'account.move', aucune règle de groupe n'est applicable pour cet utilisateur, car il n'appartient à aucun des groupes visés par les règles de groupe. Les seules règles globales s'appliquent, qui ne comportent aucune restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (11.05s) :**
```text
En fonction des informations disponibles, il semble que les règles d'enregistrement (ir.rule) pour le modèle 'custom.reimbursement.request' n'aient pas de règles globales ni de règles de groupe applicables pour l'utilisateur en question. 

Ainsi, aucune règle de groupe n'est applicable pour cet utilisateur, ce qui signifie que seules les règles globales s'appliquent. Il n'y a pas de restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur.

En conséquence, pour valider une demande de remboursement de frais dans le module 'custom_expense_reimbursement_indirect', il faudrait vérifier les règles globales applicables pour ce modèle.

[Source: Graphe de Connaissances Code Intelligence]
```

---