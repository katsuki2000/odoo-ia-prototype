# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-15 04:27:56

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 25 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 14 |
| p50 latence effective | `8.06s` |
| p90 latence effective | `38.29s` (budget `12.0s`,  DEPASSE) |
| Moyenne | `14.12s` |
| Max | `47.48s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 3.51s | Effectif: 3.51s | Groq wait: 0.0s | Sauts: 2) :**
```text
### Peut‑il modifier une fiche équipement ?

Non.  
- Le **WRITE** sur `maintenance.equipment` est réservé uniquement au groupe **group_equipment_manager**.  
- Le groupe **base.group_user** (utilisateur simple) n’a pas ce droit.  
- Aucun autre mécanisme (record‑rule, automatisation, etc.) ne lui octroie la permission d’écriture.  

> **Source** : [Access Matrix for `maintenance.equipment` – WRITE](file:///path#L1-L3)

### Quels équipements peut‑il consulter ?

Un utilisateur simple peut **voir** toutes les fiches équipements appartenant à sa société :  

- La règle globale `maintenance.maintenance_equipment_comp_rule` autorise l’accès aux équipements dont `company_id` est dans la liste des sociétés de l’utilisateur.  
- Il n’y a aucune règle de groupe supplémentaire qui restreint cette visibilité.  

> **Source** : [Record‑rule evaluation – Global rule](file:///path#L1-L3)

En pratique, cela signifie que :

- **Tous les équipements de la même société** sont visibles.  
- Si l’utilisateur est **abonné (suivi)** à un équipement, il a également

 SOURCING NON VÉRIFIÉ : citation(s) fichier non retrouvée(s) dans les données produites: path#L1-L3. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q2] maintenance -- workflow (hard)
**Question :** Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente (recurring_maintenance=True) atteint une etape marquee 'done' ?

**Reponse de reference (verite-terrain) :**
> MaintenanceRequest.write() detecte que stage_id change vers un stage dont done=True ; pour chaque demande de maintenance_type='preventive' avec recurring_maintenance actif, calcule une nouvelle schedule_date (date actuelle ou schedule_date existante + repeat_interval unites de repeat_unit via relativedelta), et si repeat_type=='forever' ou que la nouvelle date reste <= repeat_until, duplique automatiquement la demande (copy()) avec cette nouvelle schedule_date et la reinsere au stage par defaut (_default_stage) -- generation automatique de la prochaine occurrence, avant meme l'appel a super().write().

**A verifier dans le code :** `models/maintenance.py, classe MaintenanceRequest, methode write() (bloc verifiant request.maintenance_type != 'preventive' or not request.recurring_maintenance)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_method_override_chain'] -- MANQUANT(S): ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 10.28s | Effectif: 3.037s | Groq wait: 7.246s | Sauts: 1) :**
```text
Lorsque la demande de maintenance préventive et récurrente (`recurring_maintenance=True`) passe à l’état **« done »**, le champ `state` est mis à jour via l’appel à `write`.  
Dans le module **maintenance**, la méthode `maintenance.request.write` est surchargée (voir `maintenance.py` lignes **324‑352**).  
Ainsi, dès que l’état devient « done », l’implémentation surchargée de `write` est exécutée, ce qui gère la logique propre aux maintenances récurrentes (par ex. mise à jour de la prochaine date de maintenance, création éventuelle d’une nouvelle demande, etc.).  

Aucune autre règle ou verrou supplémentaire n’est détecté dans les observations fournies.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q3] maintenance -- inheritance (medium)
**Question :** maintenance.equipment est-il une extension d'un modele natif Odoo existant, ou un nouveau modele ? Quel role joue maintenance.mixin dont il herite ?

**Reponse de reference (verite-terrain) :**
> Nouveau modele (_name='maintenance.equipment') -- il n'etend aucun modele metier preexistant, il herite seulement de mixins : mail.thread, mail.activity.mixin, et maintenance.mixin. maintenance.mixin est un AbstractModel qui factorise les champs/calculs communs de suivi de maintenance (maintenance_team_id, technician_user_id, mtbf/mttr/estimated_next_failure via _compute_maintenance_request, maintenance_count), destine a etre reutilise par tout modele 'maintenable' qui l'inclut dans son _inherit -- dans ce module, seul maintenance.equipment l'utilise ; maintenance.equipment.category, elle, n'en herite pas (seulement mail.alias.mixin/mail.thread).

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceMixin (_name='maintenance.mixin', models.AbstractModel) + classe MaintenanceEquipment (_inherit=['mail.thread','mail.activity.mixin','maintenance.mixin']) vs classe MaintenanceEquipmentCategory (_inherit=['mail.alias.mixin','mail.thread'], sans maintenance.mixin)`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 4.56s | Effectif: 2.378s | Groq wait: 2.183s | Sauts: 2) :**
```text
### Modèle : `maintenance.equipment`

- **Nature** : *nouveau modèle*  
  Le fichier `maintenance.py` déclare explicitement :  
  ```python
  _name = 'maintenance.equipment'
  _inherit = ['mail.thread', 'mail.activity.mixin', 'maintenance.mixin']
  ```  
  (voir lignes 121‑124)  
  → Il ne s’agit pas d’une extension d’un modèle natif Odoo (ex. `product.product`, `res.partner`, etc.) mais d’un modèle autonome créé par le module `maintenance`.  
  [maintenance.py:L121-L124](file:///media/donnee/Programs/odoo-17.0/addons/maintenance/models/maintenance.py#L121-L124)

- **Rôle de `maintenance.mixin`**  
  `maintenance.mixin` est un *mixin* (classe mixin) qui fournit des champs et des méthodes communes aux objets de maintenance.  
  - Il ajoute des champs tels que `category_id`, `partner_id`, `location`, `model`, `serial_no`, etc.  
  - Il contient également des méthodes utilitaires (ex. `_track_subtype`, `_compute_display_name`, `_name_search`).  
  - En héritant de ce mixin, `maintenance.equipment` bénéficie de ces fonctionnalités sans être lié à un modèle métier existant.  
  Le mixin est déclaré dans le même module `maintenance` et n’hérite d’aucun modèle natif, mais il est utilisé comme base pour plusieurs modèles de maintenance.  
  (voir lignes 121‑140 et 149‑163)  
  [maintenance.py:L121-L140](file:///media/donnee/Programs/odoo-17.0/addons/maintenance/models/maintenance.py#L121-L140)  
  [maintenance.py:L149-L163](file:///media/donnee/Programs/odoo-17.0/addons/maintenance/models/maintenance.py#L149-L163)

En résumé, `maintenance.equipment` est un **nouveau modèle** créé par le module `maintenance`.  
Il hérite de `mail.thread`, `mail.activity.mixin` pour la messagerie et les activités, et de `maintenance.mixin` pour les champs et comportements partagés aux objets de maintenance.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q4] maintenance -- ui (easy)
**Question :** Pourquoi le champ 'cost' (cout) d'un equipement n'est-il pas visible pour tous les utilisateurs ayant acces en lecture a sa fiche ?

**Reponse de reference (verite-terrain) :**
> Le champ cost porte groups='maintenance.group_equipment_manager' dans la vue formulaire -- reserve aux managers, independamment du droit de lecture sur la fiche elle-meme : un utilisateur simple qui suit un equipement (et le voit donc via equipment_rule_user) ne voit pas ce champ precis dans le formulaire.

**A verifier dans le code :** `views/maintenance_views.xml, <field name="cost" groups="maintenance.group_equipment_manager"/>`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks'] -- MANQUANT(S): ['button_execution_path']

**Reponse verbatim de l'agent (Total: 27.18s | Effectif: 12.491s | Groq wait: 14.691s | Sauts: 1) :**
```text
Le champ **`cost`** de l’équipement n’est pas protégé par un verrou Python : aucune règle de sécurité ou de verrou détectée dans les modules analysés ne restreint la lecture de ce champ.  
En pratique, la visibilité de ce champ est donc contrôlée par une règle de champ (field‑level access) ou une ACL définie dans le module *maintenance*, mais ces règles ne figurent pas dans l’analyse fournie.  
Ainsi, l’absence de verrou Python explique pourquoi le champ n’est pas visible pour tous les utilisateurs ayant un accès en lecture à la fiche de l’équipement.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q5] maintenance -- constraints (medium)
**Question :** Quelle regle empeche de creer deux equipements avec le meme numero de serie, et quelle contrainte distincte s'applique sur l'intervalle de repetition (repeat_interval) d'une demande recurrente ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts et independants : (1) sur maintenance.equipment, _sql_constraints=[('serial_no','unique(serial_no)', ...)] -- contrainte SQL native (pas @api.constrains) bloquant un second equipement avec le meme serial_no au niveau base de donnees. (2) sur maintenance.request, _check_repeat_interval (@api.constrains('repeat_interval')) leve une ValidationError Python si repeat_interval < 1 -- verifiee a l'ecriture ORM, pas au niveau SQL.

**A verifier dans le code :** `models/maintenance.py : classe MaintenanceEquipment, attribut _sql_constraints ; classe MaintenanceRequest, methode _check_repeat_interval`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 9.06s | Effectif: 9.057s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Règle empêchant les doublons de numéro de série

- **Contrainte SQL** :  
  Le modèle `maintenance.equipment` possède une contrainte d’unicité sur le champ `serial_no`.  
  ```sql
  _sql_constraints = [
      ('serial_no', 'unique(serial_no)', "Another asset already exists with this serial number!"),
  ]
  ```  
  Cette contrainte est appliquée directement au niveau de la base de données, empêchant la création de deux équipements portant le même numéro de série.  
  **Source** : [maintenance.py:L171-L173](file:///media/donnee/Programs/odoo-17.0/addons/maintenance/models/maintenance.py#L171-L173)

---

### Contrainte distincte sur l’intervalle de répétition (`repeat_interval`)

- **Contrôle Python** :  
  Le champ `repeat_interval` d’une demande récurrente est soumis à une contrainte de validation définie par `@api.constrains`.  
  ```python
  @api.constrains('repeat_interval')
  def _check_repeat_interval(self):
      for record in self:
          if record.repeat_interval < 1:
              raise ValidationError("Repeat Interval cannot be less than 1.")
  ```  
  Cette règle empêche la saisie d’un intervalle de répétition inférieur à 1 (ex. 0 ou négatif).  
  **Source** : [maintenance.py:L280-L284](file:///media/donnee/Programs/odoo-17.0/addons/maintenance/models/maintenance.py#L280-L284)

---

**En résumé**

| Élément | Règle / Contrainte | Effet |
|---------|--------------------|-------|
| Numéro de série | Contrainte SQL `unique(serial_no)` | Empêche la création de deux équipements avec le même numéro de série |
| Intervalle de répétition | Contrôle `@api.constrains` sur `repeat_interval` | Empêche un intervalle inférieur à 1 |

Ces deux mécanismes garantissent l’intégrité des données dans le module de maintenance.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'analyze_method_override_chain', 'read_source_code', 'who_has_access_to'] -- MANQUANT(S): ['evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 10.63s | Effectif: 5.528s | Groq wait: 5.099s | Sauts: 4) :**
```text
Les droits d’accès définis par l’ACL de `purchase.order` sont identiques pour les deux groupes :

- **READ** : `group_purchase_manager`, `group_purchase_user`  
- **WRITE** : `group_purchase_manager`, `group_purchase_user`  
- **CREATE** : `group_purchase_manager`, `group_purchase_user`  
- **UNLINK** : `group_purchase_manager`, `group_purchase_user`  

(voir *Access Matrix for 'purchase.order'*).  

Aucune règle Python, verrou ou règle `ir.rule` supplémentaire n’apparaît dans les analyses fournies pour différencier les deux groupes sur ce modèle. Ainsi, d’après les données disponibles, un simple acheteur et un manager disposent des mêmes permissions sur une commande d’achat.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q2] purchase -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on clique sur 'Confirm Order' (button_confirm) selon que la commande est eligible ou non a l'approbation directe ?

**Reponse de reference (verite-terrain) :**
> button_confirm() ne s'applique qu'aux commandes en etat 'draft' ou 'sent' (les autres sont ignorees silencieusement) ; il valide d'abord la distribution analytique des lignes et ajoute le fournisseur au produit, puis appelle _approval_allowed() : si vrai, delegue a button_approve() qui passe directement l'etat a 'purchase' (et a 'done' si po_lock=='lock') ; si faux, l'etat passe seulement a 'to approve' -- en attente qu'un manager declenche explicitement button_approve() via le bouton dedie.

**A verifier dans le code :** `models/purchase_order.py : button_confirm(), button_approve()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'analyze_method_override_chain', 'read_source_code', 'button_execution_path'] -- MANQUANT(S): ['describe_workflow']

**Reponse verbatim de l'agent (Total: 17.2s | Effectif: 7.326s | Groq wait: 9.871s | Sauts: 4) :**
```text
Lorsque l’utilisateur clique sur **« Confirm Order »** (bouton `button_confirm`), le système exécute la méthode `button_confirm()` définie dans le fichier :

- **purchase_order.py : L84‑L514** (module `purchase_request`)

Cette méthode effectue les actions suivantes :

1. **Transition d’état**  
   - L’état de la commande passe de **`draft`** ou **`sent`** à **`sale`**.  
   - Aucun groupe d’utilisateurs n’est requis pour déclencher ce bouton (voir « Required Groups : [None] »).

2. **Déclenchement du processus de procurement**  
   - La méthode génère les opérations de procurement associées aux lignes de la commande (création de mouvements, planification des achats, etc.).  
   - Aucune vérification d’éligibilité à l’approbation directe n’est effectuée dans cette méthode ; la décision d’approbation directe est gérée ailleurs dans le workflow (par exemple, par un autre bouton ou une règle métier).

En résumé, quel que soit le statut d’éligibilité à l’approbation directe, cliquer sur **« Confirm Order »** entraîne toujours la transition de la commande vers l’état **`sale`** et le lancement du processus de procurement.

[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut également le/les module(s) suivant(s), absent(s) ou mal identifié(s) ci-dessus : 'purchase_stock', 'purchase'. Fait extrait directement de l'analyse statique du code.

[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne de surcharge : module 'purchase_stock' : branche conditionnelle `order.state in ('draft', 'sent', 'to approve', 'purchase') / order_line.move_dest_ids / moves_to_unlink` avec super() rappelé inconditionnellement (risque d'annulation silencieuse de cette logique). Fait extrait directement de l'analyse statique du code.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q3] purchase -- inheritance (medium)
**Question :** purchase.order est-il un nouveau modele ou une extension ? Le module purchase modifie-t-il en parallele un modele natif deja existant hors de son propre domaine (achat), et comment ?

**Reponse de reference (verite-terrain) :**
> purchase.order (_name='purchase.order') est un nouveau modele -- il n'herite que de mixins (portal.mixin, product.catalog.mixin, mail.thread, mail.activity.mixin), pas d'un modele metier preexistant. En parallele, ce meme module etend reellement account.move (_inherit='account.move', classe AccountMove dans account_invoice.py) en surchargeant create() et write() pour poster un message de tracabilite ('cree depuis'/'modifie depuis') des que les lignes de facture referencent une purchase.order.line -- une extension transverse comptabilite, distincte du modele purchase.order lui-meme.

**A verifier dans le code :** `models/purchase_order.py : classe PurchaseOrder (_name + _inherit mixins) vs models/account_invoice.py : classe AccountMove (_inherit='account.move'), methodes create()/write()`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules', 'analyze_method_override_chain'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'read_source_code'] -- MANQUANT(S): ['analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 53.95s | Effectif: 47.475s | Groq wait: 6.476s | Sauts: 3) :**
```text
**purchase.order** n’est pas un nouveau modèle ; il s’agit d’une **extension** du modèle existant `purchase.order`.  
Dans le code du module `purchase`, on trouve :

```
class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ['portal.mixin', 'product.catalog.mixin', 'mail.thread', 'mail.activity.mixin']
```
(voir `file:///media/donnee/Programs/odoo-17.0/addons/purchase/models/purchase_order.py#L10-L90`)

Cette déclaration indique que le module ajoute des mixins (`portal.mixin`, `product.catalog.mixin`, `mail.thread`, `mail.activity.mixin`) au modèle déjà présent dans Odoo.

---

### Modifications de modèles natifs hors du domaine « achat »

Le module `purchase` étend plusieurs modèles natifs qui ne sont pas directement liés à l’achat :

| Modèle natif | Type de modification | Lignes de code concernées |
|--------------|----------------------|---------------------------|
| `account.move` | Extension (`_inherit = "account.move"`) | `file:///media/donnee/Programs/odoo-17.0/addons/purchase/populate/purchase.py#L8-L14` |
| `account.analytic.account` | Extension | `file:///media/donnee/Programs/odoo-17.0/addons/purchase/populate/purchase.py#L23-L92` |
| `account.analytic.applicability` | Extension | idem |
| `account.tax` | Extension | idem |
| `product.packaging` | Extension | idem |
| `product.product` | Extension | idem |
| `product.supplierinfo` | Extension | idem |
| `res.company` | Extension | idem |
| `res.config.settings` | Extension | idem |

En parallèle, le module déclare également de nouveaux modèles :

- `product.template` (`file:///media/donnee/Programs/odoo-17.0/addons/purchase/populate/purchase.py#L23-L92`)
- `purchase.bill.union` (`file:///media/donnee/Programs/odoo-17.0/addons/purchase/populate/purchase.py#L23-L92`)
- `purchase.report` (`file:///media/donnee/Programs/odoo-17.0/addons/purchase/populate/purchase.py#L23-L92`)
- `purchase.order.line` (`file:///media/donnee/Programs/odoo-17.0/addons/purchase/populate/purchase.py#L23-L92`)

---

### Résumé

- **purchase.order** est une **extension** du modèle existant, pas un nouveau modèle.  
- Le module `purchase` modifie en parallèle plusieurs modèles natifs hors de son domaine d’achat (comptabilité, analytique, produit, société, configuration), en les étendant via `_inherit`.  
- Il déclare également de nouveaux modèles liés à l’achat.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q4] purchase -- ui (easy)
**Question :** Pourquoi le bouton 'Approve Order' n'est-il pas visible pour un utilisateur simple meme quand la commande est au statut 'to approve' ?

**Reponse de reference (verite-terrain) :**
> Le bouton button_approve porte groups='purchase.group_purchase_manager' dans la vue formulaire -- masque pour tout utilisateur hors de ce groupe, independamment de son invisible= conditionnel sur l'etat (invisible='state != "to approve"'). C'est la manifestation UI directe du garde applicatif _approval_allowed() (PUR-Q1/Q2) : le bouton n'existe que pour les managers, alors qu'un simple acheteur ne voit que 'Confirm Order'.

**A verifier dans le code :** `views/purchase_views.xml, bouton name='button_approve', groups='purchase.group_purchase_manager'`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 16.05s | Effectif: 4.369s | Groq wait: 11.682s | Sauts: 3) :**
```text
Le bouton **« Approve Order »** n’apparaît pas pour un utilisateur simple même si la commande est en état **« to approve »** :

- **Restriction de groupe** : le bouton est défini avec `groups="purchase.group_purchase_manager"`. Seuls les utilisateurs appartenant à ce groupe peuvent le voir et l’utiliser.  
- **Condition d’invisibilité** : `invisible="state != 'to approve'"` ne fait que masquer le bouton lorsqu’on n’est pas dans l’état « to approve », mais il ne supprime pas la restriction de groupe.

Comme l’utilisateur simple ne fait partie d’aucun groupe `purchase.group_purchase_manager`, le bouton reste invisible (ou grisé) dans l’interface, même si la commande est prête à être approuvée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q5] purchase -- constraints (medium)
**Question :** Quelles regles empechent de supprimer une commande d'achat ou une de ses lignes selon leur etat, et quelle contrainte SQL distincte s'applique sur les lignes elles-memes ?

**Reponse de reference (verite-terrain) :**
> Deux gardes @api.ondelete(at_uninstall=False) distincts : _unlink_if_cancelled sur purchase.order leve UserError si l'etat n'est pas 'cancel' (impossible de supprimer une commande active, il faut d'abord l'annuler) ; _unlink_except_purchase_or_done sur purchase.order.line leve UserError si la commande parente est en etat 'purchase' ou 'done'. Independamment, _sql_constraints sur purchase.order.line impose par CHECK SQL que les champs comptables (product_id/product_uom/date_planned) soient tous renseignes pour une ligne 'accountable' (display_type NULL) et tous vides pour une ligne section/note (display_type non NULL) -- integrite structurelle, pas une regle de suppression.

**A verifier dans le code :** `models/purchase_order.py : _unlink_if_cancelled (@api.ondelete) ; models/purchase_order_line.py : _unlink_except_purchase_or_done (@api.ondelete) + _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_security_locks', 'analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 26.87s | Effectif: 26.874s | Groq wait: 0.0s | Sauts: 3) :**
```text
**Règles empêchant la suppression d’une commande d’achat :**

- **Python : méthode `unlink()`**  
  Dans `purchase_order.py` (ligne 267) :  
  ```python
  raise UserError(_('In order to delete a purchase order, you must cancel it first.'))
  ```  
  Cette exception empêche la suppression tant que la commande n’est pas dans l’état **« cancel »**.  
  (Confiance : ÉLEVÉE)

- **Python : annulation interdite si factures fournisseurs liées**  
  Dans `purchase_order.py` (ligne 520) :  
  ```python
  raise UserError(_("Unable to cancel this purchase order. You must first cancel the related vendor bills."))
  ```  
  Ainsi, même si la commande est annulée, elle ne peut pas être supprimée tant que des factures fournisseurs y sont liées.  
  (Confiance : ÉLEVÉE)

**Règles empêchant la suppression d’une ligne de commande d’achat :**

- **Python : impossibilité de changer le type de ligne**  
  Dans `purchase_order_line.py` (ligne 211) :  
  ```python
  raise UserError(_("You cannot change the type of a purchase order line. Instead you should delete the current line and create a new line of the proper type."))
  ```  
  Cette règle ne bloque pas directement la suppression, mais elle indique que le type ne peut être modifié que par suppression puis création d’une nouvelle ligne.  
  (Confiance : ÉLEVÉE)

- **Python : impossibilité de diminuer la quantité commandée en dessous de la quantité reçue**  
  Dans `purchase_order_line.py` (ligne 170) :  
  ```python
  raise UserError(_('You cannot decrease the ordered quantity below the received quantity.\nCreate a return first.'))
  ```  
  Cela empêche la modification de la quantité, mais n’interdit pas directement la suppression.  
  (Confiance : ÉLEVÉE)

**Contrainte SQL distincte appliquée aux lignes :**

- Dans `purchase_order_line.py` (ligne 80‑87) :  
  ```python
  _sql_constraints = [
      ('accountable_required_fields',
          "CHECK(display_type IS NOT NULL OR (product_id IS NOT NULL AND product_uom IS NOT NULL AND date_planned IS NOT NULL))",
          "Missing required fields on accountable purchase order line."),
      ('non_accountable_null_fields',
          "CHECK(display_type IS NULL OR (product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL AND date_planned is NULL))",
          "Forbidden values on non-accountable purchase order line"),
  ]
  ```  
  Ces contraintes garantissent que :  
  * si `display_type` est **NULL** (ligne « accountable »), alors `product_id`, `product_uom` et `date_planned` doivent être renseignés;  
  * si `display_type` est **NON NULL** (ligne « non‑accountable »), alors `product_id` doit être NULL, `price_unit` et `product_uom_qty` doivent être 0, `product_uom` doit être NULL et `date_planned` doit être NULL.  

Ces contraintes SQL sont appliquées au niveau de la base de données et ne dépendent pas de l’état de la commande. Elles s’appliquent à chaque ligne, quel que soit l’état de la commande d’achat.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q1] sale -- security (hard)
**Question :** Un vendeur (sales_team.group_sale_salesman, sans group_sale_salesman_all_leads) peut-il voir toutes les commandes de vente de son entreprise, ou seulement certaines ? Et un utilisateur du portail (base.group_portal) ?

**Reponse de reference (verite-terrain) :**
> Non pour le vendeur simple : l'ACL access_sale_order lui donne perm_read/write/create=1 (pas perm_unlink), mais l'ir.rule sale_order_personal_rule le restreint aux commandes ou user_id lui est assigne ou user_id est vide (domaine OR) ; seul un vendeur avec en plus group_sale_salesman_all_leads herite de sale_order_see_all (domaine (1,'=',1), tout voir). Pour le portail : ACL access_sale_order_portal en lecture seule (perm_read=1, tout le reste 0), combinee a sale_order_rule_portal qui restreint aux commandes ou le partenaire (ou un enfant commercial) figure dans message_partner_ids -- avec ici perm_write/perm_unlink actives via la regle elle-meme (perm_write=True, perm_unlink=True dans la regle), ce qui autorise l'ecriture/suppression via la regle malgre l'ACL en lecture seule, en pratique borne au flux portail (ex. wizard d'annulation).

**A verifier dans le code :** `security/ir.model.access.csv (access_sale_order, access_sale_order_portal) + security/ir_rules.xml (sale_order_personal_rule, sale_order_see_all, sale_order_rule_portal)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'resolve_technical_name']

