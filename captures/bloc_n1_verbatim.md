# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-23 00:27:02

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees (consolidees) | 7 |
| Questions rejouees ce tour | 1 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 0 |
| p50 latence effective (run courant) | `95.66s` |
| p90 latence effective (run courant) | `95.66s` (budget `12.0s`,  DEPASSE) |
| Moyenne (run courant) | `95.66s` |
| Max (run courant) | `95.66s` |

---

## [MNT-Q1] maintenance -- security (hard)
**Question :** Un utilisateur simple (base.group_user, sans group_equipment_manager) peut-il modifier une fiche equipement (maintenance.equipment), et quels equipements peut-il seulement consulter ?

**Reponse de reference (verite-terrain) :**
> Non pour l'ecriture : l'ACL access_equipment_user reserve perm_write=0/perm_create=0/perm_unlink=0 a base.group_user (lecture seule) ; seul group_equipment_manager (ACL access_equipment_admin_user) a perm_write/create/unlink=1. Meme en lecture, l'ir.rule equipment_rule_user restreint base.group_user aux equipements ou il figure dans message_partner_ids (suiveur) -- group_equipment_manager n'a pas cette restriction (equipment_rule_admin_user, domain (1,'=',1), acces total). Sur maintenance.request en revanche, base.group_user a les 4 permissions ACL completes (access_maintenance_system_user), mais reste borne par ir.rule aux demandes ou il est owner_user_id, user_id, ou suiveur (equipment_request_rule_user).

**A verifier dans le code :** `security/ir.model.access.csv (access_equipment_user, access_equipment_admin_user, access_maintenance_system_user) + security/maintenance.xml (equipment_rule_user, equipment_rule_admin_user, equipment_request_rule_user)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'read_source_code']

**Reponse verbatim de l'agent (Total: 80.46s | Effectif: 80.457s | Groq wait: 0.0s | Sauts: 6) :**
```text
**Accès d’un utilisateur simple (base.group_user, sans group_equipment_manager)**  

| Action | Autorisation ACL | Règle ir.rule applicable | Résultat |
|--------|------------------|--------------------------|----------|
| **Lecture** | `READ` autorisé à `base.group_user` (voir Access Matrix) | `maintenance.equipment_rule_user` : `message_partner_ids` doit contenir l’ID du partenaire de l’utilisateur. <br> `maintenance.maintenance_equipment_comp_rule` : `company_id` doit appartenir à la liste des entreprises de l’utilisateur. | L’utilisateur peut **voir** les fiches équipements qui respectent les deux conditions ci‑dessus (équipements qu’il suit et appartenant à sa société). |
| **Écriture / création / suppression** | `WRITE`, `CREATE`, `UNLINK` autorisés uniquement à `group_equipment_manager` (Access Matrix). | Même règle `maintenance.equipment_rule_user` s’applique, mais elle ne suffit pas sans l’autorisation ACL. | L’utilisateur **ne peut pas modifier, créer ni supprimer** aucune fiche équipement, même si l’équipement est suivi ou appartient à sa société. |

### Conclusion

- Un utilisateur simple **ne peut pas modifier** une fiche équipement (aucune permission `WRITE` dans l’ACL).  
- Il peut **seulement consulter** les équipements qu’il suit (`message_partner_ids` contient son partenaire) et qui appartiennent à sa société (contrôle global `maintenance.maintenance_equipment_comp_rule`).  

Ainsi, la visibilité est limitée aux équipements suivis par l’utilisateur et à ceux de sa propre entreprise, tandis que toute modification requiert le groupe `group_equipment_manager`.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [MNT-Q2] maintenance -- workflow (hard)
**Question :** Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente (recurring_maintenance=True) atteint une etape marquee 'done' ?

