# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-24 16:01:24

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees (consolidees) | 25 |
| Questions rejouees ce tour | 5 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 4 |
| p50 latence effective (run courant) | `10.17s` |
| p90 latence effective (run courant) | `48.55s` (budget `12.0s`,  DEPASSE) |
| Moyenne (run courant) | `17.24s` |
| Max (run courant) | `48.55s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 13.27s | Effectif: 13.268s | Groq wait: 0.0s | Sauts: 5) :**
```text
### Accès d’un utilisateur simple à la fiche équipement

- **Modification (création, mise à jour, suppression)**  
  Un utilisateur qui ne fait partie que du groupe « utilisateur simple » (base.group_user) **ne possède pas les droits** pour modifier, créer ou supprimer une fiche équipement. Seuls les membres du groupe « group_equipment_manager » disposent de ces autorisations.

- **Consultation**  
  Un utilisateur simple peut **consulter** uniquement les fiches équipements auxquelles il est **affilié** (c’est‑à‑dire les équipements pour lesquels il figure dans la liste des partenaires suivis). Il ne peut pas voir les équipements qui ne lui sont pas associés.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q2] maintenance -- workflow (hard)
**Question :** Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente (recurring_maintenance=True) atteint une etape marquee 'done' ?

**Reponse de reference (verite-terrain) :**
> MaintenanceRequest.write() detecte que stage_id change vers un stage dont done=True ; pour chaque demande de maintenance_type='preventive' avec recurring_maintenance actif, calcule une nouvelle schedule_date (date actuelle ou schedule_date existante + repeat_interval unites de repeat_unit via relativedelta), et si repeat_type=='forever' ou que la nouvelle date reste <= repeat_until, duplique automatiquement la demande (copy()) avec cette nouvelle schedule_date et la reinsere au stage par defaut (_default_stage) -- generation automatique de la prochaine occurrence, avant meme l'appel a super().write().

**A verifier dans le code :** `models/maintenance.py, classe MaintenanceRequest, methode write() (bloc verifiant request.maintenance_type != 'preventive' or not request.recurring_maintenance)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 17.58s | Effectif: 17.581s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Ce qui se produit automatiquement

- **Création d’une nouvelle demande**  
  Dès que la demande de maintenance préventive et récurrente passe à l’étape « done », Odoo génère automatiquement une nouvelle demande de maintenance.  
  - La date de planification de la nouvelle demande est calculée en ajoutant l’intervalle de répétition (ex. : chaque mois, chaque trimestre…) à la date de planification actuelle.  
  - La nouvelle demande est placée dans l’étape par défaut (généralement « planifiée »).

- **Mise à jour de la demande actuelle**  
  - La date de clôture de la demande qui vient d’être terminée est fixée à la date d’aujourd’hui.  
  - Les activités liées à la demande (tâches, rappels, notifications) sont mises à jour ou créées pour la nouvelle demande.  
  - Le champ « état Kanban » est réinitialisé à « normal » pour refléter le changement de phase.

- **Gestion des notifications**  
  - Les followers (utilisateurs suivis) de la demande sont conservés et les notifications sont envoyées aux personnes concernées pour la nouvelle demande.

En résumé, lorsqu’une demande de maintenance préventive récurrente atteint l’étape « done », Odoo prépare automatiquement la prochaine itération en créant une nouvelle demande avec la date suivante, tout en clôturant la demande actuelle et en mettant à jour les activités et notifications associées.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q3] maintenance -- inheritance (medium)
**Question :** maintenance.equipment est-il une extension d'un modele natif Odoo existant, ou un nouveau modele ? Quel role joue maintenance.mixin dont il herite ?

**Reponse de reference (verite-terrain) :**
> Nouveau modele (_name='maintenance.equipment') -- il n'etend aucun modele metier preexistant, il herite seulement de mixins : mail.thread, mail.activity.mixin, et maintenance.mixin. maintenance.mixin est un AbstractModel qui factorise les champs/calculs communs de suivi de maintenance (maintenance_team_id, technician_user_id, mtbf/mttr/estimated_next_failure via _compute_maintenance_request, maintenance_count), destine a etre reutilise par tout modele 'maintenable' qui l'inclut dans son _inherit -- dans ce module, seul maintenance.equipment l'utilise ; maintenance.equipment.category, elle, n'en herite pas (seulement mail.alias.mixin/mail.thread).

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceMixin (_name='maintenance.mixin', models.AbstractModel) + classe MaintenanceEquipment (_inherit=['mail.thread','mail.activity.mixin','maintenance.mixin']) vs classe MaintenanceEquipmentCategory (_inherit=['mail.alias.mixin','mail.thread'], sans maintenance.mixin)`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 47.21s | Effectif: 47.205s | Groq wait: 0.0s | Sauts: 3) :**
```text
`maintenance.equipment` est un **nouveau modèle** : il possède son propre nom (`_name = 'maintenance.equipment'`) et ne reprend pas la structure d’un modèle natif déjà présent dans Odoo.  

Il hérite uniquement de trois mixins :  
- `mail.thread` et `mail.activity.mixin` pour la traçabilité et les activités,  
- **`maintenance.mixin`** qui apporte les champs et la logique communs aux objets liés à la maintenance (équipe de maintenance, technicien, dates d’échéance, MTBF/MTTR, etc.).  

En résumé : `maintenance.equipment` est un modèle autonome, et `maintenance.mixin` sert de base partagée pour les éléments de maintenance.

À noter : ce module étend bien 1 modèle(s) hors de son propre périmètre : 'res.config.settings'.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q4] maintenance -- ui (easy)
**Question :** Pourquoi le champ 'cost' (cout) d'un equipement n'est-il pas visible pour tous les utilisateurs ayant acces en lecture a sa fiche ?

**Reponse de reference (verite-terrain) :**
> Le champ cost porte groups='maintenance.group_equipment_manager' dans la vue formulaire -- reserve aux managers, independamment du droit de lecture sur la fiche elle-meme : un utilisateur simple qui suit un equipement (et le voit donc via equipment_rule_user) ne voit pas ce champ precis dans le formulaire.

**A verifier dans le code :** `views/maintenance_views.xml, <field name="cost" groups="maintenance.group_equipment_manager"/>`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 11.59s | Effectif: 11.585s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi le champ « Cost » n’est pas visible

Le champ **Cost** est affiché uniquement aux utilisateurs appartenant au groupe **« Gestionnaire d’équipement »**.  
Même si un utilisateur a le droit de lecture sur la fiche d’équipement, il ne voit pas ce champ tant qu’il ne fait pas partie de ce groupe.  

Pour voir le coût, il faut soit :

- rejoindre le groupe **« Gestionnaire d’équipement »**,  
- ou demander à un membre de ce groupe de le consulter pour vous.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q5] maintenance -- constraints (medium)
**Question :** Quelle regle empeche de creer deux equipements avec le meme numero de serie, et quelle contrainte distincte s'applique sur l'intervalle de repetition (repeat_interval) d'une demande recurrente ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts et independants : (1) sur maintenance.equipment, _sql_constraints=[('serial_no','unique(serial_no)', ...)] -- contrainte SQL native (pas @api.constrains) bloquant un second equipement avec le meme serial_no au niveau base de donnees. (2) sur maintenance.request, _check_repeat_interval (@api.constrains('repeat_interval')) leve une ValidationError Python si repeat_interval < 1 -- verifiee a l'ecriture ORM, pas au niveau SQL.

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceEquipment, attribut _sql_constraints ; classe MaintenanceRequest, methode _check_repeat_interval`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 26.93s | Effectif: 26.926s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Règle empêchant les doublons de numéro de série

