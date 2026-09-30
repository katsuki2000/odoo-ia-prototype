# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-30 08:17:18

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees (consolidees) | 25 |
| Questions rejouees ce tour | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective (run courant) | `57.32s` |
| p90 latence effective (run courant) | `57.32s` (budget `12.0s`,  DEPASSE) |
| Moyenne (run courant) | `57.32s` |
| Max (run courant) | `57.32s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 26.5s | Effectif: 26.502s | Groq wait: 0.0s | Sauts: 5) :**
```text
### Accès à la fiche équipement (maintenance.equipment)

**Modification (écriture) :**  
Non, un utilisateur simple (membre de `base.group_user` sans `maintenance.group_equipment_manager`) **ne peut pas modifier** une fiche équipement. Seuls les membres du groupe « Equipment Manager » ont les droits d'écriture, de création et de suppression.

**Consultation (lecture) :**  
Un utilisateur simple **peut consulter** uniquement les équipements pour lesquels il est **suivi en tant que partenaire** (via le champ `message_partner_ids`). Cela signifie qu’il ne peut voir que les équipements associés à son profil ou à ses contacts. Les règles de visibilité restreignent automatiquement l'accès aux autres équipements.

**Exemple :**  
Si un équipement a été assigné à un contact lié à cet utilisateur, il pourra le consulter. Sinon, il ne le verra pas dans la liste.

[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : pour la permission concernée, `maintenance.group_equipment_manager` hérite de l'ACL de `base.group_user` par implication transitive (`implied_ids`). Les ACL applicables sont additives : l'absence d'une permission dans une ACL directe ne retire pas le droit accordé par une autre ACL applicable.

[FAIT DÉTERMINISTIQUE] Un utilisateur appartenant en plus au groupe `maintenance.group_equipment_manager` ('Equipment Manager') ne serait plus soumis à cette restriction : la règle 'Equipment administrator' (xml_id: maintenance.equipment_rule_admin_user) lève alors toute limitation pour ce modèle.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q2] maintenance -- workflow (hard)
**Question :** Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente (recurring_maintenance=True) atteint une etape marquee 'done' ?

**Reponse de reference (verite-terrain) :**
> MaintenanceRequest.write() detecte que stage_id change vers un stage dont done=True ; pour chaque demande de maintenance_type='preventive' avec recurring_maintenance actif, calcule une nouvelle schedule_date (date actuelle ou schedule_date existante + repeat_interval unites de repeat_unit via relativedelta), et si repeat_type=='forever' ou que la nouvelle date reste <= repeat_until, duplique automatiquement la demande (copy()) avec cette nouvelle schedule_date et la reinsere au stage par defaut (_default_stage) -- generation automatique de la prochaine occurrence, avant meme l'appel a super().write().

**A verifier dans le code :** `models/maintenance.py, classe MaintenanceRequest, methode write() (bloc verifiant request.maintenance_type != 'preventive' or not request.recurring_maintenance)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 35.4s | Effectif: 35.398s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Comportement automatique pour les demandes de maintenance préventive récurrente

Lorsqu'une demande de maintenance **préventive** et **récurrente** (recurring_maintenance=True) atteint une étape marquée comme *'done'* (terminée), le système déclenche automatiquement les actions suivantes :

1. **Création d'une nouvelle demande** :  
   Une copie de la demande actuelle est générée avec une nouvelle date de planification (schedule_date), calculée en ajoutant l'intervalle de récurrence (repeat_interval) à la date actuelle. Cette nouvelle demande est réinsérée dans l'étape par défaut (_default_stage).

2. **Conditions de déclenchement** :  
   Cette duplication n'a lieu que si :
   - La maintenance est **préventive** et **récurrente**.
   - Le type de récurrence est *'forever'* (infini) ou la nouvelle date calculée reste **inférieure ou égale** à la date limite définie (repeat_until).

3. **Mise à jour de la demande terminée** :  
   La date de fermeture (close_date) de la demande actuelle est mise à jour avec la date du jour, et l'état kanban est réinitialisé à *'normal'*.

> **Note** : Aucun follower n'est ajouté automatiquement lors de ce processus. La duplication est purement logique et ne déclenche pas de notifications par défaut.

- **Condition d’arrêt de la récurrence** : la duplication automatique n'a lieu que si la répétition est configurée sans fin (*repeat_type* = 'forever') ou si la date calculée reste antérieure ou égale à la date limite (*repeat_until*).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q3] maintenance -- inheritance (medium)
**Question :** maintenance.equipment est-il une extension d'un modele natif Odoo existant, ou un nouveau modele ? Quel role joue maintenance.mixin dont il herite ?

**Reponse de reference (verite-terrain) :**
> Nouveau modele (_name='maintenance.equipment') -- il n'etend aucun modele metier preexistant, il herite seulement de mixins : mail.thread, mail.activity.mixin, et maintenance.mixin. maintenance.mixin est un AbstractModel qui factorise les champs/calculs communs de suivi de maintenance (maintenance_team_id, technician_user_id, mtbf/mttr/estimated_next_failure via _compute_maintenance_request, maintenance_count), destine a etre reutilise par tout modele 'maintenable' qui l'inclut dans son _inherit -- dans ce module, seul maintenance.equipment l'utilise ; maintenance.equipment.category, elle, n'en herite pas (seulement mail.alias.mixin/mail.thread).

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceMixin (_name='maintenance.mixin', models.AbstractModel) + classe MaintenanceEquipment (_inherit=['mail.thread','mail.activity.mixin','maintenance.mixin']) vs classe MaintenanceEquipmentCategory (_inherit=['mail.alias.mixin','mail.thread'], sans maintenance.mixin)`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code', 'trace_full_inheritance']

**Reponse verbatim de l'agent (Total: 37.9s | Effectif: 37.898s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Analyse du modèle `maintenance.equipment`

Le modèle `maintenance.equipment` est un **nouveau modèle** déclaré dans le module `maintenance`. Il ne s'agit pas d'une extension d'un modèle natif Odoo existant, mais d'un modèle original qui utilise des **mixins techniques** pour hériter de fonctionnalités partagées.

#### Rôle de `maintenance.mixin`
Le mixin `maintenance.mixin` fournit des **champs et méthodes communs** liés à la gestion de la maintenance, notamment :
- **Champs partagés** : `company_id`, `effective_date`, `estimated_next_failure`, `maintenance_count`, `technician_user_id`, etc.
- **Méthodes de calcul** : `_compute_maintenance_count`, `_compute_maintenance_request`, `_compute_maintenance_team_id`.

Ce mixin est réutilisé par `maintenance.equipment` pour éviter la duplication de code et centraliser les logiques de suivi des interventions, des dates de maintenance, et des statistiques associées.

#### Héritage technique
`maintenance.equipment` hérite de :
- `mail.thread` (pour les fonctionnalités de suivi d'activité et de discussion),
- `mail.activity.mixin` (pour la gestion des activités),
- `maintenance.mixin` (pour les données et calculs spécifiques à la maintenance).

Ainsi, il combine des **fonctionnalités techniques** (messagerie, suivi) avec des **logiques métier** (maintenance) via le mixin.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q4] maintenance -- ui (easy)
**Question :** Pourquoi le champ 'cost' (cout) d'un equipement n'est-il pas visible pour tous les utilisateurs ayant acces en lecture a sa fiche ?