**Reponse de reference (verite-terrain) :**
> MaintenanceRequest.write() detecte que stage_id change vers un stage dont done=True ; pour chaque demande de maintenance_type='preventive' avec recurring_maintenance actif, calcule une nouvelle schedule_date (date actuelle ou schedule_date existante + repeat_interval unites de repeat_unit via relativedelta), et si repeat_type=='forever' ou que la nouvelle date reste <= repeat_until, duplique automatiquement la demande (copy()) avec cette nouvelle schedule_date et la reinsere au stage par defaut (_default_stage) -- generation automatique de la prochaine occurrence, avant meme l'appel a super().write().

**A verifier dans le code :** `models/maintenance.py, classe MaintenanceRequest, methode write() (bloc verifiant request.maintenance_type != 'preventive' or not request.recurring_maintenance)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'read_source_code']

**Reponse verbatim de l'agent (Total: 56.46s | Effectif: 56.454s | Groq wait: 0.0s | Sauts: 2) :**
```text
Les observations disponibles ne montrent aucun mécanisme automatique lié à l’achèvement d’une étape « done » pour une demande de maintenance préventive récurrente (`recurring_maintenance=True`).  

- Le modèle `maintenance.request` est présent dans l’index, mais aucune transition d’état explicite n’est définie dans le code (voir observation : *Model 'maintenance.request' exists in the index but has no explicit workflow state transitions defined*).  
- Le fichier `maintenance/models/maintenance_request.py` n’existe pas dans les sources analysées (*File 'maintenance/models/maintenance_request.py' does not exist*).  

En l’absence de code ou de règle définie, on ne peut pas déterminer ce qui se passe automatiquement lorsqu’une étape est marquée « done ». Les données recueillies ne contiennent donc aucune information sur un comportement automatique.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q1] purchase -- security (hard)
**Question :** L'ACL de purchase.order accorde les 4 permissions (lecture/ecriture/creation/suppression) a group_purchase_user comme a group_purchase_manager. Qu'est-ce qui distingue alors reellement un simple acheteur d'un manager sur une commande d'achat ?

**Reponse de reference (verite-terrain) :**
> Rien au niveau ACL/ir.rule (access_purchase_order et access_purchase_order_manager sont strictement identiques, 1,1,1,1 ; purchase_order_comp_rule ne fait que filtrer par societe, sans distinction de groupe). La distinction reelle est portee par une methode Python, _approval_allowed() : une commande peut etre approuvee sans intervention manager si po_double_validation=='one_step', ou si po_double_validation=='two_step' et que le montant total reste sous po_double_validation_amount (Monetary, defaut 5000) -- sinon seul un utilisateur avec purchase.group_purchase_manager (via user_has_groups) peut l'approuver. Cette regle n'est pas un ACL/ir.rule mais un garde applicatif invoque depuis button_confirm()/button_approve().

**A verifier dans le code :** `security/ir.model.access.csv (access_purchase_order vs access_purchase_order_manager, identiques) + models/purchase_order.py : _approval_allowed(), models/res_company.py : po_double_validation/po_double_validation_amount`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'describe_workflow', 'button_execution_path', 'read_source_code']

