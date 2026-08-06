# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-08-06 14:18:24

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim et la latence après instrumentation J30-J31.

---
## Synthèse Latence & Performance (J30-J31)

| Métrique | Temps Effectif (Algorithmique) | Budget Target | Statut |
|---|---|---|---|
| **p50 (Médiane)** | `2.38s` | — | — |
| **p90 (90e Percentile)** | `7.42s` | `12.0s` | ✅ RESPECTÉ |
| **p95 (95e Percentile)** | `7.42s` | — | — |
| **Moyenne** | `3.39s` | — | — |
| **Max** | `7.42s` | — | — |

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (Total: 79.75s | Effectif: 7.421s | Groq wait: 72.328s | Sauts: 4) :**
```text
Analyse des droits d'approuver un avoir de 25 000€ pour un client normal (pas VIP) :

- L'analyse des verrous Python dans le module `account_move.py` (L1-L22) indique que "Seul un responsable comptable peut valider un avoir de plus de 5000€." [Confiance: HIGH].

- L'analyse des verrous Python dans les modules `account_move.py` (L1-L21) et `account_move.py` (L1-L14) ne détecte aucun verrou spécifique ni incertitude dynamique.

- L'analyse des verrous Python dans le module `account_bank_statement_line.py` (L1-L807) ne détecte aucun verrou spécifique ni incertitude dynamique.

- La chaîne de surcharge de la méthode `action_valider_avoir` (3 modules, ordre d'exécution réel, pas l'ordre de dépendance) indique que la méthode `action_valider_avoir` du module `custom_credit_note_approval_vip` contient une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par la branche conditionnelle -- risque réel que la condition soit silencieusement annulée. [Confiance: FAIBLE].

- La chaîne de surcharge de la méthode `action_valider_avoir` (3 modules, ordre d'exécution réel, pas l'ordre de dépendance) indique que la méthode `action_valider_avoir` du module `custom_credit_note_approval_regional` et `custom_credit_note_approval` ne détecte aucun verrou spécifique ni incertitude dynamique.

- Le module `account.invoice` n'a pas été trouvé dans le graphique de connaissance indexé (probable typo ou modèle manquant).

En conclusion, selon l'analyse des verrous Python dans le module `account_move.py` (L1-L22), seul un responsable comptable peut valider un avoir de plus de 5000€.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (Total: 65.09s | Effectif: 5.576s | Groq wait: 59.515s | Sauts: 4) :**
```text
Analyse des résultats :

- L'analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH] indique que seul un responsable comptable peut valider un avoir de plus de 5000€.
- L'analyse des verrous Python ([account_bank_statement_line.py:L1-L807](file:///home/user/odoo-ia-prototype/miro-rag/fake_data/code/account/account_bank_statement_line.py#L1-L807)) [Confiance: HIGH] n'a pas détecté de verrou spécifique ni d'incertitude dynamique.
- L'analyse des verrous Python ([account_move.py:L1-L14](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_vip/models/account_move.py#L1-L14)) [Confiance: HIGH] n'a pas détecté de verrou spécifique ni d'incertitude dynamique.
- La chaîne de surcharge de 'account.move._reverse_moves' (2 modules, ordre d'exécution réel, pas l'ordre de dépendance) indique que la logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par la branche conditionnelle -- risque réel que la condition soit silencieusement annulée.
- La chaîne de surcharge de 'account.move.action_valider_avoir' (3 modules, ordre d'exécution réel, pas l'ordre de dépendance) indique que la logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par la branche conditionnelle -- risque réel que la condition soit silencieusement annulée.
- Le groupe identifiant 'client_vip_group' n'a pas pu être résolu contre aucun groupe avec des règles d'écriture ou des ACLs sur 'account.move'. Cela ne signifie pas que l'accès est refusé -- cela signifie que l'identifiant lui-même n'a pas pu être matché.

Réponse finale :

