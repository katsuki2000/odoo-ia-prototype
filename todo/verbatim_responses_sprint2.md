# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-07 10:29:33

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim et la latence après instrumentation J30-J31.

---
## Synthèse Latence & Performance (J30-J31)

| Métrique | Temps Effectif (Algorithmique) | Budget Target | Statut |
|---|---|---|---|
| **p50 (Médiane)** | `2.22s` | — | — |
| **p90 (90e Percentile)** | `12.61s` | `12.0s` | ❌ DÉPASSÉ |
| **p95 (95e Percentile)** | `12.61s` | — | — |
| **Moyenne** | `5.17s` | — | — |
| **Max** | `12.61s` | — | — |

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (Total: 72.21s | Effectif: 12.608s | Groq wait: 59.602s | Sauts: 6) :**
```text
Analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH]:
  - Messages de verrous (UserError/ValidationError):
    * "Seul un responsable comptable peut valider un avoir de plus de 5000€."

Évaluation des règles d'enregistrement (ir.rule) pour 'account.move':
  - Règles Globales (ET pour tous): Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]]
  - Règles de Groupe applicables: Aucune (l'utilisateur n'appartient à aucun des groupes visés)
  - Règles de Groupe ignorées (non-membre): Purchase User Account Move [[('move_type', 'in', ('in_invoice', 'in_refund', 'in_receipt'))]], Avoirs - visibilite par departement (sauf managers) [['|', ('move_type', '!=', 'out_refund'), '|', ('invoice_user_id', '=', user.id), ('journal_id.department_id', '=', user.employee_id.department_id.id)]], Avoirs - plafond visibilite regionale (50000e) [['|', ('move_type', '!=', 'out_refund'), ('amount_total', '<=', 50000)]], Avoirs - visibilite nationale (illimitee) [[(1, '=', 1)]], Expense Team Approver Account Move [[('line_ids.expense_id', '!=', False)]]
  -> CONCLUSION: Aucune regle de groupe applicable (l'utilisateur n'appartient a aucun groupe cible par une regle sur ce modele). Seules les regles globales ci-dessus s'appliquent -- il n'y a AUCUNE restriction supplementaire de montant ou de portee pour valider un avoir de 25 000€.

Cependant, il est important de noter que la chaîne de surcharge de 'account.move.action_valider_avoir' (3 modules, ordre d'exécution réel, pas l'ordre de dépendance) contient une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par la branche conditionnelle -- risque réel que la condition soit silencieusement annulée. [Confiance: FAIBLE -- heuristique statique sur la forme exacte du contrôle de flux, ne détecte pas les gardes formulées autrement]

En conclusion, seul un responsable comptable peut valider un avoir de plus de 5000€, mais il n'y a pas de restriction supplémentaire de montant ou de portée pour valider un avoir de 25 000€. Cependant, il existe un risque réel que la condition soit silencieusement annulée en raison de la chaîne de surcharge de 'account.move.action_valider_avoir'.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (Total: 65.33s | Effectif: 10.411s | Groq wait: 54.916s | Sauts: 6) :**
```text
Analyse des droits d'approuver un avoir pour un client VIP :

- Le module 'custom_credit_note_approval' n'a pas de verrou spécifique ni incertitude dynamique détecté.
- Le module 'custom_credit_note_approval_vip' n'a pas de verrou spécifique ni incertitude dynamique détecté.
- Le module 'hr_expense' n'a pas de verrou spécifique ni incertitude dynamique détecté.
- Le module 'purchase' n'a pas de verrou spécifique ni incertitude dynamique détecté.

Cependant, la chaîne de surcharge de 'account.move.action_valider_avoir' (module 'custom_credit_note_approval_vip') contient une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par la branche conditionnelle -- risque réel que la condition soit silencieusement annulée.

En outre, la chaîne de surcharge de 'account.move.action_valider_avoir' (module 'custom_credit_note_approval_regional') contient une CHAINE RELATIONNELLE NON VÉRIFIÉE (Règle 3) : 'action_valider_avoir' (module 'custom_credit_note_approval_regional') dépasse la condition de base du module 'custom_credit_note_approval_vip' et ajoute une restriction supplémentaire.

Enfin, le Model 'account.move' [WRITE] est autorisé pour les groupes account.group_account_invoice, account.group_account_manager, account.group_account_user, group_purchase_user, purchase.group_purchase_manager.

En conclusion, pour approuver un avoir pour un client VIP, il faut vérifier les conditions suivantes :