**Reponse verbatim de l'agent (Total: 55.89s | Effectif: 55.88s | Groq wait: 0.0s | Sauts: 7) :**
```text
Les droits d’accès (ACL) sont identiques : `group_purchase_user` et `group_purchase_manager` disposent tous deux des permissions **lecture / écriture / création / suppression** sur le modèle `purchase.order`.  
La différence entre un acheteur « simple » et un manager ne se trouve donc pas dans les ACL, mais dans la logique métier implémentée en Python.

---

### 1. Contrôle d’approbation (Python)

Dans le fichier `purchase_order.py` (voir l’observation **Analyse des verrous Python**), la méthode `_approval_allowed()` contient :

```
has_group('purchase.group_purchase_manager')
```

(Observation : `[Confiance: ÉLEVÉE]` – `has_group('purchase.group_purchase_manager')` se trouve dans la méthode `_approval_allowed()` – xml_id: purchase.group_purchase_manager, ligne 969‑969).

Cette vérification est utilisée lorsqu’un utilisateur tente d’approuver une commande d’achat (par exemple via le bouton « Confirm Order »).  
- **Si l’utilisateur appartient à `group_purchase_manager`** : la méthode renvoie `True` et l’approbation est autorisée.  
- **Si l’utilisateur n’appartient pas à ce groupe** : la méthode renvoie `False`, bloquant l’approbation.

Ainsi, **seul le manager peut approuver une commande d’achat** ; un acheteur ne possède pas cette autorité.

---

### 2. Pas de restriction supplémentaire via les règles de sécurité

- **Règles globales** : `purchase.purchase_order_comp_rule` (multi‑entreprise) s’applique à tous les utilisateurs, mais ne différencie pas les groupes.  
- **Règles de groupe** : aucune règle de groupe n’est appliquée à `purchase.order`.  
- **Règles ignorées** : la règle du portail (`purchase.portal_purchase_order_user_rule`) ne concerne que les utilisateurs portail et n’affecte pas les deux groupes.

En conséquence, aucune règle d’accès supplémentaire ne distingue les deux groupes au niveau des enregistrements.

---

### 3. Autres actions spécifiques aux managers

Les observations montrent également que :

- `group_warning_purchase` est utilisé dans `onchange_partner_id_warning()` (ligne 329‑329).  
- `group_send_reminder` est utilisé dans `_send_reminder_mail()` (ligne 768‑768).

Ces groupes permettent respectivement d’afficher des avertissements et d’envoyer des rappels.  
Ils ne sont pas requis pour l’approbation, mais ils indiquent que les managers ont des capacités supplémentaires (avertissements, rappels) que les acheteurs n’ont pas.

---

## Résumé

- **ACL** : identiques pour les deux groupes.  
- **Différence clé** : la méthode `_approval_allowed()` (ligne 969‑969) exige l’appartenance à `group_purchase_manager` pour approuver une commande d’achat.  
- **Pas de restriction via ir.rule** : aucune règle de groupe ne s’applique.  
- **Fonctions supplémentaires** : les managers peuvent afficher des avertissements (`group_warning_purchase`) et envoyer des rappels (`group_send_reminder`), fonctions non disponibles pour les acheteurs.

En pratique, un acheteur peut créer, modifier et supprimer des commandes d’achat, mais il ne peut pas les approuver ; seul un manager possède cette autorité.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q2] purchase -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on clique sur 'Confirm Order' (button_confirm) selon que la commande est eligible ou non a l'approbation directe ?

**Reponse de reference (verite-terrain) :**
> button_confirm() ne s'applique qu'aux commandes en etat 'draft' ou 'sent' (les autres sont ignorees silencieusement) ; il valide d'abord la distribution analytique des lignes et ajoute le fournisseur au produit, puis appelle _approval_allowed() : si vrai, delegue a button_approve() qui passe directement l'etat a 'purchase' (et a 'done' si po_lock=='lock') ; si faux, l'etat passe seulement a 'to approve' -- en attente qu'un manager declenche explicitement button_approve() via le bouton dedie.

**A verifier dans le code :** `models/purchase_order.py : button_confirm(), button_approve()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'analyze_method_override_chain', 'read_source_code', 'describe_workflow', 'button_execution_path', 'read_source_code', 'read_source_code']