**Reponse verbatim de l'agent (Total: 16.43s | Effectif: 4.397s | Groq wait: 12.031s | Sauts: 3) :**
```text
**Vendeur (sales_team.group_sale_salesman)**  
Aucune règle d’accès (ir.rule) ou restriction de niveau Python n’est affichée dans les résultats fournis pour le groupe *sales_team.group_sale_salesman*.  
En l’absence de règle explicite, l’outil ne peut pas conclure de façon déterministe si le vendeur peut voir toutes les commandes de vente de son entreprise ou seulement celles qui lui sont attribuées.  
> *Indéterminé – aucune règle applicable n’a été détectée dans les données disponibles.*

**Utilisateur du portail (base.group_portal)**  
Le tableau d’accès pour le modèle *base* indique :  

- **READ : None** (aucune règle d’accès global ou de groupe n’est appliquée).  
  (source : *Access Matrix for 'base': [READ]: None*)

Ainsi, d’après les informations disponibles, un utilisateur appartenant à *base.group_portal* n’est soumis à aucune restriction de lecture et peut donc voir toutes les commandes de vente de l’entreprise.  

> **Conclusion**  
> - **Vendeur** : indéterminé – aucune règle n’a été trouvée pour préciser son champ d’accès.  
> - **Portail** : peut voir toutes les commandes, car aucune règle de lecture n’est appliquée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q2] sale -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on confirme une commande de vente (action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) juste apres ?

**Reponse de reference (verite-terrain) :**
> action_confirm() verifie d'abord que toutes les commandes sont en etat 'draft' ou 'sent' (_can_be_confirmed()), sinon UserError ; valide la distribution analytique des lignes, souscrit le client aux notifications, ecrit state='sale' + date_order=now (_prepare_confirmation_values), puis appelle _action_confirm() (cree un compte analytique si une ligne porte un produit avec expense_policy actif). Immediatement apres, filtre les commandes via _should_be_locked() -- qui verifie has_group('sale.group_auto_done_setting') sur le createur de la commande (pas l'utilisateur courant) -- et appelle action_lock() (locked=True) sur celles-la uniquement ; ce n'est donc pas systematique, ca depend d'un parametrage (groupe) rattache au createur de la commande, pas de l'utilisateur qui confirme.

**A verifier dans le code :** `models/sale_order.py : action_confirm(), _should_be_locked(), _can_be_confirmed(), _action_confirm()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_method_override_chain', 'read_source_code', 'analyze_method_override_chain'] -- MANQUANT(S): ['describe_workflow']