- **Contrainte** : `unique(serial_no)` sur le champ `serial_no` du modèle `maintenance.equipment`.  
- **Source** : [maintenance.py:L171-L173](file:///home/user/odoo-17.0/addons/maintenance/models/maintenance.py#L171-L173)

Cette contrainte SQL garantit qu’aucun équipement ne peut être créé avec un numéro de série déjà présent dans la base.

---

### Contrainte distincte sur l’intervalle de répétition

- **Contrainte** : `@api.constrains('repeat_interval')` qui vérifie que `repeat_interval` est **≥ 1**.  
- **Source** : [maintenance.py:L280-L284](file:///home/user/odoo-17.0/addons/maintenance/models/maintenance.py#L280-L284)

Si l’intervalle de répétition est inférieur à 1, une `ValidationError` est levée, empêchant la création ou la modification de la demande récurrente.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'button_execution_path', 'read_source_code', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 21.83s | Effectif: 21.825s | Groq wait: 0.0s | Sauts: 10) :**
```text
### Différence entre un acheteur et un gestionnaire sur une commande d’achat

| Action | Acheteur (group_purchase_user) | Gestionnaire (group_purchase_manager) |
|--------|--------------------------------|---------------------------------------|
| **Validation de la commande** | Après avoir cliqué sur **« Valider »**, la commande passe en état **« à valider »**. Elle doit ensuite être approuvée par un gestionnaire. | Le même bouton **« Valider »** passe directement l’état à **« validée »** (ou **« en approbation »** si la validation double est activée). Le gestionnaire n’est pas soumis à la limite de montant. |
| **Déblocage d’une commande terminée** | Le bouton **« Débloquer »** n’est pas visible. | Le bouton **« Débloquer »** est disponible et permet de revenir à l’état **« en cours »** pour modifier la commande. |
| **Accès aux états « à valider »** | L’acheteur peut voir les commandes en attente d’approbation, mais ne peut pas les approuver. | Le gestionnaire peut approuver ces commandes directement. |
| **Limite de montant** | Si la valeur dépasse le seuil défini par l’entreprise, l’acheteur doit passer par l’approbation. | Le gestionnaire peut valider sans se soucier du seuil. |

En résumé, les deux groupes disposent des mêmes droits de lecture, écriture, création et suppression, mais le **gestionnaire** possède des privilèges supplémentaires : il peut **valider directement** les commandes (en contournant la double validation) et **débloquer** les commandes terminées, tandis que l’**acheteur** doit attendre l’approbation d’un gestionnaire.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q2] purchase -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on clique sur 'Confirm Order' (button_confirm) selon que la commande est eligible ou non a l'approbation directe ?

**Reponse de reference (verite-terrain) :**
> button_confirm() ne s'applique qu'aux commandes en etat 'draft' ou 'sent' (les autres sont ignorees silencieusement) ; il valide d'abord la distribution analytique des lignes et ajoute le fournisseur au produit, puis appelle _approval_allowed() : si vrai, delegue a button_approve() qui passe directement l'etat a 'purchase' (et a 'done' si po_lock=='lock') ; si faux, l'etat passe seulement a 'to approve' -- en attente qu'un manager declenche explicitement button_approve() via le bouton dedie.

**A verifier dans le code :** `models/purchase_order.py : button_confirm(), button_approve()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 20.53s | Effectif: 20.533s | Groq wait: 0.0s | Sauts: 7) :**
```text
### Que se passe‑t‑il quand on clique sur « Confirm Order » ?

- **Vérification de l’état**  
  Le bouton ne fonctionne que si la commande est encore en *Brouillon* ou *Envoyée*.

- **Pré‑traitements**  
  - Les lignes de la commande sont vérifiées pour s’assurer que la distribution analytique est correcte.  
  - Le fournisseur de la commande est ajouté à la liste des fournisseurs du produit (si ce n’est pas déjà le cas).  
  - Le partenaire de la commande est ajouté aux destinataires de la discussion.

- **Décision d’approbation**  
  - **Si la commande est éligible à l’approbation directe** (c’est‑à‑dire :  
    - la validation double est désactivée,  
    - ou le montant total est inférieur au seuil de validation double,  
    - ou vous faites partie du groupe « Gestionnaire des achats »),  
    alors la commande passe immédiatement à l’état **« Achetée »** (et si la société a activé le verrouillage, elle passe directement à **« Terminée »**).  
  - **Si la commande n’est pas éligible** (montant trop élevé et vous n’êtes pas gestionnaire),  
    elle passe à l’état **« À approuver »** et attend l’approbation d’un gestionnaire.

- **Résultat final**  
  - **Éligible** : la commande est validée immédiatement et peut être facturée ou livrée.  
  - **Non éligible** : la commande reste en attente d’approbation et ne peut pas encore être traitée.

En résumé, le bouton « Confirm Order » vérifie d’abord si la commande peut être approuvée sans intervention supplémentaire ; si oui, elle est validée immédiatement, sinon elle est mise en attente d’une approbation managériale.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q3] purchase -- inheritance (medium)
**Question :** purchase.order est-il un nouveau modele ou une extension ? Le module purchase modifie-t-il en parallele un modele natif deja existant hors de son propre domaine (achat), et comment ?

**Reponse de reference (verite-terrain) :**
> purchase.order (_name='purchase.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin), pas d'un modele metier preexistant. En parallele, ce meme module etend reellement account.move (_inherit='account.move', classe AccountMove dans account_invoice.py) en surchargeant create() et write() pour poster un message de tracabilite ('cree depuis'/'modifie depuis') des que les lignes de facture referencent une purchase.order.line -- une extension transverse comptabilite, distincte du modele purchase.order lui-meme.

**A verifier dans le code :** `models/purchase_order.py : classe PurchaseOrder (_name + _inherit mixins) vs models/account_invoice.py : classe AccountMove (_inherit='account.move'), methodes create()/write()`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules', 'analyze_method_override_chain'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code'] -- MANQUANT(S): ['analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 19.02s | Effectif: 19.016s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Modèle « purchase.order »

- **Nature** : *purchase.order* est un **nouveau modèle**.  
  Il est déclaré dans le module *purchase* avec son propre nom (`_name = "purchase.order"`) et ne repose que sur des mixins techniques (mail, portail, catalogue produit).  
  Il ne s’agit donc pas d’une extension d’un modèle existant.

### Impact du module *purchase* sur d’autres modèles natifs

- Le module *purchase* **modifie plusieurs modèles natifs** qui ne font pas partie de son domaine d’achat.  
  Parmi ceux-ci, on trouve notamment :  
  - `account.move` et `account.move.line` (ajout de champs et de logiques liés aux bons d’achat)  
  - `res.partner` (ajout de champs de référence fournisseur)  
  - `res.company` et `res.config.settings` (ajout de paramètres liés aux achats)  
  - `product.template`, `product.product`, `product.packaging`, `product.supplierinfo` (ajout de champs de gestion des fournisseurs et des emballages)  
  - `account.analytic.account` et `account.analytic.applicability` (ajout de champs d’analyse de coûts liés aux achats)  
  - `account.tax` (ajout de règles de calcul de taxes spécifiques aux achats)

Ces extensions permettent d’intégrer les achats dans les processus comptables, de gérer les fournisseurs, les taxes, les coûts analytiques et les paramètres de l’entreprise, tout en conservant la structure de base des modèles natifs.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q4] purchase -- ui (easy)
**Question :** Pourquoi le bouton 'Approve Order' n'est-il pas visible pour un utilisateur simple meme quand la commande est au statut 'to approve' ?

**Reponse de reference (verite-terrain) :**
> Le bouton button_approve porte groups='purchase.group_purchase_manager' dans la vue formulaire -- masque pour tout utilisateur hors de ce groupe, independamment de son invisible= conditionnel sur l'etat (invisible='state != "to approve"'). C'est la manifestation UI directe du garde applicatif _approval_allowed() (PUR-Q1/Q2) : le bouton n'existe que pour les managers, alors qu'un simple acheteur ne voit que 'Confirm Order'.

**A verifier dans le code :** `views/purchase_views.xml, bouton name='button_approve', groups='purchase.group_purchase_manager'`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 8.65s | Effectif: 8.654s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Pourquoi le bouton « Approve Order » n’apparaît pas

Le bouton « Approve Order » est **restreint aux utilisateurs du groupe « Purchase Manager »**.  
Même si la commande est en statut « to approve », un utilisateur qui ne fait pas partie de ce groupe ne voit pas le bouton dans l’interface.  

En pratique :  
- Le bouton est invisible pour tout le monde sauf les membres du groupe « Purchase Manager ».  
- Seuls ces utilisateurs peuvent déclencher l’action d’approbation.  

Ainsi, un simple utilisateur ne peut pas approver une commande, même lorsqu’elle est prête à être approuvée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q5] purchase -- constraints (medium)
**Question :** Quelles regles empechent de supprimer une commande d'achat ou une de ses lignes selon leur etat, et quelle contrainte SQL distincte s'applique sur les lignes elles-memes ?

**Reponse de reference (verite-terrain) :**
> Deux gardes @api.ondelete(at_uninstall=False) distincts : _unlink_if_cancelled sur purchase.order leve UserError si l'etat n'est pas 'cancel' (impossible de supprimer une commande active, il faut d'abord l'annuler) ; _unlink_except_purchase_or_done sur purchase.order.line leve UserError si la commande parente est en etat 'purchase' ou 'done'. Independamment, _sql_constraints sur purchase.order.line impose par CHECK SQL que les champs comptables (product_id/product_uom/date_planned) soient tous renseignes pour une ligne 'accountable' (display_type NULL) et tous vides pour une ligne section/note (display_type non NULL) -- integrite structurelle, pas une regle de suppression.

**A verifier dans le code :** `models/purchase_order.py : _unlink_if_cancelled (@api.ondelete) ; models/purchase_order_line.py : _unlink_except_purchase_or_done (@api.ondelete) + _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 41.98s | Effectif: 41.985s | Groq wait: 0.0s | Sauts: 2) :**
```text
**Règles empêchant la suppression d’une commande d’achat ou d’une de ses lignes**

| Objet | Condition / message | Source |
|-------|---------------------|--------|
| **Commande d’achat (`purchase.order`)** | La suppression (`unlink`) est bloquée tant que la commande n’est pas annulée. Le code lève une `UserError` : *« In order to delete a purchase order, you must cancel it first. »* | `purchase_order.py:L267-L267` |
| **Lignes de commande (`purchase.order.line`)** | Aucun verrou SQL n’est déclaré dans les observations fournies. La seule contrainte liée aux lignes est une contrainte Python qui vérifie que les produits appartiennent à la même société que la commande (voir `@api.constrains('company_id', 'order_line')` dans `purchase_order.py:L153-L168`). | `purchase_order.py:L153-L168` |

**Conclusion**

- La suppression d’une commande d’achat est interdite tant qu’elle n’est pas dans l’état « annulée » ; le mécanisme est un contrôle Python levé à l’appel de `unlink()` (ligne 267).  
- Pour les lignes de commande, aucune contrainte SQL distincte n’apparaît dans les observations. Seule une contrainte Python vérifie la cohérence des sociétés entre la commande et ses lignes (ligne 153‑168).  

Ainsi, la règle de suppression est entièrement gérée par le code Python, et aucune contrainte SQL supplémentaire n’est appliquée aux lignes elles‑mêmes selon les données disponibles.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q1] sale -- security (hard)
**Question :** Un vendeur (sales_team.group_sale_salesman, sans group_sale_salesman_all_leads) peut-il voir toutes les commandes de vente de son entreprise, ou seulement certaines ? Et un utilisateur du portail (base.group_portal) ?

**Reponse de reference (verite-terrain) :**
> Non pour le vendeur simple : l'ACL access_sale_order lui donne perm_read/write/create=1 (pas perm_unlink), mais l'ir.rule sale_order_personal_rule le restreint aux commandes ou user_id lui est assigne ou user_id est vide (domaine OR) ; seul un vendeur avec en plus group_sale_salesman_all_leads herite de sale_order_see_all (domaine (1,'=',1), tout voir). Pour le portail : ACL access_sale_order_portal en lecture seule (perm_read=1, tout le reste 0), combinee a sale_order_rule_portal qui restreint aux commandes ou le partenaire (ou un enfant commercial) figure dans message_partner_ids -- avec ici perm_write/perm_unlink actives via la regle elle-meme (perm_write=True, perm_unlink=True dans la regle), ce qui autorise l'ecriture/suppression via la regle malgre l'ACL en lecture seule, en pratique borne au flux portail (ex. wizard d'annulation).

**A verifier dans le code :** `security/ir.model.access.csv (access_sale_order, access_sale_order_portal) + security/ir_rules.xml (sale_order_personal_rule, sale_order_see_all, sale_order_rule_portal)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 15.06s | Effectif: 15.063s | Groq wait: 0.0s | Sauts: 9) :**
```text
### Accès aux commandes de vente

| Persona | Accès aux commandes de l’entreprise | Conditions |
|---------|--------------------------------------|------------|
| **Vendeur (group_sale_salesman)** | **Seulement les commandes qui lui sont attribuées ou qui n’ont pas de vendeur assigné** | La règle « Personal Orders » autorise la lecture uniquement des commandes où le champ `user_id` est le vendeur lui‑même ou vide. |
| **Utilisateur du portail (group_portal)** | **Seulement les commandes auxquelles il est lié en tant que partenaire de message** | La règle « Portal Personal Quotations/Sales Orders » permet la lecture uniquement des commandes dont le champ `message_partner_ids` contient le partenaire commercial de l’utilisateur. |

En résumé, un vendeur ne peut pas voir toutes les commandes de son entreprise, mais uniquement celles qui lui sont directement attribuées ou qui n’ont pas de vendeur. Un utilisateur du portail ne voit que les commandes auxquelles il est lié en tant que partenaire de message.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q2] sale -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on confirme une commande de vente (action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) juste apres ?

**Reponse de reference (verite-terrain) :**
> action_confirm() verifie d'abord que toutes les commandes sont en etat 'draft' ou 'sent' (_can_be_confirmed()), sinon UserError ; valide la distribution analytique des lignes, souscrit le client aux notifications, ecrit state='sale' + date_order=now (_prepare_confirmation_values), puis appelle _action_confirm() (cree un compte analytique si une ligne porte un produit avec expense_policy actif). Immediatement apres, filtre les commandes via _should_be_locked() -- qui verifie has_group('sale.group_auto_done_setting') sur le createur de la commande (pas l'utilisateur courant) -- et appelle action_lock() (locked=True) sur celles-la uniquement ; ce n'est donc pas systematique, ca depend d'un parametrage (groupe) rattache au createur de la commande, pas de l'utilisateur qui confirme.

**A verifier dans le code :** `models/sale_order.py : action_confirm(), _should_be_locked(), _can_be_confirmed(), _action_confirm()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 16.95s | Effectif: 16.95s | Groq wait: 0.0s | Sauts: 9) :**
```text
### Ce qui se passe lors de la confirmation d’une commande de vente

- **Changement d’état** : la commande passe de *Brouillon* ou *Envoyée* à *En cours* (état « sale »).  
- **Validation des taxes** : les taxes sont recalculées et validées pour chaque ligne de produit.  
- **Abonnement du client** : le client est automatiquement ajouté aux abonnés de la commande afin de recevoir les notifications.  
- **Envoi d’un e‑mail** (si la case « Envoyer par e‑mail » est cochée) : un e‑mail de confirmation est envoyé au client.  
- **Création d’un compte analytique** (si la commande contient un produit à frais) : un compte analytique est créé pour suivre les coûts.  
- **Enregistrement des valeurs de confirmation** : la date de commande est fixée à la date courante et l’état est mis à jour.

### Cas de verrouillage automatique (champ `locked`)

- **Condition** : la commande est verrouillée immédiatement après la confirmation **si** l’utilisateur qui l’a créée appartient au groupe **« Lock Confirmed Sales »** (paramètre de configuration `group_auto_done_setting`).  
- **Effet** : le champ `locked` passe à **Vrai**, ce qui empêche toute modification ultérieure de la commande sans action spéciale.  

En résumé, la confirmation transforme la commande en état « En cours », applique les taxes, notifie le client, crée un compte analytique si nécessaire, et, selon le groupe de l’auteur, peut verrouiller la commande pour la protéger contre les modifications.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q3] sale -- inheritance (medium)
**Question :** sale.order est-il un nouveau modele ou une extension ? Quel modele natif hors du perimetre 'vente' ce module etend-il directement, et sous quel nom de classe ?

**Reponse de reference (verite-terrain) :**
> sale.order (_name='sale.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin, utm.mixin), aucun modele metier preexistant. En parallele, ce meme module etend reellement account.move (classe AccountMove, _inherit=['account.move', 'utm.mixin'] dans models/account_move.py) -- une extension transverse comptabilite comparable au constat fait sur purchase (PUR-Q3), meme modele cible (account.move), module different.

**A verifier dans le code :** `models/sale_order.py : classe SaleOrder (_name='sale.order', _inherit=[mixins]) vs models/account_move.py : classe AccountMove (_inherit=['account.move','utm.mixin'])`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules', 'analyze_method_override_chain'] | **Outils invoques :** ['trace_full_inheritance', 'read_source_code', 'list_involved_modules', 'list_involved_modules'] -- MANQUANT(S): ['analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 20.68s | Effectif: 20.68s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Analyse du modèle « sale.order »

- **Nature du modèle**  
  Le module « vente » déclare **un nouveau modèle** : `sale.order`.  
  En réalité, ce module étend bien 24 modèle(s) hors de son propre périmètre : 'account.analytic.applicability', 'account.analytic.line', 'account.invoice.report', 'account.move', 'account.move.line', 'account.payment.register', 'crm.team', 'ir.config_parameter', 'onboarding.onboarding', 'onboarding.onboarding.step', 'payment.link.wizard', 'payment.provider', 'payment.transaction', 'product.attribute', 'product.attribute.custom.value', 'product.attribute.value', 'product.document', 'product.packaging', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.partner', 'utm.campaign'.

- **Modèle natif étendu**  
  Le modèle `sale.order` étend directement les mixins suivants, qui sont des modèles natifs d’Odoo :  
  - `portal.mixin` (classe : *portal.mixin*)  
  - `product.catalog.mixin`  
  - `mail.thread`  
  - `mail.activity.mixin`  
  - `utm.mixin`

  Parmi ces mixins, le plus proche d’un modèle métier classique est `mail.thread`, mais le mixin `portal.mixin` est le premier modèle natif hors du périmètre « vente » que le module étend directement.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q4] sale -- ui (easy)
**Question :** Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) une commande verrouillee, meme si c'est lui qui l'a confirmee ?

**Reponse de reference (verite-terrain) :**
> Le bouton action_unlock porte groups='sales_team.group_sale_manager' dans la vue formulaire -- reserve aux managers, quel que soit le lien du vendeur avec la commande (createur, assigne via user_id, etc.). Le bouton n'est meme visible (invisible="not locked") que si la commande est deja verrouillee, mais son affichage reste conditionne au groupe manager en plus de cette condition d'etat. Le bouton action_lock, lui, n'est visible que si le parametrage sale.group_auto_done_setting est actif (t groups=), et porte la meme restriction sales_team.group_sale_manager.

**A verifier dans le code :** `views/sale_order_views.xml : boutons action_unlock (groups='sales_team.group_sale_manager', invisible='not locked') et action_lock (dans <t groups='sale.group_auto_done_setting'>, lui-meme groups='sales_team.group_sale_manager')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 7.26s | Effectif: 7.263s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi un vendeur simple ne peut pas déverrouiller une commande

