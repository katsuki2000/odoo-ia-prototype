# Rapport Verbatim — Test Adversarial (Sprint 2 / End-to-End Benchmark)

**Date d'exécution :** 2026-07-29 11:37:18

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et mesurer les réponses verbatim après résolution des verrous Sprint 2.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (8.82s) :**
```text
D'après les règles d'enregistrement et les analyses des verrous Python, il semble qu'il n'y ait pas de règle spécifique qui interdise explicitement l'approbation d'un avoir de 25 000€ pour un client normal (pas VIP). Cependant, il est important de noter que les règles de groupe applicables ne sont pas définies pour les utilisateurs non-VIP, et que les règles de groupe ignorées (non-membre) incluent des plafonds de visibilité régionaux et nationaux.

Cependant, l'analyse des verrous Python révèle un message de verrou qui indique que "Seul un responsable comptable peut valider un avoir de plus de 5000€." Cela suggère que les avoirs supérieurs à 5 000€ nécessitent l'approbation d'un responsable comptable.

En conséquence, il est probable que l'approbation d'un avoir de 25 000€ pour un client normal nécessite l'intervention d'un responsable comptable, en raison du montant élevé de l'avoir. Il est recommandé de consulter les règles et les procédures internes de l'entreprise pour confirmer les exigences spécifiques pour l'approbation d'avoirs de ce montant.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (55.12s) :**
```text
D'après les règles d'enregistrement (ir.rule) pour 'account.move', les avoirs pour les clients VIP peuvent être approuvés par les utilisateurs ayant les droits suivants :

- Les membres du groupe 'account.group_account_invoice' 
- Les membres du groupe 'account.group_account_manager' 
- Les membres du groupe 'account.group_account_user'

Cependant, il est important de noter qu'il existe des règles spécifiques pour les avoirs, notamment celles liées au montant et à la visibilité départementale ou nationale. Par exemple, seuls les responsables comptables peuvent valider un avoir de plus de 5000€.

En résumé, pour approuver un avoir pour un client VIP, il faut disposer des droits appropriés au sein des groupes 'account.group_account_invoice', 'account.group_account_manager' ou 'account.group_account_user', et respecter les règles spécifiques liées aux avoirs, telles que les limitations de montant.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (16.76s) :**
```text
Bonjour,

Nous avons analysé votre situation et identifié les raisons pour lesquelles vous n'arrivez pas à valider votre demande de congé malgré avoir coché l'option 'urgente'. 

Selon les informations disponibles, il semble que le solde de congés restant est insuffisant pour valider votre demande. Même si vous avez coché 'Demande urgente', une validation exceptionnelle par le N+2 ou un responsable RH est nécessaire lorsque la demande dépasse le solde disponible.

Il est important de noter que les règles d'enregistrement (ir.rule) pour 'hr.leave' ne sont pas applicables dans votre cas, car il n'y a pas de règles globales ou de règles de groupe qui vous soient spécifiquement attribuées.

Pour résoudre ce problème, nous vous recommandons de vérifier votre solde de congés restant et de contacter le N+2 ou un responsable RH pour obtenir une validation exceptionnelle de votre demande de congé.

Cordialement,
[Votre Nom]

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (11.96s) :**
```text
Selon les règles d'enregistrement et les verrous Python analysés, les utilisateurs ayant le droit d'approuver une demande d'achat de 15 000€ sont les membres du groupe 'direction' ou ceux ayant les adresses e-mail 'direction@societe.com' ou 'daf@societe.com'. En effet, les messages de verrous Python indiquent explicitement que seule la Direction peut valider les demandes d'achat supérieures à 10 000 euros. Les groupes 'base.group_user', 'group_miro_ai_admin', 'group_miro_ai_user', 'miro_ai.group_miro_ai_admin' et 'miro_ai.group_miro_ai_user' ont des droits d'écriture sur le modèle 'custom.purchase.request', mais les règles spécifiques pour les demandes supérieures à 10 000 euros restreignent l'approbation à la Direction.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (17.17s) :**
```text
Pour faire une demande de mise à disposition de matériel, il suffit de cliquer sur le bouton "Demande de mise à disposition de matériel" sur le formulaire de vue de "custom.asset.loan". Cette action appellera la méthode Python "action_demande de mise à disposition de matériel()".

Il est important de noter qu'il n'y a pas de restrictions de groupe pour accéder à ce bouton, ce qui signifie que tout utilisateur peut effectuer cette demande.

Cependant, il existe une règle de validation spécifique pour les demandes de mise à disposition de matériel. En effet, si le bénéficiaire d'un matériel dont la valeur est supérieure à 2000 euros est le même que le demandeur initial, la demande sera rejetée avec un message d'erreur indiquant que la séparation des rôles est requise.

Il n'y a pas d'autres conditions particulières ou de règles d'enregistrement spécifiques pour les demandes de mise à disposition de matériel. Les demandes seront traitées en fonction de la logique définie dans la méthode Python "action_demande de mise à disposition de matériel()".

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (12.31s) :**
```text
Non, tous les avoirs fournisseurs ne passent pas par les mêmes règles d'approbation. Selon les données analysées, il existe des règles globales et des règles de groupe qui s'appliquent à l'enregistrement des avoirs. Les règles globales portent sur le cantonnement société et s'appliquent à tous les utilisateurs, tandis que les règles de groupe sont spécifiques à certains départements ou régions et sont ignorées si l'utilisateur n'en fait pas partie.

