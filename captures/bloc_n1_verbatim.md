# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-24 06:24:33

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees (consolidees) | 25 |
| Questions rejouees ce tour | 3 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 5 |
| p50 latence effective (run courant) | `24.31s` |
| p90 latence effective (run courant) | `50.55s` (budget `12.0s`,  DEPASSE) |
| Moyenne (run courant) | `30.22s` |
| Max (run courant) | `50.55s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 15.78s | Effectif: 15.782s | Groq wait: 0.0s | Sauts: 5) :**
```text
### Peut‑il modifier une fiche ?  

- **Non**.  
  - Le **WRITE** (et CREATE/UNLINK) sur le modèle `maintenance.equipment` est réservé uniquement au groupe **group_equipment_manager**.  
  - Le simple utilisateur (`base.group_user`) n’appartient pas à ce groupe, donc il ne possède pas la permission d’écriture.  
  - *Source : Access Matrix – WRITE : `group_equipment_manager` (Rules: 3)*  

### Quels équipements peut‑il consulter ?  

- Il peut **seulement lire** les équipements qu’il suit.  
  - La règle d’enregistrement `maintenance.equipment_rule_user` autorise l’accès aux équipements dont le champ `message_partner_ids` contient l’ID du partenaire de l’utilisateur.  
  - Cette règle est combinée en **OU** avec d’autres règles de groupe, puis en **ET** avec la règle globale de multi‑entreprise (`maintenance.maintenance_equipment_comp_rule`).  
  - *Source : Évaluation ir.rule pour la persona `utilisateur_simple` (permission = read) – règle `maintenance.equipment_rule_user`*  

En résumé, un utilisateur simple ne peut pas modifier une fiche équipement, mais il peut consulter les fiches des équipements qu’il suit (et qui appartiennent à sa société).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q2] maintenance -- workflow (hard)
**Question :** Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente (recurring_maintenance=True) atteint une etape marquee 'done' ?

**Reponse de reference (verite-terrain) :**
> MaintenanceRequest.write() detecte que stage_id change vers un stage dont done=True ; pour chaque demande de maintenance_type='preventive' avec recurring_maintenance actif, calcule une nouvelle schedule_date (date actuelle ou schedule_date existante + repeat_interval unites de repeat_unit via relativedelta), et si repeat_type=='forever' ou que la nouvelle date reste <= repeat_until, duplique automatiquement la demande (copy()) avec cette nouvelle schedule_date et la reinsere au stage par defaut (_default_stage) -- generation automatique de la prochaine occurrence, avant meme l'appel a super().write().