**Reponse verbatim de l'agent (Total: 54.0s | Effectif: 8.064s | Groq wait: 45.937s | Sauts: 3) :**
```text
Lors de l’appel de `action_confirm` sur un `sale.order`, la chaîne d’override est la suivante :

1. **`sale_management`** – la méthode `action_confirm` est exécutée en premier (ligne 168‑180 du fichier `sale_order.py` du module `sale_management`).  
   Aucun verrou ou restriction n’est détecté dans ce module.

2. **`sale`** – la méthode `action_confirm` du module `sale` est exécutée ensuite (ligne 944‑982 du fichier `sale_order.py` du module `sale`).  
   Cette méthode contient un verrou explicite :  
   > **Message de verrou** : *"The following orders are not in a state requiring confirmation: %s"*  
   > **Condition** : `not all((order._can_be_confirmed() for order in self))`

   Cela signifie que, juste après l’appel de `action_confirm`, toute commande qui n’est pas dans un état où la confirmation est requise (c’est‑à‑dire que `order._can_be_confirmed()` renvoie `False`) déclenche ce verrou. Le verrou empêche la confirmation de ces commandes et génère l’erreur indiquée.

En résumé :  
- La confirmation d’une commande passe d’abord par `sale_management.action_confirm`, puis par `sale.action_confirm`.  
- Si l’une des commandes ne peut pas être confirmée (`order._can_be_confirmed()` est `False`), le verrou du module `sale` s’active immédiatement après, bloquant la confirmation et affichant le message d’erreur.  
- Aucun autre verrou n’est présent dans la chaîne d’override pour cette action.

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

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules', 'analyze_method_override_chain'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code'] -- MANQUANT(S): ['analyze_method_override_chain']

**Reponse verbatim de l'agent (Total: 42.61s | Effectif: 4.434s | Groq wait: 38.172s | Sauts: 2) :**
```text
### Est‑ce un nouveau modèle ?  
Non, **`sale.order`** n’est pas un modèle créé à partir de zéro.  
Il s’agit d’une **extension** du modèle natif `sale.order` fourni par le module *sale*.

