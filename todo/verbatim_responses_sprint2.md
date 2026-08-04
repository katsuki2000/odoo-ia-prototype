# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-04 15:44:12

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (93.84s) :**
```text
En fonction des informations disponibles, il semble que l'analyse de sécurité via `analyser_verrous_securite` n'a pas pu divulguer le contenu nécessaire au demandeur actuel, faute de droits de gestion suffisants sur le modèle `account.move`.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - analyser_verrous_securite(account.move) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'account.move'.
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (136.67s) :**
```text
En fonction des informations disponibles, il semble que l'analyse de sécurité via `analyser_verrous_securite` n'a pas pu divulguer le contenu nécessaire pour répondre à la question. Cependant, il est mentionné que l'analyse a été exécutée sur l'élément `account.move`. 

Il est donc impossible de fournir une réponse claire et professionnelle basée sur les données disponibles.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - analyser_verrous_securite(account.move) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'account.move'.
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (125.1s) :**
```text
Je suis désolé d'entendre que vous rencontrez des difficultés pour valider votre demande de congé. Selon les informations disponibles, il semble que le système ait détecté un problème de sécurité lié à l'analyse de votre demande de congé via la fonction `analyser_verrous_securite`. Cette fonction a été exécutée, mais le contenu de l'analyse n'a pas été divulgué à votre demande actuelle en raison de droits de gestion insuffisants sur le modèle `hr.leave`.

Je vous recommande de contacter l'administrateur système ou le responsable de la gestion des congés pour obtenir plus d'informations sur la cause de ce problème et pour trouver une solution pour valider votre demande de congé.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - analyser_verrous_securite(hr.leave) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'hr.leave'.
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (54.25s) :**
```text
Analyse de la demande d'achat de 15 000€ :

- L'analyse de sécurité via `analyser_verrous_securite` n'a pas permis de déterminer qui a le droit d'approuver la demande, faute de droits de gestion suffisants sur le modèle `custom.purchase.request`.
- L'analyse de sécurité via `analyser_verrous_securite` n'a pas permis de déterminer qui a le droit d'approuver la demande, faute de droits de gestion suffisants sur le modèle `purchase.order`.
- L'évaluation des règles d'enregistrement (`ir.rule`) pour `custom.purchase.request` n'a pas trouvé de règles de groupe applicables, car l'utilisateur n'appartient à aucun des groupes visés par les règles.
- Le moteur de règles (`evaluer_regles_enregistrement`) a déterminé que l'utilisateur peut voir l'enregistrement pour un montant de 15 000€, car `can_view_amount()` est True.
- Le modèle `purchase.order` n'a pas été trouvé dans le graphique de connaissance indexé.

En conclusion, il n'est pas possible de déterminer avec certitude qui a le droit d'approuver la demande d'achat de 15 000€ en fonction des informations disponibles. Cependant, l'utilisateur a le droit de voir l'enregistrement pour un montant de 15 000€, car `can_view_amount()` est True.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - analyser_verrous_securite(custom.purchase.request) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'custom.purchase.request'.
  - analyser_verrous_securite(purchase.order) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'purchase.order'.
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (12.51s) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez suivre les étapes suivantes :

1. Cliquez sur le bouton 'Demande de mise à disposition' sur la vue de formulaire de 'custom.asset.loan'.
2. Cette action appelle la méthode Python 'action_demande de mise à disposition()'.
3. La méthode exécute la logique sans transition d'état de la machine à états.

Il n'y a pas de restriction de groupe spécifiée pour ce bouton.

L'évaluation des règles d'enregistrement (ir.rule) pour 'custom.asset.loan' n'a pas trouvé de règles globales ou de règles de groupe applicables. L'utilisateur n'appartient à aucun des groupes visés par les règles de groupe.

Il n'y a pas de contraintes SQL ou de modèles de domaine relationnel définis pour le modèle 'custom.asset.loan'.

Le modèle 'custom.asset.loan' existe dans l'index mais n'a pas de transitions d'état de workflow explicites définies.

La demande de mise à disposition de matériel est liée à la demande de mise à disposition 'demande_mise_disposition'.