Seul un responsable comptable peut valider un avoir de plus de 5000€.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (Total: 59.6s | Effectif: 2.376s | Groq wait: 57.224s | Sauts: 2) :**
```text
Bonjour,

Je suis désolé d'entendre que vous rencontrez des difficultés pour valider votre demande de congé. Selon l'analyse des verrous Python, il semble que le problème soit lié à votre solde de congés restant. Vous avez coché 'urgente', mais votre solde de congés est insuffisant. Vous devez cocher 'Demande urgente' pour soumettre une demande de validation exceptionnelle du N+2.

Cependant, il est important de noter que même si vous cochez 'urgente', votre demande doit être validée par le N+2 ou un responsable RH si elle dépasse votre solde de congés.

J'espère que cela vous aidera à résoudre le problème. Si vous avez d'autres questions, n'hésitez pas à me demander.

Cordialement, [Votre nom]

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (Total: 93.32s | Effectif: 3.187s | Groq wait: 90.131s | Sauts: 3) :**
```text
En fonction des informations disponibles, il semble que la demande d'achat de 15 000€ nécessite une validation spécifique. 

D'après l'analyse des verrous Python, il y a deux messages de verrous possibles :

- "Vous n'avez pas le droit de valider cette demande d'achat."
- "Au-delà de 10 000 euros, seule la Direction peut valider (liste restreinte)."

Cependant, il est important de noter que la première règle est masquée par un mécanisme de contournement de sécurité, ce qui signifie que la validation peut être autorisée malgré cette règle.

En revanche, la deuxième règle est basée sur une condition spécifique (au-delà de 10 000 euros) et ne concerne pas directement la validation de la demande d'achat.

Enfin, il est important de noter que la validation de la demande d'achat de 15 000€ nécessite une validation spécifique, mais il n'est pas clair qui a le droit d'approuver cette demande.

En résumé, la réponse finale est :

- La Direction a le droit d'approuver la demande d'achat de 15 000€ (liste restreinte).
- La validation de la demande d'achat nécessite une validation spécifique, mais il n'est pas clair qui a le droit d'approuver cette demande.
- La première règle est masquée par un mécanisme de contournement de sécurité, ce qui signifie que la validation peut être autorisée malgré cette règle.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - Logins/Emails privilégies en dur (custom.purchase.request) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'custom.purchase.request'.
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (Total: 32.32s | Effectif: 2.049s | Groq wait: 30.275s | Sauts: 2) :**
```text
Pour faire une demande de mise à disposition de matériel, il est important de prendre en compte les conditions particulières. 

D'après l'analyse des verrous Python, il existe une condition selon laquelle le bénéficiaire d'un matériel de plus de 2000 euros doit être différent du demandeur initial. Cette condition est indiquée par le message d'erreur "Separation des roles requise : le beneficiaire d'un materiel de plus de 2000 euros doit etre different du demandeur initial." [Confiance: HIGH].

Il est donc essentiel de vérifier que les rôles sont séparés avant de faire une demande de mise à disposition de matériel.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (Total: 71.02s | Effectif: 6.356s | Groq wait: 64.664s | Sauts: 5) :**
```text
En analysant les règles d'approbation pour les avoirs fournisseurs, nous constatons que :

- Les avoirs de plus de 5000€ nécessitent l'approbation d'un responsable comptable, comme indiqué par le message d'erreur "Seul un responsable comptable peut valider un avoir de plus de 5000€." (Analyse des verrous Python [account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22) [Confiance: HIGH]).

- Les autres avoirs fournisseurs ne sont pas soumis à des règles d'approbation spécifiques, comme indiqué par les analyses des verrous Python (Analyse des verrous Python [account_move.py:L1-L21](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_regional/models/account_move.py#L1-L21) [Confiance: HIGH] et Analyse des verrous Python [account_move.py:L1-L14](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_vip/models/account_move.py#L1-L14) [Confiance: HIGH]).

- L'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' automatise la validation d'avoirs reçus de trois fournisseurs spécifiques, en contournant les règles d'accès et les ACL via sudo(), comme indiqué par l'analyse du code de l'action serveur (Analyse du code de l'action serveur 'custom_automation_traps.ir_action_server_avoir_fournisseur_privilegie' [Confiance: FAIBLE - logique en données XML, modifiable à l'exécution]).