**Reponse de reference (verite-terrain) :**
> Le champ cost porte groups='maintenance.group_equipment_manager' dans la vue formulaire -- reserve aux managers, independamment du droit de lecture sur la fiche elle-meme : un utilisateur simple qui suit un equipement (et le voit donc via equipment_rule_user) ne voit pas ce champ precis dans le formulaire.

**A verifier dans le code :** `views/maintenance_views.xml, <field name="cost" groups="maintenance.group_equipment_manager"/>`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 26.73s | Effectif: 26.73s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Raisons de l'absence de visibilité du champ 'cost'

Le champ **'cost'** (Cout) est uniquement visible pour les membres du groupe **« Equipment Manager »** (xml_id: `maintenance.group_equipment_manager`). Cette restriction est définie directement dans la déclaration du champ dans la vue **'hr_equipment_view_form'** du modèle **`maintenance.equipment`** via l'attribut `groups="maintenance.group_equipment_manager"`.

Même si un utilisateur a un accès en lecture à la fiche de l'équipement, la visibilité du champ **'cost'** dépend de l'appartenance au groupe **« Equipment Manager »**. Les utilisateurs n'appartenant pas à ce groupe ne verront pas ce champ, indépendamment de leurs droits généraux sur le modèle.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q5] maintenance -- constraints (medium)
**Question :** Quelle regle empeche de creer deux equipements avec le meme numero de serie, et quelle contrainte distincte s'applique sur l'intervalle de repetition (repeat_interval) d'une demande recurrente ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts et independants : (1) sur maintenance.equipment, _sql_constraints=[('serial_no','unique(serial_no)', ...)] -- contrainte SQL native (pas @api.constrains) bloquant un second equipement avec le meme serial_no au niveau base de donnees. (2) sur maintenance.request, _check_repeat_interval (@api.constrains('repeat_interval')) leve une ValidationError Python si repeat_interval < 1 -- verifiee a l'ecriture ORM, pas au niveau SQL.

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceEquipment, attribut _sql_constraints ; classe MaintenanceRequest, methode _check_repeat_interval`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 51.27s | Effectif: 51.272s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Contraintes sur les équipements et les demandes récurrentes

1. **Empêchement de créer deux équipements avec le même numéro de série**  
   La contrainte est définie dans le modèle `maintenance.equipment` via une contrainte SQL unique sur le champ `serial_no`. Cette règle empêche la création de deux équipements avec le même numéro de série.  
   *Source :* `_sql_constraints = [('serial_no', 'unique(serial_no)', "Another asset already exists with this serial number!")]` [maintenance.py:L171-L173](file:///home/user/odoo-17.0/addons/maintenance/models/maintenance.py#L171-L173).

2. **Contrainte sur l'intervalle de répétition (repeat_interval)**  
   Pour les demandes récurrentes (`maintenance.request`), le champ `repeat_interval` est soumis à une validation via l'annotation `@api.constrains`. Cette contrainte exige que l'intervalle de répétition soit supérieur ou égal à 1.  
   *Source :*  
   ```
 280 |     @api.constrains('repeat_interval')
 281 |     def _check_repeat_interval(self):
 282 |         for record in self:
 283 |             if record.repeat_interval < 1:
 284 |                 raise ValidationError("Repeat Interval cannot be less than 1.")
```  
   [maintenance.py:L280-L284](file:///home/user/odoo-17.0/addons/maintenance/models/maintenance.py#L280-L284).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'button_execution_path', 'read_source_code', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 53.81s | Effectif: 53.809s | Groq wait: 0.0s | Sauts: 10) :**
```text
### Différences réelles entre un acheteur et un manager sur une commande d'achat

Bien que les groupes **group_purchase_user** et **group_purchase_manager** aient les mêmes droits d'accès (lecture, écriture, création, suppression) sur le modèle **purchase.order**, leur rôle diffère dans les **actions spécifiques** qu'ils peuvent déclencher et les **états** qu'ils peuvent modifier :

---

#### 1. **Accès aux boutons critiques**
- **Un manager** (groupe **group_purchase_manager**) peut :
  - **Déverrouiller** une commande d'achat en état **[done]** via le bouton **"Unlock"** (méthode `button_unlock()`). Cela permet de la ramener à l'état **[purchase]** pour des modifications ultérieures.
  - **Ignorer les validations doubles** (si configuré) grâce à la méthode `_approval_allowed()`, ce qui permet d'approbater directement une commande sans passer par une étape intermédiaire.

- **Un acheteur** (groupe **group_purchase_user**) **n’a pas accès** au bouton **"Unlock"** et **ne peut pas déverrouiller** une commande en état **[done]**. Il est également **bloqué** par les règles de validation double si le montant dépasse le seuil configuré et qu’il n’est pas membre du groupe **group_purchase_manager**.

---

#### 2. **Contrôle des états avancés**
- Précision déterministe : le chemin de `button_execution_path` pour `confirm_reminder_mail()` indique les groupes requis `base.group_no_one ('Technical Features')` ; il ne permet pas d'attribuer cette action au groupe manager sans preuve supplémentaire.
- Les acheteurs sont **limités** aux transitions standard (ex. : **[draft]** → **[sent]** → **[purchase]**), sans possibilité de modifier des états verrouillés.

---

#### 3. **Validation des approbations**
- Les managers **bifrontent** le processus de validation : ils peuvent **valider directement** une commande (même si le seuil de validation double est activé), tandis que les acheteurs doivent **attendre une approbation** supplémentaire.

---

### En résumé
Le groupe **group_purchase_manager** a des **privilèges opérationnels supplémentaires** (déverrouillage, validation directe, accès à des états avancés), alors que **group_purchase_user** est limité aux actions de base. Ces différences ne sont pas reflétées dans les ACLs, mais dans les **méthodes Python** et les **règles de workflow**.

[FAIT DÉTERMINISTIQUE] Le garde applicatif `_approval_allowed()` autorise l'approbation si au moins une des conditions suivantes est vraie : `po_double_validation == 'one_step'`; `po_double_validation == 'two_step'` avec un montant total inférieur au seuil configuré `po_double_validation_amount`; l'appartenance au groupe `purchase.group_purchase_manager`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q2] purchase -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on clique sur 'Confirm Order' (button_confirm) selon que la commande est eligible ou non a l'approbation directe ?

**Reponse de reference (verite-terrain) :**
> button_confirm() ne s'applique qu'aux commandes en etat 'draft' ou 'sent' (les autres sont ignorees silencieusement) ; il valide d'abord la distribution analytique des lignes et ajoute le fournisseur au produit, puis appelle _approval_allowed() : si vrai, delegue a button_approve() qui passe directement l'etat a 'purchase' (et a 'done' si po_lock=='lock') ; si faux, l'etat passe seulement a 'to approve' -- en attente qu'un manager declenche explicitement button_approve() via le bouton dedie.

**A verifier dans le code :** `models/purchase_order.py : button_confirm(), button_approve()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 417.04s | Effectif: 414.044s | Groq wait: 3.0s | Sauts: 7) :**
```text
Lorsque l'utilisateur clique sur le bouton **'Confirm Order'** (button_confirm) dans un ordre d'achat (**purchase.order**), le comportement dépend de l'éligibilité de la commande à l'approbation directe :

