# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-26 13:55:01

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees (consolidees) | 25 |
| Questions rejouees ce tour | 5 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 2 |
| p50 latence effective (run courant) | `10.21s` |
| p90 latence effective (run courant) | `17.78s` (budget `12.0s`,  DEPASSE) |
| Moyenne (run courant) | `11.23s` |
| Max (run courant) | `17.78s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 14.98s | Effectif: 14.978s | Groq wait: 0.0s | Sauts: 5) :**
```text
### Accès d’un utilisateur simple à la fiche équipement

- **Modification** :  
  Un utilisateur simple (groupe « Internal User ») **ne peut pas modifier** une fiche équipement. Seuls les membres du groupe « Equipment Manager » disposent des droits d’écriture, de création ou de suppression sur le modèle *maintenance.equipment*.

- **Consultation** :  
  L’utilisateur simple peut consulter uniquement les équipements **qu’il suit**.  
  Cela correspond aux fiches où il apparaît dans la liste des partenaires suivis (champ *message_partner_ids*).  
  Il ne voit pas les équipements qui ne lui sont pas associés, même s’il a le droit de lecture général.

[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : `maintenance.group_equipment_manager` ne détient pas ces permissions directement via son propre enregistrement ACL (qui peut être restreint), mais en hérite par implication transitive (`implied_ids`) depuis le groupe `base.group_user`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q2] maintenance -- workflow (hard)
**Question :** Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente (recurring_maintenance=True) atteint une etape marquee 'done' ?

**Reponse de reference (verite-terrain) :**
> MaintenanceRequest.write() detecte que stage_id change vers un stage dont done=True ; pour chaque demande de maintenance_type='preventive' avec recurring_maintenance actif, calcule une nouvelle schedule_date (date actuelle ou schedule_date existante + repeat_interval unites de repeat_unit via relativedelta), et si repeat_type=='forever' ou que la nouvelle date reste <= repeat_until, duplique automatiquement la demande (copy()) avec cette nouvelle schedule_date et la reinsere au stage par defaut (_default_stage) -- generation automatique de la prochaine occurrence, avant meme l'appel a super().write().

**A verifier dans le code :** `models/maintenance.py, classe MaintenanceRequest, methode write() (bloc verifiant request.maintenance_type != 'preventive' or not request.recurring_maintenance)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 24.06s | Effectif: 24.057s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Ce qui se produit automatiquement

- **Duplication de la demande**  
  Quand la demande de maintenance préventive et récurrente passe à une étape « terminée » (done), Odoo crée **une nouvelle demande**.  
  - La nouvelle demande reçoit une **nouvelle date de planification** calculée en ajoutant l’intervalle de répétition (ex. 1 mois, 3 jours…) à la date actuelle ou à la date de planification précédente.  
  - Elle est placée dans l’étape par défaut du processus de maintenance.

- **Clôture de la demande actuelle**  
  - La demande qui vient d’être terminée obtient une **date de clôture** (aujourd’hui).  
  - Son état Kanban est remis à « normal » pour que l’affichage en tableau Kanban soit cohérent.

- **Mise à jour des activités**  
  - Les activités liées à la demande (telles que les rappels ou notifications) sont recalculées et mises à jour pour refléter le passage à l’état terminé.

- **Gestion des followers**  
  - Les followers ne sont ajoutés que si le créateur ou le technicien de la demande change ; sinon, la liste des followers reste inchangée.

En résumé, lorsqu’une demande préventive et récurrente atteint l’étape « done », Odoo clôt la demande actuelle, crée automatiquement la prochaine occurrence avec la date suivante, et met à jour les activités associées.

- **Condition d’arrêt de la récurrence** : la duplication automatique n'a lieu que si la répétition est configurée sans fin (*repeat_type* = 'forever') ou si la date calculée reste antérieure ou égale à la date limite (*repeat_until*).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q3] maintenance -- inheritance (medium)
**Question :** maintenance.equipment est-il une extension d'un modele natif Odoo existant, ou un nouveau modele ? Quel role joue maintenance.mixin dont il herite ?

**Reponse de reference (verite-terrain) :**
> Nouveau modele (_name='maintenance.equipment') -- il n'etend aucun modele metier preexistant, il herite seulement de mixins : mail.thread, mail.activity.mixin, et maintenance.mixin. maintenance.mixin est un AbstractModel qui factorise les champs/calculs communs de suivi de maintenance (maintenance_team_id, technician_user_id, mtbf/mttr/estimated_next_failure via _compute_maintenance_request, maintenance_count), destine a etre reutilise par tout modele 'maintenable' qui l'inclut dans son _inherit -- dans ce module, seul maintenance.equipment l'utilise ; maintenance.equipment.category, elle, n'en herite pas (seulement mail.alias.mixin/mail.thread).

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceMixin (_name='maintenance.mixin', models.AbstractModel) + classe MaintenanceEquipment (_inherit=['mail.thread','mail.activity.mixin','maintenance.mixin']) vs classe MaintenanceEquipmentCategory (_inherit=['mail.alias.mixin','mail.thread'], sans maintenance.mixin)`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 15.64s | Effectif: 15.633s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Analyse du modèle **maintenance.equipment**

- **Nature du modèle**  
  Le modèle **maintenance.equipment** est un **nouveau modèle**. Il possède son propre nom (`_name = 'maintenance.equipment'`) et ne reprend pas un modèle métier existant d’Odoo. Il ne s’agit donc pas d’une extension d’un modèle natif, mais d’une entité propre à la gestion de l’équipement de maintenance.

- **Rôle du mixin **maintenance.mixin**  
  Le mixin **maintenance.mixin** est un **contributeur technique** qui ajoute des fonctionnalités communes aux objets de maintenance. Il fournit des champs, des méthodes ou des comportements partagés (par ex. gestion de la société, suivi de l’état, etc.) que les modèles de maintenance utilisent pour rester cohérents et éviter la duplication de code. En pratique, il permet aux équipements et aux demandes de maintenance d’hériter de fonctionnalités standardisées sans réécrire le même code.

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

**Reponse verbatim de l'agent (Total: 11.95s | Effectif: 11.951s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi le champ « Cost » n’est pas visible pour tous les utilisateurs

Le champ **Cost** (coût) de l’équipement est affiché uniquement aux membres du groupe **« Equipment Manager »**.  
Même si un utilisateur possède un accès en lecture à la fiche de l’équipement, il ne verra pas ce champ tant qu’il ne fait pas partie de ce groupe.  