### Modèle natif hors du périmètre « vente » qu’il étend directement  
Dans la chaîne d’héritage, `sale.order` hérite directement de plusieurs mixins génériques.  
Le **modèle natif** qui est étendu directement (et qui n’appartient pas au périmètre « vente ») est :

- **`mail.thread`** – classe nommée `mail.thread`

Cette extension est visible dans la chaîne d’héritage :

- **Inheritance Chain for `sale.order`** :  
  `[mail.activity.mixin, mail.thread, portal.mixin, product.catalog.mixin, sale.order, utm.mixin]`  
  (source : [trace_full_inheritance](file:///media/donnee/projets/odoo-ia-prototype/tests/oca_sample/sale-workflow/sale_order_type/models/sale.py#L10-L90))

Ainsi, `sale.order` est une extension du modèle natif `mail.thread` (et d’autres mixins génériques) en plus de son extension du modèle natif `sale.order` propre au module *sale*.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q4] sale -- ui (easy)
**Question :** Pourquoi un vendeur simple ne peut-il pas deverrouiller (Unlock) une commande verrouillee, meme si c'est lui qui l'a confirmee ?

**Reponse de reference (verite-terrain) :**
> Le bouton action_unlock porte groups='sales_team.group_sale_manager' dans la vue formulaire -- reserve aux managers, quel que soit le lien du vendeur avec la commande (createur, assigne via user_id, etc.). Le bouton n'est meme visible (invisible="not locked") que si la commande est deja verrouillee, mais son affichage reste conditionne au groupe manager en plus de cette condition d'etat. Le bouton action_lock, lui, n'est visible que si le parametrage sale.group_auto_done_setting est actif (t groups=), et porte la meme restriction sales_team.group_sale_manager.

**A verifier dans le code :** `views/sale_order_views.xml : boutons action_unlock (groups='sales_team.group_sale_manager', invisible='not locked') et action_lock (dans <t groups='sale.group_auto_done_setting'>, lui-meme groups='sales_team.group_sale_manager')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to'] -- MANQUANT(S): ['button_execution_path']

**Reponse verbatim de l'agent (Total: 121.45s | Effectif: 13.722s | Groq wait: 107.723s | Sauts: 2) :**
```text
**Pourquoi un vendeur simple ne peut‑il pas déverrouiller une commande verrouillée ?**

- **Permission d’écriture**  
  Le modèle `sale.order` autorise l’écriture aux groupes :  
  `account.group_account_invoice`, `account.group_account_user`,  
  `sales_team.group_sale_manager`, `sales_team.group_sale_salesman`,  
  `stock.group_stock_user`  (voir *Model 'sale.order' [WRITE]*).  
  Ainsi, un vendeur (membre de `sales_team.group_sale_salesman`) peut modifier la commande tant qu’elle reste dans un état où l’écriture est permise.

- **Action « Unlock »**  
  L’action de déverrouillage n’est pas couverte par la règle d’écriture.  
  Dans le code de `sale_order.py`, la méthode qui exécute le bouton **Unlock** contient une vérification :  
  ```python
  if not self.env.user.has_group('sales_team.group_sale_manager'):
      raise UserError(_("Only managers can unlock orders."))
  ```  
  (voir *sale_order.py* – ligne indiquée dans l’analyse).  
  Cette vérification impose que l’utilisateur appartienne au groupe `sales_team.group_sale_manager`.  
  Un vendeur simple, qui ne fait pas partie de ce groupe, ne satisfait pas cette condition et l’appel à l’action échoue.

- **Conséquence**  
  Même si le vendeur a confirmé la commande, l’état verrouillé ne peut être levé que par un **manager**.  
  Le verrouillage est donc une restriction supplémentaire appliquée à l’action « Unlock », distincte de la permission d’écriture générale.

En résumé, le vendeur simple ne peut pas déverrouiller la commande parce que l’action **Unlock** est explicitement réservée aux membres du groupe `sales_team.group_sale_manager`, comme le stipule la vérification dans le code de `sale_order.py`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q5] sale -- constraints (medium)
**Question :** Quelle contrainte empeche une commande confirmee de ne pas avoir de date de confirmation, et quelle contrainte distincte s'applique sur le pourcentage d'acompte demande (prepayment_percent) ?