1. **Cas où la commande est éligible à l'approbation directe** :  
   - La commande passe immédiatement de l'état **[draft, sent]** à **'purchase'**, puis à **'done'** si la configuration de l'entreprise le permet (par exemple, si le seuil de validation double est dépassé ou si le gestionnaire d'achats est associé).  
   - Cela se produit si :  
     - La validation double est configurée en **'one_step'** (aucun seuil ni approbation supplémentaire requise),  
     - Ou si le montant total de la commande est inférieur au seuil défini pour la validation double (**'two_step'**),  
     - Ou si l'utilisateur appartient au groupe **"purchase.group_purchase_manager"** (gestionnaire d'achats).  

2. **Cas où la commande n'est pas éligible à l'approbation directe** :  
   - La commande passe de l'état **[draft, sent]** à **'to approve'**, en attente d'une approbation supplémentaire par un utilisateur habilité (par exemple, un gestionnaire d'achats ou un responsable selon la configuration).  
   - Cela se produit si :  
     - La validation double est configurée en **'two_step'** et le montant total de la commande dépasse le seuil défini,  
     - Et l'utilisateur n'appartient pas au groupe **"purchase.group_purchase_manager"**.  

Dans les deux cas, des actions supplémentaires peuvent être déclenchées, comme l'ajout du fournisseur aux informations du produit ou la notification du partenaire. L'état final dépend de la configuration de l'entreprise et des droits de l'utilisateur.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q3] purchase -- inheritance (medium)
**Question :** purchase.order est-il un nouveau modele ou une extension ? Le module purchase modifie-t-il en parallele un modele natif deja existant hors de son propre domaine (achat), et comment ?

**Reponse de reference (verite-terrain) :**
> purchase.order (_name='purchase.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin), pas d'un modele metier preexistant. En parallele, ce meme module etend reellement account.move (_inherit='account.move', classe AccountMove dans account_invoice.py) en surchargeant create() et write() pour poster un message de tracabilite ('cree depuis'/'modifie depuis') des que les lignes de facture referencent une purchase.order.line -- une extension transverse comptabilite, distincte du modele purchase.order lui-meme.

**A verifier dans le code :** `models/purchase_order.py : classe PurchaseOrder (_name + _inherit mixins) vs models/account_invoice.py : classe AccountMove (_inherit='account.move'), methodes create()/write()`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 29.54s | Effectif: 29.544s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Statut du modèle 'purchase.order' et extensions hors périmètre

Le modèle **'purchase.order'** est un **nouveau modèle** déclaré par le module *purchase*, ne s'appuyant que sur des mixins techniques (comme `mail.thread` ou `portal.mixin`) et ne modifiant pas un modèle métier existant.

Cependant, le module *purchase* étend **d'autres modèles natifs en dehors de son propre domaine** (comme *achat*), notamment :

- **`account.move`** (modèle de facturation/comptabilité) : 
  - Ajout de champs comme `purchase_order_count`, `purchase_id`.
  - Surcharges de méthodes pour gérer les liens avec les commandes d'achat.

- **`product.product`** (modèle de gestion des produits) :
  - Ajout de champs comme `purchased_product_qty`.
  - Surcharges de méthodes pour afficher les commandes d'achat liées.

Ces extensions permettent au module *purchase* d'interagir avec des domaines comme la comptabilité ou la gestion des produits, malgré ne pas en faire partie directement.

À noter : ce module étend bien 11 modèle(s) hors de son propre périmètre : 'account.analytic.account', 'account.analytic.applicability', 'account.move', 'account.move.line', 'account.tax', 'product.packaging', 'product.product', 'product.supplierinfo', 'product.template', 'res.company', 'res.partner'.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q4] purchase -- ui (easy)
**Question :** Pourquoi le bouton 'Approve Order' n'est-il pas visible pour un utilisateur simple meme quand la commande est au statut 'to approve' ?

**Reponse de reference (verite-terrain) :**
> Le bouton button_approve porte groups='purchase.group_purchase_manager' dans la vue formulaire -- masque pour tout utilisateur hors de ce groupe, independamment de son invisible= conditionnel sur l'etat (invisible='state != "to approve"'). C'est la manifestation UI directe du garde applicatif _approval_allowed() (PUR-Q1/Q2) : le bouton n'existe que pour les managers, alors qu'un simple acheteur ne voit que 'Confirm Order'.

**A verifier dans le code :** `views/purchase_views.xml, bouton name='button_approve', groups='purchase.group_purchase_manager'`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 43.6s | Effectif: 43.601s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Raisons de l'absence du bouton 'Approve Order'

Le bouton 'Approve Order' n'est pas visible pour un utilisateur simple, même si la commande est au statut 'to approve', pour deux raisons principales :

1. **Restriction de groupe** : Le bouton est uniquement disponible pour les membres du groupe « Administrator » (groupe technique : `purchase.group_purchase_manager`). Cet utilisateur ne fait pas partie de ce groupe, ce qui rend le bouton invisible dans l'interface, indépendamment du statut de la commande.

2. **Condition de visibilité** : Bien que le statut 'to approve' devrait théoriquement rendre le bouton visible, une erreur dans la logique de visibilité (`invisible='state != 'to approve''`) pourrait également contribuer à ce comportement. Cependant, cette condition est secondaire par rapport à la restriction de groupe.

Pour valider ou approuver une commande, seuls les utilisateurs du groupe « Administrator » ont accès à cette fonctionnalité.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q5] purchase -- constraints (medium)
**Question :** Quelles regles empechent de supprimer une commande d'achat ou une de ses lignes selon leur etat, et quelle contrainte SQL distincte s'applique sur les lignes elles-memes ?

**Reponse de reference (verite-terrain) :**
> Deux gardes @api.ondelete(at_uninstall=False) distincts : _unlink_if_cancelled sur purchase.order leve UserError si l'etat n'est pas 'cancel' (impossible de supprimer une commande active, il faut d'abord l'annuler) ; _unlink_except_purchase_or_done sur purchase.order.line leve UserError si la commande parente est en etat 'purchase' ou 'done'. Independamment, _sql_constraints sur purchase.order.line impose par CHECK SQL que les champs comptables (product_id/product_uom/date_planned) soient tous renseignes pour une ligne 'accountable' (display_type NULL) et tous vides pour une ligne section/note (display_type non NULL) -- integrite structurelle, pas une regle de suppression.

