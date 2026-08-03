# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-03 14:45:32

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (41.34s) :**
```text
En fonction des analyses effectuées, voici la réponse claire et professionnelle :

Selon l'analyse des verrous Python dans le fichier [account_move.py](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py) avec une confiance élevée, il est indiqué que "Seul un responsable comptable peut valider un avoir de plus de 5000€." Cela suggère que pour un avoir de 25 000€, seul un responsable comptable a le droit d'approuver.

Cependant, il est important de noter que cette analyse est spécifique à l'addon `custom_credit_note_approval` et que d'autres addons ou règles peuvent avoir des exigences différentes.

En outre, l'évaluation des règles d'enregistrement (ir.rule) pour le modèle `account.move` n'a pas trouvé de règles de groupe applicables pour cet utilisateur, ce qui signifie que les règles globales s'appliquent uniquement. Les règles globales ne mentionnent pas de restriction supplémentaire de montant ou de portée pour cet utilisateur.

Enfin, la synthèse des résultats a conclu que pour un montant de 25 000€, l'utilisateur PEUT voir cet enregistrement, ce qui suggère que l'utilisateur a le droit d'approuver l'avoir.

En résumé, bien que l'analyse des verrous Python suggère que seul un responsable comptable a le droit d'approuver un avoir de plus de 5 000€, les autres analyses ne mentionnent pas de restriction supplémentaire de montant ou de portée pour cet utilisateur. Il est donc possible que l'utilisateur ait le droit d'approuver l'avoir de 25 000€.

⚠️ SOURCING NON VÉRIFIÉ (J14): lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (37.72s) :**
```text
En réponse à la question "Qui a le droit d'approuver un avoir pour un client VIP ?", nous pouvons faire les observations suivantes :

- L'analyse des verrous Python dans le fichier `account_move.py` (file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py) [Confiance: HIGH] indique que "Seul un responsable comptable peut valider un avoir de plus de 5000€."
- L'analyse des verrous Python dans le fichier `account_move.py` (file:///home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_move.py) [Confiance: LOW] indique qu'une incertitude dynamique est présente et que une revue manuelle est recommandée.
- L'évaluation des règles d'enregistrement (ir.rule) pour 'account.move' indique que les règles globales suivantes s'appliquent : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]].
- L'évaluation des règles d'enregistrement (ir.rule) pour 'account.move' indique également que les règles de groupe suivantes sont ignorées car l'utilisateur n'appartient pas aux groupes visés : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee).
- La recherche de groupes identifiants 'res.partner.category,client_vip' n'a pas abouti à une correspondance avec un groupe ayant des règles d'écriture ou des ACLs sur 'account.move'.

En conclusion, il n'y a pas de règle spécifique qui indique qui a le droit d'approuver un avoir pour un client VIP. Cependant, l'analyse des verrous Python dans le fichier `account_move.py` (file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py) [Confiance: HIGH] suggère que seul un responsable comptable peut valider un avoir de plus de 5000€.

⚠️ SOURCING NON VÉRIFIÉ (J14): lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py, home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_move.py, home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (78.2s) :**
```text
Réponse claire et professionnelle :

Il semble que vous rencontriez des difficultés pour valider votre demande de congé malgré avoir coché 'urgente'. 

Analyse des verrous Python (hr_leave.py#L12-L25) [Confiance: HIGH] :
- Vous recevez un message d'erreur indiquant que le solde de congés restant est insuffisant. Cela suggère que vous n'avez pas suffisamment de jours de congé disponibles pour valider votre demande.

Évaluation des règles d'enregistrement (ir.rule) pour 'hr.leave' :
- Aucune règle globale n'est applicable.
- Aucune règle de groupe n'est applicable pour l'utilisateur en question.

Model 'hr.leave' [CREATE] :
- Aucun groupe n'est explicitement autorisé.
- Aucune règle active n'est présente.

Modules impliqués pour le modèle 'hr.leave' :

En conséquence, il est probable que le problème soit lié à votre solde de congés insuffisant. Vous devriez vérifier votre solde de congés et potentiellement soumettre une demande de congé exceptionnelle si nécessaire.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (57.58s) :**
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

**Réponse Verbatim de l'agent (12.46s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez suivre les étapes suivantes :

1. Cliquez sur le bouton 'Demande de mise à disposition' sur la vue de formulaire du modèle 'custom.asset.loan'.
2. Le bouton 'Demande de mise à disposition' appelle la méthode Python 'action_demande de mise à disposition()'.
3. La méthode 'action_demande de mise à disposition()' exécute la logique de la méthode sans transition d'état.

Il n'y a pas de restriction de groupe spécifiée pour le bouton 'Demande de mise à disposition'.

Il est important de noter que le modèle 'custom.asset.loan' n'hérite d'aucun autre modèle et n'a pas de transitions d'état de workflow définies explicitement.

En ce qui concerne les conditions particulières, il est mentionné que la séparation des rôles est requise : le bénéficiaire d'un matériel de plus de 2000 euros doit être différent du demandeur initial. Cela est indiqué dans les messages de verrous (UserError/ValidationError) analysés.

Enfin, il est important de noter que le modèle 'custom.asset.loan' existe dans l'index mais n'a pas d'actions de serveur (ir.actions.server) associées.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (117.71s) :**
```text
En réponse à votre question, il semble que les avoirs fournisseurs ne passent pas par les mêmes règles d'approbation. 

