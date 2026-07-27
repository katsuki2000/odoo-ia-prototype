# Rapport Verbatim — Test Adversarial (Sprint 1 / Story S1.3)

**Date d'exécution :** 2026-07-27 10:31:26

**Objectif :** Poser les questions test du README à l'agent Code Intelligence et noter les réponses verbatim pour cartographier les gaps.

---

## [Q1.1] 1. Cascade avoirs (Standard)
**Question :** Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

**Vérité Terrain attendue :**
> Niveau 1: Groupe account.group_account_manager (>5000€). Niveau 2: Directeur régional (N+2) notifié (>20000€, code Python). Risque: N+2 non géré si vide.

**Réponse Verbatim de l'agent (7.43s) :**
```text
Je suis désolé, mais avec les informations disponibles, je ne peux pas fournir une réponse précise à votre question. Cependant, je peux vous donner quelques éléments généraux qui pourraient vous aider à trouver la réponse.

En général, l'approbation d'un avoir pour un client normal (pas VIP) dépend de la politique de votre entreprise ou de votre organisation. Voici quelques personnes qui pourraient avoir le droit d'approuver un avoir de 25 000€ :

- Le responsable des achats ou de la gestion des finances
- Le comptable ou le responsable des comptes
- Le directeur financier ou le directeur des ressources humaines
- Le propriétaire ou le dirigeant de l'entreprise

Il est important de noter que ces personnes peuvent varier en fonction de la taille et de la structure de votre entreprise. Il est également possible que vous ayez des procédures spécifiques en place pour l'approbation des avoirs, telles que des signatures requises ou des délais pour l'approbation.

Je vous recommande de consulter votre politique d'entreprise ou de contacter votre responsable des finances pour obtenir des informations plus précises sur la procédure d'approbation des avoirs.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q1.2] 1. Cascade avoirs (VIP)
**Question :** Qui a le droit d'approuver un avoir pour un client VIP ?

**Vérité Terrain attendue :**
> Bypass total pour avoir_vip_exempt = True. Piège: super().action_valider_avoir() rappelé sur tout le recordset à la fin.

**Réponse Verbatim de l'agent (11.28s) :**
```text
Je suis désolé, mais je n'ai pas trouvé de modèle 'client.vip' dans la base de connaissances. Cependant, je peux vous fournir une réponse générale.

L'approbation d'un avoir pour un client VIP dépend de la politique et des procédures de votre entreprise. En général, cela peut être attribué à un responsable commercial, un directeur de compte ou un responsable de la relation client. Il est possible que ce soit également le cas pour un responsable financier ou un comptable, selon les besoins spécifiques de votre entreprise.

Il est important de noter que l'approbation d'un avoir pour un client VIP nécessite souvent une validation supplémentaire, notamment pour s'assurer que les conditions de paiement sont claires et que les risques associés à la relation client sont bien évalués.