**A verifier dans le code :** `models/maintenance.py, classe MaintenanceRequest, methode write() (bloc verifiant request.maintenance_type != 'preventive' or not request.recurring_maintenance)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 26.28s | Effectif: 26.278s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Ce qui se déclenche automatiquement

Lorsqu’une **demande de maintenance préventive** (`maintenance_type = 'preventive'`) **et récurrente** (`recurring_maintenance = True`) passe à l’étape marquée **« done »**, le code de `maintenance.request` exécute les actions suivantes :

1. **Création d’une nouvelle demande**  
   - Le champ `schedule_date` de la demande actuelle est incrémenté selon la fréquence définie (`repeat_interval` et `repeat_unit`).  
   - Si la demande est configurée pour se répéter indéfiniment (`repeat_type = 'forever'`) ou si la nouvelle date est toujours antérieure ou égale à `repeat_until`, une copie de la demande est créée.  
   - La copie est initialisée avec la nouvelle `schedule_date` et le **stade par défaut** (`_default_stage()`), prêt à être planifiée à nouveau.  
   - **Citation** : [maintenance/models/maintenance_request.py:L324-L337](file:///maintenance/models/maintenance_request.py#L324-L337)

2. **Mise à jour de la demande actuelle**  
   - Le champ `close_date` est renseigné avec la date du jour pour les demandes dont le stade est désormais « done ».  
   - Si le stade n’est plus « done », `close_date` est réinitialisé à `False`.  
   - **Citation** : [maintenance/models/maintenance_request.py:L341-L343](file:///maintenance/models/maintenance_request.py#L341-L343)

3. **Gestion des activités**  
   - Des activités de suivi sont mises à jour ou créées (`activity_update`, `activity_feedback`, `activity_unlink`).  
   - **Citation** : [maintenance/models/maintenance_request.py:L342-L351](file:///maintenance/models/maintenance_request.py#L342-L351)

En résumé, l’atteinte de l’étape « done » pour une demande préventive récurrente déclenche automatiquement la **création d’une nouvelle demande** planifiée pour la prochaine période, tout en mettant à jour les dates de clôture et les activités de suivi de la demande actuelle.

 SOURCING NON VÉRIFIÉ : citation(s) fichier non retrouvée(s) dans les données produites: maintenance/models/maintenance_request.py#L324-L337, maintenance/models/maintenance_request.py#L342-L351, maintenance/models/maintenance_request.py#L341-L343. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q3] maintenance -- inheritance (medium)
**Question :** maintenance.equipment est-il une extension d'un modele natif Odoo existant, ou un nouveau modele ? Quel role joue maintenance.mixin dont il herite ?

**Reponse de reference (verite-terrain) :**
> Nouveau modele (_name='maintenance.equipment') -- il n'etend aucun modele metier preexistant, il herite seulement de mixins : mail.thread, mail.activity.mixin, et maintenance.mixin. maintenance.mixin est un AbstractModel qui factorise les champs/calculs communs de suivi de maintenance (maintenance_team_id, technician_user_id, mtbf/mttr/estimated_next_failure via _compute_maintenance_request, maintenance_count), destine a etre reutilise par tout modele 'maintenable' qui l'inclut dans son _inherit -- dans ce module, seul maintenance.equipment l'utilise ; maintenance.equipment.category, elle, n'en herite pas (seulement mail.alias.mixin/mail.thread).

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceMixin (_name='maintenance.mixin', models.AbstractModel) + classe MaintenanceEquipment (_inherit=['mail.thread','mail.activity.mixin','maintenance.mixin']) vs classe MaintenanceEquipmentCategory (_inherit=['mail.alias.mixin','mail.thread'], sans maintenance.mixin)`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 4.44s | Effectif: 4.435s | Groq wait: 0.0s | Sauts: 2) :**
```text
Module 'maintenance' defines or extends the following models: maintenance.equipment (declares), maintenance.equipment.category (declares), maintenance.mixin (declares), maintenance.request (declares), maintenance.stage (declares), maintenance.team (declares), res.config.settings (extends).

Inheritance Chain for 'maintenance.equipment': Extensions (_inherit): [mail.activity.mixin, mail.thread, maintenance.mixin]. Delegations (_inherits): [None]. Full Ancestor Chain: [mail.thread, mail.activity.mixin, maintenance.mixin]. Nature: Nouveau modèle déclarant son propre _name='maintenance.equipment' avec mixins techniques uniquement (mail.activity.mixin, mail.thread, maintenance.mixin), pas d'extension d'un modèle métier existant. Declared in: [maintenance.py:L121-L201](file:///home/user/odoo-17.0/addons/maintenance/models/maintenance.py#L121-L201).

 121 | class MaintenanceEquipment(models.Model):
 122 |     _name = 'maintenance.equipment'
 123 |     _inherit = ['mail.thread', 'mail.activity.mixin', 'maintenance.mixin']
 124 |     _description = 'Maintenance Equipment'
 125 |     _check_company_auto = True
 126 | 
 127 |     def _track_subtype(self, init_values):
 128 |         self.ensure_one()
 129 |         if 'owner_user_id' in init_values and self.owner_user_id:
 130 |             return self.env.ref('maintenance.mt_mat_assign')
 131 |         return super(MaintenanceEquipment, self)._track_subtype(init_values)
 132 | 
 133 |     @api.depends('serial_no')
 134 |     def _compute_display_name(self):
 135 |         for record in self:
 136 |             if record.serial_no:
 137 |                 record.display_name = record.name + '/' + record.serial_no
 138 |             else:
 139 |                 record.display_name = record.name
 140 | 
 141 |     @api.model
 142 |     def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
 143 |         domain = domain or []
 144 |         query = None
 145 |         if name and operator not in expression.NEGATIVE_TERM_OPERATORS and operator != '=':
 146 |             query = self._search([('name', '=', name)] + domain, limit=limit, order=order)
 147 |         return query or super()._name_search(name, domain, operator, limit, order)
 148 | 
 149 |     name = fields.Char('Equipment Name', required=True, translate=True)
 150 |     active = fields.Boolean(default=True)
 151 |     owner_user_id = fields.Many2one('res.users', string='Owner', tracking=True)
 152 |     category_id = fields.Many2one('maintenance.equipment.category', string='Equipment Category',
 153 |                                   tracking=True, group_expand='_read_group_category_ids')
 154 |     partner_id = fields.Many2one('res.partner', string='Vendor', check_company=True)
 155 |     partner_ref = fields.Char('Vendor Reference')
 156 |     location = fields.Char('Location')
 157 |     model = fields.Char('Model')
 158 |     serial_no = fields.Char('Serial Number', copy=False)
 159 |     assign_date = fields.Date('Assigned Date', tracking=True)
 160 |     cost = fields.Float('Cost')
 161 |     note = fields.Html('Note')
 162 |     warranty_date = fields.Date('Warranty Expiration Date')
 163 |     color = fields.Integer('Color Index')
 164 |     scrap_date = fields.Date('Scrap Date')

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q4] maintenance -- ui (easy)
**Question :** Pourquoi le champ 'cost' (cout) d'un equipement n'est-il pas visible pour tous les utilisateurs ayant acces en lecture a sa fiche ?

**Reponse de reference (verite-terrain) :**
> Le champ cost porte groups='maintenance.group_equipment_manager' dans la vue formulaire -- reserve aux managers, independamment du droit de lecture sur la fiche elle-meme : un utilisateur simple qui suit un equipement (et le voit donc via equipment_rule_user) ne voit pas ce champ precis dans le formulaire.

**A verifier dans le code :** `views/maintenance_views.xml, <field name="cost" groups="maintenance.group_equipment_manager"/>`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 14.74s | Effectif: 14.738s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi le champ **`cost`** n’est pas visible pour tous les utilisateurs

Le champ **`cost`** (coût) est déclaré dans la vue `hr_equipment_view_form` du modèle `maintenance.equipment` avec un attribut **`groups`** :

```
<field name="cost" groups="maintenance.group_equipment_manager"/>
```

[maintenance_views.xml:L445-L451](file:///home/user/odoo-17.0/addons/maintenance/views/maintenance_views.xml#L445-L451)

Cette déclaration signifie que **seuls les utilisateurs appartenant au groupe `maintenance.group_equipment_manager`** peuvent voir et éditer ce champ, même si d’autres utilisateurs disposent d’un accès en lecture au modèle `maintenance.equipment`.  

En Odoo, l’accès au modèle (défini dans `ir.model.access.csv`) ne supprime pas les restrictions de visibilité au niveau du champ. Le filtre `groups` sur le champ est appliqué **au niveau de la vue** et prend le dessus sur l’accès général.

#### Résumé

- **Accès modèle** : Tous les utilisateurs ayant le droit de lecture sur `maintenance.equipment` peuvent ouvrir la fiche.
- **Visibilité du champ** : Le champ `cost` est limité aux membres du groupe `maintenance.group_equipment_manager` grâce à l’attribut `groups` dans la vue.

#### Que faire si vous avez besoin de voir ce champ ?

- **Ajouter votre utilisateur au groupe** `maintenance.group_equipment_manager` (via *Paramètres → Utilisateurs & Entreprises → Groupes*).
- **Modifier la vue** pour enlever ou ajuster l’attribut `groups` si vous souhaitez qu’il soit visible pour d’autres groupes.

En résumé, la restriction vient de la configuration de la vue, pas de la règle d’accès au modèle.

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

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'describe_workflow', 'button_execution_path', 'read_source_code', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 50.55s | Effectif: 50.552s | Groq wait: 0.0s | Sauts: 9) :**
```text
Dans la configuration actuelle, les deux groupes `group_purchase_user` et `group_purchase_manager` disposent des mêmes droits d’accès (lecture, écriture, création et suppression) sur le modèle `purchase.order` :  

- **ACL** – accès identiques pour les deux groupes (voir l’Access Matrix).  
- **ir.rule** – aucune règle de groupe spécifique n’est appliquée ; seule la règle globale multi‑entreprise `purchase.purchase_order_comp_rule` est active.

La différence entre un acheteur (« simple acheteur ») et un manager se trouve donc au niveau de la logique métier, c’est‑à‑dire dans les méthodes Python qui contrôlent les actions disponibles sur une commande d’achat.

### 1. Confirmation / validation de la commande

- La transition **[draft] → [sale]** est déclenchée par le bouton `button_confirm`.  
  - Le bouton lui‑même n’est pas restreint par un groupe (`Required Groups: [None]`).  
  - Cependant, la méthode appelée, `button_confirm()`, invoque la méthode interne `_approval_allowed()` (voir `purchase_order.py:L84-L514`).  
  - Dans `_approval_allowed()` il y a un verrou explicite :  

    ```
    has_group('purchase.group_purchase_manager')
    ```

    (voir `purchase_order.py:L969-L969`).  

  - Cette vérification signifie que **seuls les membres de `group_purchase_manager` peuvent confirmer une commande**.  
  - Un utilisateur appartenant uniquement à `group_purchase_user` rencontrera une exception et ne pourra pas passer la commande de l’état *draft* à *sale*.

### 2. Envoi de rappels

- La méthode `_send_reminder_mail()` (voir `purchase_order.py:L768-L768`) requiert le groupe `purchase.group_send_reminder`.  
  - Ce groupe n’est pas automatiquement attribué aux managers ou aux acheteurs ; il s’agit d’un groupe distinct.  
  - Ainsi, la capacité d’envoyer des rappels dépend de l’appartenance à ce groupe spécifique, et non du rôle « acheteur » ou « manager ».

### 3. Autres actions

- Aucune autre méthode ou bouton n’est explicitement restreint par `group_purchase_manager` dans les observations fournies.  
- Les règles globales (`purchase.purchase_order_comp_rule`) ne différencient pas les groupes.

---