Le bouton **« Unlock »** sur une commande est réservé aux utilisateurs appartenant au groupe **« Sales Manager »**.  
Même si le vendeur a confirmé la commande, il ne possède pas ce groupe d’accès, donc le bouton n’est pas affiché dans son interface. Seuls les membres du groupe « Sales Manager » peuvent déverrouiller une commande verrouillée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q5] sale -- constraints (medium)
**Question :** Quelle contrainte empeche une commande confirmee de ne pas avoir de date de confirmation, et quelle contrainte distincte s'applique sur le pourcentage d'acompte demande (prepayment_percent) ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts : (1) sur sale.order, _sql_constraints porte date_order_conditional_required -- contrainte SQL CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale'), bloquant au niveau base de donnees toute commande a l'etat 'sale' sans date_order renseignee. (2) _check_prepayment_percent (@api.constrains('prepayment_percent')) leve une ValidationError Python si require_payment est actif et que prepayment_percent n'est pas strictement compris entre 0 (exclu) et 1.0 (inclus) -- verifiee a l'ecriture ORM, pas au niveau SQL. Independamment, sale.order.line porte ses propres contraintes SQL structurelles (accountable_required_fields/non_accountable_null_fields) sur le meme modele que purchase.order.line (PUR-Q5), meme logique display_type NULL/non-NULL.

