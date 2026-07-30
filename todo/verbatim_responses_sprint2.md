# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-07-30 13:36:12

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (106.46s) :**
```text
Selon les informations disponibles, les utilisateurs ayant le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) sont :

- Les utilisateurs appartenant au groupe `account.group_account_invoice`
- Les utilisateurs appartenant au groupe `account.group_account_manager`
- Les utilisateurs appartenant au groupe `account.group_account_user`

Il convient de noter que les utilisateurs appartenant au groupe `res.partner` n'ont pas l'accès en écriture pour le modèle `account.move`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (11.16s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour 'account.move', seul l'utilisateur qui appartient à la société (company_id) a le droit d'approuver un avoir pour un client VIP.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (63.01s) :**
```text
Bonjour,

Je suis désolé d'apprendre que vous rencontrez des difficultés pour valider votre demande de congé malgré avoir coché l'option 'urgente'. 

Après avoir analysé les règles de validation de votre demande, j'ai identifié deux raisons possibles pour ce problème :

1. **Solde de congés insuffisant** : Votre solde de congés restant est inférieur à la durée de votre demande. Dans ce cas, vous pouvez essayer de cocher l'option 'Demande urgente' et soumettre votre demande à validation exceptionnelle du N+2.
2. **Validation par le N+2 ou un responsable RH** : Si votre demande urgente dépasse votre solde de congés, elle doit être validée par le N+2 ou un responsable RH. Veuillez contacter votre supérieur hiérarchique ou un responsable RH pour obtenir leur validation.

J'espère que ces informations vous aideront à résoudre votre problème. N'hésitez pas à me contacter si vous avez d'autres questions.

Cordialement,
[Votre nom]

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (11.11s) :**
```text
Selon les informations disponibles, les personnes autorisées à approuver une demande d'achat de 15 000€ sont :

- Les utilisateurs appartenant au groupe `base.group_user`
- Les administrateurs de Miro AI appartenant au groupe `miro_ai.group_miro_ai_admin`
- Les utilisateurs de Miro AI appartenant au groupe `miro_ai.group_miro_ai_user`
- Les administrateurs de Miro AI appartenant au groupe `group_miro_ai_admin`
- Les utilisateurs de Miro AI appartenant au groupe `group_miro_ai_user`

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (11.4s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez cliquer sur le bouton 'demande_mise_disposition' sur la vue de formulaire du modèle 'custom.asset.loan'. Cette action appelle la méthode Python 'action_demande_mise_disposition()'.

Il est important de noter que pour demander un matériel d'une valeur supérieure à 2000 euros, il est nécessaire que le bénéficiaire soit différent du demandeur initial. Cette condition est vérifiée par la règle de sécurité 'Separation des roles requise'.

Il n'y a pas de conditions particulières à respecter pour faire une demande de mise à disposition de matériel, mais il est recommandé de vérifier les règles de sécurité et les conditions de demande avant de soumettre votre demande.

En outre, il est à noter que le modèle 'custom.asset.loan' n'a pas de workflow d'état défini, ce qui signifie que la demande de mise à disposition de matériel ne sera pas soumise à un processus de validation ou d'approbation automatique.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (11.17s) :**
```text
Les avoirs fournisseurs ne passent pas nécessairement par les mêmes règles d'approbation. En effet, les règles d'enregistrement (ir.rule) pour le modèle 'account.move' indiquent que les règles globales sont appliquées pour les avoirs, mais il n'y a pas de règles de groupe applicables pour les avoirs fournisseurs.

Cependant, il est important de noter que les règles de groupe ignorées (non-membre) sont appliquées pour les avoirs fournisseurs, ce qui signifie que certaines règles ne sont pas appliquées à l'utilisateur en raison de son appartenance ou non à certains groupes.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (59.19s) :**
```text
L'utilisateur membre à la fois du groupe régional et du groupe national ne peut pas voir un avoir de 80 000€. 

En effet, les règles de groupe applicables ne sont pas trouvées car l'utilisateur n'appartient à aucun des groupes visés. Les règles de groupe ignorées ne sont pas non plus applicables car l'utilisateur n'est pas membre des groupes 'group_regional' et 'group_national' qui n'ont pas d'accès de lecture sur le modèle 'account.move'. 

Par conséquent, l'utilisateur ne peut pas voir l'élément 'account.move' en question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (11.09s) :**
```text
L'utilisateur en question ne peut pas voir l'avoir de 80 000€ car il n'appartient à aucun des groupes régional ou national. Les règles de visibilité définies pour les avois ne sont pas applicables à cet utilisateur, car il n'est membre d'aucun groupe ciblé.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (10.79s) :**
```text
Tout utilisateur authentifié peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect.

[Source: Graphe de Connaissances Code Intelligence]
```

---