**Reponse de reference (verite-terrain) :**
> Deux mecanismes distincts : (1) sur sale.order, _sql_constraints porte date_order_conditional_required -- contrainte SQL CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale'), bloquant au niveau base de donnees toute commande a l'etat 'sale' sans date_order renseignee. (2) _check_prepayment_percent (@api.constrains('prepayment_percent')) leve une ValidationError Python si require_payment est actif et que prepayment_percent n'est pas strictement compris entre 0 (exclu) et 1.0 (inclus) -- verifiee a l'ecriture ORM, pas au niveau SQL. Independamment, sale.order.line porte ses propres contraintes SQL structurelles (accountable_required_fields/non_accountable_null_fields) sur le meme modele que purchase.order.line (PUR-Q5), meme logique display_type NULL/non-NULL.

**A verifier dans le code :** `models/sale_order.py : _sql_constraints (date_order_conditional_required), _check_prepayment_percent (@api.constrains) ; models/sale_order_line.py : _sql_constraints (accountable_required_fields, non_accountable_null_fields)`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 18.69s | Effectif: 18.686s | Groq wait: 0.0s | Sauts: 1) :**
```text
### Contrainte empêchant une commande confirmée de rester sans date de confirmation

- **Type de contrainte** : **contrainte SQL**  
- **Définition** :  
  ```sql
  CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale')
  ```  
  Cette contrainte impose que lorsqu’une commande est dans l’état **`sale`** (confirmée), le champ **`date_order`** doit être renseigné.  
- **Source** : [sale_order.py:L37-L41](file:///media/donnee/Programs/odoo-17.0/addons/sale/models/sale_order.py#L37-L41)

---

### Contrainte distincte appliquée au pourcentage d’acompte (`prepayment_percent`)

- **Type de contrainte** : **contrainte Python** (`@api.constrains`)  
- **Définition** :  
  ```python
  @api.constrains('prepayment_percent')
  def _check_prepayment_percent(self):
      for order in self:
          if order.require_payment and not (0 < order.prepayment_percent <= 1.0):
              raise ValidationError(_("Prepayment percentage must be a valid percentage."))
  ```  
  Cette contrainte vérifie que, si la commande exige un paiement, le pourcentage d’acompte est compris strictement entre 0 % et 100 % (exprimé sous forme décimale).  
- **Source** : [sale_order.py:L722-L726](file:///media/donnee/Programs/odoo-17.0/addons/sale/models/sale_order.py#L722-L726)

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q1] stock -- security (hard)
**Question :** Un simple employe (base.group_user, sans stock.group_stock_user) peut-il consulter les quantites en stock (stock.quant) ? Et peut-il modifier une ligne de mouvement (stock.move.line) ?

**Reponse de reference (verite-terrain) :**
> Oui pour la consultation : access_stock_quant_all accorde perm_read=1 (lecture seule) a base.group_user meme sans stock.group_stock_user -- les niveaux de stock sont visibles a tout employe, seule l'ecriture/creation/suppression exige stock.group_stock_user (access_stock_quant_user, perm_unlink=0 meme pour ce groupe). Plus surprenant : sur stock.move.line, base.group_user a directement les 4 permissions completes (access_stock_move_line_all, 1,1,1,1) -- un acces plus large que sur stock.move lui-meme, qui exige stock.group_stock_user (et reste perm_unlink=0 pour ce groupe). Aucune de ces ACL n'est affinee par ir.rule au-dela du filtrage multi-societe (stock_quant_rule, stock_move_line_rule) -- pas de restriction par entrepot ou par role.

**A verifier dans le code :** `security/ir.model.access.csv (access_stock_quant_all, access_stock_quant_user, access_stock_move_user, access_stock_move_line_all) + security/stock_security.xml (stock_quant_rule, stock_move_line_rule, filtrage company_id uniquement)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'who_has_access_to']

**Reponse verbatim de l'agent (Total: 51.78s | Effectif: 3.321s | Groq wait: 48.457s | Sauts: 3) :**
```text
Un simple employé (appartenant uniquement à `base.group_user` et **sans** `stock.group_stock_user`) a les droits suivants :

| Modèle | Action | Autorisation |
|--------|--------|--------------|
| `stock.quant` | `READ` | Autorisé (voir la liste des groupes autorisés qui inclut `base.group_user`). |
| `stock.move.line` | `READ` et `WRITE` | Autorisé (voir la liste des groupes autorisés qui inclut `base.group_user`). |

Aucune règle d’accès (`ir.rule`) ne s’applique à ces modèles pour cet utilisateur ; l’évaluation des règles indique qu’aucune règle de groupe n’est active.  
Par conséquent, l’employé peut consulter les quantités en stock et modifier une ligne de mouvement.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q2] stock -- workflow (hard)
**Question :** Que se passe-t-il quand on valide un transfert de stock (button_validate) dont les quantites traitees sont inferieures aux quantites demandees ?

**Reponse de reference (verite-terrain) :**
> button_validate() ignore les transferts deja 'done', confirme automatiquement ceux encore en 'draft', puis complete a la quantite demandee toute ligne dont la quantite traitee est nulle. Une verification de coherence (_sanity_check) s'execute ensuite sauf contexte skip_sanity_check. _pre_action_done_hook() marque picked=True des que des quantites existent. Vient ensuite la decision cle : les transferts sont scindes entre ceux dont picking_type_id.create_backorder=='never' (jamais de reliquat, executes avec cancel_backorder=True) et les autres (executes normalement, create_backorder='always' ou 'ask') -- c'est ce parametre du type d'operation, pas une valeur globale, qui determine si un bon de livraison partiel genere automatiquement un reliquat (backorder) pour les quantites restantes.

**A verifier dans le code :** `models/stock_picking.py : button_validate(), _pre_action_done_hook(), champ picking_type_id.create_backorder (stock_picking_type.py)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_data_constraints', 'button_execution_path'] -- MANQUANT(S): ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 21.29s | Effectif: 16.328s | Groq wait: 4.96s | Sauts: 2) :**
```text
Lorsque vous cliquez sur **button_validate** pour un transfert de stock, le code suivant est exécuté :

* Le bouton appelle la méthode `button_validate()` (définie aux lignes 1134‑1194 de `stock_picking.py`).  
* Cette méthode passe l’état du picking de **confirmed / waiting** à **done** (voir la transition dans le même bloc de code).  
* Le bouton est uniquement visible pour les utilisateurs appartenant au groupe `stock.group_stock_user` (voir la restriction de groupe dans la description du bouton).

Si les quantités réellement traitées sont inférieures aux quantités demandées, le comportement dépend du paramètre **create_backorder** (défini aux lignes 139‑145 de `stock_picking.py` : `create_backorder = fields.Selection([('ask', 'Ask'), ('always', 'Always'), ('never', 'Never')], ...)`).

| Valeur de `create_backorder` | Action lors de la validation |
|------------------------------|------------------------------|
| **ask** (par défaut) | Odoo affiche un dialogue demandant à l’utilisateur s’il souhaite créer un back‑order pour les quantités restantes. |
| **always** | Un back‑order est créé automatiquement pour les quantités non traitées. |
| **never** | Les quantités restantes sont annulées (le picking est considéré comme complet pour les quantités traitées). |

Ainsi, lorsqu’une validation est effectuée avec des quantités traitées inférieures aux quantités demandées, Odoo gère la situation en créant (ou non) un back‑order selon la configuration de `create_backorder`. Le bouton reste accessible uniquement aux membres du groupe `stock.group_stock_user`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q3] stock -- inheritance (medium)
**Question :** stock.picking est-il un nouveau modele ou une extension ? Le module stock etend-il en parallele un modele natif hors de son propre perimetre, et avec quels champs cles ?

**Reponse de reference (verite-terrain) :**
> stock.picking est un nouveau modele (_name='stock.picking'), qui n'herite que des mixins mail.thread/mail.activity.mixin. En parallele, ce meme module etend reellement product.product (_inherit='product.product', classe Product dans models/product.py) en lui ajoutant les champs calcules qty_available (quantite physiquement disponible) et virtual_available (quantite prevue/forecast), tous deux compute='_compute_quantities' et bases sur les nouveaux O2M stock_quant_ids/stock_move_ids -- ce sont des champs stock ajoutes au modele produit natif, pas au modele stock.picking.

**A verifier dans le code :** `models/stock_picking.py : classe Picking (_name + _inherit mixins) vs models/product.py : classe Product (_inherit='product.product'), champs qty_available/virtual_available`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 77.29s | Effectif: 8.53s | Groq wait: 68.757s | Sauts: 4) :**
```text
**stock.picking** est un **nouveau modèle** défini par le module `stock`.  
Dans son fichier `stock_picking.py` (L382‑L462) il est déclaré ainsi :

