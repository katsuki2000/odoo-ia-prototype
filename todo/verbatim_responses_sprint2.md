# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-03 13:35:58

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (86.09s) :**
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

**Réponse Verbatim de l'agent (112.41s) :**
```text
En fonction des règles d'enregistrement (ir.rule) pour 'account.move', nous constatons que :

- Les règles globales s'appliquent, notamment la règle 'Avoirs - cantonnement societe' qui autorise l'enregistrement d'un avoir pour un client VIP si l'utilisateur appartient à la même société que le client.
- Il n'y a aucune règle de groupe applicable pour cet utilisateur, car il n'appartient à aucun groupe cible par une règle sur ce modèle.
- Le groupe 'client_vip_manager' n'a pas pu être résolu contre aucun groupe avec des règles d'écriture ou des ACLs sur 'account.move'. Cela ne signifie pas que l'accès est refusé, mais plutôt que l'identifiant du groupe n'a pas pu être trouvé.

En conclusion, en fonction des règles d'enregistrement, l'utilisateur a le droit d'approuver un avoir pour un client VIP si l'utilisateur appartient à la même société que le client.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (11.91s) :**
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

**Réponse Verbatim de l'agent (11.29s) :**
```text
En fonction des informations disponibles, voici la réponse :

Selon l'analyse des verrous Python, seuls les utilisateurs avec les logins/emails privilégés en dur 'direction@societe.com' ou 'daf@societe.com' ont le droit d'approuver une demande d'achat de 15 000€.

Cela signifie que les utilisateurs avec ces logins/emails peuvent valider la demande d'achat, tandis que les autres utilisateurs ne peuvent pas.

Il n'y a pas d'autres restrictions ou règles qui s'appliquent à cette demande d'achat en fonction des règles d'enregistrement (ir.rule) ou des modules impliqués.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (55.09s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez suivre les étapes suivantes :

1. Cliquez sur le bouton 'demande_mise_disposition' sur la vue de formulaire de 'custom.asset.loan'.
2. Le bouton 'demande_mise_disposition' appelle la méthode Python 'action_demande_mise_disposition()'.
3. La méthode 'action_demande_mise_disposition()' exécute la logique de la demande sans transition d'état.

Il n'y a pas de conditions particulières pour faire une demande de mise à disposition de matériel, mais il est important de noter que :

- La séparation des rôles est requise : le bénéficiaire d'un matériel de plus de 2000 euros doit être différent du demandeur initial. (Analyse des verrous Python [asset_loan.py](file:///home/user/odoo-17.0/addons/custom_asset_loan/models/asset_loan.py) [Confiance: HIGH])
- Il n'y a pas de règles de groupe applicables pour cet utilisateur. (Évaluation des règles d'enregistrement (ir.rule) pour 'custom.asset.loan')
- Il n'y a pas de restrictions supplémentaires de montant ou de portée provenant d'une règle de groupe pour cet utilisateur. (Évaluation des règles d'enregistrement (ir.rule) pour 'custom.asset.loan')
- Il n'y a pas de workflow d'état défini pour le modèle 'custom.asset.loan'. (Model 'custom.asset.loan' exists in the index but does not inherit from any other models.)
- Le champ 'state' n'existe pas dans le modèle 'custom.asset.loan'. (Field 'state' on model 'custom.asset.loan' was not found in the indexed knowledge graph.)

⚠️ SOURCING NON VÉRIFIÉ (J14): lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): home/user/odoo-17.0/addons/custom_asset_loan/models/asset_loan.py. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (42.56s) :**
```text
En réponse à votre question, les avoirs fournisseurs ne passent pas tous par les mêmes règles d'approbation. 

Analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] :
- SUDO détecté : Contournement des droits d'accès via sudo()
- IDs en dur : [42, 108, 231] → traitement privilégié non documenté

Cet action serveur automatise la validation d'avoirs reçus de trois fournisseurs spécifiques, en contournant les règles d'accès et les ACL via sudo(), ce qui suggère que ces avoirs sont traités différemment des autres.

Évaluation des règles d'enregistrement (ir.rule) pour 'account.move' :
- Règles Globales (ET pour tous) : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]]
- Règles de Groupe applicables : Aucune (l'utilisateur n'appartient à aucun des groupes visés)
- Règles de Groupe ignorées (non-membre) : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee)

La conclusion est que seule la règle globale s'applique, sans aucune restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur.

Modules implicated for model 'account.move' :

Ainsi, il est clair que les avoirs fournisseurs ne passent pas tous par les mêmes règles d'approbation, car certains sont traités différemment en raison de l'utilisation de sudo() et d'autres règles spécifiques.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (89.79s) :**
```text
L'utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

Évaluation des règles d'enregistrement (ir.rule) pour 'account.move' :
- Règles Globales (ET pour tous) : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]]
- Règles de Groupe applicables (combinées en OU) : Avoirs - plafond visibilite regionale (50000e) [['|', ('move_type', '!=', 'out_refund'), ('amount_total', '<=', 50000)]], Avoirs - visibilite nationale (illimitee) [[(1, '=', 1)]]
- Règles de Groupe ignorées (non-membre) : Avoirs - visibilite par departement (sauf managers)
-> CONCLUSION : Au moins une regle de groupe applicable restreint potentiellement l'acces -- se referer aux domain_force ci-dessus pour les conditions exactes (combinees en OU entre elles, puis en ET avec les regles globales).

Puisque l'utilisateur est membre du groupe régional, la règle Avoirs - plafond visibilite regionale (50000e) s'applique. Cette règle impose un plafond de 50 000€ pour la visibilité des avoirs. Puisque l'import de l'avoir est de 80 000€, ce plafond est dépassé.

Par conséquent, l'utilisateur ne peut pas voir l'avoir de 80 000€ en raison de la règle Avoirs - plafond visibilite regionale (50000e).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (11.13s) :**
```text
En réponse à votre question, l'utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut voir l'avoir de 80 000€. 

Cette conclusion est basée sur l'évaluation des règles d'enregistrement (ir.rule) pour le modèle 'account.move', qui n'a pas trouvé d'application de règles de groupe pour cet utilisateur. Les seules règles globales s'appliquant à cet utilisateur ne comportent aucune restriction supplémentaire de montant ou de portée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (11.1s) :**
```text
En fonction des informations disponibles, il semble que les règles d'enregistrement (ir.rule) pour le modèle 'custom.reimbursement.request' n'aient pas de règles globales applicables. De plus, l'utilisateur n'appartient à aucun groupe cible par une règle sur ce modèle, ce qui signifie qu'il n'y a pas de règles de groupe applicables.

Par conséquent, pour valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect, il n'y a pas de restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour cet utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---