**A verifier dans le code :** `models/sale_order.py : _sql_constraints (date_order_conditional_required), _check_prepayment_percent (@api.constrains) ; models/sale_order_line.py : _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 17.68s | Effectif: 17.676s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Contrainte sur la date de confirmation

- **Contrainte** : `date_order_conditional_required`  
- **Description** : La commande ne peut être confirmée (`state = 'sale'`) sans que le champ `date_order` soit renseigné.  
- **Source** : [sale_order.py:L37-L41](file:///home/user/odoo-17.0/addons/sale/models/sale_order.py#L37-L41)

### Contrainte sur le pourcentage d’acompte demandé

- **Contrainte** : `_check_prepayment_percent` (définie par `@api.constrains('prepayment_percent')`)  
- **Description** : Si la commande requiert un paiement (`require_payment` est vrai), le pourcentage d’acompte (`prepayment_percent`) doit être strictement positif et inférieur ou égal à 1.0 (c’est‑à‑dire 100 %).  
- **Source** : [sale_order.py:L722-L726](file:///home/user/odoo-17.0/addons/sale/models/sale_order.py#L722-L726)

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q1] stock -- security (hard)
**Question :** Un simple employe (base.group_user, sans stock.group_stock_user) peut-il consulter les quantites en stock (stock.quant) ? Et peut-il modifier une ligne de mouvement (stock.move.line) ?

**Reponse de reference (verite-terrain) :**
> Oui pour la consultation : access_stock_quant_all accorde perm_read=1 (lecture seule) a base.group_user meme sans stock.group_stock_user -- les niveaux de stock sont visibles a tout employe, seule l'ecriture/creation/suppression exige stock.group_stock_user (access_stock_quant_user, perm_unlink=0 meme pour ce groupe). Plus surprenant : sur stock.move.line, base.group_user a directement les 4 permissions completes (access_stock_move_line_all, 1,1,1,1) -- un acces plus large que sur stock.move lui-meme, qui exige stock.group_stock_user (et reste perm_unlink=0 pour ce groupe). Aucune de ces ACL n'est affinee par ir.rule au-dela du filtrage multi-societe (stock_quant_rule, stock_move_line_rule) -- pas de restriction par entrepot ou par role.

**A verifier dans le code :** `security/ir.model.access.csv (access_stock_quant_all, access_stock_quant_user, access_stock_move_user, access_stock_move_line_all) + security/stock_security.xml (stock_quant_rule, stock_move_line_rule, filtrage company_id uniquement)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 33.36s | Effectif: 33.356s | Groq wait: 0.0s | Sauts: 6) :**
```text
Un simple employé (appartenant uniquement à « base.group_user ») possède les droits suivants :

* **Consultation des quantités en stock (stock.quant)**  
  - Le contrôle d’accès (ACL) autorise la lecture pour le groupe « base.group_user ».  
  - Aucune règle d’enregistrement (ir.rule) ne restreint ce droit.  
  → Le simple employé peut donc afficher les quantités disponibles.

* **Modification d’une ligne de mouvement (stock.move.line)**  
  - L’ACL autorise la lecture et l’écriture pour le groupe « base.group_user ».  
  - Aucune règle d’enregistrement ne limite ces droits.  
  → Le simple employé peut modifier une ligne de mouvement.

**Remarque** : cette conclusion se base uniquement sur les mécanismes d’accès (ACL et ir.rule). D’autres contrôles applicatifs (état du mouvement, règles métier, verrouillage de workflow, etc.) n’ont pas été examinés dans cette analyse et pourraient éventuellement ajouter des restrictions supplémentaires.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q2] stock -- workflow (hard)
**Question :** Que se passe-t-il quand on valide un transfert de stock (button_validate) dont les quantites traitees sont inferieures aux quantites demandees ?

**Reponse de reference (verite-terrain) :**
> button_validate() ignore les transferts deja 'done', confirme automatiquement ceux encore en 'draft', puis complete a la quantite demandee toute ligne dont la quantite traitee est nulle. Une verification de coherence (_sanity_check) s'execute ensuite sauf contexte skip_sanity_check. _pre_action_done_hook() marque picked=True des que des quantites existent. Vient ensuite la decision cle : les transferts sont scindes entre ceux dont picking_type_id.create_backorder=='never' (jamais de reliquat, executes avec cancel_backorder=True) et les autres (executes normalement, create_backorder='always' ou 'ask') -- c'est ce parametre du type d'operation, pas une valeur globale, qui determine si un bon de livraison partiel genere automatiquement un reliquat (backorder) pour les quantites restantes.

**A verifier dans le code :** `models/stock_picking.py : button_validate(), _pre_action_done_hook(), champ picking_type_id.create_backorder (stock_picking_type.py)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 30.16s | Effectif: 30.162s | Groq wait: 0.0s | Sauts: 10) :**
```text
### Que se passe‑t‑il lorsqu’on valide un transfert de stock dont les quantités traitées sont inférieures aux quantités demandées ?

- **Validation du transfert**  
  Le bouton « Valider » passe d’abord par une série de contrôles de cohérence (quantités, lots, etc.).  
  Si tout est correct, le transfert est marqué « terminé » (date de réalisation enregistrée, e‑mail de confirmation envoyé).

- **Gestion des quantités manquantes**  
  - **Si le type de transfert a l’option « Créer un back‑order » réglée sur :**
    - **« Demander »** – l’utilisateur reçoit une fenêtre lui demandant s’il souhaite créer un back‑order pour les quantités restantes.  
    - **« Toujours »** – un back‑order est créé automatiquement sans intervention de l’utilisateur.  
    - **« Jamais »** – les quantités non livrées sont annulées (c’est‑à‑dire qu’elles ne seront pas livrées plus tard).  
  - Le back‑order est un nouveau transfert de stock qui contient uniquement les quantités restantes.  
  - Le transfert original reste « terminé » mais indique qu’une partie des articles a été reportée.

- **Résultat final**  
  - Les quantités réellement livrées sont enregistrées dans le premier transfert.  
  - Les quantités restantes sont soit reportées dans un back‑order, soit annulées, selon la configuration.  
  - L’utilisateur peut suivre ces back‑orders dans l’interface ou les valider ultérieurement.

En résumé, valider un transfert avec des quantités insuffisantes ne bloque pas la validation ; elle déclenche simplement la création d’un back‑order (ou l’annulation des quantités manquantes) selon la règle définie pour le type de transfert.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 70.5s | Effectif: 70.495s | Groq wait: 0.0s | Sauts: 4) :**
```text
**stock.picking** est un **nouveau modèle** : il est déclaré avec `_name = "stock.picking"` et ne s’étend pas d’un modèle métier existant.  