En pratique, seuls les utilisateurs désignés comme **Equipment Manager** peuvent consulter ou modifier le coût d’un équipement. Les autres utilisateurs, même avec un accès lecture, ne voient pas ce champ dans l’interface.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q5] maintenance -- constraints (medium)
**Question :** Quelle regle empeche de creer deux equipements avec le meme numero de serie, et quelle contrainte distincte s'applique sur l'intervalle de repetition (repeat_interval) d'une demande recurrente ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts et independants : (1) sur maintenance.equipment, _sql_constraints=[('serial_no','unique(serial_no)', ...)] -- contrainte SQL native (pas @api.constrains) bloquant un second equipement avec le meme serial_no au niveau base de donnees. (2) sur maintenance.request, _check_repeat_interval (@api.constrains('repeat_interval')) leve une ValidationError Python si repeat_interval < 1 -- verifiee a l'ecriture ORM, pas au niveau SQL.

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceEquipment, attribut _sql_constraints ; classe MaintenanceRequest, methode _check_repeat_interval`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 27.77s | Effectif: 27.767s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Règle empêchant les doublons de numéro de série

- **Unicité du numéro de série**  
  Le système ne permet pas de créer deux équipements portant le même numéro de série. Cette règle est appliquée par une contrainte de base de données qui rend le champ *Numéro de série* unique dans la table des équipements.

### Contrainte sur l’intervalle de répétition d’une demande récurrente

- **Intervalle de répétition**  
  Pour une demande récurrente, l’intervalle de répétition (*repeat_interval*) doit être **au moins 1**. Si l’utilisateur saisit une valeur inférieure à 1, le système déclenche une erreur et empêche la sauvegarde de la demande.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 26.1s | Effectif: 26.096s | Groq wait: 0.0s | Sauts: 9) :**
```text
### Différence entre un acheteur et un manager sur une commande d’achat

| Action | Acheteur (group_purchase_user) | Manager (group_purchase_manager) |
|--------|--------------------------------|---------------------------------|
| **Valider une commande** | L’acheteur clique sur « Confirmer la commande ». Si la commande ne respecte pas la règle de double validation (montant supérieur au seuil défini par l’entreprise), elle passe automatiquement dans l’état **« à valider »**. Le manager doit alors l’approuver manuellement. | Le manager peut valider la commande immédiatement, même si le montant dépasse le seuil de double validation. Il n’est pas obligé de passer par l’état « à valider ». |
| **Approuver une commande en attente** | L’acheteur ne peut pas approuver une commande qui est déjà en état « à valider » ; il doit la transmettre au manager. | Le manager peut approuver directement toute commande en état « à valider » grâce à l’action « Approuver ». |
| **Accès aux états** | L’acheteur voit les commandes dans les états « brouillon », « envoyé », « à valider », « validé », etc., mais ne peut pas les approuver. | Le manager a la même visibilité mais possède l’autorité supplémentaire d’approuver et de passer les commandes à l’état « validé » sans passer par le seuil de double validation. |

En résumé, même si les deux groupes disposent des mêmes droits de lecture, écriture, création et suppression, le **manager** possède un droit supplémentaire d’**approbation directe** et peut **bypasser** la règle de double validation, ce qui lui permet de finaliser les commandes plus rapidement que l’acheteur.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q2] purchase -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on clique sur 'Confirm Order' (button_confirm) selon que la commande est eligible ou non a l'approbation directe ?

**Reponse de reference (verite-terrain) :**
> button_confirm() ne s'applique qu'aux commandes en etat 'draft' ou 'sent' (les autres sont ignorees silencieusement) ; il valide d'abord la distribution analytique des lignes et ajoute le fournisseur au produit, puis appelle _approval_allowed() : si vrai, delegue a button_approve() qui passe directement l'etat a 'purchase' (et a 'done' si po_lock=='lock') ; si faux, l'etat passe seulement a 'to approve' -- en attente qu'un manager declenche explicitement button_approve() via le bouton dedie.

**A verifier dans le code :** `models/purchase_order.py : button_confirm(), button_approve()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'analyze_method_override_chain', 'read_source_code', 'read_source_code', 'analyze_method_override_chain', 'read_source_code', 'read_source_code', 'describe_workflow', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 81.17s | Effectif: 81.173s | Groq wait: 0.0s | Sauts: 14) :**
```text
### Que se passe‑t‑il quand on clique sur **« Confirm Order »** ?

1. **Vérification de l’état**  
   Le bouton ne s’exécute que si la commande est en état **« draft »** ou **« sent »**.  
   Si l’état est différent, rien ne se produit.

2. **Pré‑traitements**  
   - La répartition analytique de chaque ligne est validée.  
   - Le fournisseur de la commande est ajouté à la liste des fournisseurs du produit (si ce n’est pas déjà le cas).  
   - Un message est envoyé au fournisseur pour l’informer de la commande.

3. **Test d’éligibilité à l’approbation directe**  
   La méthode `_approval_allowed()` détermine si la commande peut être approuvée immédiatement :  
   - **Un seul niveau d’approbation** (`po_double_validation = 'one_step'`) ;  
   - **Deux niveaux** mais le montant total est **inférieur** au seuil défini par l’entreprise ;  
   - **Ou** l’utilisateur appartient au groupe **responsable des achats** (`purchase.group_purchase_manager`).

4. **Si la commande est éligible**  
   - La méthode `button_approve()` est appelée.  
   - L’état passe à **« purchase »** (ou à **« done »** si l’entreprise a activé le verrou `po_lock`).  
   - La date d’approbation est enregistrée.  
   - La commande est considérée comme approuvée et prête à être traitée (livraison, facturation, etc.).

5. **Si la commande n’est pas éligible**  
   - L’état est mis à **« to approve »**.  
   - La commande attend l’approbation d’un responsable des achats.  
   - Aucun verrou supplémentaire n’est appliqué ; la commande reste dans l’état « to approve » jusqu’à ce qu’un utilisateur du groupe responsable des achats l’approuve.

En résumé, **« Confirm Order »** prépare la commande, vérifie si elle peut être approuvée immédiatement, et la place soit dans l’état approuvé, soit dans l’état d’attente d’approbation.

