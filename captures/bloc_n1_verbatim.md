# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-23 11:41:17

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees (consolidees) | 15 |
| Questions rejouees ce tour | 3 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 3 |
| p50 latence effective (run courant) | `22.53s` |
| p90 latence effective (run courant) | `35.7s` (budget `12.0s`,  DEPASSE) |
| Moyenne (run courant) | `26.02s` |
| Max (run courant) | `35.7s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 284.63s | Effectif: 284.625s | Groq wait: 0.0s | Sauts: 5) :**
```text
**Réponse**

- **Modification (WRITE) d’une fiche equipment (`maintenance.equipment`) :**  
  L’ACL indique que seul le groupe `group_equipment_manager` possède le droit d’écriture (`[WRITE]: group_equipment_manager`).  
  Un utilisateur qui ne fait partie que de `base.group_user` ne dispose donc pas du droit d’écriture, même si une règle de groupe (voir ci‑dessous) lui permettrait d’accéder à certains enregistrements.  
  **Conclusion :** un utilisateur simple ne peut pas modifier une fiche équipement.

- **Consultation (READ) des fiches equipment :**  
  1. **ACL READ** autorise `base.group_user` à lire les équipements.  
  2. **Règle globale** (`maintenance.maintenance_equipment_comp_rule`) impose la restriction multi‑entreprise : `company_id` doit appartenir aux entreprises de l’utilisateur ou être vide.  
  3. **Règle de groupe** (`maintenance.equipment_rule_user`) limite l’accès aux équipements dont le champ `message_partner_ids` contient le partenaire de l’utilisateur : `('message_partner_ids', 'in', [user.partner_id.id])`.  
  4. La règle d’administrateur (`maintenance.equipment_rule_admin_user`) est ignorée pour les utilisateurs non membres.

  Ainsi, un utilisateur simple peut consulter **seuls** les équipements qu’il suit (c’est‑à‑dire ceux dont son partenaire apparaît dans `message_partner_ids`), sous réserve de la restriction multi‑entreprise.

En résumé :

| Action | Autorisé pour `base.group_user` (sans `group_equipment_manager`) |
|--------|-----------------------------------------------------------------|
| **Lire** | Oui, mais uniquement les équipements qu’il suit (`message_partner_ids`). |
| **Modifier** | Non, le droit d’écriture est réservé à `group_equipment_manager`. |

Cette conclusion est basée sur l’ACL et l’évaluation des règles `ir.rule` présentées dans les observations. Aucun autre mécanisme (workflow, verrou Python, etc.) n’a été vérifié dans cette analyse.

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

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 35.7s | Effectif: 35.701s | Groq wait: 0.0s | Sauts: 6) :**
```text
## Différences concrètes entre **group_purchase_user** et **group_purchase_manager** sur un `purchase.order`

| Fonctionnalité | **group_purchase_user** (acheteur) | **group_purchase_manager** (manager) |
|----------------|------------------------------------|--------------------------------------|
| **Créer / modifier / supprimer** | Autorisé (ACL) | Autorisé (ACL) |
| **Valider une commande** |  <ul><li>Appuie sur **« Confirm Order »** → `button_confirm()`</li><li>Si la commande n’est pas en double validation, elle passe directement à l’état *to approve*.</li><li>Si la commande est en double validation, l’utilisateur doit attendre l’approbation d’un manager.</li></ul> |  <ul><li>Appuie sur **« Confirm Order »** → `button_confirm()`</li><li>La méthode `_approval_allowed()` renvoie **True** dès que l’utilisateur appartient à `purchase.group_purchase_manager` (voir code ci‑dessous).</li><li>La commande passe immédiatement à l’état *approved* (ou *sale* selon la configuration).</li></ul> |
| **Approbation** |  <ul><li>Peut appeler **« Approve »** uniquement si la commande est déjà en état *to approve* et que la règle de double validation le permet.</li></ul> |  <ul><li>Peut appeler **« Approve »** directement depuis l’état *draft* ou *sent* grâce à `_approval_allowed()`.</li></ul> |
| **Déverrouiller une commande** |  Non disponible (bouton **« Unlock »** nécessite `purchase.group_purchase_manager`). |  Disponible (bouton **« Unlock »** → `button_unlock()`). |
| **Autres actions** |  Toutes les actions disponibles à tous les utilisateurs (définir à brouillon, annuler, créer facture, etc.). |  Même ensemble d’actions, plus celles mentionnées ci‑dessus. |

### Points clés du code

- **`button_confirm()`** (défini dans `purchase_order.py` lignes 501‑514) :  
  ```python
  if order._approval_allowed():
      order.button_approve()
  else:
      order.write({'state': 'to approve'})
  ```
  *Citation :* [purchase_order.py:L501-L514](file:///home/user/odoo-17.0/addons/purchase/models/purchase_order.py#L501-L514)

- **`_approval_allowed()`** (défini lignes 960‑969) :  
  ```python
  return (
      self.company_id.po_double_validation == 'one_step'
      or (self.company_id.po_double_validation == 'two_step'
          and self.amount_total < self.env.company.currency_id._convert(
              self.company_id.po_double_validation_amount, self.currency_id, self.company_id,
              self.date_order or fields.Date.today()))
      or self.user_has_groups('purchase.group_purchase_manager'))
  ```
  *Citation :* [purchase_order.py:L960-L969](file:///home/user/odoo-17.0/addons/purchase/models/purchase_order.py#L960-L969)

  Cette fonction permet aux managers de contourner la double validation (qu’elle soit à un ou deux niveaux) grâce à la présence du groupe `purchase.group_purchase_manager`.

- **`button_unlock()`** (défini dans `purchase_order.py` lignes 1070‑1075) :  
  *(bloc de code omis : la plage citée (L960-L969, L1070-L1075) n'a pas pu être rattachée à la définition de `button_unlock` -- citation à ne pas considérer comme confirmée.)*
  *Citation :* [purchase_order.py:L1070-L1075](file:///home/user/odoo-17.0/addons/purchase/models/purchase_order.py#L1070-L1075)

  Ce bouton est protégé par `purchase.group_purchase_manager` (voir le workflow).

### Résumé

- **Acheteur (`group_purchase_user`)** :  
  - Peut créer, modifier, supprimer des commandes.  
  - Peut confirmer une commande, mais si la double validation est activée, la commande passe en état *to approve* et attend l’approbation d’un manager.  
  - Ne peut pas déverrouiller une commande verrouillée.

- **Manager (`group_purchase_manager`)** :  
  - Toutes les permissions de l’acheteur.  
  - Peut **bypass** la double validation et approuver directement les commandes.  
  - Peut **déverrouiller** les commandes verrouillées.  
  - Dispose de toutes les actions supplémentaires liées à la gestion des commandes (ex. approbation, déverrouillage).

En pratique, la différence se situe donc dans la capacité du manager à **valider et déverrouiller** les commandes sans passer par le processus de double validation, ce qui n’est pas possible pour un simple acheteur.

 SOURCING NON VÉRIFIÉ : citation(s) fichier non retrouvée(s) dans les données produites: home/user/odoo-17.0/addons/purchase/models/purchase_order.py#L1070-L1075. Ne pas considérer ces éléments comme confirmés pour cette question.

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

**Reponse verbatim de l'agent (Total: 22.53s | Effectif: 22.527s | Groq wait: 0.0s | Sauts: 9) :**
```text
### Accès aux commandes de vente