Il est important de noter que les conditions particulières pour faire une demande de mise à disposition de matériel ne sont pas explicitement définies dans les observations fournies. Il est donc recommandé de consulter les documents internes ou les responsables concernés pour obtenir plus d'informations sur les conditions particulières.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - analyser_verrous_securite(custom.asset.loan) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'custom.asset.loan'.
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (81.89s) :**
```text
En réponse à votre question, tous les avoirs fournisseurs ne passent pas par les mêmes règles d'approbation. 

En effet, l'évaluation des règles d'enregistrement (ir.rule) pour 'account.move' a révélé que seules les règles globales s'appliquent, sans aucune règle de groupe applicable pour l'utilisateur actuel. 

Cependant, l'analyse des contraintes de données (Semgrep) pour 'account.move' a révélé que le champ 'partner_id' spécifie une condition de domaine qui restreint les partenaires autorisés, et que le champ 'journal_id' spécifie une condition de domaine qui restreint les journaux autorisés.

De plus, l'analyse des droits de gestion pour le modèle 'account.move' a révélé que les groupes 'account.group_account_invoice', 'account.group_account_manager' et 'account.group_account_user' ont le droit d'écrire sur ce modèle.

Enfin, l'analyse des transitions de workflow pour 'account.move' a révélé que les utilisateurs ont la possibilité de passer le modèle 'account.move' de l'état 'draft' à l'état 'done' via le bouton 'Post', et de passer le modèle 'account.move' de l'état 'cancel' à l'état 'cancel' via le bouton 'Cancel Entry'.

En conclusion, bien que les règles globales s'appliquent pour l'utilisateur actuel, d'autres contraintes et règles peuvent s'appliquer en fonction du contexte et des droits de gestion.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - analyser_verrous_securite(account.move) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'account.move'.
  - analyser_actions_serveur(account.move) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'account.move'.
  - ir.rule sur 'account.move' non applicable(s) au demandeur : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : ces règles de sécurité visent des groupes dont le demandeur n'est pas membre ; leur nom et leur condition (domain_force) ne sont pas divulgués.
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (11.37s) :**
```text
L'utilisateur membre à la fois du groupe régional et du groupe national peut voir un avoir de 80 000€.

La règle d'enregistrement 'Avoirs - visibilite nationale (illimitee)' permet à l'utilisateur de voir l'enregistrement, car le montant total est supérieur à 50 000€. Cette règle est applicable car l'utilisateur est membre du groupe national.

La règle d'enregistrement 'Avoirs - plafond visibilite regionale (50000e)' n'est pas applicable, car le montant total est supérieur à 50 000€.

La règle d'enregistrement 'Avoirs - cantonnement societe' est applicable, mais elle ne restreint pas l'accès à l'enregistrement.

La résolution du nom technique 'group_region' et 'group_national' n'a pas pu être effectuée, mais cela ne signifie pas que l'accès est refusé.

Les modules impliqués pour le modèle 'account.move' sont :

Synthèse : L'utilisateur peut voir l'enregistrement car la règle d'enregistrement 'Avoirs - visibilite nationale (illimitee)' est applicable et ne restreint pas l'accès.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - ir.rule sur 'account.move' non applicable(s) au demandeur : Avoirs - visibilite par departement (sauf managers) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : ces règles de sécurité visent des groupes dont le demandeur n'est pas membre ; leur nom et leur condition (domain_force) ne sont pas divulgués.
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (11.22s) :**
```text
L'utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut voir cet avoir de 80 000€. 

Cette conclusion est basée sur l'évaluation des règles d'enregistrement (ir.rule) pour le modèle 'account.move', qui n'ont pas trouvé d'application pour cet utilisateur. Les règles globales s'appliquant à tous les utilisateurs n'ont pas imposé de restriction supplémentaire de montant ou de portée. De plus, la méthode can_view_amount() a retourné True, ce qui signifie que l'utilisateur peut voir cet enregistrement.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - ir.rule sur 'account.move' non applicable(s) au demandeur : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : ces règles de sécurité visent des groupes dont le demandeur n'est pas membre ; leur nom et leur condition (domain_force) ne sont pas divulgués.
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (0.08s) :**
```text
Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. Ne pas présenter cette validation comme autorisée ou refusée de manière certaine. Source à revoir : [reimbursement.py:L1-L39](file:///home/user/odoo-17.0/addons/custom_expense_reimbursement_indirect/models/reimbursement.py#L1-L39).

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - analyser_verrous_securite(hr.expense) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette analyse porte sur un mécanisme de sécurité interne (verrou codé en dur / contournement) et le demandeur ne dispose pas d'un accès de gestion (write ou unlink) sur 'hr.expense'.
```

---