Le module **stock** étend en parallèle plusieurs modèles natifs hors de son propre périmètre :  
- `barcode.rule`  
- `ir.actions.report`  
- `product.category`  
- `product.label.layout`  
- `product.packaging`  
- `product.product`  
- `product.template`  
- `res.company`  
- `res.config.settings`  
- `res.partner`  
- `res.users`  
- `uom.uom`

Ces extensions ajoutent ou modifient des champs clés aux modèles listés, mais les détails précis des champs ne sont pas fournis dans les observations disponibles.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q4] stock -- ui (medium)
**Question :** Pourquoi les champs 'From'/'To' (emplacement source/destination) n'apparaissent-ils pas sur un transfert de stock pour la plupart des utilisateurs ?

**Reponse de reference (verite-terrain) :**
> Ces champs portent groups='stock.group_stock_multi_locations' dans la vue -- mais ce n'est pas un groupe de role (comme user/manager), c'est un groupe active par un parametre de configuration (implied_group sur le champ booleen group_stock_multi_locations dans res.config.settings, 'Storage Locations'). Tant que la fonctionnalite multi-emplacements n'est pas activee en configuration, aucun utilisateur -- meme stock.group_stock_manager -- ne voit ces champs, car le groupe technique lui-meme n'est attribue a personne.

