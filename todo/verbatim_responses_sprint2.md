# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-07-31 14:48:51

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (61.78s) :**
```text
En analysant les verrous Python, nous constatons que seul un responsable comptable peut valider un avoir de plus de 5000€. Cependant, cette règle n'est pas applicable dans le cas d'un client normal (pas VIP).

En évaluant les règles d'enregistrement (ir.rule) pour le modèle 'account.move', nous constatons que les règles globales s'appliquent, mais aucune règle de groupe n'est applicable pour cet utilisateur. Les règles globales ne comportent aucune restriction supplémentaire de montant ou de portée.

Enfin, en analysant les modules impliqués pour le modèle 'account.move', nous constatons que les droits d'enregistrement sont accordés aux groupes account.group_account_invoice, account.group_account_manager et account.group_account_user.

En conclusion, en l'absence de règles de groupe applicables et de restrictions supplémentaires de montant ou de portée, il semble que n'importe quel utilisateur ayant les droits d'enregistrement pour le modèle 'account.move' puisse approuver un avoir de 25 000€ pour un client normal (pas VIP), à condition qu'il ne dépasse pas le plafond de 5000€.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (11.25s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour le modèle 'account.move', nous pouvons conclure que :

- Seules les règles globales s'appliquent, sans restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur. [Confiance: ÉLEVÉE]

- Aucune règle de groupe n'est applicable pour cet utilisateur, car il n'appartient à aucun des groupes visés par une règle sur ce modèle. [Confiance: ÉLEVÉE]

- Les règles globales suivantes s'appliquent : Avoirs - cantonnement societe (sans groupe). [Confiance: ÉLEVÉE]

Cependant, il est important de noter que les règles de groupe suivantes sont ignorées car l'utilisateur n'appartient pas aux groupes ciblés : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee). [Confiance: ÉLEVÉE]

En conclusion, pour approuver un avoir pour un client VIP, il est nécessaire de vérifier les règles globales applicables, qui ne comportent aucune restriction supplémentaire de montant ou de portée. [Confiance: ÉLEVÉE]

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (85.17s) :**
```text
Je suis désolé d'entendre que vous rencontrez des difficultés pour valider votre demande de congé. Voici quelques observations qui pourraient expliquer ce problème :