[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut également le/les module(s) suivant(s), absent(s) ou mal identifié(s) ci-dessus : 'purchase_stock', 'sale_order_type', 'sale_stock', 'sale'. Fait extrait directement de l'analyse statique du code.

[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne de surcharge : module 'purchase_stock' : branche conditionnelle `order.state in ('draft', 'sent', 'to approve', 'purchase') / order_line.move_dest_ids / moves_to_unlink` avec super() rappelé inconditionnellement (risque d'annulation silencieuse de cette logique) ; module 'sale_order_type' : branche conditionnelle `vals.get('type_id') / record.state in {'draft', 'sent'} and record.type_id.sequence_id != sale_type.sequence_id and (not ignore_default_sequence)` avec super() rappelé inconditionnellement (risque d'annulation silencieuse de cette logique) ; module 'sale_stock' : branche conditionnelle `'commitment_date' in values` avec super() rappelé inconditionnellement (risque d'annulation silencieuse de cette logique). Fait extrait directement de l'analyse statique du code.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q3] purchase -- inheritance (medium)
**Question :** purchase.order est-il un nouveau modele ou une extension ? Le module purchase modifie-t-il en parallele un modele natif deja existant hors de son propre domaine (achat), et comment ?

**Reponse de reference (verite-terrain) :**
> purchase.order (_name='purchase.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin), pas d'un modele metier preexistant. En parallele, ce meme module etend reellement account.move (_inherit='account.move', classe AccountMove dans account_invoice.py) en surchargeant create() et write() pour poster un message de tracabilite ('cree depuis'/'modifie depuis') des que les lignes de facture referencent une purchase.order.line -- une extension transverse comptabilite, distincte du modele purchase.order lui-meme.

**A verifier dans le code :** `models/purchase_order.py : classe PurchaseOrder (_name + _inherit mixins) vs models/account_invoice.py : classe AccountMove (_inherit='account.move'), methodes create()/write()`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules', 'analyze_method_override_chain'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code'] -- MANQUANT(S): ['analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 17.54s | Effectif: 17.539s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Modèle : `purchase.order`

- **Nature** : `purchase.order` est un **nouveau modèle**.  
  Il possède son propre nom (`_name = "purchase.order"`) et ne s’étend qu’à des mixins techniques (mail.thread, mail.activity.mixin, portal.mixin, product.catalog.mixin).  
  Il ne reprend pas la définition d’un modèle métier existant.

### Impact du module `purchase` sur d’autres modèles natifs

Le module **`purchase`** modifie plusieurs modèles natifs qui ne font pas partie de son domaine d’achat.  
Ces extensions se font en ajoutant des champs et en surchargeant des méthodes :

| Modèle natif | Ajouts / Modifications |
|--------------|------------------------|
| **`account.move`** | Ajout des champs `purchase_order_count`, `purchase_id`, `purchase_vendor_bill_id`. Surcharge des méthodes de création, d’écriture et de calcul des liens entre factures et bons de commande. |
| **`account.move.line`** | Ajout des champs `purchase_line_id`, `purchase_order_id`. Surcharge de la méthode de copie pour conserver les liens avec les bons de commande. |
| **`product.product`** | Ajout du champ `purchased_product_qty`. Surcharge du calcul de cette quantité et ajout d’une action pour afficher les bons de commande liés. |
| **`product.template`** | Ajout des champs `purchased_product_qty`, `purchase_line_warn`, `purchase_line_warn_msg`, `purchase_method`. Surcharge du calcul de la méthode d’achat, de la quantité achetée et de l’affichage des bons de commande. |
| **`account.tax`** | Surcharge de la méthode de calcul pour tenir compte des règles d’achat. |

Ces modifications permettent d’associer les bons de commande aux factures, aux produits et aux taxes, et d’afficher les informations pertinentes dans l’interface d’achat.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q4] purchase -- ui (easy)
**Question :** Pourquoi le bouton 'Approve Order' n'est-il pas visible pour un utilisateur simple meme quand la commande est au statut 'to approve' ?

**Reponse de reference (verite-terrain) :**
> Le bouton button_approve porte groups='purchase.group_purchase_manager' dans la vue formulaire -- masque pour tout utilisateur hors de ce groupe, independamment de son invisible= conditionnel sur l'etat (invisible='state != "to approve"'). C'est la manifestation UI directe du garde applicatif _approval_allowed() (PUR-Q1/Q2) : le bouton n'existe que pour les managers, alors qu'un simple acheteur ne voit que 'Confirm Order'.

**A verifier dans le code :** `views/purchase_views.xml, bouton name='button_approve', groups='purchase.group_purchase_manager'`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 10.21s | Effectif: 10.21s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Pourquoi le bouton « Approve Order » n’apparaît pas pour un utilisateur simple

- **Restriction de groupe** : Le bouton est réservé aux membres du groupe **« Administrator »** (groupe *purchase.group_purchase_manager*).  
- **Condition d’état** : Il ne s’affiche que lorsque la commande est en statut **« to approve »**.  
- **En pratique** : Même si la commande est prête à être approuvée, un utilisateur qui n’appartient pas au groupe « Administrator » ne voit pas le bouton, car il ne possède pas les droits requis pour l’utiliser.  

Pour pouvoir approuver la commande, l’utilisateur doit être ajouté au groupe « Administrator » ou un responsable ayant ce rôle doit le faire.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q5] purchase -- constraints (medium)
**Question :** Quelles regles empechent de supprimer une commande d'achat ou une de ses lignes selon leur etat, et quelle contrainte SQL distincte s'applique sur les lignes elles-memes ?

**Reponse de reference (verite-terrain) :**
> Deux gardes @api.ondelete(at_uninstall=False) distincts : _unlink_if_cancelled sur purchase.order leve UserError si l'etat n'est pas 'cancel' (impossible de supprimer une commande active, il faut d'abord l'annuler) ; _unlink_except_purchase_or_done sur purchase.order.line leve UserError si la commande parente est en etat 'purchase' ou 'done'. Independamment, _sql_constraints sur purchase.order.line impose par CHECK SQL que les champs comptables (product_id/product_uom/date_planned) soient tous renseignes pour une ligne 'accountable' (display_type NULL) et tous vides pour une ligne section/note (display_type non NULL) -- integrite structurelle, pas une regle de suppression.

**A verifier dans le code :** `models/purchase_order.py : _unlink_if_cancelled (@api.ondelete) ; models/purchase_order_line.py : _unlink_except_purchase_or_done (@api.ondelete) + _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 44.45s | Effectif: 44.451s | Groq wait: 0.0s | Sauts: 2) :**
```text
**Supprimer une commande d’achat**

- **État requis** : une commande ne peut être supprimée que lorsqu’elle est dans l’état **« Annulée »**.  
  - Si vous essayez de supprimer une commande qui n’est pas annulée, le système affiche :  
    *« In order to delete a purchase order, you must cancel it first. »*  
- **Vérification supplémentaire** : avant d’annuler une commande, le système vérifie qu’aucune facture fournisseur liée n’existe.  
  - Si des factures sont présentes, l’annulation (et donc la suppression) est bloquée par le message :  
    *« Unable to cancel this purchase order. You must first cancel the related vendor bills. »*  

En résumé, pour supprimer une commande d’achat, il faut d’abord l’annuler (état « Annulée ») et s’assurer qu’aucune facture fournisseur n’est liée à cette commande.

---

**Supprimer une ligne de commande d’achat**

- **Contraintes SQL** : chaque ligne de commande est soumise à deux contraintes CHECK qui garantissent l’intégrité des données :
  1. **`accountable_required_fields`** – pour les lignes « comptabilisables », les champs `product_id`, `product_uom` et `date_planned` doivent être renseignés.  
  2. **`non_accountable_null_fields`** – pour les lignes « non comptabilisables », ces mêmes champs doivent rester vides (ou à zéro) et ne pas contenir de valeurs.  

Ces contraintes empêchent la création ou la modification de lignes qui ne respectent pas ces règles, assurant ainsi que chaque ligne possède les informations nécessaires selon son type.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q1] sale -- security (hard)
**Question :** Un vendeur (sales_team.group_sale_salesman, sans group_sale_salesman_all_leads) peut-il voir toutes les commandes de vente de son entreprise, ou seulement certaines ? Et un utilisateur du portail (base.group_portal) ?