**Reponse verbatim de l'agent (Total: 95.67s | Effectif: 95.664s | Groq wait: 0.0s | Sauts: 7) :**
```text
**Que se passe‑t‑il exactement lorsqu’on clique sur « Confirm Order » ?**

1. **Appel de la méthode `button_confirm()`**  
   Le bouton déclenche la méthode définie dans `purchase_order.py` aux lignes 84‑514 :  
   *(bloc de code omis : non retrouvé verbatim dans les observations produites pour cette question -- voir la/les citation(s) file:// à proximité pour le contenu réel.)*
   (source : file:///.../purchase_order.py#L84-L514)

2. **Vérification d’éligibilité**  
   La première instruction est `self._purchase_request_line_check()`.  
   - Si cette vérification échoue, elle lève généralement une `UserError` (ou un autre type d’exception) ; le reste de la méthode n’est alors pas exécuté et la commande reste dans son état actuel (`draft` ou `sent`).  
   - Si la vérification réussit, le code continue.

3. **Confirmation standard**  
   `super().button_confirm()` exécute la logique de confirmation propre au module `purchase`.  
   - Elle passe l’état de la commande de `draft`/`sent` à `sale`.  
   - Elle crée les lignes de réquisition, les mouvements de stock, etc., conformément au workflow d’achat standard.  
   (voir le code hérité dans le module `purchase`, non détaillé ici mais appelé par `super()`).

4. **Message de confirmation**  
   Après la confirmation, `self._purchase_request_confirm_message()` est invoqué pour poster un message de confirmation (par ex. sur le chatter de la commande).  
   (source : file:///.../purchase_order.py#L87)

5. **Pas de restriction de groupe sur le bouton**  
   Le bouton « Confirm Order » n’est pas limité par un groupe d’utilisateurs (`groups="..."`), donc tout utilisateur ayant accès à la vue de la commande peut cliquer dessus.

**En résumé**

- **Commande éligible à l’approbation directe** :  
  `self._purchase_request_line_check()` passe, `super().button_confirm()` confirme la commande (état → `sale`), puis un message de confirmation est posté.

- **Commande non éligible** :  
  `self._purchase_request_line_check()` lève une exception, empêchant la confirmation ; l’état de la commande ne change pas et aucun message n’est posté.

[FAIT DÉTERMINISTIQUE] La chaîne de surcharge de méthode inclut également le/les module(s) suivant(s), absent(s) ou mal identifié(s) ci-dessus : 'purchase_stock'. Fait extrait directement de l'analyse statique du code.

[FAIT DÉTERMINISTIQUE] SUPER() NON GARDÉ détecté dans la chaîne de surcharge : module 'purchase_stock' : branche conditionnelle `order.state in ('draft', 'sent', 'to approve', 'purchase') / order_line.move_dest_ids / moves_to_unlink` avec super() rappelé inconditionnellement (risque d'annulation silencieuse de cette logique). Fait extrait directement de l'analyse statique du code.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q1] sale -- security (hard)
**Question :** Un vendeur (sales_team.group_sale_salesman, sans group_sale_salesman_all_leads) peut-il voir toutes les commandes de vente de son entreprise, ou seulement certaines ? Et un utilisateur du portail (base.group_portal) ?

**Reponse de reference (verite-terrain) :**
> Non pour le vendeur simple : l'ACL access_sale_order lui donne perm_read/write/create=1 (pas perm_unlink), mais l'ir.rule sale_order_personal_rule le restreint aux commandes ou user_id lui est assigne ou user_id est vide (domaine OR) ; seul un vendeur avec en plus group_sale_salesman_all_leads herite de sale_order_see_all (domaine (1,'=',1), tout voir). Pour le portail : ACL access_sale_order_portal en lecture seule (perm_read=1, tout le reste 0), combinee a sale_order_rule_portal qui restreint aux commandes ou le partenaire (ou un enfant commercial) figure dans message_partner_ids -- avec ici perm_write/perm_unlink actives via la regle elle-meme (perm_write=True, perm_unlink=True dans la regle), ce qui autorise l'ecriture/suppression via la regle malgre l'ACL en lecture seule, en pratique borne au flux portail (ex. wizard d'annulation).

**A verifier dans le code :** `security/ir.model.access.csv (access_sale_order, access_sale_order_portal) + security/ir_rules.xml (sale_order_personal_rule, sale_order_see_all, sale_order_rule_portal)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'read_source_code']