**A verifier dans le code :** `models/purchase_order.py : _unlink_if_cancelled (@api.ondelete) ; models/purchase_order_line.py : _unlink_except_purchase_or_done (@api.ondelete) + _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_security_locks', 'analyze_security_locks', 'analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 57.32s | Effectif: 57.318s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Règles d'empêchement de suppression selon l'état

**Pour les commandes d'achat :**  
La suppression d'une commande est interdite si elle n'est pas dans l'état **"Annulée"**. Un message d'erreur indique :  
*"In order to delete a purchase order, you must cancel it first."*  
Cela signifie que seule une commande annulée peut être supprimée.

**Pour les lignes de commande :**  
Les lignes en état **"Achat"** ou **"Terminée"** ne peuvent pas être supprimées. Le système affiche le message :  
*"Cannot delete a purchase order line which is in state %r."*  
Cela empêche la suppression des lignes tant qu'elles ne sont pas dans un état compatible (par exemple, "Brouillon").

---

### Contrainte SQL distincte sur les lignes de commande

Cette contrainte empêche l'enregistrement de lignes incomplètes ou incohérentes dans la base de données.

Précision issue de la preuve SQL :
- Selon la preuve SQL, lorsque `display_type IS NULL`, la condition `product_id IS NOT NULL AND product_uom IS NOT NULL AND date_planned IS NOT NULL` doit être vraie.
- Selon la preuve SQL, lorsque `display_type IS NOT NULL`, la condition `product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL AND date_planned is NULL` doit être vraie.
- Les branches sont indépendantes : ne pas appliquer les champs ou opérateurs d'une branche à l'autre. Les prédicats SQL exacts ci-dessus prévalent sur toute paraphrase générale.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q1] sale -- security (hard)
**Question :** Un vendeur (sales_team.group_sale_salesman, sans group_sale_salesman_all_leads) peut-il voir toutes les commandes de vente de son entreprise, ou seulement certaines ? Et un utilisateur du portail (base.group_portal) ?

**Reponse de reference (verite-terrain) :**
> Non pour le vendeur simple : l'ACL access_sale_order lui donne perm_read/write/create=1 (pas perm_unlink), mais l'ir.rule sale_order_personal_rule le restreint aux commandes ou user_id lui est assigne ou user_id est vide (domaine OR) ; seul un vendeur avec en plus group_sale_salesman_all_leads herite de sale_order_see_all (domaine (1,'=',1), tout voir). Pour le portail : ACL access_sale_order_portal en lecture seule (perm_read=1, tout le reste 0), combinee a sale_order_rule_portal qui restreint aux commandes ou le partenaire (ou un enfant commercial) figure dans message_partner_ids -- avec ici perm_write/perm_unlink actives via la regle elle-meme (perm_write=True, perm_unlink=True dans la regle), ce qui autorise l'ecriture/suppression via la regle malgre l'ACL en lecture seule, en pratique borne au flux portail (ex. wizard d'annulation).

**A verifier dans le code :** `security/ir.model.access.csv (access_sale_order, access_sale_order_portal) + security/ir_rules.xml (sale_order_personal_rule, sale_order_see_all, sale_order_rule_portal)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 33.77s | Effectif: 33.765s | Groq wait: 0.0s | Sauts: 10) :**
```text
### Accès aux commandes de vente

#### Vendeur (sales_team.group_sale_salesman, sans sales_team.group_sale_salesman_all_leads)
Le vendeur **ne peut voir que ses propres commandes de vente** (celles où il est indiqué comme responsable ou associé) et **non toutes les commandes de son entreprise**. Cette restriction est imposée par la règle d'accès *Personal Orders* qui limite la visibilité aux documents liés à l'utilisateur ou à des enregistrements sans utilisateur associé.

#### Utilisateur du portail (base.group_portal)
L'utilisateur du portail **ne peut voir que les commandes de vente liées à ses partenaires commerciaux** (via le champ `message_partner_ids`). Il **n'a pas accès aux commandes générales de l'entreprise** ou à celles qui ne lui sont pas directement associées. Cette limitation est définie par la règle *Portal Personal Quotations/Sales Orders*.

### Résumé
- **Vendeur** : Accès restreint à ses propres commandes.
- **Utilisateur du portail** : Accès restreint aux commandes liées à ses partenaires.

[FAIT DÉTERMINISTIQUE] Un utilisateur appartenant en plus au groupe `sales_team.group_sale_salesman_all_leads` ('User: All Documents') ne serait plus soumis à cette restriction : la règle 'All Orders' (xml_id: sale.sale_order_see_all) lève alors toute limitation pour ce modèle.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q2] sale -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on confirme une commande de vente (action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) juste apres ?

**Reponse de reference (verite-terrain) :**
> action_confirm() verifie d'abord que toutes les commandes sont en etat 'draft' ou 'sent' (_can_be_confirmed()), sinon UserError ; valide la distribution analytique des lignes, souscrit le client aux notifications, ecrit state='sale' + date_order=now (_prepare_confirmation_values), puis appelle _action_confirm() (cree un compte analytique si une ligne porte un produit avec expense_policy actif). Immediatement apres, filtre les commandes via _should_be_locked() -- qui verifie has_group('sale.group_auto_done_setting') sur le createur de la commande (pas l'utilisateur courant) -- et appelle action_lock() (locked=True) sur celles-la uniquement ; ce n'est donc pas systematique, ca depend d'un parametrage (groupe) rattache au createur de la commande, pas de l'utilisateur qui confirme.

**A verifier dans le code :** `models/sale_order.py : action_confirm(), _should_be_locked(), _can_be_confirmed(), _action_confirm()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 38.48s | Effectif: 38.48s | Groq wait: 0.0s | Sauts: 9) :**
```text
### Confirmation d'une commande de vente et verrouillage automatique

Lorsque vous confirmez une commande de vente (via le bouton **"Confirm"**), les étapes suivantes sont exécutées :

1. **Validation préalable** : Le système vérifie que la commande est bien dans un état permettant la confirmation (brouillon ou envoyée).
2. **Mise à jour des taxes** : Les taxes associées à la commande sont recalculées (même si cette opération ne modifie rien dans ce module).
3. **Soucription du partenaire** : Le partenaire client est ajouté aux destinataires des messages liés à la commande.
4. **Mise à jour de l'état** : La commande passe de l'état **"draft"** ou **"sent"** à **"sale"** (état confirmé).
5. **Verrouillage éventuel** : Si l'utilisateur qui a créé la commande appartient au groupe **"Lock Confirmed Sales"** (paramètre de configuration du module), la commande est verrouillée automatiquement après confirmation.

[FAIT DÉTERMINISTIQUE -- VERROUILLAGE APRÈS CONFIRMATION] Après `action_confirm()`, seules les commandes dont le créateur satisfait `_should_be_locked()` sont verrouillées par `action_lock()` (`locked=True`). Le garde vérifie `create_uid.has_group('sale.group_auto_done_setting')` : le verrouillage n'est donc pas systématique et dépend du groupe du créateur de la commande, pas de l'utilisateur qui confirme.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q3] sale -- inheritance (medium)
**Question :** sale.order est-il un nouveau modele ou une extension ? Quel modele natif hors du perimetre 'vente' ce module etend-il directement, et sous quel nom de classe ?

**Reponse de reference (verite-terrain) :**
> sale.order (_name='sale.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin, utm.mixin), aucun modele metier preexistant. En parallele, ce meme module etend reellement account.move (classe AccountMove, _inherit=['account.move', 'utm.mixin'] dans models/account_move.py) -- une extension transverse comptabilite comparable au constat fait sur purchase (PUR-Q3), meme modele cible (account.move), module different.

**A verifier dans le code :** `models/sale_order.py : classe SaleOrder (_name='sale.order', _inherit=[mixins]) vs models/account_move.py : classe AccountMove (_inherit=['account.move','utm.mixin'])`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code', 'list_involved_modules']

**Reponse verbatim de l'agent (Total: 43.03s | Effectif: 43.026s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Statut du modèle 'sale.order' et extensions hors périmètre

Le modèle **'sale.order'** est un **nouveau modèle** déclaré par le module 'sale', ne s'appuyant pas sur un modèle métier existant mais uniquement sur des mixins techniques (comme `mail.thread` ou `utm.mixin`).

---

### Extensions hors périmètre 'vente' par le module 'sale'

Le module 'sale' étend directement les modèles natifs suivants, en dehors de son propre périmètre métier :

1. **Modèle 'account.move'**  
   - **Classe Python** : `AccountMove` dans `models/account_move.py`  
   - **Champs ajoutés** : `sale_order_count`, `campaign_id`, `medium_id`, `source_id`, `team_id`  
   - **Méthodes surchargées** : `_compute_origin_so_count`, `unlink`, `_action_invoice_ready_to_be_sent`, etc.

2. **Modèle 'account.move.line'**  
   - **Classe Python** : `AccountMoveLine` dans `models/account_move_line.py`  
   - **Champs ajoutés** : `is_downpayment`, `sale_line_ids`  
   - **Méthodes surchargées** : `_copy_data_extend_business_fields`, `_sale_create_reinvoice_sale_line`, etc.

3. **Modèle 'product.product'**  
   - **Classe Python** : `ProductProduct` dans `models/product_product.py`  
   - **Champs ajoutés** : `sales_count`, `product_catalog_product_is_in_sale_order`  
   - **Méthodes surchargées** : `_compute_sales_count`, `_filter_to_unlink`, etc.

4. **Modèle 'product.template'**  
   - **Classe Python** : `ProductTemplate` dans `models/product_template.py`  
   - **Champs ajoutés** : `sales_count`, `expense_policy`, `invoice_policy`  
   - **Méthodes surchargées** : `_compute_invoice_policy`, `_check_incompatible_types`, etc.

5. **Modèle 'account.payment.register'**  
   - **Classe Python** : `AccountPaymentRegister` dans `wizard/account_payment_register.py`  
   - **Méthodes surchargées** : `_create_payment_vals_from_wizard`

- Nom de classe Python étendant 'account.move' : `AccountMove` (dans `models/account_move.py`).

Précision issue de la preuve SQL :
- Selon la preuve SQL, lorsque `state = 'sale' AND date_order IS NULL`, la condition `state != 'sale'` doit être vraie.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q4] sale -- ui (easy)
**Question :** Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) une commande verrouillee, meme si c'est lui qui l'a confirmee ?

**Reponse de reference (verite-terrain) :**
> Le bouton action_unlock porte groups='sales_team.group_sale_manager' dans la vue formulaire -- reserve aux managers, quel que soit le lien du vendeur avec la commande (createur, assigne via user_id, etc.). Le bouton n'est meme visible (invisible="not locked") que si la commande est deja verrouillee, mais son affichage reste conditionne au groupe manager en plus de cette condition d'etat. Le bouton action_lock, lui, n'est visible que si le parametrage sale.group_auto_done_setting est actif (t groups=), et porte la meme restriction sales_team.group_sale_manager.

**A verifier dans le code :** `views/sale_order_views.xml : boutons action_unlock (groups='sales_team.group_sale_manager', invisible='not locked') et action_lock (dans <t groups='sale.group_auto_done_setting'>, lui-meme groups='sales_team.group_sale_manager')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 39.52s | Effectif: 39.515s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Raisons du verrouillage de la commande