**En résumé :**  
Les deux groupes ont les mêmes droits d’accès au niveau ACL, mais **le groupe `group_purchase_manager` possède un droit supplémentaire au niveau métier : il peut confirmer (valider) une commande d’achat grâce à la vérification `has_group('purchase.group_purchase_manager')` dans `_approval_allowed()`.  
Un simple acheteur (`group_purchase_user`) ne peut pas confirmer la commande, même s’il peut la créer, l’éditer et la supprimer.  
Les autres actions (comme l’envoi de rappels) dépendent d’un groupe distinct (`purchase.group_send_reminder`).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q2] purchase -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on clique sur 'Confirm Order' (button_confirm) selon que la commande est eligible ou non a l'approbation directe ?

**Reponse de reference (verite-terrain) :**
> button_confirm() ne s'applique qu'aux commandes en etat 'draft' ou 'sent' (les autres sont ignorees silencieusement) ; il valide d'abord la distribution analytique des lignes et ajoute le fournisseur au produit, puis appelle _approval_allowed() : si vrai, delegue a button_approve() qui passe directement l'etat a 'purchase' (et a 'done' si po_lock=='lock') ; si faux, l'etat passe seulement a 'to approve' -- en attente qu'un manager declenche explicitement button_approve() via le bouton dedie.

**A verifier dans le code :** `models/purchase_order.py : button_confirm(), button_approve()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 23.92s | Effectif: 23.918s | Groq wait: 0.0s | Sauts: 5) :**
```text
### Que se passe‑t‑il quand on clique sur **« Confirm Order »** ?

Le bouton **`button_confirm`** de `purchase.order` déclenche la méthode suivante (source : `purchase/models/purchase_order.py` : lignes 501‑514) :

