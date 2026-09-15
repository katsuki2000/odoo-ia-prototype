# Rapport Verbatim -- Bloc N1 (banc de questions natif)

**Date d'execution :** 2026-09-15 09:09:15

**Objectif :** rejouer les questions verite-terrain des 5 modules natifs (maintenance, purchase, sale, stock, account) contre l'agent Code Intelligence reel et capturer la reponse verbatim pour comparaison manuelle avec `reference_answer` -- aucune notation automatique.

---
## Synthese

| Metrique | Valeur |
|---|---|
| Questions executees | 4 |
| Erreurs d'execution | 0 |
| Ecarts de couverture d'outils (expected_tools non tous invoques) | 3 |
| p50 latence effective | `3.53s` |
| p90 latence effective | `10.52s` (budget `12.0s`,  RESPECTE) |
| Moyenne | `5.1s` |
| Max | `10.52s` |

---

## [MNT-Q2] maintenance -- workflow (hard)
**Question :** Que se passe-t-il automatiquement quand une demande de maintenance preventive et recurrente (recurring_maintenance=True) atteint une etape marquee 'done' ?

**Reponse de reference (verite-terrain) :**
> MaintenanceRequest.write() detecte que stage_id change vers un stage dont done=True ; pour chaque demande de maintenance_type='preventive' avec recurring_maintenance actif, calcule une nouvelle schedule_date (date actuelle ou schedule_date existante + repeat_interval unites de repeat_unit via relativedelta), et si repeat_type=='forever' ou que la nouvelle date reste <= repeat_until, duplique automatiquement la demande (copy()) avec cette nouvelle schedule_date et la reinsere au stage par defaut (_default_stage) -- generation automatique de la prochaine occurrence, avant meme l'appel a super().write().

**A verifier dans le code :** `models/maintenance.py, classe MaintenanceRequest, methode write() (bloc verifiant request.maintenance_type != 'preventive' or not request.recurring_maintenance)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'analyze_server_actions'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 7.72s | Effectif: 2.808s | Groq wait: 4.916s | Sauts: 2) :**
```text
Dans le modèle **`maintenance.request`**, aucune transition de workflow n’est définie pour l’état « done ».  
De plus, aucun **ir.actions.server** n’est configuré pour ce modèle.  

En conséquence, lorsqu’une demande de maintenance préventive et récurrente (`recurring_maintenance=True`) atteint l’étape marquée « done », **aucune action automatique n’est déclenchée**. Il n’y a pas de changement d’état supplémentaire, de notification ou d’opération programmée liée à cet état.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [PUR-Q2] purchase -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on clique sur 'Confirm Order' (button_confirm) selon que la commande est eligible ou non a l'approbation directe ?

**Reponse de reference (verite-terrain) :**
> button_confirm() ne s'applique qu'aux commandes en etat 'draft' ou 'sent' (les autres sont ignorees silencieusement) ; il valide d'abord la distribution analytique des lignes et ajoute le fournisseur au produit, puis appelle _approval_allowed() : si vrai, delegue a button_approve() qui passe directement l'etat a 'purchase' (et a 'done' si po_lock=='lock') ; si faux, l'etat passe seulement a 'to approve' -- en attente qu'un manager declenche explicitement button_approve() via le bouton dedie.

**A verifier dans le code :** `models/purchase_order.py : button_confirm(), button_approve()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'button_execution_path'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 10.04s | Effectif: 2.923s | Groq wait: 7.057s | Sauts: 2) :**
```text
Lorsque l’utilisateur clique sur le bouton **« Confirm Order »** dans la vue formulaire d’une commande d’achat (`purchase.order`), le système exécute la méthode Python `button_confirm()` (définie dans `purchase_order.py` aux lignes L501‑L514).  

Cette action entraîne une transition d’état :  
- Si la commande est en état **draft** ou **sent**, elle passe immédiatement à l’état **sale**.  

Aucune restriction de groupe n’est appliquée à ce bouton (voir la description du workflow : « Button 'Confirm Order' (Method: `button_confirm()`, Role: [All Users]) »).  

En conséquence, qu’une commande soit éligible ou non à une approbation directe, le clic sur « Confirm Order » le mettra toujours en état **sale** sans déclencher de vérification supplémentaire.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [SAL-Q2] sale -- workflow (medium)
**Question :** Que se passe-t-il exactement quand on confirme une commande de vente (action_confirm), et dans quel cas est-elle automatiquement verrouillee (locked) juste apres ?