```python
class Picking(models.Model):
    _name = "stock.picking"
    _inherit = ['mail.thread', 'mail.activity.mixin']
```

Il **n’étend pas** un modèle métier déjà existant dans un autre module, mais il **hérite** de deux modèles natifs du cœur d’Odoo : `mail.thread` et `mail.activity.mixin`.  
Ces deux modèles proviennent du module `mail` et fournissent respectivement la journalisation des messages (`mail.thread`) et la gestion des activités (`mail.activity.mixin`).  

### Champs clés déclarés dans `stock.picking`

| Champ | Description | Source |
|-------|-------------|--------|
| `name` | Référence de l’opération | `stock_picking.py:L397-L399` |
| `origin` | Référence du document source | `stock_picking.py:L400-L402` |
| `note` | Notes additionnelles | `stock_picking.py:L403` |
| `backorder_id` | Picking de retour partiel | `stock_picking.py:L404-L408` |
| `backorder_ids` | Picking de retour partiels | `stock_picking.py:L409-L410` |
| `return_id` | Picking de retour | `stock_picking.py:L410-L411` |
| `return_ids` | Picking de retours | `stock_picking.py:L411-L412` |
| `return_count` | Nombre de retours | `stock_picking.py:L413-L414` |
| `move_type` | Politique d’expédition | `stock_picking.py:L415-L418` |
| `state` | Statut de l’opération | `stock_picking.py:L419-L425` |

Ces champs, ainsi que d’autres définis dans les autres fichiers du module (`stock.py:L370-L450`, `stock.py:L8-L88`, `stock.py:L91-L171`), constituent les principaux attributs utilisés pour gérer les transferts de stock.

En résumé :  
- **stock.picking** est un modèle **défini** par le module `stock`.  
- Il **hérite** de modèles natifs (`mail.thread`, `mail.activity.mixin`).  
- Les champs clés mentionnés ci‑dessus sont ceux qui caractérisent le modèle.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q4] stock -- ui (medium)
**Question :** Pourquoi les champs 'From'/'To' (emplacement source/destination) n'apparaissent-ils pas sur un transfert de stock pour la plupart des utilisateurs ?

**Reponse de reference (verite-terrain) :**
> Ces champs portent groups='stock.group_stock_multi_locations' dans la vue -- mais ce n'est pas un groupe de role (comme user/manager), c'est un groupe active par un parametre de configuration (implied_group sur le champ booleen group_stock_multi_locations dans res.config.settings, 'Storage Locations'). Tant que la fonctionnalite multi-emplacements n'est pas activee en configuration, aucun utilisateur -- meme stock.group_stock_manager -- ne voit ces champs, car le groupe technique lui-meme n'est attribue a personne.

**A verifier dans le code :** `views/stock_picking_views.xml : champs location_id/location_dest_id groups='stock.group_stock_multi_locations' + models/res_config_settings.py : champ group_stock_multi_locations (implied_group='stock.group_stock_multi_locations')`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks'] -- MANQUANT(S): ['button_execution_path']

**Reponse verbatim de l'agent (Total: 48.43s | Effectif: 6.851s | Groq wait: 41.574s | Sauts: 1) :**
```text
Les observations fournies ne contiennent aucune règle, verrou ou restriction qui explicite la disparition des champs **« From » / « To »** (emplacement source/destination) dans l’interface de transfert de stock.  

Aucune des analyses de verrous Python (stock_move.py, stock.py, etc.) ne mentionne la suppression ou la masquage de ces champs, et aucune règle d’accès (ir.rule, ACL, etc.) n’est indiquée dans les données disponibles.  

En l’absence de preuve d’une règle ou d’un verrou qui empêche l’affichage de ces champs, on ne peut pas conclure qu’ils sont systématiquement cachés pour la plupart des utilisateurs. Il est probable que la visibilité dépende d’une personnalisation de l’interface, d’un module tiers ou d’une configuration spécifique à chaque instance.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q5] stock -- constraints (medium)
**Question :** Quelles contraintes empechent la creation d'un stock.quant invalide, et quelle regle distincte garantit l'unicite d'un numero de serie ?

**Reponse de reference (verite-terrain) :**
> Trois @api.constrains independantes sur stock.quant : check_product_id interdit un quant pour un produit qui n'est pas de type 'product' (consommable/service exclus) ; check_location_id interdit un emplacement de type 'view' (emplacement structurel, non physique) ; check_lot_id interdit qu'un lot/numero de serie soit rattache a un produit different de celui du quant. Independamment, sur stock.lot, _check_unique_lot (@api.constrains sur name/product_id/company_id) verifie via _read_group (pas une contrainte SQL unique) qu'aucune combinaison produit+societe+nom de lot n'est dupliquee -- une verification applicative, pas une contrainte de base de donnees.

**A verifier dans le code :** `models/stock_quant.py : check_product_id, check_location_id, check_lot_id (@api.constrains) ; models/stock_lot.py : _check_unique_lot (@api.constrains('name','product_id','company_id'))`

**Outils attendus :** ['analyze_data_constraints'] | **Outils invoques :** ['analyze_data_constraints', 'analyze_data_constraints']

**Reponse verbatim de l'agent (Total: 44.24s | Effectif: 20.602s | Groq wait: 23.637s | Sauts: 2) :**
```text
Les contraintes qui empêchent la création d’un `stock.quant` invalide sont définies dans le modèle `stock.quant`.  
- **Contrôle du type de produit** :  
  ```python
  @api.constrains('product_id')
  def check_product_id(self):
      if any(elem.product_id.type != 'product' for elem in self):
          raise ValidationError(_('Quants cannot be created for consumables or services.'))
  ```  
  (source : `stock_quant.py:L615-L618`)  
  Cette contrainte empêche la création d’un quant pour un produit dont le type n’est pas « product » (consommables ou services).

En ce qui concerne l’unicité du numéro de série, c’est la règle suivante qui est appliquée dans le modèle `stock.lot` :  
- **Unicité du numéro de série par produit et par société** :  
  ```python
  @api.constrains('name', 'product_id', 'company_id')
  def _check_unique_lot(self):
      domain = [('product_id', 'in', self.product_id.ids),
                ('company_id', 'in', self.company_id.ids),
                ('name', 'in', self.mapped('name'))]
      groupby = ['company_id', 'product_id', 'name']
      records = self._read_group(domain, groupby, having=[('__count', '>', 1)])
      ...
      if error_message_lines:
          raise ValidationError(_('The combination of serial number and product must be unique across a company.\nFollowing combination contains duplicates:\n') + '\n'.join(error_message_lines))
  ```  
  (source : `stock_lot.py:L91-L102`)  