De plus, les analyses des verrous Python révèlent que certaines règles d'approbation sont spécifiques à certaines conditions, telles que le montant de l'avoir (par exemple, "Seul un responsable comptable peut valider un avoir de plus de 5000€"). Cela indique que les règles d'approbation peuvent varier en fonction de facteurs tels que le montant, le département ou la région.

Enfin, les données montrent que les utilisateurs appartenant aux groupes "account.group_account_invoice", "account.group_account_manager" et "account.group_account_user" ont accès à l'écriture sur le modèle "account.move", mais les règles d'approbation spécifiques peuvent varier en fonction de leur appartenance à ces groupes. En résumé, les règles d'approbation pour les avoirs fournisseurs sont complexes et dépendent de plusieurs facteurs, ce qui signifie que tous les avoirs ne passent pas par les mêmes règles d'approbation.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (15.59s) :**
```text
D'après les règles d'enregistrement (ir.rule) pour 'account.move', il est évident que les règles globales ne permettent pas l'accès à l'avoir de 80 000€ pour un utilisateur membre à la fois du groupe régional et du groupe national. 

Les règles de groupe applicables ne sont pas non plus respectées, car l'utilisateur n'appartient à aucun des groupes visés. De plus, les règles de groupe ignorées (non-membre) incluent des plafonds de visibilité régionaux de 50 000€ et une visibilité nationale illimitée.

Cependant, les résultats indiquent explicitement que les groupes 'regional' et 'national' n'ont pas d'accès en lecture à 'account.move'. Par conséquent, un utilisateur membre à la fois du groupe régional et du groupe national ne peut pas voir un avoir de 80 000€ en raison du manque d'accès en lecture pour ces groupes.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (12.3s) :**
```text
D'après les règles d'enregistrement évaluées pour 'account.move', il est évident que les règles globales s'appliquent sans considération de groupe. Les règles spécifiques aux groupes, telles que "Avoirs - visibilite par departement (sauf managers)" et "Avoirs - visibilite nationale (illimitee)", sont ignorées dans ce cas puisque l'utilisateur n'appartient à aucun des groupes visés.

Cependant, les règles globales définies comme [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]] s'appliquent. Ces règles n'impliquent pas directement un plafond de visibilité basé sur le montant de l'avoir, mais plutôt sur le type de mouvement et l'appartenance à la société.

Étant donné que l'utilisateur n'appartient à aucun groupe et que les règles globales ne spécifient pas de restriction de montant pour la visibilité des avoirs, il est raisonnable de conclure que l'utilisateur peut voir l'avoir de 80 000€ si celui-ci correspond aux critères définis par les règles globales, notamment en termes de type de mouvement et d'appartenance à la société de l'utilisateur. Cependant, sans informations supplémentaires sur la configuration spécifique des règles d'accès et des droits de l'utilisateur, il est difficile de donner une réponse définitive. Il faudrait vérifier les paramètres de sécurité et les règles d'accès spécifiques à l'entreprise pour confirmer les droits de visibilité de cet utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (11.58s) :**
```text
Selon les informations disponibles, tous les utilisateurs authentifiés ont l'autorisation d'écrire sur le modèle 'custom.reimbursement.request'. Cela signifie qu'ils peuvent valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect. Il n'y a pas de règles actives spécifiques qui restreignent cette autorisation. Cependant, il est important de noter que le modèle 'hr.expense' n'a pas été trouvé dans le graphique de connaissances indexé, ce qui pourrait indiquer une erreur de frappe ou un modèle manquant.

[Source: Graphe de Connaissances Code Intelligence]
```

---