**Reponse de reference (verite-terrain) :**
> action_confirm() verifie d'abord que toutes les commandes sont en etat 'draft' ou 'sent' (_can_be_confirmed()), sinon UserError ; valide la distribution analytique des lignes, souscrit le client aux notifications, ecrit state='sale' + date_order=now (_prepare_confirmation_values), puis appelle _action_confirm() (cree un compte analytique si une ligne porte un produit avec expense_policy actif). Immediatement apres, filtre les commandes via _should_be_locked() -- qui verifie has_group('sale.group_auto_done_setting') sur le createur de la commande (pas l'utilisateur courant) -- et appelle action_lock() (locked=True) sur celles-la uniquement ; ce n'est donc pas systematique, ca depend d'un parametrage (groupe) rattache au createur de la commande, pas de l'utilisateur qui confirme.

**A verifier dans le code :** `models/sale_order.py : action_confirm(), _should_be_locked(), _can_be_confirmed(), _action_confirm()`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'analyze_method_override_chain'] -- MANQUANT(S): ['read_source_code']

**Reponse verbatim de l'agent (Total: 15.77s | Effectif: 4.138s | Groq wait: 11.633s | Sauts: 2) :**
```text
Lorsque vous cliquez sur **« Confirm »** sur une commande de vente, le système exécute la méthode `action_confirm()` du modèle `sale.order`.  
Cette méthode :

1. **Vérifie l’état de chaque commande** en appelant `order._can_be_confirmed()`.  
2. Si **toutes** les commandes sont dans un état qui nécessite une confirmation, elles passent de l’état **draft** à l’état **sale** (voir la transition du workflow : `[draft] -> [sale] via Button 'Confirm' (Method: action_confirm())`).  
3. **Si au moins une commande n’est pas dans un état requérant une confirmation**, la méthode déclenche un verrou (lock) et affiche le message :  
   > *« The following orders are not in a state requiring confirmation: %s »*  
   (voir le code source : `file:///home/user/odoo-17.0/addons/sale/models/sale_order.py#L944-L982`).

En résumé, la commande est automatiquement verrouillée **juste après** l’appel à `action_confirm()` lorsqu’elle n’est pas dans un état qui requiert une confirmation (par exemple, si elle est déjà confirmée ou dans un état qui ne permet pas la confirmation). Cette logique est définie uniquement dans le module `sale` et aucune surcharge supplémentaire n’est détectée.

[Source: Graphe de Connaissances Code Intelligence]
```

---

## [STK-Q2] stock -- workflow (hard)
**Question :** Que se passe-t-il quand on valide un transfert de stock (button_validate) dont les quantites traitees sont inferieures aux quantites demandees ?

**Reponse de reference (verite-terrain) :**
> button_validate() ignore les transferts deja 'done', confirme automatiquement ceux encore en 'draft', puis complete a la quantite demandee toute ligne dont la quantite traitee est nulle. Une verification de coherence (_sanity_check) s'execute ensuite sauf contexte skip_sanity_check. _pre_action_done_hook() marque picked=True des que des quantites existent. Vient ensuite la decision cle : les transferts sont scindes entre ceux dont picking_type_id.create_backorder=='never' (jamais de reliquat, executes avec cancel_backorder=True) et les autres (executes normalement, create_backorder='always' ou 'ask') -- c'est ce parametre du type d'operation, pas une valeur globale, qui determine si un bon de livraison partiel genere automatiquement un reliquat (backorder) pour les quantites restantes.

**A verifier dans le code :** `models/stock_picking.py : button_validate(), _pre_action_done_hook(), champ picking_type_id.create_backorder (stock_picking_type.py)`

**Outils attendus :** ['describe_workflow', 'read_source_code'] | **Outils invoques :** ['describe_workflow', 'analyze_data_constraints', 'read_source_code']

**Reponse verbatim de l'agent (Total: 20.39s | Effectif: 10.52s | Groq wait: 9.867s | Sauts: 3) :**
```text
Lorsque vous cliquez sur **button_validate** pour un transfert de stock dont les quantités traitées sont inférieures aux quantités demandées, le picking passe de l’état **confirmed** à l’état **done** (voir transition 6 : `[confirmed] -> [done] via Button 'Validate' (Method: button_validate())`).  

À ce moment‑là, Odoo vérifie le champ **create_backorder** (défini dans `stock_picking.py` : `create_backorder = fields.Selection([('ask', 'Ask'), ('always', 'Always'), ('never', 'Never')], ...)`).  
- **ask** : l’utilisateur est invité à choisir s’il souhaite créer un backorder pour les quantités restantes.  
- **always** : un backorder est créé automatiquement pour les quantités non traitées.  
- **never** : les quantités restantes sont annulées.

Ainsi, la validation ne fait pas simplement passer le picking à l’état « done » ; elle déclenche également la logique de backorder ou d’annulation des quantités restantes selon la configuration du champ `create_backorder`.

[Source: Graphe de Connaissances Code Intelligence]
```

---