**Reponse de reference (verite-terrain) :**
> Non pour le vendeur simple : l'ACL access_sale_order lui donne perm_read/write/create=1 (pas perm_unlink), mais l'ir.rule sale_order_personal_rule le restreint aux commandes ou user_id lui est assigne ou user_id est vide (domaine OR) ; seul un vendeur avec en plus group_sale_salesman_all_leads herite de sale_order_see_all (domaine (1,'=',1), tout voir). Pour le portail : ACL access_sale_order_portal en lecture seule (perm_read=1, tout le reste 0), combinee a sale_order_rule_portal qui restreint aux commandes ou le partenaire (ou un enfant commercial) figure dans message_partner_ids -- avec ici perm_write/perm_unlink actives via la regle elle-meme (perm_write=True, perm_unlink=True dans la regle), ce qui autorise l'ecriture/suppression via la regle malgre l'ACL en lecture seule, en pratique borne au flux portail (ex. wizard d'annulation).

**A verifier dans le code :** `security/ir.model.access.csv (access_sale_order, access_sale_order_portal) + security/ir_rules.xml (sale_order_personal_rule, sale_order_see_all, sale_order_rule_portal)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 8.98s | Effectif: 8.975s | Groq wait: 0.0s | Sauts: 9) :**
```text
### Accès aux commandes de vente

| Rôle | Accès aux commandes de l’entreprise |
|------|--------------------------------------|
| **Vendeur (groupe « User : Own Documents Only ») ** | Peut uniquement consulter les commandes dont il est le client ou le commercial ; il ne voit pas les commandes d’autres vendeurs. |
| **Utilisateur du portail (groupe « Portal ») ** | Peut uniquement consulter les commandes auxquelles il est lié en tant que partenaire de discussion (message partner). Il ne voit pas les commandes d’autres clients ou vendeurs. |

En résumé, un vendeur ne peut pas voir toutes les commandes de son entreprise, seulement celles qui lui sont directement attribuées. Un utilisateur du portail ne voit que les commandes auxquelles il est associé en tant que partenaire de discussion.

[FAIT DÉTERMINISTIQUE] Un utilisateur appartenant en plus au groupe `sales_team.group_sale_salesman_all_leads` ('User: All Documents') ne serait plus soumis à cette restriction : la règle 'All Orders' (xml_id: sale.sale_order_see_all) lève alors toute limitation pour ce modèle.

 GROUPE(S) NON VÉRIFIÉ(S) : sales_team.group_sale_salesman_all_leads mentionné(s) dans la réponse sans correspondance has_group() dans les données produites pour cette question. Ne pas considérer ce(s) groupe(s) comme confirmé(s) sans vérification manuelle.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q2] sale -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on confirme une commande de vente (action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) juste apres ?

**Reponse de reference (verite-terrain) :**
> action_confirm() verifie d'abord que toutes les commandes sont en etat 'draft' ou 'sent' (_can_be_confirmed()), sinon UserError ; valide la distribution analytique des lignes, souscrit le client aux notifications, ecrit state='sale' + date_order=now (_prepare_confirmation_values), puis appelle _action_confirm() (cree un compte analytique si une ligne porte un produit avec expense_policy actif). Immediatement apres, filtre les commandes via _should_be_locked() -- qui verifie has_group('sale.group_auto_done_setting') sur le createur de la commande (pas l'utilisateur courant) -- et appelle action_lock() (locked=True) sur celles-la uniquement ; ce n'est donc pas systematique, ca depend d'un parametrage (groupe) rattache au createur de la commande, pas de l'utilisateur qui confirme.

**A verifier dans le code :** `models/sale_order.py : action_confirm(), _should_be_locked(), _can_be_confirmed(), _action_confirm()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_method_override_chain', 'read_source_code', 'read_source_code', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 56.76s | Effectif: 56.754s | Groq wait: 0.0s | Sauts: 12) :**
```text
### Que se passe‑t‑il quand on clique sur **« Confirmer »** ?

- **Changement d’état** : la commande passe de *Brouillon* ou *Pro‑forma* à *Confirmée* (état « sale »).  
- **Date de confirmation** : la date de la commande est fixée à la date et l’heure actuelles.  
- **Notification** : le client est automatiquement ajouté aux discussions de la commande et, si l’option « Envoyer par e‑mail » est activée, un e‑mail de confirmation est envoyé.  
- **Comptabilité analytique** : si la commande contient des produits qui génèrent des frais, un compte analytique est créé pour la commande.  
- **Envoi de la facture** : la commande reste en état *Confirmée* jusqu’à ce qu’une facture soit créée (ou qu’une autre action la transforme en *Terminée*).  

### Quand la commande est‑elle verrouillée ?

Après la confirmation, le système vérifie si l’utilisateur qui a créé la commande possède le **groupe « Lock Confirmed Sales »** (paramètre de configuration *group_auto_done_setting*).  
- **Si oui** : la commande est automatiquement verrouillée (le champ *Verrouillé* passe à VRAI).  
- **Si non** : la commande reste modifiable.

Le verrouillage empêche toute modification ultérieure de la commande tant que le champ *Verrouillé* est actif.  
Cette règle est appliquée uniquement à la commande qui vient d’être confirmée et ne dépend pas d’autres groupes ou rôles.