- La condition de base du module 'custom_credit_note_approval_vip' (pas de verrou spécifique ni incertitude dynamique détecté).
- La condition supplémentaire du module 'custom_credit_note_approval_regional' (CHAINE RELATIONNELLE NON VÉRIFIÉE).
- La chaîne de surcharge de 'account.move.action_valider_avoir' (module 'custom_credit_note_approval_vip') qui peut annuler la condition de base.

Il est donc important de vérifier les conditions supplémentaires et les chaînes de surcharge pour déterminer qui a le droit d'approuver un avoir pour un client VIP.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (Total: 86.51s | Effectif: 2.986s | Groq wait: 83.522s | Sauts: 3) :**
```text
Analyse des verrous Python ([hr_leave.py:L1-L28](file:///home/user/odoo-17.0/addons/custom_hr_leave_workflow/models/hr_leave.py#L1-L28)) [Confiance: HIGH] :

- Vous avez un message de verrou qui indique : "Impossible de valider : le solde de conges restant (%.1f jours) est insuffisant. Cochez 'Demande urgente' pour soumettre quand meme a validation exceptionnelle du N+2."
- Vous avez un autre message de verrou qui indique : "Une demande urgente depassant le solde doit etre validee par le N+2 ou un responsable RH."

Analyse des verrous Python ([hr_leave.py:L1-L1825](file:///home/user/odoo-17.0/addons/hr_holidays/models/hr_leave.py#L1-L1825)) [Confiance: HIGH] :

- Aucun verrou spécifique ni incertitude dynamique détecté.

Analyse des verrous Python ([hr_leave.py:L1-L67](file:///home/user/odoo-17.0/addons/hr_holidays/populate/hr_leave.py#L1-L67)) [Confiance: HIGH] :

- Aucun verrou spécifique ni incertitude dynamique détecté.

Chaîne de surcharge de 'hr.leave.action_approve' (2 modules, ordre d'exécution réel, pas l'ordre de dépendance) :

- Le module 'custom_hr_leave_workflow' contient une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_approve(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par la branche conditionnelle -- risque réel que la condition soit silencieusement annulée. [Confiance: FAIBLE -- heuristique statique sur la forme exacte du contrôle de flux, ne détecte pas les gardes formulées autrement]
- Le module 'hr_holidays' contient une logique de validation qui n'a pas été détectée par les analyses précédentes.

Button 'valider demande de congé' on 'hr.leave' :

- Appelle la méthode 'action_valider demande de congé()'.
- La transition d'état est exécutée sans passer par la machine à états.
- Il n'y a pas de restriction de groupe spécifiée pour ce bouton.

En résumé, vous avez deux messages de verrou qui indiquent que vous ne pouvez pas valider votre demande de congé car votre solde de congés est insuffisant. Vous devez cocher la case 'Demande urgente' pour soumettre votre demande à validation exceptionnelle du N+2. De plus, une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (Total: 49.51s | Effectif: 1.841s | Groq wait: 47.671s | Sauts: 3) :**
```text
Analyse des droits d'approuver une demande d'achat de 15 000€ :

- Selon l'analyse des verrous Python dans le fichier `purchase_request.py` (L1-L33), il y a deux messages de verrous :
  * "Vous n'avez pas le droit de valider cette demande d'achat."
  * "Au-delà de 10 000 euros, seule la Direction peut valider (liste restreinte)."

- Selon l'analyse des verrous Python dans le fichier `purchase_order.py` (L1-L1101), aucun verrou spécifique ni incertitude dynamique n'a été détecté.

- Selon l'analyse des verrous Python dans le fichier `purchase.py` (L1-L92), aucun verrou spécifique ni incertitude dynamique n'a été détecté.

- Selon l'évaluation des règles, le modèle `purchase.order` est accessible aux groupes `account.group_account_invoice`, `group_purchase_manager`, `group_purchase_user` et `purchase.group_purchase_manager`.