**A verifier dans le code :** `views/stock_picking_views.xml : champs location_id/location_dest_id groups='stock.group_stock_multi_locations' + models/res_config_settings.py : champ group_stock_multi_locations (implied_group='stock.group_stock_multi_locations')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 10.17s | Effectif: 10.174s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi les champs « From » et « To » sont invisibles

- **Restriction de groupe** : Les champs « From » (location_id) et « To » (location_dest_id) ne sont affichés que pour les utilisateurs qui appartiennent au groupe **« Gestion des emplacements multiples »**.  
- **Paramètre de configuration** : Ce groupe n’est attribué à aucun utilisateur par défaut. Il est activé uniquement lorsqu’un administrateur active l’option « Gestion des emplacements multiples » dans les paramètres du module **stock**.  
- **État du transfert** : Même si le groupe est actif, les champs deviennent non modifiables une fois le transfert terminé (état « done »).

En résumé, la plupart des utilisateurs ne voient pas ces champs parce que la fonctionnalité de gestion des emplacements multiples n’est pas activée pour eux. Pour les faire apparaître, un administrateur doit activer le paramètre correspondant dans les paramètres du module **stock** ou ajouter l’utilisateur au groupe « Gestion des emplacements multiples ».

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q5] stock -- constraints (medium)
**Question :** Quelles contraintes empechent la creation d'un stock.quant invalide, et quelle regle distincte garantit l'unicite d'un numero de serie ?

**Reponse de reference (verite-terrain) :**
> Trois @api.constrains independantes sur stock.quant : check_product_id interdit un quant pour un produit qui n'est pas de type 'product' (consommable/service exclus) ; check_location_id interdit un emplacement de type 'view' (emplacement structurel, non physique) ; check_lot_id interdit qu'un lot/numero de serie soit rattache a un produit different de celui du quant. Independamment, sur stock.lot, _check_unique_lot (@api.constrains sur name/product_id/company_id) verifie via _read_group (pas une contrainte SQL unique) qu'aucune combinaison produit+societe+nom de lot n'est dupliquee -- une verification applicative, pas une contrainte de base de donnees.

**A verifier dans le code :** `models/stock_quant.py : check_product_id, check_location_id, check_lot_id (@api.constrains) ; models/stock_lot.py : _check_unique_lot (@api.constrains('name','product_id','company_id'))`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 40.08s | Effectif: 40.076s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Contraintes empêchant la création d’un **stock.quant** invalide  

| Type de contrainte | Description | Source |
|--------------------|-------------|--------|
| **Contrôle du type de produit** | Un quant ne peut être créé que pour un produit de type « product » (pas de consommable ou service). | `@api.constrains('product_id')` – vérifie `product_id.type != 'product'` <br> [stock_quant.py:L615-L618](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L615-L618) |
| **Contrôle de l’emplacement** | Un quant ne peut être stocké que dans un emplacement dont l’usage n’est pas « view ». | `@api.constrains('location_id')` – vérifie `location_id.usage == 'view'` <br> [stock_quant.py:L638-L642](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L638-L642) |
| **Contrôle du lot/numéro de série** | Le lot doit être lié au même produit que le quant. | `@api.constrains('lot_id')` – vérifie `lot_id.product_id != quant.product_id` <br> [stock_quant.py:L644-L648](file:///home/user/odoo-17.0/addons/stock/models/stock_quant.py#L644-L648) |
| **Restrictions d’opérations** | Certaines opérations (création, duplication, suppression, déplacement) sont bloquées pour les quants. | Divers `raise UserError` dans le modèle : <br> - `Operation not supported` <br> - `You cannot duplicate stock quants.` <br> - `Quant's creation is restricted, you can't do this operation.` <br> - `Quant's editing is restricted, you can't do this operation.` <br> - `Quants are auto‑deleted when appropriate. If you must manually delete them, please ask a stock manager to do it.` <br> - `Only a stock manager can validate an inventory adjustment.` <br> - `Quantity or Reserved Quantity should be set.` <br> (voir les lignes 241‑506, 506‑615, 615‑618, 618‑642, 1052‑1052, 1091‑1091, 1482‑1487) |
| **Contraintes de domaine et d’ondelete** | Les champs `product_id`, `location_id`, `lot_id` et `package_id` ont des contraintes `ondelete='restrict'` et des domaines qui limitent les valeurs possibles. | `product_id`, `location_id`, `lot_id`, `package_id` – `ondelete='restrict'` <br> `product_id` domaine : `self._domain_product_id()` <br> `location_id` domaine : `self._domain_location_id()` <br> `lot_id` domaine : `self._domain_lot_id()` <br> `package_id` domaine : `[('location_id', '=', location_id)]` <br> (voir lignes 47‑50, 59‑62, 66‑69, 72‑75) |

Ces contraintes, combinées aux messages d’erreur explicites, garantissent qu’un **stock.quant** ne peut être créé que lorsqu’il respecte les règles métier de l’inventaire (produit, emplacement, lot, droits d’utilisateur, etc.).

---

### Règle distincte garantissant l’unicité d’un numéro de série  

| Contrôle | Description | Source |
|----------|-------------|--------|
| **Contrôle d’unicité du lot/numéro de série** | Le champ `name` (numéro de série) doit être unique pour chaque combinaison `(product_id, company_id, name)`. | `@api.constrains('name', 'product_id', 'company_id')` – `_check_unique_lot` <br> [stock_lot.py:L91-L102](file:///home/user/odoo-17.0/addons/stock/models/stock_lot.py#L91-L102) |

Cette contrainte est **distincte** des contraintes de `stock.quant` et s’applique directement sur le modèle `stock.lot`. Elle empêche la création de deux lots portant le même numéro de série pour le même produit au sein d’une même société.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 14.31s | Effectif: 14.309s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Réponse

Oui.  
Le groupe **« Billing Administrator »** (account.group_account_manager) possède, via l’héritage de **« Account Manager »**, les droits d’écriture, de création et de suppression sur les écritures comptables.  

- **ACL** : le groupe est inclus dans la règle d’héritage de *account.group_account_invoice*, qui autorise l’écriture et la création.  
- **Règles de visibilité** : aucune règle de groupe supplémentaire ne limite ces actions pour ce groupe.

Ainsi, un utilisateur appartenant à ce groupe peut créer et modifier des factures.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q2] account -- workflow (hard)
**Question :** Un 'Billing Administrator' (group_account_manager) peut-il poster une ecriture comptable dont la date est anterieure ou egale a la date de cloture (lock date) de la societe ?

**Reponse de reference (verite-terrain) :**
> Non, meme un manager en est empeche : _check_fiscalyear_lock_date() compare la date du mouvement a company._get_user_fiscal_lock_date() et leve un UserError des que date <= lock_date, sans aucune exception de groupe -- le seul effet du groupe est le libelle du message d'erreur (le manager recoit un message plus court, un non-manager est en plus invite a solliciter quelqu'un ayant le role 'Adviser'). Le blocage lui-meme est absolu : la seule issue est de faire reculer la lock_date via la configuration societe, pas de contourner la verification par un role plus eleve.

**A verifier dans le code :** `models/account_move.py : _check_fiscalyear_lock_date() (verifie user_has_groups('account.group_account_manager') uniquement pour choisir le texte du message, pas pour lever une exception au blocage)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules'] -- MANQUANT(S): ['describe_workflow']