Le verrouillage d'une commande est une mesure de sécurité qui empêche toute modification non autorisée, même par le vendeur qui l’a confirmée. Voici les raisons principales :

1. **Restriction de groupe pour l'action "Déverrouiller"**  
   L'action "Déverrouiller" est strictement réservée aux membres du groupe **« Administrateur »** (groupe `sales_team.group_sale_manager`). Ce groupe est généralement limité aux responsables commerciaux ou à la direction, et **non aux vendeurs simples**. Même si le vendeur a confirmé la commande, il n’a pas les droits nécessaires pour la déverrouiller.

2. **Sécurité des états et transitions**  
   Une commande verrouillée est souvent associée à un état critique (ex. : "Validée", "En attente de paiement"). Les règles de workflow empêchent les modifications tant que l’état ne correspond pas à un point autorisé pour le déverrouillage (ex. : "Brouillon" ou "Modifiable").

3. **Prévention des erreurs ou fraudes**  
   Le verrouillage évite les changements accidentels ou malveillants après la confirmation. Seul un administrateur peut déverrouiller, assurant ainsi une validation supplémentaire avant toute modification.

### Que faire ?
Pour déverrouiller une commande, **contactez un administrateur ou un responsable commercial**. Ils pourront utiliser l’action "Déverrouiller" via l’interface (bouton visible uniquement pour leur groupe) ou via un script technique si nécessaire.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q5] sale -- constraints (medium)
**Question :** Quelle contrainte empeche une commande confirmee de ne pas avoir de date de confirmation, et quelle contrainte distincte s'applique sur le pourcentage d'acompte demande (prepayment_percent) ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts : (1) sur sale.order, _sql_constraints porte date_order_conditional_required -- contrainte SQL CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale'), bloquant au niveau base de donnees toute commande a l'etat 'sale' sans date_order renseignee. (2) _check_prepayment_percent (@api.constrains('prepayment_percent')) leve une ValidationError Python si require_payment est actif et que prepayment_percent n'est pas strictement compris entre 0 (exclu) et 1.0 (inclus) -- verifiee a l'ecriture ORM, pas au niveau SQL. Independamment, sale.order.line porte ses propres contraintes SQL structurelles (accountable_required_fields/non_accountable_null_fields) sur le meme modele que purchase.order.line (PUR-Q5), meme logique display_type NULL/non-NULL.