En conclusion, pour approuver une demande d'achat de 15 000€, il faut être membre d'un des groupes suivants : `account.group_account_invoice`, `group_purchase_manager`, `group_purchase_user` ou `purchase.group_purchase_manager`. Cependant, si la demande dépasse 10 000€, seule la Direction peut valider la demande.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - Logins/Emails privilégies en dur (custom.purchase.request) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'custom.purchase.request'.
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (Total: 60.06s | Effectif: 2.219s | Groq wait: 57.843s | Sauts: 2) :**
```text
Pour faire une demande de mise à disposition de matériel, vous devez cliquer sur le bouton 'Demande de mise à disposition' sur la vue de formulaire de 'custom.asset.loan'. Cette action appelle la méthode 'action_demande de mise à disposition()'.

Il est important de noter que la demande de mise à disposition est disponible pour les utilisateurs qui appartiennent à un groupe requis (ou aucun groupe n'est requis).

En ce qui concerne les conditions particulières, il est mentionné que la séparation des rôles est requise : le bénéficiaire d'un matériel de plus de 2000 euros doit être différent du demandeur initial. Cela signifie que si vous demandez un matériel d'une valeur supérieure à 2000 euros, vous devez être différent du demandeur initial.

Il n'y a pas d'autres conditions ou restrictions supplémentaires mentionnées dans les observations disponibles.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (Total: 99.65s | Effectif: 12.236s | Groq wait: 87.409s | Sauts: 7) :**
```text
En analysant les règles d'approbation pour les avoirs fournisseurs, nous constatons que :

- Les règles globales (ir.rule) pour 'account.move' sont les suivantes : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]].
- Aucune règle de groupe n'est applicable pour l'utilisateur, car il n'appartient à aucun groupe cible par une règle sur ce modèle.
- Seules les règles globales s'appliquent, sans restriction supplémentaire de montant ou de portée.

Cependant, nous avons également détecté les suivants :

- Dans le module 'custom_credit_note_approval', il existe une règle d'approbation qui nécessite la validation d'un responsable comptable pour les avoirs de plus de 5000€.
- Dans la chaîne de surcharge de 'account.move.action_valider_avoir', nous avons trouvé une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel. Cela peut entraîner un risque réel que la condition soit silencieusement annulée.
- Dans la chaîne de surcharge de 'account.move._reverse_moves', nous avons trouvé une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super()._reverse_moves(...)` inconditionnel. Cela peut également entraîner un risque réel que la condition soit silencieusement annulée.

En conclusion, les règles d'approbation pour les avoirs fournisseurs sont les suivantes :

- Les règles globales s'appliquent sans restriction supplémentaire de montant ou de portée.
- Les avoirs de plus de 5000€ nécessitent la validation d'un responsable comptable.
- Il existe un risque réel que les conditions d'approbation soient silencieusement annulées en raison de la chaîne de surcharge de 'account.move.action_valider_avoir' et 'account.move._reverse_moves'.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - SUDO détecté (account.move) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'account.move'.
  - IDs en dur (account.move) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'account.move'.
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (Total: 40.03s | Effectif: 2.03s | Groq wait: 38.0s | Sauts: 1) :**
```text
L'utilisateur membre à la fois du groupe régional et du groupe national peut voir un avoir de 80 000€.

La règle d'enregistrement 'Avoirs - plafond visibilité régionale (50000e)' ne s'applique pas car l'amount_total est supérieur à 50 000€. La règle d'enregistrement 'Avoirs - visibilité nationale (illimitée)' ne pose pas de restriction.

La fonction can_view_amount() a été évaluée et a retourné True, ce qui signifie que l'utilisateur peut voir cet enregistrement.

Ce résultat est calculé directement par le moteur de règles et ne doit jamais être recalculé ou contredit.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (Total: 43.66s | Effectif: 2.058s | Groq wait: 41.599s | Sauts: 1) :**
```text
L'utilisateur peut voir l'enregistrement d'un avoir de 80 000€. Cela est déterminé par l'évaluation des règles d'enregistrement (ir.rule) pour le modèle 'account.move', qui n'applique aucune règle de groupe à l'utilisateur car il n'appartient à aucun des groupes visés. Seules les règles globales s'appliquent, et il n'y a aucune restriction supplémentaire de montant ou de portée pour cet enregistrement. Le moteur de règles (evaluer_regles_enregistrement) calcule directement que l'utilisateur peut voir cet enregistrement, ce qui est confirmé par le verdict [FAIT DÉTERMINISTIQUE] : l'utilisateur PEUT voir cet enregistrement.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (Total: 0.12s | Effectif: 0.12s | Groq wait: 0.0s | Sauts: 2) :**
```text
Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. Ne pas présenter cette validation comme autorisée ou refusée de manière certaine. Source à revoir : [reimbursement.py:L1-L39](file:///home/user/odoo-17.0/addons/custom_expense_reimbursement_indirect/models/reimbursement.py#L1-L39).

[Source: Graphe de Connaissances Code Intelligence]
```

---