[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut également le/les module(s) suivant(s), absent(s) ou mal identifié(s) ci-dessus : 'sale_order_type', 'sale_stock'. Fait extrait directement de l'analyse statique du code.

[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne de surcharge : module 'sale_order_type' : branche conditionnelle `vals.get('type_id') / record.state in {'draft', 'sent'} and record.type_id.sequence_id != sale_type.sequence_id and (not ignore_default_sequence)` avec super() rappelé inconditionnellement (risque d'annulation silencieuse de cette logique) ; module 'sale_stock' : branche conditionnelle `'commitment_date' in values` avec super() rappelé inconditionnellement (risque d'annulation silencieuse de cette logique). Fait extrait directement de l'analyse statique du code.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q3] sale -- inheritance (medium)
**Question :** sale.order est-il un nouveau modele ou une extension ? Quel modele natif hors du perimetre 'vente' ce module etend-il directement, et sous quel nom de classe ?

**Reponse de reference (verite-terrain) :**
> sale.order (_name='sale.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin, utm.mixin), aucun modele metier preexistant. En parallele, ce meme module etend reellement account.move (classe AccountMove, _inherit=['account.move', 'utm.mixin'] dans models/account_move.py) -- une extension transverse comptabilite comparable au constat fait sur purchase (PUR-Q3), meme modele cible (account.move), module different.

**A verifier dans le code :** `models/sale_order.py : classe SaleOrder (_name='sale.order', _inherit=[mixins]) vs models/account_move.py : classe AccountMove (_inherit=['account.move','utm.mixin'])`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code', 'list_involved_modules', 'list_involved_modules', 'inspect_module_extensions']

**Reponse verbatim de l'agent (Total: 23.98s | Effectif: 23.976s | Groq wait: 0.0s | Sauts: 6) :**
```text
### Modèle « sale.order »

- **Nature** : *nouveau modèle* – il ne reprend pas un modèle métier existant, mais définit son propre nom (`sale.order`) et ne contient que des mixins techniques (mail, portail, catalogue produit, etc.).

### Extension hors du périmètre « vente »

- Le module **account_invoice_section_sale_order** étend directement les modèles natifs suivants :
  - **res.company** – classe `ResCompany` (dans `models/res_company.py`)
  - **res.partner** – classe `ResPartner` (dans `models/res_partner.py`)

Ces extensions ajoutent des champs et des comportements liés à la facturation par section, mais ne touchent pas le cœur du module de vente.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q4] sale -- ui (easy)
**Question :** Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) une commande verrouillee, meme si c'est lui qui l'a confirmee ?

**Reponse de reference (verite-terrain) :**
> Le bouton action_unlock porte groups='sales_team.group_sale_manager' dans la vue formulaire -- reserve aux managers, quel que soit le lien du vendeur avec la commande (createur, assigne via user_id, etc.). Le bouton n'est meme visible (invisible="not locked") que si la commande est deja verrouillee, mais son affichage reste conditionne au groupe manager en plus de cette condition d'etat. Le bouton action_lock, lui, n'est visible que si le parametrage sale.group_auto_done_setting est actif (t groups=), et porte la meme restriction sales_team.group_sale_manager.

**A verifier dans le code :** `views/sale_order_views.xml : boutons action_unlock (groups='sales_team.group_sale_manager', invisible='not locked') et action_lock (dans <t groups='sale.group_auto_done_setting'>, lui-meme groups='sales_team.group_sale_manager')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 8.54s | Effectif: 8.536s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi un vendeur simple ne peut pas déverrouiller une commande verrouillée

- **Le bouton « Unlock » n’est visible que lorsqu’une commande est verrouillée.**  
- **Seuls les utilisateurs appartenant au groupe « Administrator » (groupe *sales_team.group_sale_manager*) peuvent cliquer sur ce bouton.**  
- Un vendeur simple n’appartient pas à ce groupe, même s’il a confirmé la commande.  
- Par conséquent, le bouton « Unlock » n’apparaît pas dans son interface et il ne peut pas déverrouiller la commande.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q5] sale -- constraints (medium)
**Question :** Quelle contrainte empeche une commande confirmee de ne pas avoir de date de confirmation, et quelle contrainte distincte s'applique sur le pourcentage d'acompte demande (prepayment_percent) ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts : (1) sur sale.order, _sql_constraints porte date_order_conditional_required -- contrainte SQL CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale'), bloquant au niveau base de donnees toute commande a l'etat 'sale' sans date_order renseignee. (2) _check_prepayment_percent (@api.constrains('prepayment_percent')) leve une ValidationError Python si require_payment est actif et que prepayment_percent n'est pas strictement compris entre 0 (exclu) et 1.0 (inclus) -- verifiee a l'ecriture ORM, pas au niveau SQL. Independamment, sale.order.line porte ses propres contraintes SQL structurelles (accountable_required_fields/non_accountable_null_fields) sur le meme modele que purchase.order.line (PUR-Q5), meme logique display_type NULL/non-NULL.

**A verifier dans le code :** `models/sale_order.py : _sql_constraints (date_order_conditional_required), _check_prepayment_percent (@api.constrains) ; models/sale_order_line.py : _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 20.47s | Effectif: 20.471s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Contrainte sur la date de confirmation

- **Quand une commande est confirmée** (état : *sale*), le système impose que la date de confirmation soit renseignée.  
- Si la date est manquante, la base de données rejette l’opération et l’utilisateur reçoit un message d’erreur indiquant qu’une commande confirmée doit obligatoirement avoir une date de confirmation.

### Contrainte sur le pourcentage d’acompte (prepayment_percent)

- **Si la commande nécessite un acompte** (`require_payment` est activé), le pourcentage d’acompte doit être compris entre 0 % et 100 % (exprimé sous forme décimale : 0 < prepayment_percent ≤ 1,0).  
- Toute valeur en dehors de cette plage déclenche une erreur de validation qui empêche la sauvegarde de la commande.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q1] stock -- security (hard)
**Question :** Un simple employe (base.group_user, sans stock.group_stock_user) peut-il consulter les quantites en stock (stock.quant) ? Et peut-il modifier une ligne de mouvement (stock.move.line) ?

**Reponse de reference (verite-terrain) :**
> Oui pour la consultation : access_stock_quant_all accorde perm_read=1 (lecture seule) a base.group_user meme sans stock.group_stock_user -- les niveaux de stock sont visibles a tout employe, seule l'ecriture/creation/suppression exige stock.group_stock_user (access_stock_quant_user, perm_unlink=0 meme pour ce groupe). Plus surprenant : sur stock.move.line, base.group_user a directement les 4 permissions completes (access_stock_move_line_all, 1,1,1,1) -- un acces plus large que sur stock.move lui-meme, qui exige stock.group_stock_user (et reste perm_unlink=0 pour ce groupe). Aucune de ces ACL n'est affinee par ir.rule au-dela du filtrage multi-societe (stock_quant_rule, stock_move_line_rule) -- pas de restriction par entrepot ou par role.

**A verifier dans le code :** `security/ir.model.access.csv (access_stock_quant_all, access_stock_quant_user, access_stock_move_user, access_stock_move_line_all) + security/stock_security.xml (stock_quant_rule, stock_move_line_rule, filtrage company_id uniquement)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'who_has_access_to']

**Reponse verbatim de l'agent (Total: 31.84s | Effectif: 31.84s | Groq wait: 0.0s | Sauts: 6) :**
```text
Un employé qui ne possède que le groupe « Internal User » (base.group_user) a les droits suivants :

* **Consultation des quantités en stock (stock.quant)**  
  Le groupe « Internal User » est autorisé à lire les enregistrements de stock.quant.  
  → **Oui, il peut consulter les quantités en stock.**

* **Modification d’une ligne de mouvement (stock.move.line)**  
  La lecture est permise pour le groupe « Internal User », mais la modification (write) n’est autorisée que pour les groupes « User » et « Administrator » du module de gestion des stocks (stock.group_stock_user / stock.group_stock_manager).  
  → **Non, il ne peut pas modifier une ligne de mouvement.**

En résumé : un simple employé peut voir les quantités en stock, mais il ne possède pas les droits nécessaires pour modifier les lignes de mouvement.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q2] stock -- workflow (hard)
**Question :** Que se passe-t-il quand on valide un transfert de stock (button_validate) dont les quantites traitees sont inferieures aux quantites demandees ?

**Reponse de reference (verite-terrain) :**
> button_validate() ignore les transferts deja 'done', confirme automatiquement ceux encore en 'draft', puis complete a la quantite demandee toute ligne dont la quantite traitee est nulle. Une verification de coherence (_sanity_check) s'execute ensuite sauf contexte skip_sanity_check. _pre_action_done_hook() marque picked=True des que des quantites existent. Vient ensuite la decision cle : les transferts sont scindes entre ceux dont picking_type_id.create_backorder=='never' (jamais de reliquat, executes avec cancel_backorder=True) et les autres (executes normalement, create_backorder='always' ou 'ask') -- c'est ce parametre du type d'operation, pas une valeur globale, qui determine si un bon de livraison partiel genere automatiquement un reliquat (backorder) pour les quantites restantes.

**A verifier dans le code :** `models/stock_picking.py : button_validate(), _pre_action_done_hook(), champ picking_type_id.create_backorder (stock_picking_type.py)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'read_source_code', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 83.21s | Effectif: 83.212s | Groq wait: 0.0s | Sauts: 10) :**
```text
### Que se passe‑t‑il lorsqu’on valide un transfert de stock dont les quantités traitées sont inférieures aux quantités demandées ?

Lorsque vous cliquez sur **Valider** (bouton *button_validate*) :

1. **Validation partielle**  
   - Les mouvements dont la quantité disponible est suffisante sont marqués comme *fait*.
   - Les mouvements qui ne peuvent pas être complétés restent en attente.

2. **Gestion des quantités restantes**  
   - **Si le paramètre « Créer un back‑order » est réglé sur « Toujours »**  
     → Odoo crée automatiquement un nouveau transfert contenant uniquement les quantités restantes.  
   - **Si le paramètre est réglé sur « Demander »**  
     → Un assistant apparaît vous demandant si vous souhaitez créer un back‑order ou annuler les quantités restantes.  
   - **Si le paramètre est réglé sur « Jamais »**  
     → Les quantités non traitées sont annulées et ne seront pas prises en compte dans le transfert final.

3. **Résultat final**  
   - Le transfert original passe à l’état **« terminé »** pour les mouvements validés.  
   - Un ou plusieurs nouveaux transferts (back‑orders) peuvent être créés pour les quantités restantes, selon le réglage ci‑dessus.  
   - Si aucune quantité n’est disponible du tout, un message d’erreur vous informe qu’il n’y a rien à valider.

En résumé, la validation d’un transfert avec des quantités insuffisantes ne bloque pas l’opération ; elle crée automatiquement (ou vous propose de créer) un back‑order pour les quantités manquantes, ou les annule si le paramètre le demande.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code', 'button_execution_path']

**Reponse verbatim de l'agent (Total: 22.25s | Effectif: 22.246s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Modèle : `stock.picking`

- **Nature** : *Nouveau modèle* – il possède son propre nom (`_name = "stock.picking"`) et ne s’étend pas d’un modèle métier existant.  
- **Héritage technique** : il hérite uniquement des mixins `mail.thread` et `mail.activity.mixin`, qui ajoutent la messagerie et les activités, mais ne modifient pas la logique métier principale.

### Extensions du module `stock` sur des modèles natifs

Le module `stock` étend plusieurs modèles natifs hors de son périmètre propre. Les champs clés ajoutés sont :

| Modèle natif | Champs ajoutés (principaux) |
|--------------|-----------------------------|
| `product.product` | `free_qty`, `incoming_qty`, `outgoing_qty`, `qty_available`, `reordering_max_qty`, `reordering_min_qty` |
| `product.template` | `has_available_route_ids`, `incoming_qty`, `outgoing_qty`, `qty_available`, `reordering_max_qty`, `reordering_min_qty` |
| `uom.uom` | (aucun champ supplémentaire, mais des méthodes de gestion des quantités sont surchargées) |
| `product.category` | `filter_for_stock_putaway_rule`, `packaging_reserve_method`, `putaway_rule_ids`, `removal_strategy_id`, `route_ids`, `total_route_ids` |
| `product.packaging` | `package_type_id`, `route_ids` |

Ces ajouts permettent de gérer les quantités disponibles, les règles de réapprovisionnement, les itinéraires de stockage et les types de colis directement depuis les modèles de produit et de catégorie.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q4] stock -- ui (medium)
**Question :** Pourquoi les champs 'From'/'To' (emplacement source/destination) n'apparaissent-ils pas sur un transfert de stock pour la plupart des utilisateurs ?

**Reponse de reference (verite-terrain) :**
> Ces champs portent groups='stock.group_stock_multi_locations' dans la vue -- mais ce n'est pas un groupe de role (comme user/manager), c'est un groupe active par un parametre de configuration (implied_group sur le champ booleen group_stock_multi_locations dans res.config.settings, 'Storage Locations'). Tant que la fonctionnalite multi-emplacements n'est pas activee en configuration, aucun utilisateur -- meme stock.group_stock_manager -- ne voit ces champs, car le groupe technique lui-meme n'est attribue a personne.

**A verifier dans le code :** `views/stock_picking_views.xml : champs location_id/location_dest_id groups='stock.group_stock_multi_locations' + models/res_config_settings.py : champ group_stock_multi_locations (implied_group='stock.group_stock_multi_locations')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 7.67s | Effectif: 7.67s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi les champs « From » et « To » sont invisibles