Cette contrainte distincte garantit que chaque numéro de série (`name`) est unique pour un même produit (`product_id`) au sein d’une même société (`company_id`).

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'analyze_server_actions'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 18.09s | Effectif: 6.819s | Groq wait: 11.265s | Sauts: 4) :**
```text
**Short answer**

Non, un utilisateur qui appartient uniquement au groupe **`account.group_account_manager`** ne pourra pas créer ou modifier des factures tant que l’ACL directe de ce groupe sur le modèle `account.move` ne lui accorde que la permission de lecture.  

**Mais** :  
- Si ce groupe hérite d’un autre groupe (par ex. `account.group_account_user`) qui possède déjà les droits `write`/`create` sur `account.move`, alors l’utilisateur hérite de ces droits.  
- De même, un *record rule* (règle de filtre) ou un autre ACL appliqué à un groupe différent peut lui octroyer les droits d’écriture, même si l’ACL directe du groupe `account.group_account_manager` ne le fait pas.

---

## 1. Comment Odoo applique les ACL

| Étape | Description |
|-------|-------------|
| **ACLs** | Chaque groupe possède un fichier ACL (`ir.model.access`). Les droits sont cumulés : si **au moins un** ACL donne `write`/`create`/`unlink`, le groupe obtient ces droits. |
| **Héritage de groupes** | Un groupe peut hériter d’un autre (`groups_id`). Un utilisateur dans le groupe enfant possède automatiquement les droits du groupe parent. |
| **Record rules** | Les règles de filtre (`ir.rule`) peuvent restreindre ou autoriser l’accès à des enregistrements spécifiques, indépendamment des ACL. |

### Exemple typique

- `account.group_account_user` → `read`, `write`, `create`, `unlink` sur `account.move`.
- `account.group_account_manager` → hérite de `account.group_account_user` (dans la plupart des installations Odoo 15+).

Dans ce cas, même si vous avez créé une ACL *directe* pour `account.group_account_manager` qui ne donne que `read`, l’héritage du groupe parent lui confère toujours les droits d’écriture.

---

## 2. Pourquoi votre ACL directe ne suffit pas

Si vous avez **déclaré** une ACL pour `account.group_account_manager` qui ne donne que `read`, vous avez **supprimé** les droits d’écriture *pour ce groupe uniquement*.  
Mais :

1. **Il n’y a pas d’ACL supplémentaire** qui donne `write`/`create` à ce groupe.  
2. **Il n’y a pas de record rule** qui autorise l’écriture pour ce groupe.  
3. **Il n’y a pas d’héritage** d’un groupe qui possède déjà ces droits.

Dans ce scénario, l’utilisateur ne pourra **pas** créer ou modifier des factures.

---

## 3. Que faire si vous voulez qu’il puisse le faire

| Option | Action |
|--------|--------|
| **Ajouter les droits dans l’ACL** | Modifier le fichier `ir.model.access` pour `account.group_account_manager` et ajouter `write`, `create`, `unlink`. |
| **Hériter d’un groupe** | Ajouter `account.group_account_user` (ou un autre groupe avec les droits) dans la liste `groups_id` du groupe `account.group_account_manager`. |
| **Créer une règle de filtre** | Créer un `ir.rule` qui autorise l’écriture sur `account.move` pour ce groupe. |

---

## 4. Résumé

- **ACL directe uniquement `read`** → l’utilisateur ne peut pas créer/éditer.  
- **Héritage ou autre ACL** → l’utilisateur peut créer/éditer.  
- **Record rule** → peut aussi autoriser l’écriture.

Donc, **sans** aucune autre règle ou héritage, un « Billing Administrator » (group_account_manager) **ne pourra pas** créer ou modifier des factures. Si vous observez le contraire, vérifiez s’il hérite d’un groupe avec des droits d’écriture ou s’il existe une règle de filtre qui le permet.

 GROUPE(S) NON VÉRIFIÉ(S) : account.group_account_user mentionné(s) dans la réponse sans correspondance has_group() dans les données produites pour cette question. Ne pas considérer ce(s) groupe(s) comme confirmé(s) sans vérification manuelle.

[Source: Graphe de Connaissances Code Intelligence]

[ACCES RESTREINT] ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION:
  - SUDO détecté (account.move) : Élément omis pour raison d'autorisation (ELEMENT OMITTED FOR AUTHORIZATION REASON) : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'account.move'.
  - IDs en dur (account.move) : Élément omis pour raison d'autorisation (ELEMENT OMITTED FOR AUTHORIZATION REASON) : cette ligne décrit un mécanisme de contournement de sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès élevé sur 'account.move'.
```

---

## [ACC-Q2] account -- workflow (hard)
**Question :** Un 'Billing Administrator' (group_account_manager) peut-il poster une ecriture comptable dont la date est anterieure ou egale a la date de cloture (lock date) de la societe ?

**Reponse de reference (verite-terrain) :**
> Non, meme un manager en est empeche : _check_fiscalyear_lock_date() compare la date du mouvement a company._get_user_fiscal_lock_date() et leve un UserError des que date <= lock_date, sans aucune exception de groupe -- le seul effet du groupe est le libelle du message d'erreur (le manager recoit un message plus court, un non-manager est en plus invite a solliciter quelqu'un ayant le role 'Adviser'). Le blocage lui-meme est absolu : la seule issue est de faire reculer la lock_date via la configuration societe, pas de contourner la verification par un role plus eleve.

**A verifier dans le code :** `models/account_move.py : _check_fiscalyear_lock_date() (verifie user_has_groups('account.group_account_manager') uniquement pour choisir le texte du message, pas pour lever une exception au blocage)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] -- MANQUANT(S): ['describe_workflow']

**Reponse verbatim de l'agent (Total: 88.02s | Effectif: 33.244s | Groq wait: 54.776s | Sauts: 3) :**
```text
Il n’est pas possible de conclure avec certitude que le groupe **group_account_manager** (Billing Administrator) puisse poster une écriture comptable dont la date est antérieure ou égale à la date de clôture de la société, à partir des informations fournies.

**Pourquoi ?**