Analyse des verrous Python ([account_move.py](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py)) [Confiance: HIGH] :
- Il existe un message de verrou (UserError/ValidationError) qui indique que "Seul un responsable comptable peut valider un avoir de plus de 5000€."

Analyse des verrous Python ([account_bank_statement_line.py](file:///home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_bank_statement_line.py)) [Confiance: HIGH] :
- Aucun verrou spécifique ni incertitude dynamique détecté.

Analyse des verrous Python ([account_move.py](file:///home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_move.py)) [Confiance: LOW] :
- Incertitude dynamique (getattr) : revue manuelle recommandée.

Analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] :
- SUDO détecté : Contournement des droits d'accès via sudo().
- IDs en dur : [42, 108, 231] → traitement privilégié non documenté.

Analyse du code de l'action serveur 'ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] :
- SUDO détecté : Contournement des droits d'accès via sudo().
- IDs en dur : [42, 108, 231] → traitement privilégié non documenté.

Évaluation des règles d'enregistrement (ir.rule) pour 'account.move' :
- Règles Globales (ET pour tous) : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]].
- Règles de Groupe applicables : Aucune (l'utilisateur n'appartient à aucun des groupes visés).
- Règles de Groupe ignorées (non-membre) : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee).
- CONCLUSION : Aucune regle de groupe applicable (l'utilisateur n'appartient a aucun groupe cible par une regle sur ce modele). Seules les regles globales ci-dessus s'appliquent -- il n'y a AUCUNE restriction supplementaire de montant ou de portee provenant d'une regle de groupe pour cet utilisateur.

En conclusion, il existe des règles d'approbation spécifiques pour les avoirs fournisseurs, notamment la règle qui indique que seul un responsable comptable peut valider un avoir de plus de 5000€. Cependant, il existe également des cas où les droits d'accès sont contournés via sudo() et des règles de groupe qui ne sont pas applicables à l'utilisateur.

⚠️ SOURCING NON VÉRIFIÉ (J14): lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py, home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_bank_statement_line.py, home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_move.py. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (12.11s) :**
```text
L'utilisateur membre à la fois du groupe régional et du groupe national peut voir un avoir de 80 000€.

La règle d'enregistrement 'Avoirs - cantonnement societe' n'affecte pas l'accès à cet enregistrement, car elle ne s'applique pas au groupe de l'utilisateur.

La règle d'enregistrement 'Avoirs - plafond visibilite regionale (50000e)' n'est pas applicable, car l'amount_total de l'enregistrement est supérieur à 50 000€.

La règle d'enregistrement 'Avoirs - visibilite nationale (illimitee)' est applicable, mais elle ne restreint pas l'accès à cet enregistrement.

Le moteur de règles a évalué les règles d'enregistrement et a conclu que l'utilisateur peut voir cet enregistrement.

La résolution des groupes 'group_region' et 'group_national' n'a pas pu être effectuée, mais cela ne signifie pas que l'accès est refusé.

Les modules impliqués pour le modèle 'account.move' sont :

Synthèse : L'utilisateur peut voir l'enregistrement de l'avoir de 80 000€ en raison de la règle d'enregistrement 'Avoirs - visibilite nationale (illimitee)' et de l'évaluation des règles d'enregistrement par le moteur de règles.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (58.78s) :**
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

**Réponse Verbatim de l'agent (12.04s) :**
```text
En réponse à votre question, nous pouvons valider une demande de remboursement de frais dans le module `custom_expense_reimbursement_indirect` sans aucune restriction supplémentaire de montant ou de portée provenant d'une règle de groupe pour l'utilisateur.

En effet, l'évaluation des règles d'enregistrement (ir.rule) pour le modèle `custom.reimbursement.request` n'a révélé aucune règle de groupe applicable, et seules les règles globales s'appliquent. De plus, le module `custom.reimbursement.request` est autorisé à tous les utilisateurs authentifiés.

Cependant, il est recommandé de réviser manuellement l'utilisation de `getattr` dans le code Python du module `custom_expense_reimbursement_indirect` (reimbursement.py#L12-L25) en raison de l'incertitude dynamique associée à cette fonction.

En résumé, aucune restriction supplémentaire n'est appliquée pour valider une demande de remboursement de frais dans le module `custom_expense_reimbursement_indirect`.

[Source: Graphe de Connaissances Code Intelligence]
```

---