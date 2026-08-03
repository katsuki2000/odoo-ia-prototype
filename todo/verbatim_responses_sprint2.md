# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-03 14:01:04

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (86.25s) :**
```text
Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

Analyse des verrous Python ([account_move.py](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py)) [Confiance: HIGH] :
- Messages de verrous (UserError/ValidationError) : "Seul un responsable comptable peut valider un avoir de plus de 5000€."

Ainsi, seul un responsable comptable peut valider un avoir de plus de 5000€.

⚠️ SOURCING NON VÉRIFIÉ (J14): lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (112.33s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour 'account.move', nous pouvons conclure que :

- Les règles globales s'appliquent, mais elles ne restreignent pas l'accès à l'avoir pour les clients VIP.
- Il n'y a aucune règle de groupe applicable pour cet utilisateur, car il n'appartient à aucun groupe cible par une règle sur ce modèle.
- Le groupe 'client_vip_manager' n'a pas pu être résolu contre aucun groupe avec des règles d'écriture ou des ACLs sur 'account.move'.

En conséquence, il semble que l'utilisateur n'a pas de restriction supplémentaire pour approuver un avoir pour un client VIP en fonction des règles d'enregistrement (ir.rule) pour 'account.move'.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (11.86s) :**
```text
Réponse claire et professionnelle :

Je comprends que vous rencontrez des difficultés pour valider votre demande de congé malgré avoir coché la case « urgente ». 

Analyse des verrous Python (hr_leave.py) [Confiance: HIGH] :
- Les messages de verrous indiquent que le solde de congés restant est insuffisant. Vous pouvez essayer de valider votre demande en cochant la case « urgente » pour une validation exceptionnelle du N+2.

Évaluation des règles d'enregistrement (ir.rule) pour 'hr.leave' :
- Aucune règle globale n'est applicable.
- Aucune règle de groupe n'est applicable pour l'utilisateur en question.

Analyse des verrous Python (hr_leave.py) [Confiance: HIGH] :
- Les messages de verrous indiquent que le solde de congés restant est insuffisant. Vous pouvez essayer de valider votre demande en cochant la case « urgente » pour une validation exceptionnelle du N+2.

En résumé, il semble que le problème soit lié au solde de congés restant insuffisant. Vous pouvez essayer de valider votre demande en cochant la case « urgente » pour une validation exceptionnelle du N+2.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (50.91s) :**
```text
En fonction des informations disponibles, voici la réponse :

Selon l'analyse des verrous Python, seuls les utilisateurs avec les emails privilégés en dur 'direction@societe.com' et 'daf@societe.com' ont le droit d'approuver une demande d'achat de 15 000€.

Cependant, il est important de noter que les règles d'enregistrement (ir.rule) pour le modèle 'custom.purchase.request' ne sont pas applicables à l'utilisateur actuel, car il n'appartient à aucun des groupes visés par ces règles.

Enfin, la fonction can_view_amount() a retourné True, ce qui signifie que l'utilisateur peut voir cet enregistrement, mais cela ne signifie pas nécessairement qu'il a le droit d'approuver la demande d'achat.

En résumé, seuls les utilisateurs avec les emails privilégés en dur 'direction@societe.com' et 'daf@societe.com' ont le droit d'approuver une demande d'achat de 15 000€.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (58.42s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez suivre les étapes suivantes :

1. Cliquez sur le bouton 'Demande de mise à disposition' sur la vue de formulaire de 'custom.asset.loan'.
2. Le système exécutera la méthode logique 'action_demande de mise à disposition()' sans transition d'état.

Il n'y a pas de conditions particulières à respecter pour cette demande, car il n'y a pas de règles de groupe applicables pour cet utilisateur. Cependant, il est important de noter que le système vérifie si le bénéficiaire d'un matériel de plus de 2000 euros est différent du demandeur initial, comme indiqué dans les messages de verrous (UserError/ValidationError).

Il est également important de noter que le modèle 'custom.asset.loan' n'hérite d'aucun autre modèle et n'a pas de workflow d'état défini explicitement.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (60.98s) :**
```text
En réponse à votre question, il semble que les avoirs fournisseurs ne passent pas par les mêmes règles d'approbation. 

D'une part, l'analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] révèle que cet action serveur automatise la validation d'avoirs reçus de trois fournisseurs spécifiques, en contournant les règles d'accès et les ACL via sudo(). 

D'autre part, l'évaluation des règles d'enregistrement (ir.rule) pour 'account.move' montre que seules les règles globales s'appliquent, sans aucune règle de groupe applicable pour l'utilisateur en question. 

Cela suggère que les avoirs fournisseurs sont traités de manière spécifique, en contournant les règles d'accès et les ACL, tandis que les autres avoirs sont soumis aux règles globales et de groupe. 

Il est donc important de prendre en compte ces différences dans la gestion des avoirs fournisseurs pour garantir une approbation appropriée et sécurisée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (11.64s) :**
```text
L'utilisateur membre à la fois du groupe régional et du groupe national peut voir un avoir de 80 000€.

La règle d'enregistrement 'Avoirs - cantonnement societe' n'affecte pas l'accès à cet enregistrement, car elle ne s'applique pas au groupe de l'utilisateur.

La règle d'enregistrement 'Avoirs - plafond visibilite regionale (50000e)' n'est pas applicable, car l'amount_total est supérieur à 50 000€.

La règle d'enregistrement 'Avoirs - visibilite nationale (illimitee)' est applicable, mais elle ne restreint pas l'accès à cet enregistrement.

La synthèse des règles d'enregistrement indique que l'utilisateur peut voir cet enregistrement.

La résolution des groupes 'group_region' et 'group_national' n'a pas pu être effectuée, mais cela ne signifie pas que l'accès est refusé.

Les modules impliqués pour le modèle 'account.move' sont :

Synthèse des observations :

- L'utilisateur peut voir l'enregistrement en raison de la règle d'enregistrement 'Avoirs - visibilite nationale (illimitee)'.
- La règle d'enregistrement 'Avoirs - plafond visibilite regionale (50000e)' n'est pas applicable.
- La résolution des groupes 'group_region' et 'group_national' n'a pas pu être effectuée.
- Les modules impliqués pour le modèle 'account.move' sont :

Note : La synthèse des observations est basée sur les résultats de l'évaluation des règles d'enregistrement et de la résolution des groupes.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (11.25s) :**
```text
L'utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut voir cet avoir de 80 000€. 

Cette conclusion est basée sur l'évaluation des règles d'enregistrement (ir.rule) pour le modèle 'account.move', qui n'ont pas trouvé d'application pour cet utilisateur. Les règles globales s'appliquant à tous les utilisateurs n'ont pas imposé de restriction supplémentaire de montant ou de portée. 

De plus, la méthode can_view_amount() a retourné True pour un montant de 80 000€, ce qui signifie que l'utilisateur peut voir cet enregistrement. Ce résultat est calculé directement par le moteur de règles et ne doit pas être recalculé ou contredit.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (57.71s) :**
```text
En fonction des informations disponibles, il semble que les règles d'enregistrement (ir.rule) pour le modèle 'custom.reimbursement.request' n'aient pas de règles globales applicables. De plus, l'utilisateur n'appartient à aucun groupe cible par une règle sur ce modèle, ce qui signifie qu'il n'y a pas de règles de groupe applicables.

Par conséquent, pour valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect, il n'y a pas de restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---