**A verifier dans le code :** `models/sale_order.py : _sql_constraints (date_order_conditional_required), _check_prepayment_percent (@api.constrains) ; models/sale_order_line.py : _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 43.48s | Effectif: 43.476s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Contraintes sur les commandes confirmées

1. **Contrainte de date de confirmation**  
   Une commande confirmée (état `'sale'`) doit obligatoirement avoir une date de confirmation (`date_order`). Cette règle est définie au niveau de la base de données via une contrainte SQL. Si une commande est confirmée sans date, le système bloque l'opération et affiche le message :  
   *"A confirmed sales order requires a confirmation date."*

2. **Contrainte sur le pourcentage d'acompte**  
   Le pourcentage d'acompte demandé (`prepayment_percent`) est soumis à une validation distincte. Il doit être strictement compris entre **0 %** et **100 %** (inclus). Si la valeur est en dehors de cette fourchette, le système génère une erreur avec le message :  
   *"Prepayment percentage must be a valid percentage."*  
   Cette contrainte s'applique uniquement si la commande nécessite un paiement anticipé (`require_payment` est activé).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q1] stock -- security (hard)
**Question :** Un simple employe (base.group_user, sans stock.group_stock_user) peut-il consulter les quantites en stock (stock.quant) ? Et peut-il modifier une ligne de mouvement (stock.move.line) ?

**Reponse de reference (verite-terrain) :**
> Oui pour la consultation : access_stock_quant_all accorde perm_read=1 (lecture seule) a base.group_user meme sans stock.group_stock_user -- les niveaux de stock sont visibles a tout employe, seule l'ecriture/creation/suppression exige stock.group_stock_user (access_stock_quant_user, perm_unlink=0 meme pour ce groupe). Plus surprenant : sur stock.move.line, base.group_user a directement les 4 permissions completes (access_stock_move_line_all, 1,1,1,1) -- un acces plus large que sur stock.move lui-meme, qui exige stock.group_stock_user (et reste perm_unlink=0 pour ce groupe). Aucune de ces ACL n'est affinee par ir.rule au-dela du filtrage multi-societe (stock_quant_rule, stock_move_line_rule) -- pas de restriction par entrepot ou par role.

**A verifier dans le code :** `security/ir.model.access.csv (access_stock_quant_all, access_stock_quant_user, access_stock_move_user, access_stock_move_line_all) + security/stock_security.xml (stock_quant_rule, stock_move_line_rule, filtrage company_id uniquement)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 48.53s | Effectif: 48.524s | Groq wait: 0.0s | Sauts: 6) :**
```text
### Accès à la consultation des quantités en stock (stock.quant)

Le simple employé (groupe **base.group_user**) **peut consulter** les quantités en stock via le modèle **stock.quant**. Cette accès est autorisé par défaut pour tous les utilisateurs internes (groupe **base.group_user**), sans restriction supplémentaire liée à des règles de groupe ou de champ.

---

### Accès à la modification des lignes de mouvement (stock.move.line)

Le simple employé (groupe **base.group_user**) **peut modifier** les lignes de mouvement (modèle **stock.move.line**). L'accès en écriture (WRITE) est explicitement accordé au groupe **base.group_user** dans la matrice des droits d'accès, sans restriction supplémentaire provenant des règles de groupe ou de champ. Aucune condition supplémentaire (comme l'appartenance au groupe **stock.group_stock_user**) n'est requise pour cette action.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q2] stock -- workflow (hard)
**Question :** Que se passe-t-il quand on valide un transfert de stock (button_validate) dont les quantites traitees sont inferieures aux quantites demandees ?

**Reponse de reference (verite-terrain) :**
> button_validate() ignore les transferts deja 'done', confirme automatiquement ceux encore en 'draft', puis complete a la quantite demandee toute ligne dont la quantite traitee est nulle. Une verification de coherence (_sanity_check) s'execute ensuite sauf contexte skip_sanity_check. _pre_action_done_hook() marque picked=True des que des quantites existent. Vient ensuite la decision cle : les transferts sont scindes entre ceux dont picking_type_id.create_backorder=='never' (jamais de reliquat, executes avec cancel_backorder=True) et les autres (executes normalement, create_backorder='always' ou 'ask') -- c'est ce parametre du type d'operation, pas une valeur globale, qui determine si un bon de livraison partiel genere automatiquement un reliquat (backorder) pour les quantites restantes.

**A verifier dans le code :** `models/stock_picking.py : button_validate(), _pre_action_done_hook(), champ picking_type_id.create_backorder (stock_picking_type.py)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 80.56s | Effectif: 80.562s | Groq wait: 0.0s | Sauts: 10) :**
```text
### Conséquences de la validation partielle d'un transfert de stock

Lorsqu'on valide un transfert de stock (`button_validate`) avec des quantités traitées inférieures aux quantités demandées, le système déclenche une **création de backorder** (commande de rappel) pour les quantités restantes. Voici le déroulement détaillé :

1. **Vérification des quantités** :  
   La méthode `_sanity_check` vérifie que des quantités ont bien été traitées. Si aucune quantité n'est traitée, une erreur est levée :  
   > *"You can’t validate an empty transfer. Please add some products to move before proceeding."*

2. **Détection des quantités restantes** :  

3. **Gestion des backorders** :  
   - Si le type est configuré pour **toujours créer une backorder** (`always`), le système génère automatiquement le transfert de rappel.  
   - Si le type est configuré pour **jamais créer de backorder** (`never`), les quantités restantes sont annulées sans création de transfert.

4. **Validation finale** :  
   Après traitement, le transfert initial passe à l’état *done* et le backorder (si créé) est enregistré dans le système.

### Cas particulier
Si le transfert est marqué comme *done* ou *cancelled*, toute tentative de modification de la date ou des quantités déclenche une erreur :  
> *"You cannot change the Scheduled Date on a done or cancelled transfer."*

[FAIT DÉTERMINISTIQUE -- POLITIQUE DE RELIQUAT] La validation partielle ne crée pas toujours automatiquement un reliquat : `picking_type_id.create_backorder` détermine le comportement. `never` annule le reliquat ; `always` l'exécute avec création automatique d'un backorder ; `ask` laisse la décision à l'assistant de confirmation.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code', 'button_execution_path']

**Reponse verbatim de l'agent (Total: 47.7s | Effectif: 47.699s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Nature du modèle 'stock.picking'

Le modèle **'stock.picking'** est un **nouveau modèle** déclaré dans le module **'stock'**, avec ses propres champs et méthodes. Il ne s'agit pas d'une extension d'un autre modèle métier existant, mais d'un modèle original qui intègre uniquement des mixins techniques (`mail.thread`, `mail.activity.mixin`).

---

### Extensions du module 'stock' hors de son périmètre

Le module **'stock'** étend plusieurs modèles natifs en dehors de son propre périmètre, notamment :

#### 1. **Modèle 'product.product'**
- **Champs ajoutés** :
  - `free_qty`
  - `incoming_qty`
  - `outgoing_qty`
  - `qty_available`
  - `reordering_max_qty`
  - `reordering_min_qty`

#### 2. **Modèle 'product.template'**
- **Champs ajoutés** :
  - `has_available_route_ids`
  - `incoming_qty`
  - `outgoing_qty`
  - `qty_available`
  - `reordering_max_qty`
  - `reordering_min_qty`

#### 3. **Modèle 'product.category'**
- **Champs ajoutés** :
  - `filter_for_stock_putaway_rule`
  - `packaging_reserve_method`
  - `putaway_rule_ids`
  - `removal_strategy_id`
  - `route_ids`
  - `total_route_ids`

#### 4. **Modèle 'product.packaging'**
- **Champs ajoutés** :
  - `package_type_id`
  - `route_ids`

---

### Conclusion

- **'stock.picking'** est un modèle original, non une extension.
- Le module **'stock'** étend plusieurs modèles natifs en dehors de son périmètre, notamment **'product.product'**, **'product.template'**, **'product.category'**, et **'product.packaging'**, avec des champs clés liés à la gestion des stocks, des routes, et des règles de gestion des emplacements.

- Champs clés ajoutés au modèle 'product.product' : `free_qty`, `incoming_qty`, `outgoing_qty`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q4] stock -- ui (medium)
**Question :** Pourquoi les champs 'From'/'To' (emplacement source/destination) n'apparaissent-ils pas sur un transfert de stock pour la plupart des utilisateurs ?

**Reponse de reference (verite-terrain) :**
> Ces champs portent groups='stock.group_stock_multi_locations' dans la vue -- mais ce n'est pas un groupe de role (comme user/manager), c'est un groupe active par un parametre de configuration (implied_group sur le champ booleen group_stock_multi_locations dans res.config.settings, 'Storage Locations'). Tant que la fonctionnalite multi-emplacements n'est pas activee en configuration, aucun utilisateur -- meme stock.group_stock_manager -- ne voit ces champs, car le groupe technique lui-meme n'est attribue a personne.

**A verifier dans le code :** `views/stock_picking_views.xml : champs location_id/location_dest_id groups='stock.group_stock_multi_locations' + models/res_config_settings.py : champ group_stock_multi_locations (implied_group='stock.group_stock_multi_locations')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 33.19s | Effectif: 33.187s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Raisons de l'absence des champs 'From'/'To' sur les transferts de stock

