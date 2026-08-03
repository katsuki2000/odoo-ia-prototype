# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-03 16:00:10

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (85.93s) :**
```text
En fonction des analyses effectuées, il semble que le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) soit déterminé par les verrous Python présents dans le module `account_move.py` du module `custom_credit_note_approval`.

En effet, l'analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH] a révélé que "Seul un responsable comptable peut valider un avoir de plus de 5000€."

Il est donc probable que le responsable comptable soit l'entité autorisée à approuver un avoir de 25 000€ pour un client normal.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (83.38s) :**
```text
En réponse à la question "Qui a le droit d'approuver un avoir pour un client VIP ?", nous pouvons faire les observations suivantes :

- Analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH] : Seul un responsable comptable peut valider un avoir de plus de 5000€.
- Analyse des verrous Python ([account_bank_statement_line.py:L1-L807](file:///home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_bank_statement_line.py#L1-L807)) [Confiance: HIGH] : Aucun verrou spécifique ni incertitude dynamique détecté.
- Évaluation des règles d'enregistrement (ir.rule) pour 'account.move' : Aucune règle de groupe applicable (l'utilisateur n'appartient à aucun groupe cible par une règle sur ce modèle). Seules les règles globales s'appliquent.

Cependant, nous n'avons pas trouvé d'information spécifique concernant les droits d'approuver un avoir pour un client VIP. Il est possible que cela soit géré par une règle ou un verrou spécifique qui n'a pas été détecté par nos analyses.

En résumé, nous pouvons affirmer que :

- Un responsable comptable peut valider un avoir de plus de 5000€.
- Aucun verrou spécifique ni incertitude dynamique n'a été détecté pour les avoirs.
- Aucune règle de groupe n'est applicable pour les avoirs.

Cependant, les droits d'approuver un avoir pour un client VIP ne sont pas clairement définis par nos analyses.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (134.51s) :**
```text
Je comprends que vous rencontrez des difficultés pour valider votre demande de congé malgré avoir coché 'urgente'. 

Analyse des verrous Python (hr_leave.py:L1-L28) [Confiance: HIGH] :
- Vous recevez un message d'erreur indiquant que le solde de congés restant est insuffisant. Cela suggère que vous n'avez pas suffisamment de jours de congé disponibles pour valider votre demande.

Analyse des messages de verrous (UserError/ValidationError) :
- Vous recevez un message d'erreur indiquant que vous devez valider votre demande par exceptionnelle du N+2, car votre demande urgente dépasse le solde de congés restant.

Analyse des actions du serveur :
- Vous recevez un message d'erreur indiquant que votre demande urgente doit être validée par le N+2 ou un responsable RH, car elle dépasse le solde de congés restant.

En résumé, il semble que le problème réside dans le solde de congés restant insuffisant. Vous devriez vérifier votre solde de congés et prendre les mesures nécessaires pour le compléter avant de réessayer de valider votre demande de congé.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (55.26s) :**
```text
En fonction des informations disponibles, voici la réponse :

Selon l'analyse des verrous Python, seuls les utilisateurs avec les logins/emails privilégés en dur 'direction@societe.com' ou 'daf@societe.com' ont le droit d'approuver une demande d'achat de 15 000€.

Cependant, il est important de noter que les règles d'enregistrement (ir.rule) pour le modèle 'custom.purchase.request' ne sont pas applicables à l'utilisateur actuel, car il n'appartient à aucun des groupes visés par ces règles.

Enfin, la fonction can_view_amount() a retourné True, ce qui signifie que l'utilisateur a le droit de voir cet enregistrement.

En conclusion, en fonction des informations disponibles, seul l'utilisateur avec le login/email privilégé 'direction@societe.com' ou 'daf@societe.com' a le droit d'approuver une demande d'achat de 15 000€.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (50.44s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez suivre les étapes suivantes :

1. Cliquez sur le bouton 'Demande de mise à disposition' sur la vue de formulaire du modèle 'custom.asset.loan'.
2. Le bouton 'Demande de mise à disposition' appelle la méthode Python 'action_demande de mise à disposition()'.
3. La méthode 'action_demande de mise à disposition()' exécute la logique de la méthode sans transition d'état.

Il est important de noter que la demande de mise à disposition de matériel nécessite une séparation des rôles, c'est-à-dire que le bénéficiaire du matériel doit être différent du demandeur initial si le coût du matériel dépasse 2000 euros.

En ce qui concerne les conditions particulières, il est recommandé de vérifier les règles d'enregistrement (ir.rule) pour le modèle 'custom.asset.loan'. Actuellement, aucune règle globale ou de groupe n'est applicable pour ce modèle.

En outre, le modèle 'custom.asset.loan' n'hérite d'aucun autre modèle et n'a pas de transitions d'état de workflow explicites définies.

Il est également important de noter que la méthode 'action_demande de mise à disposition()' n'est pas définie dans le code Python.

Enfin, le modèle 'custom.asset.loan' existe dans l'index mais n'a pas d'actions de serveur (ir.actions.server) associées.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (77.86s) :**
```text
En réponse à votre question, il semble que les avoirs fournisseurs ne passent pas par les mêmes règles d'approbation. 

Analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH] :
- Il existe un message de verrou (UserError/ValidationError) qui indique que "Seul un responsable comptable peut valider un avoir de plus de 5000€."

Cependant, d'autres analyses ne détectent pas de verrous spécifiques ni d'incertitude dynamique. 

Analyse des verrous Python ([account_bank_statement_line.py:L1-L807](file:///home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_bank_statement_line.py#L1-L807)) [Confiance: HIGH] :
- Aucun verrou spécifique ni incertitude dynamique détecté.

Analyse des verrous Python ([account_move.py:L1-L5214](file:///home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_move.py#L1-L5214)) [Confiance: LOW] :
- (Contenu tronqué pour LLM context limit...)

Analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] :
- SUDO détecté : Contournement des droits d'accès via sudo()
- IDs en dur : [42, 108, 231] → traitement privilégié non documenté

Analyse du code de l'action serveur 'ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution] :
- SUDO détecté : Contournement des droits d'accès via sudo()
- IDs en dur : [42, 108, 231] → traitement privilégié non documenté

Évaluation des règles d'enregistrement (ir.rule) pour 'account.move' :
- Règles Globales (ET pour tous) : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]]
- Règles de Groupe applicables : Aucune (l'utilisateur n'appartient à aucun des groupes visés)
- Règles de Groupe ignorées (non-membre) : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee)
-> CONCLUSION : Aucune regle de groupe applicable (l'utilisateur n'appartient a aucun groupe cible par une regle sur ce modele). Seules les regles globales ci-dessus s'appliquent -- il n'y a AUCUNE restriction supplementaire de montant ou de portee provenant d'une regle de groupe pour cet utilisateur.

En conclusion, il existe des règles d'approbation spécifiques pour les avoirs fournisseurs, mais elles ne sont pas les mêmes pour tous les avoirs fournisseurs.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (45.22s) :**
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

**Réponse Verbatim de l'agent (59.62s) :**
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

**Réponse Verbatim de l'agent (0.11s) :**
```text
Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. Ne pas présenter cette validation comme autorisée ou refusée de manière certaine. Source à revoir : [reimbursement.py:L1-L39](file:///home/user/odoo-17.0/addons/custom_expense_reimbursement_indirect/models/reimbursement.py#L1-L39).

[Source: Graphe de Connaissances Code Intelligence]
```

---