Les champs **« From »** (emplacement source) et **« To »** (emplacement destination) ne sont affichés que pour les utilisateurs qui appartiennent au groupe **« Manage Multiple Stock Locations »**.  
La plupart des utilisateurs ne font pas partie de ce groupe, d’où l’invisibilité de ces champs sur les transferts de stock.  

Si vous avez besoin de voir ou de modifier ces emplacements, demandez à votre responsable de vous ajouter à ce groupe ou contactez le service informatique pour qu’il le fasse.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q5] stock -- constraints (medium)
**Question :** Quelles contraintes empechent la creation d'un stock.quant invalide, et quelle regle distincte garantit l'unicite d'un numero de serie ?

**Reponse de reference (verite-terrain) :**
> Trois @api.constrains independantes sur stock.quant : check_product_id interdit un quant pour un produit qui n'est pas de type 'product' (consommable/service exclus) ; check_location_id interdit un emplacement de type 'view' (emplacement structurel, non physique) ; check_lot_id interdit qu'un lot/numero de serie soit rattache a un produit different de celui du quant. Independamment, sur stock.lot, _check_unique_lot (@api.constrains sur name/product_id/company_id) verifie via _read_group (pas une contrainte SQL unique) qu'aucune combinaison produit+societe+nom de lot n'est dupliquee -- une verification applicative, pas une contrainte de base de donnees.