- La chaîne de surcharge de 'account.move._reverse_moves' (module 'sale') contient une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super()._reverse_moves(...)` inconditionnel, ce qui peut annuler la condition, comme indiqué par la chaîne de surcharge de 'account.move._reverse_moves' (module 'sale') (Chaîne de surcharge de 'account.move._reverse_moves' (2 modules, ordre d'exécution réel, pas l'ordre de dépendance)).

- La chaîne de surcharge de 'account.move.action_valider_avoir' (module 'custom_credit_note_approval_vip') contient également une branche conditionnelle qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel, ce qui peut annuler la condition, comme indiqué par la chaîne de surcharge de 'account.move.action_valider_avoir' (3 modules, ordre d'exécution réel, pas l'ordre de dépendance).

- L'évaluation des règles d'enregistrement (ir.rule) pour 'stock.move' n'a pas trouvé de règles globales ou de groupes applicables, ce qui signifie que les règles d'approbation pour les avoirs fournisseurs ne sont pas définies par les règles d'enregistrement, comme indiqué par l'évaluation des règles d'enregistrement (ir.rule) pour 'stock.move' (Évaluation des règles d'enregistrement (ir.rule) pour 'stock.move').

En conclusion, les avoirs de plus de 5000€ nécessitent l'approbation d'un responsable comptable, tandis que les autres avoirs fournisseurs ne sont pas soumis à des règles d'approbation spécifiques.

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

**Réponse Verbatim de l'agent (Total: 54.12s | Effectif: 1.924s | Groq wait: 52.199s | Sauts: 1) :**
```text
L'utilisateur membre à la fois du groupe régional et du groupe national peut voir un avoir de 80 000€.

La règle d'enregistrement 'Avoirs - visibilite nationale (illimitee)' permet à l'utilisateur de voir l'enregistrement, car le montant total est supérieur à 50 000€. Cette règle est combinée avec les règles globales, qui ne restreignent pas l'accès.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - ir.rule sur 'account.move' non applicable(s) au demandeur : Avoirs - visibilite par departement (sauf managers) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : ces règles de sécurité visent des groupes dont le demandeur n'est pas membre ; leur nom et leur condition (domain_force) ne sont pas divulgués.
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (Total: 9.38s | Effectif: 1.525s | Groq wait: 7.854s | Sauts: 1) :**
```text
En réponse à la question : Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

La réponse est : OUI, l'utilisateur peut voir cet enregistrement.

Cette conclusion est basée sur l'évaluation des règles d'enregistrement (ir.rule) pour le modèle 'account.move', qui n'a pas trouvé d'application de règles de groupe pour cet utilisateur. Seules les règles globales s'appliquent, qui n'imposent aucune restriction supplémentaire de montant ou de portée. Le moteur de règles a donc déterminé que l'utilisateur peut voir cet enregistrement pour un montant de 80 000€, ce qui est confirmé par le [FAIT DÉTERMINISTIQUE] : can_view_amount() = True.

[Source: Graphe de Connaissances Code Intelligence]

🔒 ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):
  - ir.rule sur 'account.move' non applicable(s) au demandeur : Avoirs - visibilite par departement (sauf managers), Avoirs - plafond visibilite regionale (50000e), Avoirs - visibilite nationale (illimitee) : ÉLÉMENT OMIS POUR RAISON D'AUTORISATION : ces règles de sécurité visent des groupes dont le demandeur n'est pas membre ; leur nom et leur condition (domain_force) ne sont pas divulgués.
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (Total: 0.11s | Effectif: 0.108s | Groq wait: 0.0s | Sauts: 2) :**
```text
Je ne peux pas classifier avec certitude qui peut valider cette demande de remboursement. L'analyse statique détecte un dispatch dynamique (`getattr`) : la méthode exécutée dépend d'un paramètre récupéré à l'exécution, donc le chemin exact doit être revu manuellement. Ne pas présenter cette validation comme autorisée ou refusée de manière certaine. Source à revoir : [reimbursement.py:L1-L39](file:///home/user/odoo-17.0/addons/custom_expense_reimbursement_indirect/models/reimbursement.py#L1-L39).

[Source: Graphe de Connaissances Code Intelligence]
```

---