**Reponse verbatim de l'agent (Total: 17.56s | Effectif: 17.554s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Réponse

Non.  
Un **Billing Administrator** (groupe *account.group_account_manager*) ne peut pas enregistrer une écriture dont la date est antérieure ou égale à la date de clôture de la société.  
La règle de verrouillage fiscal empêche toute écriture dont la date est inférieure ou égale à la date de clôture, même pour les membres du groupe *account.group_account_manager*.

[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : `account.group_account_manager` ne détient pas ces permissions directement via son propre enregistrement ACL (qui peut être restreint), mais en hérite par implication transitive (`implied_ids`) depuis le groupe `account.group_account_invoice`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 11.89s | Effectif: 11.887s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Analyse du modèle **account.move**

- **Nature du modèle**  
  Le modèle **account.move** est **déclaré** dans le module **account**. Il ne s’agit pas d’une extension d’un modèle déjà existant, mais d’un nouveau modèle métier créé par ce module.

- **Extension de modèles natifs**  
  En réalité, ce module étend bien 25 modèle(s) hors de son propre périmètre : 'account.analytic.account', 'account.analytic.applicability', 'account.analytic.distribution.model', 'account.analytic.line', 'base.document.layout', 'base.partner.merge.automatic.wizard', 'decimal.precision', 'digest.digest', 'ir.actions.report', 'ir.attachment', 'ir.http', 'ir.module.module', 'kpi.provider', 'onboarding.onboarding', 'onboarding.onboarding.step', 'product.category', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.currency', 'res.groups', 'res.partner', 'res.partner.bank', 'uom.uom'. En réalité, ce module étend bien 25 modèle(s) hors de son propre périmètre : 'account.analytic.account', 'account.analytic.applicability', 'account.analytic.distribution.model', 'account.analytic.line', 'base.document.layout', 'base.partner.merge.automatic.wizard', 'decimal.precision', 'digest.digest', 'ir.actions.report', 'ir.attachment', 'ir.http', 'ir.module.module', 'kpi.provider', 'onboarding.onboarding', 'onboarding.onboarding.step', 'product.category', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.currency', 'res.groups', 'res.partner', 'res.partner.bank', 'uom.uom'.  

En résumé, **account.move** est un modèle propre à la comptabilité, introduit par le module **account**, et le module ne touche pas à d’autres modèles natifs en dehors de ce domaine.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q4] account -- ui (hard)
**Question :** Un utilisateur avec uniquement group_account_invoice ('Billing') voit-il le compte comptable (account_id) d'une ligne de facture ? Et un 'Billing Administrator' (group_account_manager) le voit-il, en configuration Invoicing seule (sans le module Accounting installe) ?