**Reponse verbatim de l'agent (Total: 76.79s | Effectif: 76.784s | Groq wait: 0.0s | Sauts: 10) :**
```text
**Vendeur (sales_team.group_sale_salesman)**  
- Le droit de lecture est accordé au groupe `sales_team.group_sale_salesman` (voir la matrice d’accès).  
- Cependant, l’évaluation des règles d’enregistrement (`ir.rule`) montre que, en plus de la règle globale multi‑entreprise `sale.sale_order_comp_rule`, une règle de groupe s’applique :  
  - **Personal Orders** `[['|',('user_id','=',user.id),('user_id','=',False)]]` (`xml_id: sale.sale_order_personal_rule`).  
- Cette règle limite l’accès aux commandes dont le champ `user_id` est soit le même que l’utilisateur actuel, soit vide.  
- Les règles de groupe ignorées (`sale.sale_order_rule_portal`, `sale.sale_order_see_all`) ne s’appliquent pas à ce groupe.  
- **Conclusion** : un vendeur ne peut voir que les commandes qui lui sont attribuées (ou celles sans utilisateur) et non toutes les commandes de son entreprise.

**Utilisateur du portail (base.group_portal)**  
- Le droit de lecture est également accordé au groupe `base.group_portal`.  
- L’évaluation des règles d’enregistrement indique que la règle de groupe applicable est :  
  - **Portal Personal Quotations/Sales Orders** `[['message_partner_ids','child_of',[user.commercial_partner_id.id]]]` (`xml_id: sale.sale_order_rule_portal`).  
- Cette règle ne permet d’accéder qu’aux commandes dont le champ `message_partner_ids` contient le partenaire commercial de l’utilisateur.  
- Les règles de groupe ignorées (`sale.sale_order_personal_rule`, `sale.sale_order_see_all`) ne s’appliquent pas à ce groupe.  
- **Conclusion** : un utilisateur du portail ne peut voir que les commandes auxquelles il est lié via `message_partner_ids`, et non toutes les commandes de l’entreprise.

En résumé, ni le vendeur ni l’utilisateur du portail n’ont accès à l’ensemble des commandes de l’entreprise ; chacun est limité aux commandes qui lui sont directement associées selon les règles d’enregistrement décrites ci‑dessus.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q1] stock -- security (hard)
**Question :** Un simple employe (base.group_user, sans stock.group_stock_user) peut-il consulter les quantites en stock (stock.quant) ? Et peut-il modifier une ligne de mouvement (stock.move.line) ?

**Reponse de reference (verite-terrain) :**
> Oui pour la consultation : access_stock_quant_all accorde perm_read=1 (lecture seule) a base.group_user meme sans stock.group_stock_user -- les niveaux de stock sont visibles a tout employe, seule l'ecriture/creation/suppression exige stock.group_stock_user (access_stock_quant_user, perm_unlink=0 meme pour ce groupe). Plus surprenant : sur stock.move.line, base.group_user a directement les 4 permissions completes (access_stock_move_line_all, 1,1,1,1) -- un acces plus large que sur stock.move lui-meme, qui exige stock.group_stock_user (et reste perm_unlink=0 pour ce groupe). Aucune de ces ACL n'est affinee par ir.rule au-dela du filtrage multi-societe (stock_quant_rule, stock_move_line_rule) -- pas de restriction par entrepot ou par role.

**A verifier dans le code :** `security/ir.model.access.csv (access_stock_quant_all, access_stock_quant_user, access_stock_move_user, access_stock_move_line_all) + security/stock_security.xml (stock_quant_rule, stock_move_line_rule, filtrage company_id uniquement)`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules'] | **Outils invoques :** ['who_has_access_to', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules', 'evaluate_record_rules']

**Reponse verbatim de l'agent (Total: 59.54s | Effectif: 59.535s | Groq wait: 0.0s | Sauts: 6) :**
```text
**Consultation des quantités en stock (model `stock.quant`)**

- L’évaluation des règles d’enregistrement (`ir.rule`) pour `stock.quant` indique uniquement une règle globale :  
  `stock_quant multi-company [[('company_id', 'in', company_ids + [False])]]` (xml_id : `stock.stock_quant_rule`).  
  Aucune règle de groupe n’est appliquée à ce modèle pour l’utilisateur « simple_employe » (base.group_user).  