1. **Aucune règle de verrouillage (lock date) n’est visible** dans les extraits de code ou de configuration présentés.  
   - Le fragment de code `account.move._post` (file:///path#L10-L25) ne contient aucune condition liée à une date de clôture ou à un verrouillage.  
   - Aucun message de verrouillage (lock message) n’est listé dans les observations.

2. **Les permissions ACL sur le modèle `res.company`** indiquent que seul le groupe `group_erp_manager` possède les droits `WRITE`, `CREATE` et `UNLINK`.  
   - Le groupe `group_account_manager` n’apparaît pas dans ces permissions, mais cela concerne le modèle `res.company`, pas directement `account.move`.  
   - Sans information supplémentaire sur les ACL appliquées à `account.move`, on ne peut pas déterminer si `group_account_manager` a le droit de poster.

3. **Aucune règle `ir.rule` applicable** n’est mentionnée pour `account.move` dans les données fournies.  
   - Les règles globales et de groupe listées concernent uniquement `res.company`.

En l’absence de toute règle explicite ou de tout verrouillage lié à la date de clôture, on ne peut pas affirmer que le groupe Billing Administrator est autorisé ou non à poster une écriture comptable avec une date antérieure ou égale à la date de clôture. Il faudrait consulter les règles de sécurité (`ir.rule`), les ACL (`ir.model.access`) et les éventuels mécanismes de verrouillage (par ex. `account.move._post` dans d’autres modules) pour obtenir une réponse définitive.

 SOURCING NON VÉRIFIÉ : citation(s) fichier non retrouvée(s) dans les données produites: path#L10-L25. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q3] account -- inheritance (medium)
**Question :** account.move est-il un nouveau modele ou une extension ? Le module account etend-il en parallele un modele natif hors de son propre perimetre comptable ?

**Reponse de reference (verite-terrain) :**
> account.move est un nouveau modele (_name='account.move'), qui n'herite que de mixins (portal.mixin, mail.thread.main.attachment, mail.activity.mixin, sequence.mixin) -- aucune extension d'un modele metier preexistant. En parallele, ce meme module etend reellement res.partner (_inherit='res.partner', classe ResPartner dans models/partner.py), en lui ajoutant notamment le champ calcule fiscal_country_codes (base des codes pays fiscaux des societes autorisees) -- une extension comptable du modele partenaire natif, distincte du modele account.move.

**A verifier dans le code :** `models/account_move.py : classe AccountMove (_name + _inherit mixins) vs models/partner.py : classe ResPartner (_name='res.partner', _inherit='res.partner'), champ fiscal_country_codes`

**Outils attendus :** ['trace_full_inheritance', 'list_involved_modules'] | **Outils invoques :** ['list_involved_modules', 'trace_full_inheritance', 'read_source_code']

**Reponse verbatim de l'agent (Total: 4.85s | Effectif: 3.046s | Groq wait: 1.803s | Sauts: 2) :**
```text
### Modèle `account.move`

- **Nature** : `account.move` est un **modèle métier** défini dans le module `account`.  
  - Il n’est pas créé par un autre module qui l’étend, mais il **définit** le modèle lui‑même.  
  - Le fichier source principal est `account/models/account_move.py` (lignes 5‑22).  
  - Source : [account_move.py:L5-L22](file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L5-L22)

- **Extension de modèles natifs** :  
  - Le module `account` étend plusieurs modèles natifs (non comptables) via l’héritage `mail.thread`, `portal.mixin`, `sequence.mixin`, `utm.mixin`, etc.  
  - Cela se voit dans la chaîne d’héritage complète :  
    - `account.move` → `mail.activity.mixin` → `mail.thread.main.attachment` → `portal.mixin` → `sequence.mixin` → `utm.mixin`.  
  - Source : [Inheritance Chain for 'account.move'](file:///media/donnee/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L5-L22) et [account_move.py:L81-L161](file:///media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L81-L161)

### Réponse à la question

- **`account.move` est un modèle défini dans le module `account`** (pas une extension d’un modèle existant).  
- Le module `account` **étend des modèles natifs hors de son périmètre comptable** (ex. `mail.thread`, `portal.mixin`, `sequence.mixin`, `utm.mixin`).  
- Ainsi, il ne s’agit pas d’une extension parallèle d’un modèle natif hors de l’écosystème comptable, mais bien d’une extension de modèles natifs pour enrichir la fonctionnalité de `account.move`.

 SOURCING NON VÉRIFIÉ : citation(s) fichier non retrouvée(s) dans les données produites: media/donnee/odoo-ia-prototype/odoo_addons/custom_credit_note_approval/models/account_move.py#L5-L22, media/donnee/Programs/odoo-17.0/addons/account/models/account_move.py#L5-L22. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q4] account -- ui (hard)
**Question :** Un utilisateur avec uniquement group_account_invoice ('Billing') voit-il le compte comptable (account_id) d'une ligne de facture ? Et un 'Billing Administrator' (group_account_manager) le voit-il, en configuration Invoicing seule (sans le module Accounting installe) ?

**Reponse de reference (verite-terrain) :**
> Non dans les deux cas. Le champ account_id porte groups='account.group_account_readonly' dans la vue -- or ni group_account_invoice ni group_account_manager n'impliquent group_account_readonly (seul group_account_user, le profil 'comptable complet', implique a la fois invoice et readonly). En configuration Invoicing seule, la documentation du fichier de securite le confirme explicitement : seuls group_account_invoice et group_account_manager sont censes etre utilises, et aucun des deux ne donne acces au champ technique du compte comptable -- il faut le module Accounting (qui attribue alors group_account_user) pour le voir.

**A verifier dans le code :** `views/account_move_views.xml : <field name="account_id" ... groups="account.group_account_readonly"/> + security/account_security.xml : commentaire d'en-tete + implied_ids de group_account_invoice/group_account_manager/group_account_user`

**Outils attendus :** ['button_execution_path'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'read_source_code'] -- MANQUANT(S): ['button_execution_path']

**Reponse verbatim de l'agent (Total: 93.39s | Effectif: 44.602s | Groq wait: 48.785s | Sauts: 4) :**
```text
**Réponse synthétique**

- Un utilisateur appartenant uniquement au groupe `account.group_account_invoice` (Billing) **peut** voir le champ `account_id` d’une ligne de facture.  
- Un utilisateur appartenant au groupe `account.group_account_manager` (Billing Administrator) **peut** également voir ce champ, même si le module Accounting n’est pas installé (configuration Invoicing seule).

**Justification détaillée**

1. **Permissions d’accès (ACL) sur le modèle `account.move`**  
   - L’Access Matrix indique que le groupe `account.group_account_invoice` possède le droit **READ** sur le modèle `account.move` :  
     `READ: account.group_account_invoice, account.group_account_manager, …` (xml_id: `account.group_account_invoice`, `account.group_account_manager`).  
   - Le même droit READ est accordé au groupe `account.group_account_manager`.  
   - Ces droits permettent à l’utilisateur de consulter les enregistrements d’invoice et, par extension, leurs lignes (`account.move.line`), dont le champ `account_id`.

2. **Absence de règles d’enregistrement (ir.rule) restrictives**  
   - L’évaluation des règles d’enregistrement pour `account.move` ne révèle aucune règle de groupe qui limiterait la visibilité du champ `account_id`.  
   - Les seules règles globales appliquées concernent la multi‑entreprise et la visibilité des factures par état ou par utilisateur, mais aucune d’elles ne restreint l’affichage du compte comptable.

3. **Configuration Invoicing seule**  
   - Les groupes `account.group_account_invoice` et `account.group_account_manager` sont inclus dans le module Invoicing.  
   - Même sans le module Accounting installé, ces groupes conservent leurs droits READ sur `account.move`, donc la visibilité du champ `account_id` reste intacte.

En résumé, tant le groupe Billing que le groupe Billing Administrator disposent des droits nécessaires pour voir le champ `account_id` d’une ligne de facture dans une configuration Invoicing seule.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q5] account -- constraints (hard)
**Question :** account.move declare un _sql_constraints 'unique_name' dont la definition SQL est une chaine vide -- comment l'unicite du numero de piece est-elle reellement appliquee ?

**Reponse de reference (verite-terrain) :**
> Le triplet _sql_constraints=[('unique_name', '', '...')] ne cree aucune contrainte via le mecanisme standard (definition vide) ; il sert uniquement a fournir le message d'erreur associe. L'unicite reelle est creee manuellement dans _auto_init() via un index SQL partiel : CREATE UNIQUE INDEX account_move_unique_name ON account_move(name, journal_id) WHERE (state='posted' AND name != '/') -- l'unicite ne s'applique donc qu'aux ecritures postees et nommees (pas aux brouillons, qui partagent tous le placeholder '/'). Independamment, @api.constrains('journal_id','move_type') / _check_journal_move_type interdit de creer un document d'achat dans un journal dont journal_id.type != 'purchase' (et symetriquement pour la vente).

**A verifier dans le code :** `models/account_move.py : _sql_constraints (unique_name, definition vide) + _auto_init() (CREATE UNIQUE INDEX account_move_unique_name, index partiel) + _check_journal_move_type (@api.constrains)`

**Outils attendus :** ['analyze_data_constraints', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'analyze_data_constraints'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 43.26s | Effectif: 38.29s | Groq wait: 4.973s | Sauts: 2) :**
```text
Dans `account.move` le champ `name` (le numéro de pièce) n’est pas protégé par une contrainte SQL : l’entrée `_sql_constraints` nommée `unique_name` contient une chaîne vide, donc aucune contrainte SQL n’est réellement créée.  

L’unicité est assurée par une contrainte Python :

```python
@api.constrains('name', 'journal_id', 'date')
def _check_move_name(self):
    for move in self:
        if move.name and move.journal_id:
            # Vérifie qu’aucun autre mouvement du même journal et de la même date n’a le même nom
            if self.search_count([
                ('name', '=', move.name),
                ('journal_id', '=', move.journal_id.id),
                ('date', '=', move.date),
                ('id', '!=', move.id),
            ]):
                raise ValidationError(_("The name of the move must be unique per journal and date."))
```

Cette contrainte est exécutée à chaque création ou modification d’un `account.move`.  
En pratique, le numéro de pièce est généré par une séquence liée au journal (`ir.sequence`), ce qui garantit déjà une valeur unique, et la contrainte Python vérifie qu’aucun doublon n’existe dans la même combinaison journal‑date.

Ainsi, même si la contrainte SQL est vide, l’unicité du numéro de pièce est réellement appliquée grâce à cette contrainte Python.

[Source: Graphe de Connaissances Code Intelligence]
```

---