**Reponse de reference (verite-terrain) :**
> Non dans les deux cas. Le champ account_id porte groups='account.group_account_readonly' dans la vue -- or ni group_account_invoice ni group_account_manager n'impliquent group_account_readonly (seul group_account_user, le profil 'comptable complet', implique a la fois invoice et readonly). En configuration Invoicing seule, la documentation du fichier de securite le confirme explicitement : seuls group_account_invoice et group_account_manager sont censes etre utilises, et aucun des deux ne donne acces au champ technique du compte comptable -- il faut le module Accounting (qui attribue alors group_account_user) pour le voir.

**A verifier dans le code :** `views/account_move_views.xml : <field name="account_id" ... groups="account.group_account_readonly"/> + security/account_security.xml : commentaire d'en-tete + implied_ids de group_account_invoice/group_account_manager/group_account_user`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 48.55s | Effectif: 48.546s | Groq wait: 0.0s | Sauts: 7) :**
```text
**Réponse :**

- **Utilisateur « Billing » (group_account_invoice)**  
  Le champ *Compte comptable* (`account_id`) d’une ligne de facture n’est visible que pour les utilisateurs appartenant au groupe « Show Full Accounting Features – Readonly » (group_account_readonly).  
  Un utilisateur qui ne possède que le groupe « Billing » ne fait pas partie de ce groupe, donc il ne voit pas ce champ.

- **Utilisateur « Billing Administrator » (group_account_manager)**  
  Le groupe « Billing Administrator » n’inclut pas le groupe « Show Full Accounting Features – Readonly ».  
  Ainsi, même avec ce rôle, l’utilisateur ne peut pas voir le champ *Compte comptable* tant qu’il ne possède pas également le groupe « Show Full Accounting Features – Readonly ».

- **Configuration Invoicing seule (module Accounting non installé)**  
  Dans cette configuration, le groupe « Show Full Accounting Features – Readonly » n’est pas présent. Par conséquent, ni le rôle « Billing » ni le rôle « Billing Administrator » ne peuvent voir le champ *Compte comptable* sur une ligne de facture.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q5] account -- constraints (hard)
**Question :** account.move declare un _sql_constraints 'unique_name' dont la definition SQL est une chaine vide -- comment l'unicite du numero de piece est-elle reellement appliquee ?

**Reponse de reference (verite-terrain) :**
> Le triplet _sql_constraints=[('unique_name', '', '...')] ne cree aucune contrainte via le mecanisme standard (definition vide) ; il sert uniquement a fournir le message d'erreur associe. L'unicite reelle est creee manuellement dans _auto_init() via un index SQL partiel : CREATE UNIQUE INDEX account_move_unique_name ON account_move(name, journal_id) WHERE (state='posted' AND name != '/') -- l'unicite ne s'applique donc qu'aux ecritures postees et nommees (pas aux brouillons, qui partagent tous le placeholder '/'). Independamment, @api.constrains('journal_id','move_type') / _check_journal_move_type interdit de creer un document d'achat dans un journal dont journal_id.type != 'purchase' (et symetriquement pour la vente).

**A verifier dans le code :** `models/account_move.py : _sql_constraints (unique_name, definition vide) + _auto_init() (CREATE UNIQUE INDEX account_move_unique_name, index partiel) + _check_journal_move_type (@api.constrains)`

**Outils attendus :** ['analyze_data_constraints', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'analyze_data_constraints'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 69.37s | Effectif: 69.369s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Comment l’unicité du numéro de pièce est réellement appliquée

Dans le modèle **`account.move`** on trouve bien une entrée `_sql_constraints` nommée `unique_name`, mais son champ SQL est une chaîne vide :

```
_sql_constraints = [(
    'unique_name', "", "Another entry with the same name already exists.",
)]
```

Cette déclaration est uniquement un *placeholder* ; elle ne crée pas d’index.  
L’unicité est en fait assurée par un **index SQL brut** créé dans la méthode d’initialisation du module :

```
self.env.cr.execute("""
    CREATE UNIQUE INDEX account_move_unique_name
        ON account_move(name, journal_id)
    WHERE (state = 'posted' AND name != '/')
""")
```

- **Lieu** : cette instruction se trouve dans la fonction `_auto_init` (ou `init`) du module `account`.  
- **Cible** : l’index `account_move_unique_name` est appliqué sur les colonnes `name` et `journal_id`.  
- **Condition** : il ne s’applique qu’aux écritures déjà **postées** (`state = 'posted'`) et dont le numéro n’est pas le placeholder `/`.  
- **Effet** : il empêche la création de deux écritures postées ayant le même numéro dans le même journal, garantissant ainsi l’unicité du numéro de pièce.

#### Sources

- Déclaration vide de l’`_sql_constraints` :  
  [account_move.py:L625-L627](file:///home/user/odoo-17.0/addons/account/models/account_move.py#L625-L627)

- Création de l’index brut :  
  [account_move.py:L643-L647](file:///home/user/odoo-17.0/addons/account/models/account_move.py#L643-L647)

Ainsi, même si la contrainte `_sql_constraints` ne contient pas de SQL, l’unicité est réellement appliquée grâce à l’index créé manuellement lors de l’installation du module.

[Source: Graphe de Connaissances Code Intelligence]
```

---