**A verifier dans le code :** `models/stock_quant.py : check_product_id, check_location_id, check_lot_id (@api.constrains) ; models/stock_lot.py : _check_unique_lot (@api.constrains('name','product_id','company_id'))`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 26.24s | Effectif: 26.237s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Contraintes empêchant la création d’un **stock.quant** invalide  

- **Produit** : le quant ne peut être créé que pour un produit de type « Produit » (pas de consommable ou de service).  
- **Emplacement** : l’emplacement ne doit pas être de type « Vue » (usage = view).  
- **Lot / Numéro de série** : si un lot est associé, son produit doit être le même que celui du quant.  
- **Quantité** : la quantité et la quantité réservée doivent être renseignées et la quantité doit être positive.  
- **Déplacement** : on ne peut déplacer que des quantités positives stockées dans des emplacements appartenant à une seule société.  
- **Validation d’inventaire** : seule la personne ayant le rôle de « Gestionnaire de stock » peut valider un ajustement d’inventaire.  
- **Création / Duplication** : il n’est pas possible de dupliquer un quant, de créer un quant en dehors des opérations autorisées, ou de modifier un quant si l’opération n’est pas prise en charge.  

Ces règles sont appliquées automatiquement lors de la création ou de la modification d’un quant, et un message d’erreur s’affiche si l’une d’elles est violée.

---

### Règle garantissant l’unicité d’un numéro de série  

- **Lot / Numéro de série** : la combinaison *numéro de série + produit + société* doit être unique.  
  - Si un doublon est détecté, un message d’erreur indique les combinaisons en conflit et empêche la création ou la modification du lot.  

Cette règle assure que chaque numéro de série est unique au sein d’une société pour un produit donné.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 13.87s | Effectif: 13.866s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Réponse

Oui.  
Même si la règle d’accès directe ne mentionne que la lecture, le groupe **« Billing Administrator »** (account.group_account_manager) possède bien les droits d’écriture, de création et de suppression sur les écritures comptables.  

Ces droits sont accordés grâce aux règles d’accès qui regroupent ce groupe avec d’autres groupes de facturation (par exemple « Billing »). Aucun filtre de visibilité supplémentaire ne limite ces actions.  

En pratique, un utilisateur appartenant à « Billing Administrator » peut donc créer, modifier et supprimer des factures dans Odoo.

[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : `account.group_account_manager` ne détient pas ces permissions directement via son propre enregistrement ACL (qui peut être restreint), mais en hérite par implication transitive (`implied_ids`) depuis le groupe `account.group_account_invoice`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q2] account -- workflow (hard)
**Question :** Un 'Billing Administrator' (group_account_manager) peut-il poster une ecriture comptable dont la date est anterieure ou egale a la date de cloture (lock date) de la societe ?

**Reponse de reference (verite-terrain) :**
> Non, meme un manager en est empeche : _check_fiscalyear_lock_date() compare la date du mouvement a company._get_user_fiscal_lock_date() et leve un UserError des que date <= lock_date, sans aucune exception de groupe -- le seul effet du groupe est le libelle du message d'erreur (le manager recoit un message plus court, un non-manager est en plus invite a solliciter quelqu'un ayant le role 'Adviser'). Le blocage lui-meme est absolu : la seule issue est de faire reculer la lock_date via la configuration societe, pas de contourner la verification par un role plus eleve.

**A verifier dans le code :** `models/account_move.py : _check_fiscalyear_lock_date() (verifie user_has_groups('account.group_account_manager') uniquement pour choisir le texte du message, pas pour lever une exception au blocage)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules'] -- MANQUANT(S): ['describe_workflow']

**Reponse verbatim de l'agent (Total: 15.44s | Effectif: 15.442s | Groq wait: 0.0s | Sauts: 4) :**
```text
### Réponse

Non.  
Un utilisateur du groupe **« Billing Administrator »** (account.group_account_manager) ne peut pas enregistrer une écriture comptable dont la date est antérieure ou égale à la date de clôture (lock date) de la société.  

Lors de la validation d’une écriture, Odoo vérifie la date par rapport à la date de verrouillage de l’entreprise. Si la date de l’écriture est inférieure ou égale à cette date, un message d’erreur s’affiche et l’opération est bloquée, quel que soit le groupe auquel appartient l’utilisateur.  

En pratique, il faut attendre que la date de l’écriture dépasse la date de clôture avant de pouvoir la poster.

[FAIT DÉTERMINISTIQUE] Précision d'héritage de droits : `account.group_account_manager` ne détient pas ces permissions directement via son propre enregistrement ACL (qui peut être restreint), mais en hérite par implication transitive (`implied_ids`) depuis le groupe `account.group_account_invoice`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'inspect_module_extensions', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 18.6s | Effectif: 18.593s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Modèle account.move