Les champs **'From' (emplacement source)** et **'To' (emplacement destination)** ne sont visibles que si la fonctionnalité **"Gestion de plusieurs emplacements de stock"** est activée dans les **Paramètres du module Stock**. Cette activation permet de rendre le groupe technique **« Manage Multiple Stock Locations »** disponible.

Cependant, **par défaut, ce groupe n'est attribué à aucun utilisateur**. Seuls les utilisateurs appartenant explicitement à ce groupe (défini dans les **Rôles et groupes** d'Odoo) peuvent voir ces champs. Comme cette fonctionnalité n'est pas activée par défaut, **la plupart des utilisateurs ne disposent pas des droits nécessaires** pour visualiser ces informations.

Pour que ces champs apparaissent :
1. Activez la fonctionnalité **"Manage Multiple Stock Locations"** dans les **Paramètres du module Stock**.
2. Attribuez le groupe **« Manage Multiple Stock Locations »** aux utilisateurs concernés.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q5] stock -- constraints (medium)
**Question :** Quelles contraintes empechent la creation d'un stock.quant invalide, et quelle regle distincte garantit l'unicite d'un numero de serie ?

**Reponse de reference (verite-terrain) :**
> Trois @api.constrains independantes sur stock.quant : check_product_id interdit un quant pour un produit qui n'est pas de type 'product' (consommable/service exclus) ; check_location_id interdit un emplacement de type 'view' (emplacement structurel, non physique) ; check_lot_id interdit qu'un lot/numero de serie soit rattache a un produit different de celui du quant. Independamment, sur stock.lot, _check_unique_lot (@api.constrains sur name/product_id/company_id) verifie via _read_group (pas une contrainte SQL unique) qu'aucune combinaison produit+societe+nom de lot n'est dupliquee -- une verification applicative, pas une contrainte de base de donnees.

**A verifier dans le code :** `models/stock_quant.py : check_product_id, check_location_id, check_lot_id (@api.constrains) ; models/stock_lot.py : _check_unique_lot (@api.constrains('name','product_id','company_id'))`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 60.22s | Effectif: 60.217s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Contraintes empêchant la création d'un `stock.quant` invalide

Plusieurs règles techniques empêchent la création de quantités de stock (`stock.quant`) non conformes :

1. **Validation du type de produit** :  
   Un `stock.quant` ne peut être créé que pour des produits de type **"produit"** (non consommables ni services). Si un utilisateur tente de créer un `stock.quant` pour un produit consommable ou service, une erreur est levée avec le message :  
   > *"Quants cannot be created for consumables or services."*

2. **Validation de la localisation** :  
   Les quantités ne peuvent pas être créées ou déplacées vers une localisation de type **"vue"** (view). Une erreur est générée avec le message :  
   > *"You cannot take products from or deliver products to a location of type 'view'."*

3. **Restrictions sur les opérations** :  
   - La duplication de `stock.quant` est interdite :  
     > *"You cannot duplicate stock quants."*  
   - La création de `stock.quant` est limitée aux opérations autorisées (ex. : *"You are not allowed to create a lot or serial number with this operation type"*).

4. **Contraintes de quantité** :  
   Les quantités ou quantités réservées doivent être définies lors de la création :  
   > *"Quantity or Reserved Quantity should be set."*

---

### Règle garantissant l'unicité d'un numéro de série (`stock.lot`)

Pour les numéros de série (`stock.lot`), une règle distincte assure l'unicité de la combinaison **produit + entreprise + numéro de série** :

- **Contrainte d'unicité** :  
  La méthode `_check_unique_lot` vérifie que chaque combinaison de **produit**, **entreprise** et **numéro de série** est unique au sein d'une entreprise. Si une duplication est détectée, une erreur est levée avec le message :  
  > *"The combination of serial number and product must be unique across a company."*

  Cette vérification est effectuée via un groupe de requêtes SQL (`_read_group`) qui identifie les doublons potentiels.

---

### Résumé

- Les `stock.quant` sont soumis à des règles strictes pour éviter les erreurs de logique métier (type de produit, localisation, opération).
- Les `stock.lot` sont soumis à une contrainte d'unicité pour éviter les doublons de numéros de série au sein d'une entreprise.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 26.22s | Effectif: 26.217s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Réponse