Si vous avez des informations supplémentaires sur votre entreprise ou sur le modèle 'client.vip', je serais ravi de vous aider à fournir une réponse plus précise.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q2.1] 2. Congés (Message d'erreur)
**Question :** Pourquoi je n'arrive pas à valider ma demande de congé alors que j'ai coché 'urgente' ?

**Vérité Terrain attendue :**
> Message d'erreur exact: 'Une demande urgente dépassant le solde doit être validée par le N+2 ou un responsable RH.'

**Réponse Verbatim de l'agent (11.22s) :**
```text
Il semble y avoir un problème technique avec votre demande de congé. Le système n'a pas pu trouver le modèle 'hr.holidays.request' dans la base de données. Cela pourrait être dû à une erreur de typographie ou à la suppression du modèle.

Je vous recommande de vérifier les paramètres de votre demande de congé et de s'assurer que vous avez sélectionné la bonne catégorie de demande. Si le problème persiste, il est possible que vous deviez contacter l'administrateur système pour qu'il puisse résoudre le problème.

Je vous suggère également de vérifier les étapes suivantes :

- Vérifiez que vous avez sélectionné la bonne catégorie de demande (urgente).
- Assurez-vous que votre demande de congé est complète et que tous les champs obligatoires sont remplis.
- Vérifiez que vous avez les droits suffisants pour soumettre une demande de congé.

Si vous continuez à rencontrer des problèmes, n'hésitez pas à contacter l'administrateur système pour qu'il puisse vous aider à résoudre le problème.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q3.1] 3. Demande d'achat (Bypass e-mails)
**Question :** Qui a le droit d'approuver une demande d'achat de 15 000€ ?

**Vérité Terrain attendue :**
> Le groupe purchase_manager ne suffit pas >10000€. Seuls logins dans _VALIDATEURS_EXCEPTIONNELS (direction@societe.com, daf@societe.com) peuvent valider.

**Réponse Verbatim de l'agent (11.03s) :**
```text
Je suis désolé, mais avec les informations fournies, je ne peux pas fournir une réponse précise. Cependant, je peux vous donner quelques suggestions générales.

Dans la plupart des entreprises, la décision d'approuver une demande d'achat de 15 000€ relève généralement de la responsabilité d'un responsable ou d'un gestionnaire. Cela peut varier en fonction de la taille et de l'organisation de l'entreprise, ainsi que des procédures internes en vigueur.

Voici quelques exemples de personnes qui pourraient avoir le droit d'approuver une demande d'achat de 15 000€ :

- Le directeur financier ou le responsable des achats
- Le directeur général ou le PDG
- Un responsable de projet ou un gestionnaire de budget
- Un comité d'approbation des achats

Il est important de noter que ces décisions doivent être prises en fonction des procédures internes et des politiques de l'entreprise, ainsi que des lois et réglementations applicables.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q4.1] 4. Asset loan (Référence croisée)
**Question :** Comment faire une demande de mise à disposition de matériel, et y a-t-il des conditions particulières ?

**Vérité Terrain attendue :**
> Nécessite demande_achat_liee_id. Si >2000€, bénéficiaire != demandeur (séparation des rôles).

**Réponse Verbatim de l'agent (11.44s) :**
```text
Je suis désolé, mais il semble que le modèle "stock.request" n'existe pas dans la base de données Odoo que j'ai accédée. Cependant, je peux vous fournir une réponse générale sur la façon de faire une demande de mise à disposition de matériel et les conditions particulières qui pourraient s'appliquer.

**Comment faire une demande de mise à disposition de matériel :**

1. Vérifiez si le matériel que vous souhaitez demander est disponible dans la base de données Odoo.
2. Si le matériel est disponible, vous pouvez créer une demande de mise à disposition en utilisant le formulaire de demande de matériel.
3. Vous devrez fournir les informations suivantes :
 - Le nom et la description du matériel
 - La quantité requise
 - La date de début et de fin de la mise à disposition
 - Les raisons de la demande
4. Enregistrez la demande et attendez la validation de la gestion de stock.

**Conditions particulières :**

- La demande de mise à disposition doit être faite avec suffisamment de temps d'avance pour permettre à la gestion de stock de préparer le matériel.
- Le matériel doit être retourné dans les mêmes conditions que lors de sa mise à disposition.
- La demande de mise à disposition doit être validée par la gestion de stock avant que le matériel ne soit mis à disposition.
- Les conditions de stockage et de manipulation du matériel doivent être respectées.

Je vous recommande de consulter la documentation Odoo ou de contacter le support technique pour obtenir des informations plus précises sur la façon de faire une demande de mise à disposition de matériel et les conditions particulières qui s'appliquent.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q5.1] 5. Actions serveur (Data / sudo)
**Question :** Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?

**Vérité Terrain attendue :**
> NON: fournisseurs ID 42, 108, 231 auto-validés via ir.actions.server avec sudo() contournant les règles standard.

**Réponse Verbatim de l'agent (107.44s) :**
```text
En réponse à votre question, il semble que les avoirs fournisseurs ne passent pas nécessairement par les mêmes règles d'approbation. Les modules impliqués pour le modèle 'stock.move' ne sont pas directement liés aux avoirs fournisseurs, qui sont généralement gérés par les modules 'purchase.order' et 'account.move.line'. 

Cependant, il est important de noter que les règles d'approbation peuvent varier en fonction de la configuration de votre système et des besoins spécifiques de votre entreprise. Il est donc recommandé de vérifier les paramètres de votre système et de consulter les documents de configuration pour obtenir plus d'informations sur les règles d'approbation appliquées aux avoirs fournisseurs.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.1] 6. ir.rule ET/OU (Deux groupes)
**Question :** Un utilisateur membre à la fois du groupe régional et du groupe national peut-il voir un avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Règles de groupe en OU. La règle nationale (illimitée) l'emporte sur le plafond 50k€ régional.

**Réponse Verbatim de l'agent (11.12s) :**
```text
Réponse :

Il semble que les groupes régionaux et nationaux n'aient pas d'accès en lecture aux avoirs comptables (account.move) dans votre système Odoo. 

Cela signifie que même si un utilisateur est membre à la fois du groupe régional et du groupe national, il ne pourra pas voir un avoir de 80 000€ car les groupes auxquels il appartient n'ont pas les droits nécessaires pour accéder à cette information.

Il faudrait donc vérifier les droits d'accès des groupes et ajuster les permissions pour permettre aux utilisateurs de voir les informations nécessaires.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q6.2] 6. ir.rule ET/OU (Aucun groupe)
**Question :** Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?

**Vérité Terrain attendue :**
> OUI: Ni l'une ni l'autre règle ne s'applique. Soumis uniquement à la règle globale (société) sans limite de montant.

**Réponse Verbatim de l'agent (56.06s) :**
```text
En fonction des informations disponibles, il semble que l'utilisateur en question n'appartient à aucun des deux groupes (régional ou national). 

Selon les règles actives, il n'y a aucune règle qui accorde explicitement l'accès à l'avoir de 80 000€ à cet utilisateur. 

Par conséquent, il est peu probable que l'utilisateur puisse voir cet avoir de 80 000€ sans une autorisation spécifique ou une règle supplémentaire.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [Q9.1] 9. Incertitude (getattr dynamic)
**Question :** Qui peut valider une demande de remboursement de frais dans le module custom_expense_reimbursement_indirect ?

**Vérité Terrain attendue :**
> Point de contrôle dynamique (getattr/_g_q7) repéré dans action_valider mais NON CLASSIFIÉ avec certitude. Proposer pour revue manuelle avec source fichier+ligne.

**Réponse Verbatim de l'agent (11.1s) :**
```text
Désolé, mais je n'ai pas trouvé d'information sur le module "custom_expense_reimbursement_indirect" dans la base de connaissances. Il est possible qu'il s'agit d'un module personnalisé ou que le nom est incorrect.

Si vous avez besoin d'aide pour valider une demande de remboursement de frais, je serais ravi de vous aider à trouver la bonne procédure ou à vous orienter vers la bonne personne. Pour cela, pourriez-vous me fournir plus d'informations sur le contexte et le système utilisé ?

[Source: Graphe de Connaissances Code Intelligence]
```

---