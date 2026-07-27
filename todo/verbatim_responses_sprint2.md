# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-07-27 16:55:53

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (8.85s) :**
```text
En fonction des informations fournies, il semble que les utilisateurs appartenant aux groupes suivants ont le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) :

- account.group_account_manager
- account.group_account_user

Il n'y a pas d'autres règles d'enregistrement (ir.rule) spécifiques qui s'appliquent à ce cas.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (11.16s) :**
```text
En fonction des informations disponibles, il semble que les utilisateurs appartenant aux groupes suivants aient le droit d'approuver un avoir pour un client VIP :

- Le groupe `account.group_account_manager`
- Le groupe `account.group_account_user`

Il n'y a aucune règle spécifique ou module personnalisé qui s'applique à ce scénario, ce qui signifie que les utilisateurs appartenant à ces groupes ont la capacité d'approuver les avoirs pour les clients VIP sans aucune restriction supplémentaire.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (11.17s) :**
```text
Je suis désolé, mais il semble que nous ayons rencontré un problème technique. Le modèle 'hr.leave' n'a pas été trouvé dans notre base de connaissances. Cela pourrait être dû à un erreur de typographie ou à la non-existence de ce modèle.

Je vous recommande de vérifier les détails de votre demande de congé et de s'assurer que tous les champs obligatoires sont remplis correctement. Si le problème persiste, vous pouvez essayer de contacter l'équipe de support technique pour obtenir de l'aide supplémentaire.

Je m'excuse pour la gêne occasionnée et je vous remercie de votre compréhension.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (11.37s) :**
```text
Je suis désolé, mais je n'ai pas trouvé de modèle ou de module dans la base de connaissances qui correspond à la question posée. Cependant, je peux vous fournir une réponse générale basée sur les normes professionnelles.

Dans la plupart des entreprises, la décision d'approuver une demande d'achat de 15 000€ relève généralement de la responsabilité d'un responsable financier ou d'un responsable de l'approvisionnement. Ce responsable est chargé de vérifier que la demande est justifiée, que les fonds sont disponibles et que les règles de l'entreprise sont respectées.

Il est possible que la décision d'approuver une demande d'achat de cette envergure nécessite également l'approbation d'un supérieur hiérarchique ou d'un comité d'approbation. Il est donc important de vérifier les procédures internes de l'entreprise pour déterminer qui a le droit d'approuver une demande d'achat de 15 000€.

Je vous recommande de contacter votre responsable financier ou votre responsable de l'approvisionnement pour obtenir plus d'informations sur les procédures à suivre et les personnes responsables de l'approbation des demandes d'achat.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (11.98s) :**
```text
Je suis désolé, mais il semble que le modèle de connaissance requis n'existe pas dans la base de données. Cependant, je peux vous fournir une réponse générale sur la façon de faire une demande de mise à disposition de matériel et les conditions particulières qui peuvent s'appliquer.

**Comment faire une demande de mise à disposition de matériel ?**

Pour faire une demande de mise à disposition de matériel, vous devez généralement suivre les étapes suivantes :

1. Vérifiez si le matériel que vous souhaitez utiliser est disponible et si vous avez les autorisations nécessaires pour l'utiliser.
2. Préparez une demande écrite ou en ligne, en indiquant les détails suivants :
 * Le type de matériel que vous souhaitez utiliser
 * La durée de la mise à disposition
 * Les objectifs de votre projet ou de votre activité
 * Les ressources humaines et financières nécessaires pour l'utilisation du matériel
3. Envoyez votre demande à l'unité ou au service responsable de la gestion des ressources matérielles.
4. Attendez la réponse de l'unité ou du service responsable, qui vous informera de la décision concernant votre demande.

**Conditions particulières**

Il existe plusieurs conditions particulières qui peuvent s'appliquer à la mise à disposition de matériel, notamment :

* La disponibilité du matériel : le matériel doit être disponible et non réservé par d'autres utilisateurs.
* Les autorisations nécessaires : vous devez avoir les autorisations nécessaires pour utiliser le matériel, notamment les autorisations de sécurité et les autorisations de gestion des ressources.
* Les ressources humaines et financières : vous devez avoir les ressources humaines et financières nécessaires pour utiliser le matériel, notamment les ressources pour la formation et la maintenance.
* Les règles de sécurité : vous devez respecter les règles de sécurité pour l'utilisation du matériel, notamment les règles de sécurité pour les équipements électriques et les substances dangereuses.
* Les conditions d'utilisation : vous devez respecter les conditions d'utilisation du matériel, notamment les conditions de maintenance et de réparation.

Il est important de noter que les conditions particulières peuvent varier en fonction de l'organisation, du type de matériel et des objectifs de votre projet ou de votre activité. Il est donc important de vérifier les règles et les procédures de votre organisation avant de faire une demande de mise à disposition de matériel.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (68.09s) :**
```text
En analysant les règles d'approbation pour les avoirs fournisseurs, il semble que les règles globales et les règles de groupe ne soient pas applicables à l'objet 'account.move'. 

En effet, les règles de groupe ne sont pas applicables car l'utilisateur n'appartient à aucun des groupes visés. De plus, il n'y a aucune règle active associée au modèle 'account.move'.

Il est donc possible de conclure que les avoirs fournisseurs passent par les mêmes règles d'approbation, qui sont en l'occurrence, aucune règle spécifique.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (11.17s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour 'account.move', il semble que l'utilisateur membre à la fois du groupe régional et du groupe national ne dispose pas d'accès de lecture pour 'account.move'.

Les règles de groupe 'custom_credit_note_visibility_rules.group_regional' et 'custom_credit_note_visibility_rules.group_national' ne disposent pas d'accès de lecture pour 'account.move', ce qui signifie que l'utilisateur ne peut pas voir un avoir de 80 000€.

Il est donc probable que l'utilisateur ne puisse pas accéder à l'information requise en raison de la configuration des règles de groupe et des accès associés.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (13.3s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour le modèle 'account.move', il semble que l'utilisateur en question ne peut pas voir l'enregistrement d'un avoir de 80 000€.

En effet, les règles de groupe applicables ne sont pas activées pour cet utilisateur, car il n'appartient à aucun des groupes visés (ni régional, ni national). Les règles globales ne sont également pas applicables.

Par conséquent, l'utilisateur n'a pas l'autorisation nécessaire pour voir l'enregistrement d'un avoir de 80 000€.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (11.1s) :**
```text
Désolé, mais je n'ai pas trouvé de modèle appelé 'custom_expense_reimbursement_indirect' dans ma base de connaissances. Il est possible qu'il s'agit d'un modèle non existant ou d'un nom de modèle incorrect.

Si vous avez des informations supplémentaires sur ce modèle ou si vous pouvez me fournir plus de contexte, je serais ravi de vous aider à trouver la réponse à votre question.

[Source: Graphe de Connaissances Code Intelligence]
```

---