Analyse des verrous Python ([hr_leave.py](file:///home/user/odoo-17.0/addons/custom_hr_leave_workflow/models/hr_leave.py)) [Confiance: HIGH] :
- Vous recevez un message d'erreur indiquant que le solde de congés restant est insuffisant. Cela signifie que vous n'avez pas suffisamment de jours de congé pour valider votre demande. Cochez 'Demande urgente' pour soumettre une demande exceptionnelle de validation du N+2.

Évaluation des règles d'enregistrement (ir.rule) pour 'hr.leave' :
- Aucune règle globale n'est applicable.
- Aucune règle de groupe n'est applicable pour l'utilisateur, car il n'appartient à aucun groupe cible par une règle sur ce modèle. [Confiance: MÉDI]

Analyse des actions serveur (ir.actions.server) pour le modèle 'hr.leave' :
- Aucune action serveur n'est trouvée pour le modèle 'hr.leave'.

En résumé, le problème semble résider dans le solde de congés restant insuffisant. Cochez 'Demande urgente' pour soumettre une demande exceptionnelle de validation du N+2. Si vous continuez à rencontrer des difficultés, veuillez contacter votre responsable RH ou le N+2 pour obtenir plus d'informations.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (56.62s) :**
```text
En analysant les données disponibles, voici les conclusions qui peuvent être tirées :

- Selon l'analyse des verrous Python dans le fichier [purchase_request.py](file:///home/user/odoo-17.0/addons/custom_purchase_request/models/purchase_request.py) avec une confiance élevée [Confiance: HIGH], les utilisateurs autorisés à approuver une demande d'achat de 15 000€ sont ceux dont les logins/emails sont en dur : 'direction@societe.com', 'daf@societe.com'. De plus, il y a des messages de verrous qui indiquent que pour les demandes d'achat supérieures à 10 000€, seule la Direction peut valider (liste restreinte) et que l'utilisateur n'a pas le droit de valider cette demande d'achat.

- L'évaluation des règles d'enregistrement (ir.rule) pour le modèle 'custom.purchase.request' n'a pas révélé de règles globales ou de règles de groupe applicables. Ainsi, il n'y a aucune restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur [Aucune restriction supplementaire de montant ou de portée provenant d'une regle de groupe pour cet utilisateur].

- Les modules impliqués pour le modèle 'custom.purchase.request' n'ont pas été trouvés dans la base de connaissances indexée.

- Le modèle 'purchase.order' n'a pas été trouvé dans la base de connaissances indexée.

En conclusion, selon les données disponibles, les utilisateurs autorisés à approuver une demande d'achat de 15 000€ sont ceux dont les logins/emails sont en dur : 'direction@societe.com', 'daf@societe.com', et uniquement la Direction peut valider les demandes d'achat supérieures à 10 000€.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (11.68s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez cliquer sur le bouton 'demande_mise_disposition' sur la vue de formulaire du modèle 'custom.asset.loan'. Cette action appelle la méthode Python 'action_demande_mise_disposition()'.

Il est important de noter que la demande de mise à disposition de matériel est soumise à certaines conditions. Selon l'analyse des verrous Python, il est requis une séparation des rôles pour les matériaux d'un montant supérieur à 2000 euros. Le bénéficiaire doit être différent du demandeur initial.

Il n'y a pas de règles de groupe applicables pour le modèle 'custom.asset.loan' pour l'utilisateur actuel, mais il n'y a pas non plus de restriction supplémentaire de montant ou de portée provenant d'une règle de groupe.

Il n'y a pas d'action de serveur définie pour le modèle 'custom.asset.loan'.

La méthode 'action_demande_mise_disposition()' n'est pas définie explicitement, mais elle est appelée lors du clic sur le bouton 'demande_mise_disposition'.

Il n'y a pas de transition d'état définie pour le modèle 'custom.asset.loan'.

En résumé, pour faire une demande de mise à disposition de matériel, vous devez cliquer sur le bouton 'demande_mise_disposition' et respecter les conditions de séparation des rôles pour les matériaux d'un montant supérieur à 2000 euros.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (112.52s) :**
```text
En analysant les données fournies, il est clair que les avoirs fournisseurs ne passent pas par les mêmes règles d'approbation.

D'une part, l'analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] révèle que cet action serveur automatise la validation d'avoirs reçus de trois fournisseurs spécifiques, en contournant les règles d'accès et les ACL via sudo() [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution]. Cela suggère que ces avoirs sont traités de manière privilégiée et ne sont pas soumis aux règles d'approbation habituelles.

D'autre part, l'évaluation des règles d'enregistrement (ir.rule) pour 'account.move' révèle que seules les règles globales s'appliquent, sans aucune règle de groupe applicable [Confiance: ÉVALUATION DES RÈGLES D'ENREGISTREMENT]. Cela signifie que les avoirs reçus de fournisseurs ne sont pas soumis à des restrictions supplémentaires de montant ou de portée provenant d'une règle de groupe.

En conclusion, les avoirs fournisseurs passent par des règles d'approbation différentes, avec certains ayant un traitement privilégié qui les exempte des règles d'accès et des ACL habituelles, tandis que d'autres sont soumis aux règles globales sans aucune règle de groupe applicable.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (18.14s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour 'account.move', un utilisateur membre à la fois du groupe régional et du groupe national peut voir un avoir de 80 000€.

Cependant, il convient de noter que les règles de groupe applicables peuvent restreindre potentiellement l'accès. Les règles de groupe applicables sont les suivantes :

- Avoirs - plafond visibilité régionale (50 000€) : Cette règle limite la visibilité des avoirs à 50 000€. [Confiance: MÉDI]
- Avoirs - visibilité nationale (illimitée) : Cette règle permet la visibilité des avoirs sans limite. [Confiance: ÉLEVÉ]

Puisque l'utilisateur est membre du groupe national, la règle Avoirs - visibilité nationale (illimitée) s'applique, ce qui signifie qu'il peut voir un avoir de 80 000€.

Il est donc possible que l'utilisateur puisse voir un avoir de 80 000€, mais cela dépend de la combinaison des règles de groupe applicables et des règles globales.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (10.95s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour 'account.move', l'utilisateur qui n'appartient à aucun des deux groupes (ni régional, ni national) peut voir l'avoir de 80 000€, car seules les règles globales s'appliquent et il n'y a aucune restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur [Confiance: ÉLEVÉE].

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (11.07s) :**
```text
En fonction des informations disponibles, il semble que les règles d'enregistrement (ir.rule) pour le modèle 'custom.reimbursement.request' n'aient pas de règles globales applicables. De plus, l'utilisateur n'appartient à aucun groupe cible par une règle sur ce modèle, ce qui signifie qu'il n'y a pas de règles de groupe applicables pour limiter la demande de remboursement de frais.

Ainsi, en l'absence de toute restriction supplémentaire de montant ou de portée provenant d'une règle de groupe, il est possible que n'importe qui puisse valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect.

[Source: Graphe de Connaissances Code Intelligence]
```

---