| Persona | Groupe | Accès possible (lecture) | Explication |
|---------|--------|--------------------------|-------------|
| **Vendeur** (`sales_team.group_sale_salesman`) |  | **Seulement les commandes qu’il a créées ou sans utilisateur assigné** | La règle `sale.sale_order_personal_rule` (domain `[['|',('user_id','=',user.id),('user_id','=',False)]]`) est la seule règle de groupe applicable. Elle autorise l’affichage des commandes où `user_id` est l’utilisateur actuel ou `False`. La règle `sale.sale_order_see_all` (domain `(1, '=', 1)`) est ignorée car le vendeur n’appartient pas au groupe ciblé. <br>**Citation** : <br>• `Évaluation ir.rule pour la persona 'salesperson' (sales_team.group_sale_salesman), permission='read']` – « Règles de Groupe applicables (combinées en OU): Personal Orders [['|',('user_id','=',user.id),('user_id','=',False)]] (xml_id: sale.sale_order_personal_rule) » |
| **Utilisateur du portail** (`base.group_portal`) |  | **Seulement les commandes auxquelles il est lié en tant que partenaire de message** | La règle `sale.sale_order_rule_portal` (domain `[['message_partner_ids','child_of',[user.commercial_partner_id.id]]]`) est la seule règle de groupe applicable. Elle autorise l’affichage des commandes où le partenaire commercial de l’utilisateur apparaît dans les partenaires de message. La règle `sale.sale_order_personal_rule` est ignorée car le portail n’appartient pas aux groupes ciblés. <br>**Citation** : <br>• `Évaluation ir.rule pour la persona 'portal_user' (base.group_portal), permission='read']` – « Règles de Groupe applicables (combinées en OU): Portal Personal Quotations/Sales Orders [[('message_partner_ids','child_of',[user.commercial_partner_id.id])]] (xml_id: sale.sale_order_rule_portal) » |

### Résumé

- **Vendeur** : ne voit pas toutes les commandes de son entreprise, mais uniquement celles qu’il a créées ou qui n’ont pas de `user_id` assigné.  
- **Utilisateur du portail** : ne voit que les commandes où il apparaît comme partenaire de message (souvent les devis ou commandes qu’il a créés via le portail).  

Ces restrictions sont imposées par les règles `ir.rule` définies dans le module `sale`.

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

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 19.84s | Effectif: 19.838s | Groq wait: 0.0s | Sauts: 3) :**
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