- Aucun autre mécanisme d’accès (ACL, verrou Python, etc.) n’est présent dans les observations fournies.  
- **Conclusion partielle** : aucune restriction d’enregistrement n’est imposée par `ir.rule`.  
  Cependant, l’ACL n’a pas été évaluée dans ces observations, donc on ne peut pas affirmer de façon définitive que l’utilisateur possède le droit de lecture sur `stock.quant`.  

---

**Modification d’une ligne de mouvement (model `stock.move.line`)**

- **ACL** :  
  - `WRITE` est accordé à `base.group_user` (et à plusieurs autres groupes) – voir la liste des groupes dans la section ACL pour `stock.move.line`.  
- **Règles d’enregistrement (`ir.rule`)** :  
  - Aucune règle globale ni règle de groupe n’est appliquée à ce modèle pour l’utilisateur « simple_employe ».  
- **Conclusion** :  
  - Sur la base des ACL et de l’absence de règles d’enregistrement restrictives, un employé simple (base.group_user, sans stock.group_stock_user) a le droit de modifier une ligne de mouvement (`stock.move.line`).  

---

### Résumé

| Action | Modèle | Accès garanti par les observations |
|--------|--------|-------------------------------------|
| Consulter `stock.quant` | Oui, aucune règle d’enregistrement ne bloque l’accès. | **À confirmer** par l’ACL (non évaluée). |
| Modifier `stock.move.line` | Oui, ACL donne le droit d’écriture et aucune règle d’enregistrement ne le bloque. |

> **Attention** : ces conclusions se basent uniquement sur les mécanismes d’accès et de règles d’enregistrement évalués dans les observations fournies. D’autres contrôles (workflow, verrou Python, conditions de sécurité supplémentaires) n’ont pas été vérifiés dans cette passe et pourraient influencer l’accès réel.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [ACC-Q1] account -- security (hard)
**Question :** L'ACL directe de account.group_account_manager sur account.move n'accorde que perm_read=1 (aucune ecriture/creation/suppression). Un 'Billing Administrator' (group_account_manager) peut-il malgre tout creer et modifier des factures ?

**Reponse de reference (verite-terrain) :**
> Oui : access_account_move_manager est bien limite a la lecture seule, mais group_account_manager a implied_ids=[group_account_invoice], et access_account_move_uinvoice accorde a group_account_invoice les 4 permissions completes (1,1,1,1). Le manager herite donc du CRUD complet via ce groupe implique, pas via son propre ACL direct -- lire uniquement l'ACL 'manager' donne une image trompeuse (lecture seule) ; il faut evaluer la fermeture transitive des implied_ids pour connaitre les droits reels.

**A verifier dans le code :** `security/ir.model.access.csv (access_account_move_manager vs access_account_move_uinvoice) + security/account_security.xml (group_account_manager implied_ids=[group_account_invoice])`

**Outils attendus :** ['who_has_access_to', 'evaluate_record_rules', 'read_source_code'] | **Outils invoques :** ['analyze_security_locks', 'who_has_access_to', 'evaluate_record_rules', 'read_source_code']

**Reponse verbatim de l'agent (Total: 73.0s | Effectif: 73.002s | Groq wait: 0.0s | Sauts: 4) :**
```text
Oui.  
L’ACL directe ne donne pas de droits d’écriture à **account.group_account_manager**, mais ce groupe hérite des droits de **account.group_account_invoice** :  

- Dans la matrice d’accès pour le modèle `account.move`, le groupe **account.group_account_manager** apparaît dans les colonnes **WRITE**, **CREATE** et **UNLINK** via l’implied_id `account.group_account_invoice` (voir la ligne « WRITE: account.group_account_manager (via implied_ids <- account.group_account_invoice) »).  
- Aucun `ir.rule` ne restreint l’accès à ce groupe pour ce modèle (aucune règle de groupe applicable, seules les règles globales s’appliquent).  

Par conséquent, un utilisateur appartenant à **group_account_manager** (Billing Administrator) peut créer, modifier et supprimer des factures.

[Source: Graphe de Connaissances Code Intelligence]
```

---