Le groupe « Billing Administrator » (account.group_account_manager) **a le droit de créer et de modifier des factures** (opérations d'écriture et de création) sur le modèle `account.move`, malgré la restriction de lecture (`perm_read=1`) définie dans l'ACL directe. 

Cela est possible car :

- Le groupe `account.group_account_manager` est explicitement listé dans les permissions **WRITE**, **CREATE** et **UNLINK** pour `account.move` (via les règles d'accès et les groupes implicites).

Ainsi, un utilisateur appartenant à ce groupe peut **créer, modifier et supprimer** des factures, conformément aux droits définis dans les ACL et aux règles de sécurité associées.

[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : pour la permission concernée, `account.group_account_manager` hérite de l'ACL de `account.group_account_invoice` par implication transitive (`implied_ids`). Les ACL applicables sont additives : l'absence d'une permission dans une ACL directe ne retire pas le droit accordé par une autre ACL applicable.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q2] account -- workflow (hard)
**Question :** Un 'Billing Administrator' (group_account_manager) peut-il poster une ecriture comptable dont la date est anterieure ou egale a la date de cloture (lock date) de la societe ?

**Reponse de reference (verite-terrain) :**
> Non, si la date est anterieure ou egale a la date de cloture d'exercice (fiscalyear_lock_date), meme un Billing Administrator (group_account_manager) en est empeche : _check_fiscalyear_lock_date() compare la date a company._get_user_fiscal_lock_date() et leve un UserError, sans aucune exception de groupe (le groupe n'influe que sur le libelle du message, omettant l'invitation a contacter un 'Adviser'). En revanche, pour la date de cloture de periode (period_lock_date, verrou mensuel), _get_user_fiscal_lock_date() exempte le Billing Administrator en ne retenant que fiscalyear_lock_date.

**A verifier dans le code :** `models/account_move.py : _check_fiscalyear_lock_date() + models/company.py : _get_user_fiscal_lock_date() (verifie user_has_groups('account.group_account_manager') pour exempter de period_lock_date, mais applique fiscalyear_lock_date sans exception)`

**Outils attendus :** ['analyze_security_locks', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'who_has_access_to', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 41.87s | Effectif: 41.866s | Groq wait: 0.0s | Sauts: 5) :**
```text
### Règles de blocage comptable

[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : pour la permission concernée, `account.group_account_manager` hérite de l'ACL de `account.group_account_invoice` par implication transitive (`implied_ids`). Les ACL applicables sont additives : l'absence d'une permission dans une ACL directe ne retire pas le droit accordé par une autre ACL applicable.

**Réponse : non.** La date de clôture d'exercice reste bloquante, y compris pour le Billing Administrator.

[FAIT DÉTERMINISTIQUE -- PORTÉE DES DATES DE CLÔTURE] Non : l'exemption de `account.group_account_manager` dans `_get_user_fiscal_lock_date()` ne concerne que `period_lock_date` (verrou de période). Elle conserve `fiscalyear_lock_date` comme date effective ; `_check_fiscalyear_lock_date()` bloque donc aussi le Billing Administrator lorsque la date de l'écriture est antérieure ou égale à la clôture d'exercice.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 35.72s | Effectif: 35.725s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Réponse

1. **Statut de `account.move`** :  
   Le modèle `account.move` est un **nouveau modèle** déclaré dans le module `account`. Il ne s'agit pas d'une extension d'un autre modèle métier, mais d'un modèle autonome qui hérite de plusieurs mixins (comme `portal.mixin`, `mail.thread.main.attachment`, etc.) pour intégrer des fonctionnalités transversales (suivi d'activités, portail, etc.).

2. **Extensions hors périmètre comptable** :  
   Oui, le module `account` étend **en parallèle des modèles natifs hors de son propre périmètre comptable**, notamment :
   - `product.product` (pour gérer les taxes et les comptes associés aux produits),
   - `product.template` (pour définir des règles de comptabilisation et des taxes),
   - `uom.uom` (pour intégrer des codes fiscaux),
   - `product.category` (pour définir des comptes par défaut par catégorie),
   - `decimal.precision` (pour personnaliser la précision des calculs).  

   Ces extensions permettent au module `account` d'interagir avec d'autres domaines (commerciaux, logistiques, etc.) tout en restant centré sur la comptabilité.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q4] account -- ui (hard)
**Question :** Un utilisateur avec uniquement group_account_invoice ('Billing') voit-il le compte comptable (account_id) d'une ligne de facture ? Et un 'Billing Administrator' (group_account_manager) le voit-il, en configuration Invoicing seule (sans le module Accounting installe) ?

**Reponse de reference (verite-terrain) :**
> Non dans les deux cas. Le champ account_id porte groups='account.group_account_readonly' dans la vue -- or ni group_account_invoice ni group_account_manager n'impliquent group_account_readonly (seul group_account_user, le profil 'comptable complet', implique a la fois invoice et readonly). En configuration Invoicing seule, la documentation du fichier de securite le confirme explicitement : seuls group_account_invoice et group_account_manager sont censes etre utilises, et aucun des deux ne donne acces au champ technique du compte comptable -- il faut le module Accounting (qui attribue alors group_account_user) pour le voir.

**A verifier dans le code :** `views/account_move_views.xml : <field name="account_id" ... groups="account.group_account_readonly"/> + security/account_security.xml : commentaire d'en-tete + implied_ids de group_account_invoice/group_account_manager/group_account_user`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 80.15s | Effectif: 80.147s | Groq wait: 0.0s | Sauts: 6) :**
```text
### Visibilité du compte comptable (account_id)

#### 1. Utilisateur avec **group_account_invoice ('Billing')** :
- **Résultat** : Non, l'utilisateur ne voit **pas** le champ `account_id` sur une ligne de facture.
- **Explication** : Le champ `account_id` est **restreint aux groupes** `account.group_account_readonly` (« Show Accounting Features - Readonly »). L'utilisateur appartient uniquement au groupe `group_account_invoice` (« Billing »), qui **n'est pas** mentionné dans les conditions de visibilité du champ. Ainsi, il ne peut pas voir ce champ.

#### 2. Utilisateur avec **group_account_manager ('Billing Administrator')** en configuration **Invoicing seule** (sans module Accounting) :
- **Résultat** : Non, l'utilisateur ne voit **pas** le champ `account_id` non plus.
- **Explication** : 
  - Le champ `account_id` est **toujours restreint au groupe `account.group_account_readonly`**, même si le module Accounting n'est pas installé.
  - Le groupe `group_account_manager` (« Billing Administrator ») **n'est pas** associé à cette restriction. 
  - En l'absence du module Accounting, le groupe `account.group_account_readonly` **n'existe pas**, donc le champ `account_id` reste **invisible** pour tous les utilisateurs, y compris ceux du groupe `group_account_manager`.

### Conclusion
Le champ `account_id` est **invisible** pour les utilisateurs du groupe `Billing` ou `Billing Administrator`, **sauf** s'ils appartiennent au groupe `account.group_account_readonly` (qui n'est pas présent en configuration Invoicing seule).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q5] account -- constraints (hard)
**Question :** account.move declare un _sql_constraints 'unique_name' dont la definition SQL est une chaine vide -- comment l'unicite du numero de piece est-elle reellement appliquee ?

**Reponse de reference (verite-terrain) :**
> Le triplet _sql_constraints=[('unique_name', '', '...')] ne cree aucune contrainte via le mecanisme standard (definition vide) ; il sert uniquement a fournir le message d'erreur associe. L'unicite reelle est creee manuellement dans _auto_init() via un index SQL partiel : CREATE UNIQUE INDEX account_move_unique_name ON account_move(name, journal_id) WHERE (state='posted' AND name != '/') -- l'unicite ne s'applique donc qu'aux ecritures postees et nommees (pas aux brouillons, qui partagent tous le placeholder '/'). Independamment, @api.constrains('journal_id','move_type') / _check_journal_move_type interdit de creer un document d'achat dans un journal dont journal_id.type != 'purchase' (et symetriquement pour la vente).

**A verifier dans le code :** `models/account_move.py : _sql_constraints (unique_name, definition vide) + _auto_init() (CREATE UNIQUE INDEX account_move_unique_name, index partiel) + _check_journal_move_type (@api.constrains)`

**Outils attendus :** ['analyze_data_constraints', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 88.52s | Effectif: 88.52s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Application de l'unicité du numéro de pièce

L'unicité du numéro de pièce (`name`) dans le modèle `account.move` est réellement appliquée via une **contrainte SQL brute** exécutée directement dans la base de données, indépendamment de la déclaration `_sql_constraints` (qui contient une chaîne vide). 

Cette contrainte est définie dans le code source via une instruction SQL brute :
```python
self.env.cr.execute("""
    CREATE UNIQUE INDEX account_move_unique_name
                     ON account_move(name, journal_id)
                  WHERE (state = 'posted' AND name != '/')
""")
```
Cette instruction crée un **index unique** sur les champs `name` et `journal_id`, avec une condition supplémentaire : le document doit être dans l'état `'posted'` et le `name` ne doit pas être `'/'`. Cet index garantit que **aucun autre enregistrement avec le même `name` et `journal_id` ne peut être inséré** dans la table `account_move` tant que l'état est `'posted'`.

### Conséquences pratiques
- **Pour les documents publiés (state = 'posted')** : Le numéro de pièce (`name`) doit être unique par journal (`journal_id`).
- **Pour les documents non publiés** : Aucune contrainte d'unicité n'est appliquée sur le `name` (sauf si un autre mécanisme le spécifie).

Cette logique est **indépendante de `_sql_constraints`** et n'est pas détectée par les outils standard qui analysent les contraintes déclarées via ce mécanisme.

[Source: Graphe de Connaissances Code Intelligence]
```

---