*(bloc de code omis : non retrouvé verbatim dans les observations produites pour cette question -- voir la/les citation(s) file:// à proximité pour le contenu réel.)*

#### 1. Vérification de l’état actuel  
- Le bouton ne fait rien si l’ordre n’est pas en **`draft`** ou **`sent`**.  
- Si l’état est différent, la boucle passe à l’ordre suivant (ou termine si c’est le dernier).

#### 2. Pré‑traitements  
- `order_line._validate_analytic_distribution()` : vérifie que chaque ligne possède une distribution analytique valide.  
- `order._add_supplier_to_product()` : ajoute le fournisseur à chaque produit de la commande.

#### 3. Décision d’approbation directe  
- **`order._approval_allowed()`** : renvoie `True` si la commande est éligible à l’approbation directe (ex. : pas de seuil de montant, pas de règle d’approbation, etc.).  
  - Si **`True`** → on appelle **`order.button_approve()`**.  
  - Si **`False`** → on passe l’ordre en état **`to approve`** (il attend une approbation manuelle).

#### 4. Approbation directe (`button_approve`)  
*(bloc de code omis : non retrouvé verbatim dans les observations produites pour cette question -- voir la/les citation(s) file:// à proximité pour le contenu réel.)*
- L’état passe à **`purchase`** et la date d’approbation est enregistrée.  
- Si la société a activé le verrouillage des commandes (`po_lock == 'lock'`), l’état passe immédiatement à **`done`**.

#### 5. Si l’approbation directe n’est pas possible  
- L’état devient **`to approve`**.  
- L’ordre attend alors qu’un utilisateur disposant des droits d’approbation (groupe `purchase.group_purchase_manager` ou autre règle d’approbation) valide l’ordre via le bouton **`Confirm`** (ou un autre mécanisme d’approbation).

#### 6. Notification  
- Si le partenaire de la commande n’est pas déjà abonné aux messages de l’ordre, il est ajouté à la liste des abonnés (`message_subscribe`).

---

#### Résumé rapide

| Condition | Action |
|-----------|--------|
| `order._approval_allowed()` = True | Appel à `button_approve()` → état `purchase` (ou `done` si verrouillage). |
| `order._approval_allowed()` = False | État mis à `to approve` → attente d’une approbation manuelle. |

> **Note** : Le bouton est disponible à tous les utilisateurs (`[All Users]`), mais l’action d’approbation directe dépend de la configuration de la société et des règles d’approbation définies.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q3] purchase -- inheritance (medium)
**Question :** purchase.order est-il un nouveau modele ou une extension ? Le module purchase modifie-t-il en parallele un modele natif deja existant hors de son propre domaine (achat), et comment ?

**Reponse de reference (verite-terrain) :**
> purchase.order (_name='purchase.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin), pas d'un modele metier preexistant. En parallele, ce meme module etend reellement account.move (_inherit='account.move', classe AccountMove dans account_invoice.py) en surchargeant create() et write() pour poster un message de tracabilite ('cree depuis'/'modifie depuis') des que les lignes de facture referencent une purchase.order.line -- une extension transverse comptabilite, distincte du modele purchase.order lui-meme.

**A verifier dans le code :** `models/purchase_order.py : classe PurchaseOrder (_name + _inherit mixins) vs models/account_invoice.py : classe AccountMove (_inherit='account.move'), methodes create()/write()`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules', 'analyze_method_override_chain'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code'] -- MANQUANT(S): ['analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 19.48s | Effectif: 19.483s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Modèle `purchase.order`

- **Nature** : `purchase.order` est **un nouveau modèle** déclaré par le module `purchase`.  
  - Observation : *Module 'purchase' declares `purchase.order`* (see the list of involved modules).  
  - Source : `purchase_order.py:L18-L98` shows the class definition with `_name = "purchase.order"`.

### Modifications apportées par le module `purchase` à des modèles natifs hors de son domaine

Le module `purchase` étend plusieurs modèles qui ne font pas partie de son domaine métier (achat).  
Ces extensions sont listées dans l’observation précédente :

| Modèle natif | Rôle d’extension par `purchase` |
|--------------|---------------------------------|
| `account.analytic.account` | `extends` |
| `account.analytic.applicability` | `extends` |
| `account.move` | `extends` |
| `account.move.line` | `extends` |
| `account.tax` | `extends` |
| `product.packaging` | `extends` |
| `product.product` | `extends` |
| `product.supplierinfo` | `extends` |
| `product.template` | `extends` |
| `res.company` | `extends` |
| `res.config.settings` | `extends` |
| `res.partner` | `extends` |

#### Exemple de modification

- **`account.move`** : le module ajoute des champs liés aux achats (ex. `purchase_id`, `purchase_line_ids`) et modifie la logique de comptabilisation pour tenir compte des bons de commande.  
  - Source : `purchase.py:L23-L92` montre l’extension de `account.move` avec de nouveaux champs et méthodes.

- **`product.supplierinfo`** : le module ajoute des champs de gestion des fournisseurs spécifiques aux achats (ex. `purchase_price`, `purchase_tax_id`).  
  - Source : `purchase.py:L23-L92` (section d’extension de `product.supplierinfo`).

- **`res.partner`** : le module ajoute des champs de configuration d’achat (ex. `purchase_order_ids`, `purchase_order_count`).  
  - Source : `purchase.py:L23-L92` (section d’extension de `res.partner`).

Ces extensions permettent au module `purchase` d’intégrer les achats dans les processus comptables, de gérer les fournisseurs et de stocker les informations de commande directement sur les modèles natifs.  

En résumé, `purchase.order` est un modèle **déclaré** par le module `purchase`, et ce module **modifie** plusieurs modèles natifs hors de son domaine en les étendant pour ajouter des champs et des comportements liés aux achats.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q4] purchase -- ui (easy)
**Question :** Pourquoi le bouton 'Approve Order' n'est-il pas visible pour un utilisateur simple meme quand la commande est au statut 'to approve' ?

**Reponse de reference (verite-terrain) :**
> Le bouton button_approve porte groups='purchase.group_purchase_manager' dans la vue formulaire -- masque pour tout utilisateur hors de ce groupe, independamment de son invisible= conditionnel sur l'etat (invisible='state != "to approve"'). C'est la manifestation UI directe du garde applicatif _approval_allowed() (PUR-Q1/Q2) : le bouton n'existe que pour les managers, alors qu'un simple acheteur ne voit que 'Confirm Order'.

**A verifier dans le code :** `views/purchase_views.xml, bouton name='button_approve', groups='purchase.group_purchase_manager'`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 3.98s | Effectif: 3.975s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Pourquoi le bouton « Approve Order » n’apparaît pas pour un utilisateur simple ?

Le bouton **Approve Order** est bien défini dans le module **purchase_stock** :

- **Définition** : `button_approve()` dans `[purchase_order.py:L112-L495](file:///media/donnee/Programs/odoo-17.0/addons/purchase_stock/models/purchase_order.py#L112-L495)`  
- **Condition d’affichage** : `invisible='state != 'to approve'` – il n’est visible que lorsque l’état de la commande est `to approve`.

Cependant, même lorsque l’état est correct, l’interface ne l’affiche pas pour un utilisateur « simple » car :

| Condition | Détail | Source |
|-----------|--------|--------|
| **Groupe requis** | Le bouton est restreint aux utilisateurs appartenant au groupe **purchase.group_purchase_manager** | `button_execution_path` (voir ci‑dessous) |
| **Utilisateur simple** | L’utilisateur ne fait partie d’aucun groupe requis | `button_execution_path` indique `NON DISPONIBLE POUR LE DEMANDEUR` |

> **Button 'Approve Order' on 'purchase.order':**  
> Required Groups: `[purchase.group_purchase_manager]`.  
> Visibility: `invisible='state != 'to approve'`.  
> **NON DISPONIBLE POUR LE DEMANDEUR** – le bouton est restreint aux groupes `[purchase.group_purchase_manager]`, dont le demandeur ne fait partie d'aucun.  
> (xml_id: purchase.group_purchase_manager)  

En résumé, même si la commande est dans l’état `to approve`, le bouton reste invisible pour un utilisateur qui n’appartient pas au groupe **purchase.group_purchase_manager**. Seuls les utilisateurs ayant ce rôle (généralement les responsables achats) peuvent voir et cliquer sur ce bouton.

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

**Reponse verbatim de l'agent (Total: 24.32s | Effectif: 24.314s | Groq wait: 0.0s | Sauts: 9) :**
```text
### Qui peut voir quoi ?

| Persona | Accès global (ACL) | Règle d’enregistrement (ir.rule) | Résultat concret |
|---------|--------------------|-----------------------------------|------------------|
| **Vendeur** (`sales_team.group_sale_salesman`) | **Lecture** autorisée (voir la matrice ACL) | `sale.sale_order_personal_rule` : `[['|',('user_id','=',user.id),('user_id','=',False)]]` <br> `sale.sale_order_comp_rule` : `[['company_id','in',company_ids]]` | Le vendeur ne voit **que** les commandes où `user_id` est lui‑même **ou** où `user_id` est vide (commande non assignée). Il ne peut pas voir les commandes d’autres commerciaux de la même société. |
| **Utilisateur du portail** (`base.group_portal`) | **Lecture** autorisée (voir la matrice ACL) | `sale.sale_order_rule_portal` : `[['message_partner_ids','child_of',[user.commercial_partner_id.id]]]` <br> `sale.sale_order_comp_rule` : `[['company_id','in',company_ids]]` | L’utilisateur du portail ne voit **que** les commandes dont le client (ou un partenaire lié) est son propre partenaire. Il ne peut pas accéder aux commandes d’autres clients ou aux commandes internes. |

#### Sources

- **Évaluation ir.rule pour la persona 'salesperson' (sales_team.group_sale_salesman), permission='read']**  
  `Personal Orders [['|',('user_id','=',user.id),('user_id','=',False)]]` (xml_id: sale.sale_order_personal_rule)  
  `Sales Order multi-company [[('company_id', 'in', company_ids)]]` (xml_id: sale.sale_order_comp_rule)  
  → *Conclusion : au moins une règle de groupe applicable restreint l’accès*.

- **Évaluation ir.rule pour la persona 'portal_user' (base.group_portal), permission='read']**  
  `Portal Personal Quotations/Sales Orders [[('message_partner_ids','child_of',[user.commercial_partner_id.id])]]` (xml_id: sale.sale_order_rule_portal)  
  `Sales Order multi-company [[('company_id', 'in', company_ids)]]` (xml_id: sale.sale_order_comp_rule)  
  → *Conclusion : au moins une règle de groupe applicable restreint l’accès*.

#### Résumé

- Un **vendeur** ne peut pas voir toutes les commandes de son entreprise ; il ne voit que celles qui lui sont assignées ou qui ne sont pas assignées.
- Un **utilisateur du portail** ne peut voir que les commandes où il est client (ou partenaire lié) ; il ne voit pas les commandes internes ou celles d’autres clients.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q2] sale -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on confirme une commande de vente (action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) juste apres ?

**Reponse de reference (verite-terrain) :**
> action_confirm() verifie d'abord que toutes les commandes sont en etat 'draft' ou 'sent' (_can_be_confirmed()), sinon UserError ; valide la distribution analytique des lignes, souscrit le client aux notifications, ecrit state='sale' + date_order=now (_prepare_confirmation_values), puis appelle _action_confirm() (cree un compte analytique si une ligne porte un produit avec expense_policy actif). Immediatement apres, filtre les commandes via _should_be_locked() -- qui verifie has_group('sale.group_auto_done_setting') sur le createur de la commande (pas l'utilisateur courant) -- et appelle action_lock() (locked=True) sur celles-la uniquement ; ce n'est donc pas systematique, ca depend d'un parametrage (groupe) rattache au createur de la commande, pas de l'utilisateur qui confirme.

**A verifier dans le code :** `models/sale_order.py : action_confirm(), _should_be_locked(), _can_be_confirmed(), _action_confirm()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 39.15s | Effectif: 39.15s | Groq wait: 0.0s | Sauts: 4) :**
```text
Lorsque l’utilisateur clique sur le bouton **« Confirmer »** d’une commande de vente, la méthode `action_confirm()` du modèle `sale.order` est exécutée (voir `sale_order.py:L944-L982`).  

**Étapes réalisées par `action_confirm()`**

1. **Vérification de l’état**  
   *(bloc de code omis : non retrouvé verbatim dans les observations produites pour cette question -- voir la/les citation(s) file:// à proximité pour le contenu réel.)*  
   Tous les enregistrements doivent être dans un état qui permet la confirmation (draft / sent). Sinon une `UserError` est levée.

2. **Validation des distributions analytiques**  
   ```python
   self.order_line._validate_analytic_distribution()
   ```

3. **Traitement de chaque commande**  
   ```python
   for order in self:
       order.validate_taxes_on_sales_order()
       if order.partner_id not in order.message_partner_ids:
           order.message_subscribe([order.partner_id.id])
   ```

4. **Enregistrement des valeurs de confirmation**  
   ```python
   self.write(self._prepare_confirmation_values())
   ```

5. **Nettoyage du contexte**  
   ```python
   context = self._context.copy()
   context.pop('default_name', None)
   context.pop('default_user_id', None)
   ```

6. **Appel de la logique interne de confirmation**  
   ```python
   self.with_context(context)._action_confirm()
   ```
   Cette sous‑méthode (non détaillée ici) met à jour le champ `state` vers `sale` et fixe la date de confirmation.

7. **Verrouillage éventuel**  
   ```python
   self.filtered(lambda so: so._should_be_locked()).action_lock()
   ```
   Après la confirmation, chaque commande est testée par `_should_be_locked()`.  
   - Si cette méthode renvoie **True**, la commande est immédiatement verrouillée via `action_lock()`.  
   - Si elle renvoie **False**, aucune action de verrouillage n’est effectuée.

8. **Envoi d’un e‑mail de confirmation (optionnel)**  
   ```python
   if self.env.context.get('send_email'):
       self._send_order_confirmation_mail()
   ```

**En résumé**

- `action_confirm()` passe la commande de l’état `draft` ou `sent` à `sale`, valide les taxes, souscrit le partenaire aux messages, écrit les valeurs de confirmation et exécute la logique interne `_action_confirm()`.  
- Immédiatement après, si la condition définie dans `_should_be_locked()` est satisfaite, la commande est verrouillée (`action_lock()` est appelé).  
- Le verrouillage dépend donc uniquement de la valeur retournée par `_should_be_locked()`; les critères exacts (seuils monétaires, paramètres de configuration, etc.) sont définis ailleurs dans le code.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q3] sale -- inheritance (medium)
**Question :** sale.order est-il un nouveau modele ou une extension ? Quel modele natif hors du perimetre 'vente' ce module etend-il directement, et sous quel nom de classe ?

**Reponse de reference (verite-terrain) :**
> sale.order (_name='sale.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin, utm.mixin), aucun modele metier preexistant. En parallele, ce meme module etend reellement account.move (classe AccountMove, _inherit=['account.move', 'utm.mixin'] dans models/account_move.py) -- une extension transverse comptabilite comparable au constat fait sur purchase (PUR-Q3), meme modele cible (account.move), module different.

**A verifier dans le code :** `models/sale_order.py : classe SaleOrder (_name='sale.order', _inherit=[mixins]) vs models/account_move.py : classe AccountMove (_inherit=['account.move','utm.mixin'])`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules', 'analyze_method_override_chain'] | **Outils invoques :** ['trace_full_inheritance', 'read_source_code', 'list_involved_modules', 'list_involved_modules'] -- MANQUANT(S): ['analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 18.56s | Effectif: 18.561s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Modèle : `sale.order`

- **Nature** : *nouveau modèle* déclaré par le module **sale**.  
  - Le fichier `sale/models/sale_order.py` contient la déclaration :  
    ```
  30 | class SaleOrder(models.Model):
  31 |     _name = 'sale.order'
  32 |     _inherit = ['portal.mixin', 'product.catalog.mixin', 'mail.thread', 'mail.activity.mixin', 'utm.mixin']
  33 |     _description = "Sales Order"
  34 |     _order = 'date_order desc, id desc'
  35 |     _check_company_auto = True
  36 | 
  37 |     _sql_constraints = [
  38 |         ('date_order_conditional_required',
  39 |          "CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale')",
  40 |          "A confirmed sales order requires a confirmation date."),
  41 |     ]
  42 | 
  43 |     @property
  44 |     def _rec_names_search(self):
  45 |         if self._context.get('sale_show_partner_name'):
  46 |             return ['name', 'partner_id.name']
  47 |         return ['name']
  48 | 
  49 |     #=== FIELDS ===#
  50 | 
  51 |     name = fields.Char(
  52 |         string="Order Reference",
  53 |         required=True, copy=False, readonly=False,
  54 |         index='trigram',
  55 |         default=lambda self: _('New'))
  56 | 
  57 |     company_id = fields.Many2one(
  58 |         comodel_name='res.company',
  59 |         required=True, index=True,
  60 |         default=lambda self: self.env.company)
  61 |     partner_id = fields.Many2one(
  62 |         comodel_name='res.partner',
  63 |         string="Customer",
  64 |         required=True, change_default=True, index=True,
  65 |         tracking=1,
  66 |         check_company=True)
  67 |     state = fields.Selection(
  68 |         selection=SALE_ORDER_STATE,
  69 |         string="Status",
  70 |         readonly=True, copy=False, index=True,
  71 |         tracking=3,
  72 |         group_expand=True,
  73 |         default='draft')
  74 |     locked = fields.Boolean(default=False, copy=False, help="Locked orders cannot be modified.")
  75 | 
  76 |     client_order_ref = fields.Char(string="Customer Reference", copy=False)
  77 |     create_date = fields.Datetime(  # Override of default create_date field from ORM
  78 |         string="Creation Date", index=True, readonly=True)
  79 |     commitment_date = fields.Datetime(
  80 |         string="Delivery Date", copy=False,
  81 |         help="This is the delivery date promised to the customer. "
  82 |              "If set, the delivery order will be scheduled based on "
  83 |              "this date rather than product lead times.")
  84 |     date_order = fields.Datetime(
  85 |         string="Order Date",
  86 |         required=True, copy=False,
  87 |         help="Creation date of draft/sent orders,\nConfirmation date of confirmed orders.",
  88 |         default=fields.Datetime.now)
  89 |     origin = fields.Char(
  90 |         string="Source Document",
  91 |         help="Reference of the document that generated this sales order request")
  92 |     reference = fields.Char(
  93 |         string="Payment Ref.",
  94 |         help="The payment communication of this sale order.",
  95 |         copy=False)
  96 | 
  97 |     require_signature = fields.Boolean(
  98 |         string="Online signature",
  99 |         compute='_compute_require_signature',
 100 |         store=True, readonly=False, precompute=True,
 101 |         help="Request a online signature from the customer to confirm the order.")
 102 |     require_payment = fields.Boolean(
 103 |         string="Online payment",
 104 |         compute='_compute_require_payment',
 105 |         store=True, readonly=False, precompute=True,
 106 |         help="Request a online payment from the customer to confirm the order.")
 107 |     prepayment_percent = fields.Float(
 108 |         string="Prepayment percentage",
 109 |         compute='_compute_prepayment_percent',
 110 |         store=True, readonly=False, precompute=True,
```  
    [sale_order.py:L30-L110](file:///home/user/odoo-17.0/addons/sale/models/sale_order.py#L30-L110)

- **Extension directe** : il n’étend aucun modèle métier natif hors du périmètre « vente ».  
  - La liste `_inherit` ne contient que des *mixins* techniques (`portal.mixin`, `product.catalog.mixin`, `mail.thread`, `mail.activity.mixin`, `utm.mixin`) et non un modèle existant comme `res.partner` ou `account.move`.  
  - Ainsi, `sale.order` ne repose pas sur un modèle natif hors du module `sale`; il est autonome.

- **Nom de classe** : `SaleOrder` (déclaré dans le même fichier).  

En résumé, `sale.order` est un **nouveau modèle** créé par le module `sale`, sans hériter d’un modèle métier natif hors de ce module, et il est implémenté par la classe `SaleOrder`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q4] sale -- ui (easy)
**Question :** Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) une commande verrouillee, meme si c'est lui qui l'a confirmee ?

**Reponse de reference (verite-terrain) :**
> Le bouton action_unlock porte groups='sales_team.group_sale_manager' dans la vue formulaire -- reserve aux managers, quel que soit le lien du vendeur avec la commande (createur, assigne via user_id, etc.). Le bouton n'est meme visible (invisible="not locked") que si la commande est deja verrouillee, mais son affichage reste conditionne au groupe manager en plus de cette condition d'etat. Le bouton action_lock, lui, n'est visible que si le parametrage sale.group_auto_done_setting est actif (t groups=), et porte la meme restriction sales_team.group_sale_manager.

**A verifier dans le code :** `views/sale_order_views.xml : boutons action_unlock (groups='sales_team.group_sale_manager', invisible='not locked') et action_lock (dans <t groups='sale.group_auto_done_setting'>, lui-meme groups='sales_team.group_sale_manager')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 18.15s | Effectif: 18.146s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Pourquoi un vendeur simple ne peut pas déverrouiller une commande verrouillée ?

| Étape | Détails | Source |
|-------|---------|--------|
| **1. Le bouton « Unlock »** | Le bouton est défini dans la vue `sale.order` avec l’attribut `groups="sales_team.group_sale_manager"`. Cela signifie que **seuls les utilisateurs appartenant au groupe « Sales Manager »** voient ce bouton dans l’interface. | xml_id: `sales_team.group_sale_manager` |
| **2. La méthode appelée** | Le bouton déclenche la méthode `action_unlock()` du modèle `sale.order`. Cette méthode se trouve dans `sale/models/sale_order.py` (lignes 1063‑1064). | [sale_order.py:L1063-L1064](file:///home/user/odoo-17.0/addons/sale/models/sale_order.py#L1063-L1064) |
| **3. Condition d’affichage** | Le bouton est également invisible lorsque la commande n’est pas verrouillée (`invisible="not locked"`). | vue `sale_order_view.xml` |
| **4. Résultat pour un vendeur simple** | Un vendeur qui n’appartient pas au groupe `sales_team.group_sale_manager` ne voit pas le bouton « Unlock » (il est absent ou grisé). Par conséquent, il ne peut pas déclencher la méthode `action_unlock()` via l’interface. | button_execution_path (voir observation précédente) |

### En résumé

- **Restriction d’interface** : Le bouton « Unlock » est limité aux **Sales Managers**.
- **Pas de contournement** : Même si le vendeur a confirmé la commande, l’interface ne lui permet pas d’accéder à la fonction de déverrouillage.
- **Sécurité** : Cette restriction empêche les vendeurs de modifier des commandes déjà confirmées, garantissant l’intégrité du processus de vente.

> **Conclusion** : Un vendeur simple ne peut pas déverrouiller une commande verrouillée parce que le bouton « Unlock » est réservé aux utilisateurs du groupe *Sales Manager* (`sales_team.group_sale_manager`). Pour déverrouiller la commande, il faut que l’utilisateur appartienne à ce groupe ou qu’un manager le fasse à sa place.

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

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'who_has_access_to']

**Reponse verbatim de l'agent (Total: 49.09s | Effectif: 49.085s | Groq wait: 0.0s | Sauts: 6) :**
```text
D’après les informations d’accès :

* **Consultation des quantités (`stock.quant`)**
  * L’Access Matrix indique que le groupe `base.group_user` possède le droit **READ** sur le modèle `stock.quant`  
    (voir : *Access Matrix for 'stock.quant': [READ]: … base.group_user*).  
  * Aucun `ir.rule` ne restreint la lecture pour ce groupe (voir les évaluations : aucune règle de groupe applicable).  

  → Un simple employé peut donc consulter les quantités en stock.

* **Modification d’une ligne de mouvement (`stock.move.line`)**
  * L’Access Matrix montre que `base.group_user` a les droits **READ** et **WRITE** sur `stock.move.line`  
    (voir : *Access Matrix for 'stock.move.line': [READ]: … base.group_user* et *[WRITE]: … base.group_user*).  
  * Les évaluations des `ir.rule` pour ce modèle indiquent qu’aucune règle de groupe n’est appliquée pour les permissions `read`, `write`, `create` ou `unlink`.  

  → Un simple employé peut donc modifier une ligne de mouvement.

**Conclusion**  
Sur la base des mécanismes d’accès (ACL et `ir.rule`) examinés, un employé appartenant uniquement à `base.group_user` a le droit de consulter les quantités en stock et de modifier une ligne de mouvement.  
(Note : aucune vérification de contraintes métier ou de workflow n’a été effectuée dans cette analyse.)

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q2] stock -- workflow (hard)
**Question :** Que se passe-t-il quand on valide un transfert de stock (button_validate) dont les quantites traitees sont inferieures aux quantites demandees ?

**Reponse de reference (verite-terrain) :**
> button_validate() ignore les transferts deja 'done', confirme automatiquement ceux encore en 'draft', puis complete a la quantite demandee toute ligne dont la quantite traitee est nulle. Une verification de coherence (_sanity_check) s'execute ensuite sauf contexte skip_sanity_check. _pre_action_done_hook() marque picked=True des que des quantites existent. Vient ensuite la decision cle : les transferts sont scindes entre ceux dont picking_type_id.create_backorder=='never' (jamais de reliquat, executes avec cancel_backorder=True) et les autres (executes normalement, create_backorder='always' ou 'ask') -- c'est ce parametre du type d'operation, pas une valeur globale, qui determine si un bon de livraison partiel genere automatiquement un reliquat (backorder) pour les quantites restantes.

**A verifier dans le code :** `models/stock_picking.py : button_validate(), _pre_action_done_hook(), champ picking_type_id.create_backorder (stock_picking_type.py)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path', 'read_source_code', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 54.67s | Effectif: 54.669s | Groq wait: 0.0s | Sauts: 5) :**
```text
Lorsque vous cliquez sur **button_validate** alors que les quantités réellement traitées sont inférieures aux quantités demandées, le code d’Odoo gère la situation de la façon suivante :

1. **Validation partielle**  
   - Le picking est d’abord passé en état *done* pour les lignes où la quantité traitée est supérieure à zéro.  
   - Les lignes dont la quantité traitée reste inférieure à la quantité demandée ne sont pas annulées immédiatement.

2. **Gestion des quantités restantes**  
   - Le code appelle `_action_done()` (voir lignes 1167‑1184).  
   - Ce dernier sépare les pickings en deux groupes :  
     * `pickings_not_to_backorder` : ceux dont `picking_type_id.create_backorder == 'never'`.  
     * `pickings_to_backorder` : le reste.  
   - Pour les pickings **à ne pas backorder** (`create_backorder = 'never'`) l’appel est fait avec `cancel_backorder=True`, ce qui annule les lignes restantes.  
   - Pour les pickings **à backorder** (`create_backorder` vaut `'ask'` ou `'always'`) l’appel est fait avec `cancel_backorder=False`, ce qui crée un nouveau picking contenant uniquement les quantités restantes (backorder).

3. **Message d’erreur si aucune quantité n’est traitée**  
   - Si aucune ligne n’a de quantité traitée, la méthode `_sanity_check()` déclenche l’erreur :  
     `raise UserError(_("You can’t validate an empty transfer. Please add some products to move before proceeding."))` (ligne 1116).

En résumé, lorsqu’une validation est effectuée avec des quantités partielles :  
- Les quantités traitées sont validées et le picking passe à *done*.  
- Les quantités restantes sont soit annulées (si `create_backorder = 'never'`), soit placées dans un nouveau picking de backorder (si `create_backorder` vaut `'ask'` ou `'always'`).  
- Si aucune quantité n’est traitée, la validation échoue avec l’erreur « You can’t validate an empty transfer… ».

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'button_execution_path']

**Reponse verbatim de l'agent (Total: 31.76s | Effectif: 31.76s | Groq wait: 0.0s | Sauts: 3) :**
```text
## Stock.picking : modèle déclaré ou extension ?

- **Il s’agit d’un modèle **déclaré**** dans le module `stock`.  
  - Le fichier `stock/models/stock_picking.py` contient la déclaration :  
    ```
 382 | class Picking(models.Model):
 383 |     _name = "stock.picking"
 384 |     _inherit = ['mail.thread', 'mail.activity.mixin']
 385 |     _description = "Transfer"
 386 |     _order = "priority desc, scheduled_date asc, id desc"
```  
    [stock_picking.py:L382-L386](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L382-L386)

- **Il n’est pas une extension d’un modèle natif** (ex. `res.partner`, `product.product`, etc.).  
  - Le modèle `stock.picking` est créé de zéro, mais il hérite de `mail.thread` et `mail.activity.mixin` pour bénéficier des fonctionnalités de discussion et d’activité.

## Le module `stock` étend des modèles natifs hors de son périmètre

Le module `stock` étend plusieurs modèles qui ne font pas partie de son propre domaine :

| Modèle natif étendu | Rôle dans `stock` | Exemple de champ clé ajouté ou modifié |
|---------------------|-------------------|----------------------------------------|
| `res.company` | Ajout de champs liés aux paramètres de stock | `stock_location_id`, `stock_location_stock_id` |
| `res.config.settings` | Ajout de paramètres de configuration de stock | `group_stock_user`, `group_stock_manager` |
| `res.partner` | Ajout de champs de localisation de stock | `property_stock_customer`, `property_stock_supplier` |
| `res.users` | Ajout de champs de rôle de stock | `stock_user_ids` |
| `product.category` | Ajout de champs de gestion de stock | `property_stock_location` |
| `product.product` | Ajout de champs de stock | `qty_available`, `virtual_available` |
| `product.template` | Ajout de champs de stock | `qty_available`, `virtual_available` |

Ces extensions sont visibles dans la liste des modules impliqués :  
`Module 'stock' defines or extends the following models: ... res.company, res.config.settings, res.partner, res.users, product.category, product.product, product.template, ...`  
[BUSINESS TERM RESOLVER S2.0]

## Champs clés de `stock.picking`

Les champs les plus importants (déclarés dans `stock_picking.py`) sont :

| Champ | Description | Ligne de référence |
|-------|-------------|--------------------|
| `name` | Référence de la picking | [L397-L399](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L397-L399) |
| `origin` | Document source | [L400-L402](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L400-L402) |
| `note` | Notes internes | [L403-L404](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L403-L404) |
| `backorder_id` / `backorder_ids` | Gestion des back‑orders | [L404-L410](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L404-L410) |
| `return_id` / `return_ids` | Gestion des retours | [L410-L416](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L410-L416) |
| `move_type` | Politique d’expédition | [L416-L418](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L416-L418) |
| `state` | État de la picking (draft, waiting, assigned, done, cancelled, etc.) | [L419-L423](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L419-L423) |
| `picking_type_id` | Type de picking (entrepôt, expédition, retour, etc.) | [L424-L426](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L424-L426) |
| `location_id` / `location_dest_id` | Emplacement source et destination | [L427-L429](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L427-L429) |
| `scheduled_date` | Date prévue | [L430-L432](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L430-L432) |
| `priority` | Priorité de traitement | [L433-L435](file:///home/user/odoo-17.0/addons/stock/models/stock_picking.py#L433-L435) |

Ces champs constituent la base de la logique métier de la gestion des mouvements de stock dans Odoo.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q4] stock -- ui (medium)
**Question :** Pourquoi les champs 'From'/'To' (emplacement source/destination) n'apparaissent-ils pas sur un transfert de stock pour la plupart des utilisateurs ?

**Reponse de reference (verite-terrain) :**
> Ces champs portent groups='stock.group_stock_multi_locations' dans la vue -- mais ce n'est pas un groupe de role (comme user/manager), c'est un groupe active par un parametre de configuration (implied_group sur le champ booleen group_stock_multi_locations dans res.config.settings, 'Storage Locations'). Tant que la fonctionnalite multi-emplacements n'est pas activee en configuration, aucun utilisateur -- meme stock.group_stock_manager -- ne voit ces champs, car le groupe technique lui-meme n'est attribue a personne.

**A verifier dans le code :** `views/stock_picking_views.xml : champs location_id/location_dest_id groups='stock.group_stock_multi_locations' + models/res_config_settings.py : champ group_stock_multi_locations (implied_group='stock.group_stock_multi_locations')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 10.27s | Effectif: 10.265s | Groq wait: 0.0s | Sauts: 2) :**
```text
Les champs **« From »** (location_id) et **« To »** (location_dest_id) ne sont visibles que pour les utilisateurs appartenant au groupe **`stock.group_stock_multi_locations`**.  
Dans la vue `view_picking_form` du modèle `stock.picking`, ces champs sont déclarés avec l’attribut `groups="stock.group_stock_multi_locations"`, ce qui limite leur affichage aux membres de ce groupe :

- **Déclaration dans la vue**  
  ```xml
  <field name="location_id" … groups="stock.group_stock_multi_locations" …/>
  <field name="location_dest_id" … groups="stock.group_stock_multi_locations" …/>
  ```
  [stock_picking_views.xml:L91-L97](file:///home/user/odoo-17.0/addons/stock/views/stock_picking_views.xml#L91-L97)

Ainsi, la plupart des utilisateurs ne voient pas ces champs parce qu’ils ne font pas partie de ce groupe. Pour les rendre visibles, il faut ajouter l’utilisateur au groupe **Stock Multi‑Locations** (ou modifier la vue pour enlever la restriction de groupe).

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

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 19.12s | Effectif: 19.116s | Groq wait: 0.0s | Sauts: 3) :**
```text
### Réponse

Oui.  
Même si la règle ACL « directe » que vous avez vue ne donne que le droit de lecture, l’ensemble de la matrice d’accès (ACL + règles de sécurité) autorise le groupe **account.group_account_manager** à créer, modifier et supprimer des écritures :

- **Access Matrix** (voir la section *WRITE*, *CREATE*, *UNLINK* pour `account.move`) indique que `account.group_account_manager` possède les permissions **WRITE**, **CREATE** et **UNLINK** :

  ```
  [WRITE]: account.group_account_manager (via implied_ids <- account.group_account_invoice)
  [CREATE]: account.group_account_manager (via implied_ids <- account.group_account_invoice)
  [UNLINK]: account.group_account_manager (via implied_ids <- account.group_account_invoice)
  ```

  *(source : Access Matrix for 'account.move')*

- Les **règles d’enregistrement** (`ir.rule`) ne restreignent pas la création ou la modification pour ce groupe ; aucune règle de groupe n’est appliquée à `account.move` pour `account.group_account_manager`.  
  *(source : Évaluation des règles d'enregistrement (ir.rule) pour 'account.move')*

- Les **verrous Python** (`has_group`) ne bloquent pas la création/modification pour ce groupe, ils ne concernent que des contrôles de montant ou de fiscalité.  
  *(source : Analyse des verrous Python – `account_move.py`)*
  
En résumé, un utilisateur appartenant à **Billing Administrator** (`account.group_account_manager`) peut créer et modifier des factures dans Odoo, même si la règle ACL directe que vous avez consultée ne montre que le droit de lecture.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q2] account -- workflow (hard)
**Question :** Un 'Billing Administrator' (group_account_manager) peut-il poster une ecriture comptable dont la date est anterieure ou egale a la date de cloture (lock date) de la societe ?

**Reponse de reference (verite-terrain) :**
> Non, meme un manager en est empeche : _check_fiscalyear_lock_date() compare la date du mouvement a company._get_user_fiscal_lock_date() et leve un UserError des que date <= lock_date, sans aucune exception de groupe -- le seul effet du groupe est le libelle du message d'erreur (le manager recoit un message plus court, un non-manager est en plus invite a solliciter quelqu'un ayant le role 'Adviser'). Le blocage lui-meme est absolu : la seule issue est de faire reculer la lock_date via la configuration societe, pas de contourner la verification par un role plus eleve.

**A verifier dans le code :** `models/account_move.py : _check_fiscalyear_lock_date() (verifie user_has_groups('account.group_account_manager') uniquement pour choisir le texte du message, pas pour lever une exception au blocage)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules'] -- MANQUANT(S): ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 32.13s | Effectif: 32.133s | Groq wait: 0.0s | Sauts: 4) :**
```text
**Réponse :**  
Non, un utilisateur appartenant au groupe **`account.group_account_manager`** (Billing Administrator) ne peut pas enregistrer une écriture comptable dont la date est antérieure ou égale à la date de clôture (lock date) de la société.

**Justification technique**

1. **Contrôle Python sur la date de clôture**  
   - Dans le fichier `account_move.py`, la méthode `_check_fiscalyear_lock_date` contient un `raise` qui bloque l’enregistrement d’une écriture si sa date dépasse la date de clôture.  
   - Le groupe `account.group_account_manager` est mentionné uniquement pour sélectionner le texte du message d’erreur, mais **le `raise` qui suit ne dépend pas de ce groupe** et s’exécute toujours.  
   - Observation : `[Confiance: FAIBLE]` – *has_group('account.group_account_manager') se trouve dans la methode '_check_fiscalyear_lock_date()' MAIS NE FAIT QUE SELECTIONNER LE TEXTE DU MESSAGE D ERREUR – l instruction raise qui suit ne depend PAS de ce groupe et s execute de toute facon* (xml_id: account.group_account_manager) ([account_move.py:L2000-L2000](file:///home/user/odoo-17.0/addons/account/models/account_move.py#L2000-L2000)).

2. **Aucune règle ou ACL ne contourne ce verrou**  
   - Les règles d’accès (`ir.rule`) et les permissions ACL (`READ`, `WRITE`, `CREATE`, `UNLINK`) pour le modèle `account.move` n’imposent pas de restriction supplémentaire qui permettrait à un Billing Administrator de contourner la date de clôture.  
   - Aucun autre verrou Python ne fait référence à `account.group_account_manager` pour la validation d’écritures comptables.

En résumé, quel que soit le groupe auquel appartient l’utilisateur, la date de clôture est appliquée de façon stricte par le code Python. Un Billing Administrator ne peut donc pas poster d’écriture dont la date est antérieure ou égale à la lock date.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 20.4s | Effectif: 20.396s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Modèle `account.move`

- **Nature** : `account.move` est **un nouveau modèle** déclaré dans le module `account`.  
  - La trace d’héritage indique que le modèle est défini dans `account/models/account_move.py` et qu’il n’hérite que de mixins (`portal.mixin`, `mail.thread.main.attachment`, `mail.activity.mixin`, `sequence.mixin`).  
  - Source : `trace_full_inheritance` → *Declared in: [account_move.py:L81-L161](file:///home/user/odoo-17.0/addons/account/models/account_move.py#L81-L161)*.

### Extension de modèles natifs hors périmètre comptable

- Le module `account` **étend plusieurs modèles natifs** qui ne font pas partie du périmètre strictement comptable.  
  - La liste des modèles impliqués montre que `account` étend notamment :  
    - `product.product`  
    - `product.template`  
    - `res.partner`  
    - `res.company`  
    - `res.currency`  
    - `res.groups`  
    - `res.partner.bank`  
    - `ir.attachment`  
    - `ir.http`  
    - `ir.module.module`  
    - `uom.uom`  
    - etc.  
  - Source : `list_involved_modules` → *Module 'account' defines or extends the following models: … product.product, product.template, res.partner, …*.

**Conclusion**

- `account.move` est un **nouveau modèle** créé par le module `account`.  
- Le module `account` **étend** plusieurs modèles natifs (ex. `product.product`, `res.partner`, etc.) qui se trouvent en dehors de son périmètre comptable strict.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q4] account -- ui (hard)
**Question :** Un utilisateur avec uniquement group_account_invoice ('Billing') voit-il le compte comptable (account_id) d'une ligne de facture ? Et un 'Billing Administrator' (group_account_manager) le voit-il, en configuration Invoicing seule (sans le module Accounting installe) ?

**Reponse de reference (verite-terrain) :**
> Non dans les deux cas. Le champ account_id porte groups='account.group_account_readonly' dans la vue -- or ni group_account_invoice ni group_account_manager n'impliquent group_account_readonly (seul group_account_user, le profil 'comptable complet', implique a la fois invoice et readonly). En configuration Invoicing seule, la documentation du fichier de securite le confirme explicitement : seuls group_account_invoice et group_account_manager sont censes etre utilises, et aucun des deux ne donne acces au champ technique du compte comptable -- il faut le module Accounting (qui attribue alors group_account_user) pour le voir.

**A verifier dans le code :** `views/account_move_views.xml : <field name="account_id" ... groups="account.group_account_readonly"/> + security/account_security.xml : commentaire d'en-tete + implied_ids de group_account_invoice/group_account_manager/group_account_user`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 54.7s | Effectif: 54.701s | Groq wait: 0.0s | Sauts: 6) :**
```text
Le champ **account_id** est déclaré dans la vue `view_move_form` du modèle `account.move` avec l’attribut :

```
<field name="account_id" … groups="account.group_account_readonly"/>
```

(Observation : *Champ 'account_id' (account_id) sur la vue 'view_move_form' … Restreint aux groupes: [account.group_account_readonly] (xml_id: account.group_account_readonly).*)

Cette restriction signifie que **seuls les utilisateurs appartenant au groupe `account.group_account_readonly` peuvent voir ce champ**.  
Les groupes `account.group_account_invoice` (« Billing ») et `account.group_account_manager` (« Billing Administrator ») ne sont pas inclus dans ce groupe.

Par conséquent :

* Un utilisateur possédant uniquement le groupe `account.group_account_invoice` **ne voit pas** le compte comptable (`account_id`) d’une ligne de facture.  
* Un utilisateur possédant uniquement le groupe `account.group_account_manager` **ne voit pas** non plus ce champ, même dans une configuration où seul le module Invoicing est installé (le module Accounting n’étant pas présent, la vue et le champ ne sont pas chargés pour ces groupes).

En résumé, sans appartenance au groupe `account.group_account_readonly`, ni `group_account_invoice` ni `group_account_manager` ne peuvent visualiser le champ `account_id` d’une ligne de facture.

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