- **Nature** : *nouveau modèle* déclaré dans le module **account**.  
  Il hérite de plusieurs mixins (portal, mail, sequence, etc.) mais ne ré‑utilise pas un modèle existant.

### Extensions du module account hors de son périmètre comptable

Oui, le module **account** étend plusieurs modèles natifs qui ne font pas partie de la logique comptable :

| Modèle natif | Classe Python | Champs ajoutés | Méthodes ajoutées |
|--------------|---------------|----------------|-------------------|
| `product.product` | `ProductProduct` | `tax_string` | `_compute_tax_string`, `_get_product_accounts`, `_get_tax_included_unit_price`, `_get_tax_included_unit_price_from_price`, `_retrieve_product` |
| `product.template` | `ProductTemplate` | `account_tag_ids`, `fiscal_country_codes`, `property_account_expense_id`, `property_account_income_id`, `supplier_taxes_id`, `tax_string` | `_compute_fiscal_country_codes`, `_compute_tax_string`, `create`, `_check_uom_not_in_invoice`, `_construct_tax_string`, `_force_default_purchase_tax` |
| `uom.uom` | `UoM` | `fiscal_country_codes` | `_compute_fiscal_country_codes`, `_get_unece_code` |
| `product.category` | `ProductCategory` | `property_account_expense_categ_id`, `property_account_income_categ_id` | – |
| `decimal.precision` | `DecimalPrecision` | – | `precision_get` |

Ces extensions montrent que le module **account** touche des modèles qui ne sont pas strictement liés à la comptabilité, mais qui sont utilisés dans d’autres domaines (gestion des produits, unités de mesure, etc.).

À noter : ce module étend bien 25 modèle(s) hors de son propre périmètre : 'account.analytic.account', 'account.analytic.applicability', 'account.analytic.distribution.model', 'account.analytic.line', 'base.document.layout', 'base.partner.merge.automatic.wizard', 'decimal.precision', 'digest.digest', 'ir.actions.report', 'ir.attachment', 'ir.http', 'ir.module.module', 'kpi.provider', 'onboarding.onboarding', 'onboarding.onboarding.step', 'product.category', 'product.product', 'product.template', 'res.company', 'res.config.settings', 'res.currency', 'res.groups', 'res.partner', 'res.partner.bank', 'uom.uom'.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q4] account -- ui (hard)
**Question :** Un utilisateur avec uniquement group_account_invoice ('Billing') voit-il le compte comptable (account_id) d'une ligne de facture ? Et un 'Billing Administrator' (group_account_manager) le voit-il, en configuration Invoicing seule (sans le module Accounting installe) ?

**Reponse de reference (verite-terrain) :**
> Non dans les deux cas. Le champ account_id porte groups='account.group_account_readonly' dans la vue -- or ni group_account_invoice ni group_account_manager n'impliquent group_account_readonly (seul group_account_user, le profil 'comptable complet', implique a la fois invoice et readonly). En configuration Invoicing seule, la documentation du fichier de securite le confirme explicitement : seuls group_account_invoice et group_account_manager sont censes etre utilises, et aucun des deux ne donne acces au champ technique du compte comptable -- il faut le module Accounting (qui attribue alors group_account_user) pour le voir.

**A verifier dans le code :** `views/account_move_views.xml : <field name="account_id" ... groups="account.group_account_readonly"/> + security/account_security.xml : commentaire d'en-tete + implied_ids de group_account_invoice/group_account_manager/group_account_user`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 17.78s | Effectif: 17.777s | Groq wait: 0.0s | Sauts: 6) :**
```text
### Accès au champ « Compte comptable » (account_id)

- **Utilisateur « Billing » (group_account_invoice)**  
  Ce groupe ne possède pas le droit d’afficher le champ *account_id*. Seuls les utilisateurs du groupe **« Show Accounting Features – Readonly »** (group_account_readonly) peuvent le voir.

- **Utilisateur « Billing Administrator » (group_account_manager)**  
  Même si ce groupe a des droits d’administration, il n’est pas inclus dans *group_account_readonly*. Par conséquent, dans une configuration « Invoicing » seule (sans le module Accounting installé), il ne peut pas voir le champ *account_id* non plus.

En résumé, ni le groupe « Billing » ni le groupe « Billing Administrator » ne voient le compte comptable d’une ligne de facture à moins d’appartenir au groupe « Show Accounting Features – Readonly ».

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q5] account -- constraints (hard)
**Question :** account.move declare un _sql_constraints 'unique_name' dont la definition SQL est une chaine vide -- comment l'unicite du numero de piece est-elle reellement appliquee ?

**Reponse de reference (verite-terrain) :**
> Le triplet _sql_constraints=[('unique_name', '', '...')] ne cree aucune contrainte via le mecanisme standard (definition vide) ; il sert uniquement a fournir le message d'erreur associe. L'unicite reelle est creee manuellement dans _auto_init() via un index SQL partiel : CREATE UNIQUE INDEX account_move_unique_name ON account_move(name, journal_id) WHERE (state='posted' AND name != '/') -- l'unicite ne s'applique donc qu'aux ecritures postees et nommees (pas aux brouillons, qui partagent tous le placeholder '/'). Independamment, @api.constrains('journal_id','move_type') / _check_journal_move_type interdit de creer un document d'achat dans un journal dont journal_id.type != 'purchase' (et symetriquement pour la vente).

**A verifier dans le code :** `models/account_move.py : _sql_constraints (unique_name, definition vide) + _auto_init() (CREATE UNIQUE INDEX account_move_unique_name, index partiel) + _check_journal_move_type (@api.constrains)`

**Outils attendus :** ['analyze_data_constraints', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'read_source_code', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 71.17s | Effectif: 71.165s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Comment l’unicité du numéro de pièce est réellement appliquée

Dans le modèle **account.move**, la contrainte `_sql_constraints` nommée `unique_name` contient une chaîne SQL vide.  
Cette contrainte n’est donc pas utilisée pour garantir l’unicité du champ **name**.

L’unicité est assurée par un **index unique** créé directement dans la base de données :

- **Index** : `account_move_unique_name`  
- **Colonnes** : `name` et `journal_id`  
- **Condition** : l’index ne s’applique qu’aux écritures dont l’état est « posted » et dont le nom n’est pas « / ».

Cet index est créé lors de l’installation du module `account` (dans la méthode `_auto_init` ou `init`).  
Il garantit que, dès qu’une écriture est validée (passée en état *posted*), son numéro de pièce est unique dans le journal correspondant, empêchant ainsi les doublons au niveau de la base de données.

[Source: Graphe de Connaissances Code Intelligence]
```

---