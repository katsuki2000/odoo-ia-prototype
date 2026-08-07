
use of llama 3.1 8B is a must
code in english
don't use emojis
think first
clean code
find best algorithm
make the work like it was built by an human. no "plagiat", at least reformulate first
put all installed packages in requirements(we work in venv)
put everything you change in contexte.txt


## Règle 1 — Tolérance zéro pour la division par zéro

Utiliser systématiquement des conditions ou des ternaires.

```python
# ❌ Dangereux
valeur = a / b

# ✅ Défensif
valeur = a / b if b else 0.0
```

---

## Règle 2 — Gestion des Recordsets (Singleton)

Boucler systématiquement sur `self` ou utiliser `.ensure_one()` pour éviter les erreurs `Expected singleton`.

```python
# ✅ Boucle sécurisée
for record in self:
    record.name = "Valeur"

# ✅ Singleton explicite
self.ensure_one()
```

---

## Règle 3 — Validation des champs relationnels

Toujours vérifier si un `Many2one` contient une valeur avant d'accéder à ses attributs.

```python
# ❌ Dangereux
email = record.partner_id.email

# ✅ Défensif
if record.partner_id:
    email = record.partner_id.email
```

---

## Règle 4 — Sécurisation des dictionnaires et contextes

Remplacer l'accès direct par `.get()` pour éviter les `KeyError`.

```python
# ❌ Dangereux
valeur = mon_dict['cle']

# ✅ Défensif
valeur = mon_dict.get('cle', 'valeur_par_defaut')
```

---

## Règle 5 — Gestion exhaustive des cas (if / elif / else)

Ne jamais coder uniquement le "chemin heureux". Tout bloc `if` évaluant une donnée doit inclure un `else` pour gérer les cas inattendus et éviter les **bugs silencieux**.

```python
# ❌ Incomplet
if statut == 'valide':
    self._traiter()

# ✅ Exhaustif
if statut == 'valide':
    self._traiter()
elif statut == 'en_attente':
    self._mettre_en_attente()
else:
    _logger.error("Statut inattendu : %s", statut)
```

---

## Règle 6 — Encapsulation des risques

Utiliser systématiquement `try...except` pour tout appel à une API externe, parsing de fichier ou manipulation hors base de données.

```python
try:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
except requests.exceptions.RequestException as e:
    _logger.error("Échec de l'appel API : %s", e)
```

---

## Règle 7 — Propagation sécurisée du contexte lors de la surcharge
Lors de la surcharge d'une méthode (create, write, etc.), il est essentiel de ne jamais écraser le contexte existant mais de l'enrichir avec with_context(**{clé: valeur}). Cette approche garantit que toutes les valeurs déjà présentes dans le contexte parent sont préservées, évitant ainsi des comportements silencieusement incorrects en cascade. Par exemple, pour injecter un flag d'audit sans perdre le contexte courant :

```python
pythonrecords = super(Base, self.with_context(**{audit_key: True})).create(vals_list)
```
L'opérateur ** fusionne le nouveau contexte avec l'existant au lieu de le remplacer. Ne jamais utiliser .with_context(audit_key=True) avec une clé dynamique, car cela ne permet pas d'utiliser une variable comme nom de clé.

---

# Partie 3 — Bonnes Pratiques Avancées

## 1. Optimisation de l'ORM (Éviter le piège du N+1)

C'est la **cause numéro un des lenteurs** sur Odoo. Boucler sur des enregistrements pour faire des recherches en base à chaque itération rend votre module lent.

La solution : utiliser les **méthodes ensemblistes** de l'ORM.

```python
# ✅ mapped() — extraire une liste de valeurs
emails = records.mapped('partner_id.email')

# ✅ filtered() — trier en mémoire
factures_payees = invoices.filtered(lambda r: r.state == 'posted')
```

---

## 2. Utilisation propre du Logging (Fini les `print`)

Ne laissez jamais de `print()` dans un code de production.

```python
import logging
_logger = logging.getLogger(__name__)

# Utilisation
_logger.info("Le calcul a réussi pour l'ID %s", record.id)
_logger.error("Échec de la connexion à l'API externe.")
```

---

## 3. Maîtriser les champs calculés (`compute`)

- **Toujours** définir correctement le décorateur `@api.depends('champ1', 'champ2')`.
- Un champ oublié dans `@api.depends` → la valeur ne se met pas à jour.
- Un champ en trop → le calcul se déclenche inutilement.
- **Toujours** assigner une valeur à chaque enregistrement de la boucle, même `False` ou `0`, sinon Odoo lève une erreur de cache.

```python
@api.depends('prix_unitaire', 'quantite')
def _compute_total(self):
    for record in self:
        record.total = record.prix_unitaire * record.quantite if record.quantite else 0.0
```

---

## 4. Automatisation de la qualité du code (Linting)

Installez **Pylint** avec le plugin `pylint-odoo` pour scanner votre code automatiquement avant les tests.

Il vous avertit si vous avez oublié un `.ensure_one()`, si une variable n'est pas utilisée, ou si vous faites une requête SQL dangereuse (injection SQL).

```bash
pip install pylint pylint-odoo
pylint --load-plugins=pylint_odoo mon_module/
```

---

## 5. Conventions de Nommage Strictes

| Élément | Convention | Exemple |
|---|---|---|
| Modèles | Points | `mon.modele` |
| Champ Many2one | Suffixe `_id` | `partner_id` |
| Champ One2many / Many2many | Suffixe `_ids` | `line_ids` |
| Méthodes (boutons) | Préfixe `action_` | `action_valider()` |
| Méthodes (calculs) | Préfixe `_compute_` | `_compute_total()` |
| Vues XML (IDs) | `view_modele_type` | `view_mon_modele_form` |
| Vues XML (noms) | `modele.type` | `mon.modele.form` |
| Héritage XML | Suffixe `_inherit_nommodule` | `view_mon_modele_form_inherit_custom` |
| Actions | Préfixe `action_` | `action_mon_modele` |
| Menus | Préfixe `menu_` | `menu_mon_modele_root` |

---

# Partie 4 — Template de Nouveau Module Odoo

Pour accélérer la création, voici une structure standardisée. Demandez à l'IA de remplir ce squelette à chaque nouveau projet.

### Structure des dossiers

```
mon_module/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── mon_modele.py
├── views/
│   └── mon_modele_views.xml
└── security/
    └── ir.model.access.csv
```

---

### 1. `__manifest__.py`

C'est la carte d'identité du module.

```python
{
    'name': 'Mon Module Custom',
    'version': '1.0',
    'category': 'Customizations',
    'summary': 'Description courte de ce que fait le module.',
    'description': """
        Description détaillée du module.
    """,
    'author': 'P. Nom, Miro K.E.',
    'license': 'Other proprietary',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/mon_modele_views.xml',
    ],
    'installable': True,
    'application': False,
}
```

---

### 2. `models/mon_modele.py`

Exemple avec héritage de `mail.thread` pour le suivi des discussions (chatter).

```python
from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)

class MonModele(models.Model):
    _name = 'mon.modele'
    _description = 'Description du modèle'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Optionnel: ajoute le chatter

    name = fields.Char(string='Nom', required=True, tracking=True)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)

    # Exemple de champ relationnel
    user_id = fields.Many2one('res.users', string='Responsable', default=lambda self: self.env.user)
```

---

### 3. `views/mon_modele_views.xml`

Vues de base (Action, Tree, Form).

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_mon_modele_tree" model="ir.ui.view">
        <field name="name">mon.modele.tree</field>
        <field name="model">mon.modele</field>
        <field name="arch" type="xml">
            <tree string="Liste">
                <field name="name"/>
                <field name="user_id"/>
            </tree>
        </field>
    </record>

    <record id="view_mon_modele_form" model="ir.ui.view">
        <field name="name">mon.modele.form</field>
        <field name="model">mon.modele</field>
        <field name="arch" type="xml">
            <form string="Formulaire">
                <sheet>
                    <div class="oe_title">
                        <h1>
                            <field name="name" placeholder="Nom du document..."/>
                        </h1>
                    </div>
                    <group>
                        <group>
                            <field name="user_id"/>
                        </group>
                        <group>
                            <field name="active" invisible="1"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Description">
                            <field name="description"/>
                        </page>
                    </notebook>
                </sheet>
                <div class="oe_chatter">
                    <field name="message_follower_ids"/>
                    <field name="activity_ids"/>
                    <field name="message_ids"/>
                </div>
            </form>
        </field>
    </record>

    <record id="action_mon_modele" model="ir.actions.act_window">
        <field name="name">Mon Modele</field>
        <field name="res_model">mon.modele</field>
        <field name="view_mode">tree,form</field>
    </record>

    <menuitem id="menu_mon_modele_root" name="Mon Application" sequence="10"/>
    <menuitem id="menu_mon_modele_action" name="Mes Enregistrements" parent="menu_mon_modele_root" action="action_mon_modele"/>
</odoo>
```

---

### 4. `security/ir.model.access.csv`

Définition des droits (accès total pour tous les utilisateurs internes).

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_mon_modele_user,mon.modele.user,model_mon_modele,base.group_user,1,1,1,1
```





(.venv) user@debian:~/odoo-ia-prototype/miro-rag$ cd /home/user/odoo-ia-prototype
python3 scripts/check_bloc9_01_credit_note_cascade_e2e.py
================================================================================
 RAW analyser_chaine_surcharge_methode OUTPUT (account.move / action_valider_avoir)
================================================================================
Chaîne de surcharge de 'account.move.action_valider_avoir' (3 modules, ordre d'exécution réel, pas l'ordre de dépendance):
  1. module 'custom_credit_note_approval_vip' -- [account_move.py:L7-L14](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_vip/models/account_move.py#L7-L14)
     ⚠️ SUPER() NON GARDÉ: 'action_valider_avoir' (module 'custom_credit_note_approval_vip') contient une branche conditionnelle (`rec.partner_id.avoir_vip_exempt`) qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par cette condition -- risque réel qu'elle soit silencieusement annulée. [Confiance: FAIBLE -- heuristique statique sur la forme exacte du contrôle de flux, ne détecte pas les gardes formulées autrement]
  2. module 'custom_credit_note_approval_regional' -- [account_move.py:L9-L15](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_regional/models/account_move.py#L9-L15)
     ⚠️ CHAINE RELATIONNELLE NON VÉRIFIÉE (Règle 3): 'action_valider_avoir' (module 'custom_credit_note_approval_regional') dépend d'une chaîne de champs Many2one enchaînés sans vérification d'existence -- _get_directeur_regional() L20: `env.user.employee_id.parent_id.parent_id.user_id` (atteint si `rec.amount_total > 20000`). Si un maillon intermédiaire est vide, l'expression complète s'évalue silencieusement à False/un recordset vide, sans erreur -- risque réel que la personne censée être notifiée/valider ne le soit jamais, sans signal d'erreur. [Confiance: FAIBLE -- heuristique statique, ne vérifie pas si un garde est exprimé ailleurs dans l'appelant]
  3. module 'custom_credit_note_approval' -- [account_move.py:L13-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L13-L22)
--------------------------------------------------------------------------------
[OK ] raw tool mentions module: custom_credit_note_approval
[OK ] raw tool mentions module: custom_credit_note_approval_regional
[OK ] raw tool mentions module: custom_credit_note_approval_vip

================================================================================
 bloc9-01a-business
================================================================================
Question: Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?

Groq rate limit hit (attempt 1/5). Headers: {'x-ratelimit-limit-requests': '14400', 'x-ratelimit-limit-tokens': '6000', 'x-ratelimit-remaining-requests': '14396', 'x-ratelimit-remaining-tokens': '464', 'x-ratelimit-reset-requests': '24s', 'x-ratelimit-reset-tokens': '55.36s'}. Dynamically waiting 55.9s...
Node [code_intelligence_agent]: CI_MAX_HOPS (4) reached -- breaking ReAct loop.
Groq rate limit hit (attempt 1/5). Headers: {'x-ratelimit-limit-requests': '14400', 'x-ratelimit-limit-tokens': '6000', 'x-ratelimit-remaining-requests': '14399', 'x-ratelimit-remaining-tokens': '2193', 'x-ratelimit-reset-requests': '6s', 'x-ratelimit-reset-tokens': '38.07s'}. Dynamically waiting 38.6s...
Answer (hops=6):
Analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH] :

* "Seul un responsable comptable peut valider un avoir de plus de 5000€."

Évaluation des règles d'enregistrement (ir.rule) pour 'account.move' :

* Règles Globales (ET pour tous) : Avoirs - cantonnement societe (regle globale, sans groupe) [['|', ('move_type', '!=', 'out_refund'), ('company_id', '=', user.company_id.id)]]
* Règles de Groupe applicables : Aucune (l'utilisateur n'appartient à aucun des groupes visés)
* Règles de Groupe ignorées (non-membre) : Purchase User Account Move [[('move_type', 'in', ('in_invoice', 'in_refund', 'in_receipt'))]], Avoirs - visibilite par departement (sauf managers) [['|', ('move_type', '!=', 'out_refund'), '|', ('invoice_user_id', '=', user.id), ('journal_id.department_id', '=', user.employee_id.department_id.id)]], Avoirs - plafond visibilite regionale (50000e) [['|', ('move_type', '!=', 'out_refund'), ('amount_total', '<=', 50000)]], Avoirs - visibilite nationale (illimitee) [[(1, '=', 1)]], Expense Team Approver Account Move [[('line_ids.expense_id', '!=', False)]]
* CONCLUSION : Aucune règle de groupe applicable (l'utilisateur n'appartient à aucun groupe cible par une règle sur ce modèle). Seules les règles globales ci-dessus s'appliquent -- il n'y a AUCUNE restriction supplémentaire de montant ou de portée pour valider un avoir de 25 000€.

Cependant, l'analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH] indique que seul un responsable comptable peut valider un avoir de plus de 5000€. Puisque l'amount_total de l'avoir est de 25 000€, ce qui est supérieur à 5000€, il est nécessaire que le responsable comptable approuve cet avoir.

Par conséquent, la réponse finale est :

* Qui a le droit d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ? : Seul un responsable comptable peut valider cet avoir.

[Source: Graphe de Connaissances Code Intelligence]

--------------------------------------------------------------------------------
[MISSING] expected marker: account.group_account_manager
[MISSING] expected marker: 20000
[RESULT] bloc9-01a-business: INCOMPLETE -- missing ['account.group_account_manager', '20000']

================================================================================
 bloc9-01b-technical
================================================================================
Question: Dans le modèle account.move, quelles sont toutes les surcharges de la méthode action_valider_avoir et dans quel ordre s'exécutent-elles ?

Groq rate limit hit (attempt 1/5). Headers: {'x-ratelimit-limit-requests': '14400', 'x-ratelimit-limit-tokens': '6000', 'x-ratelimit-remaining-requests': '14400', 'x-ratelimit-remaining-tokens': '3002', 'x-ratelimit-reset-requests': '1ms', 'x-ratelimit-reset-tokens': '29.98s'}. Dynamically waiting 30.5s...
Node [code_intelligence_agent]: Unverified citations -- SourcingVerificationResult(unverified_scoped_citations=[('home/user/odoo-17.0/addons/custom_credit_note_approval_global/models/account_move.py', 12, 20)], bare_file_links=[], unverified_xml_ids=[])
Answer (hops=1):
Dans le modèle account.move, les surcharges de la méthode action_valider_avoir sont les suivantes :

1. Le module 'custom_credit_note_approval_vip' contient une branche conditionnelle (`rec.partner_id.avoir_vip_exempt`) qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par cette condition -- risque réel qu'elle soit silencieusement annulée. [Confiance: FAIBLE -- heuristique statique sur la forme exacte du contrôle de flux, ne détecte pas les gardes formulées autrement] (file:///home/user/odoo-17.0/addons/custom_credit_note_approval_vip/models/account_move.py#L7-L14)
2. Le module 'custom_credit_note_approval_regional' contient une chaîne relationnelle non vérifiée (Règle 3) qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par cette condition -- risque réel qu'elle soit silencieusement annulée. (file:///home/user/odoo-17.0/addons/custom_credit_note_approval_regional/models/account_move.py#L9-L15)
3. Le module 'custom_credit_note_approval_global' contient une branche conditionnelle (`rec.partner_id.approval_level > 2`) qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par cette condition -- risque réel qu'elle soit silencieusement annulée. (file:///home/user/odoo-17.0/addons/custom_credit_note_approval_global/models/account_move.py#L12-L20)

L'ordre d'exécution réel de ces surcharges est le suivant :

1. Le module 'custom_credit_note_approval_vip'
2. Le module 'custom_credit_note_approval_regional'
3. Le module 'custom_credit_note_approval_global'

Il est important de noter que la logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par les conditions spécifiques de chaque module, ce qui peut entraîner des risques de silencieuse annulation de la logique des modules enfants.

⚠️ SOURCING NON VÉRIFIÉ (J14): citation(s) fichier non retrouvée(s) dans les données produites: home/user/odoo-17.0/addons/custom_credit_note_approval_global/models/account_move.py#L12-L20. Ne pas considérer ces éléments comme confirmés pour cette question.

[Source: Graphe de Connaissances Code Intelligence]

--------------------------------------------------------------------------------
[OK ] expected marker: custom_credit_note_approval_regional
[OK ] expected marker: custom_credit_note_approval_vip
[MISSING] expected marker (word-boundary): custom_credit_note_approval
[FAIL -- HALLUCINATED] forbidden marker: custom_credit_note_approval_global
[RESULT] bloc9-01b-technical: INCOMPLETE -- missing ['custom_credit_note_approval']
[RESULT] bloc9-01b-technical: HALLUCINATION -- forbidden marker(s) present ['custom_credit_note_approval_global']

================================================================================
 bloc9-01c-vip-trap
================================================================================
Question: Qui a le droit d'approuver un avoir pour un client VIP, et y a-t-il un piège dans le code ?

LLM interpretation call failed for account.move.write: Error code: 429 - {'error': {'message': 'Rate limit reached for model `llama-3.1-8b-instant` in organization `org_01kwh6tbbrf21a22rgs04pwnn1` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Used 5062, Requested 2015. Please try again in 10.77s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
LLM interpretation call failed for account.move._reverse_moves: Error code: 429 - {'error': {'message': 'Rate limit reached for model `llama-3.1-8b-instant` in organization `org_01kwh6tbbrf21a22rgs04pwnn1` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Used 5008, Requested 1701. Please try again in 7.09s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
LLM interpretation call failed for account.move.action_valider_avoir: Error code: 429 - {'error': {'message': 'Rate limit reached for model `llama-3.1-8b-instant` in organization `org_01kwh6tbbrf21a22rgs04pwnn1` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Used 4985, Requested 1330. Please try again in 3.15s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
Groq rate limit hit (attempt 1/5). Headers: {'x-ratelimit-limit-requests': '14400', 'x-ratelimit-limit-tokens': '6000', 'x-ratelimit-remaining-requests': '14397', 'x-ratelimit-remaining-tokens': '1040', 'x-ratelimit-reset-requests': '18s', 'x-ratelimit-reset-tokens': '49.6s'}. Dynamically waiting 50.1s...
Node [code_intelligence_agent]: CI_MAX_HOPS (4) reached -- breaking ReAct loop.
Groq rate limit hit (attempt 1/5). Headers: {'x-ratelimit-limit-requests': '14400', 'x-ratelimit-limit-tokens': '6000', 'x-ratelimit-remaining-requests': '14400', 'x-ratelimit-remaining-tokens': '2623', 'x-ratelimit-reset-requests': '1ms', 'x-ratelimit-reset-tokens': '33.769s'}. Dynamically waiting 34.3s...
Answer (hops=6):
En réponse à la question : Qui a le droit d'approuver un avoir pour un client VIP, et y a-t-il un piège dans le code ?

Analyse des verrous Python ([account_move.py:L1-L22](file:///home/user/odoo-17.0/addons/custom_credit_note_approval/models/account_move.py#L1-L22)) [Confiance: HIGH] :
- Messages de verrous (UserError/ValidationError) :
  * "Seul un responsable comptable peut valider un avoir de plus de 5000€."

Cependant, il est important de noter que cette analyse ne fournit pas d'informations sur les clients VIP. Pour déterminer qui a le droit d'approuver un avoir pour un client VIP, nous devons analyser les autres modules.

Analyse des verrous Python ([account_move.py:L1-L21](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_regional/models/account_move.py#L1-L21)) [Confiance: HIGH] :
- Aucun verrou spécifique ni incertitude dynamique détecté.

Analyse des verrous Python ([account_move.py:L1-L14](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_vip/models/account_move.py#L1-L14)) [Confiance: HIGH] :
- Aucun verrou spécifique ni incertitude dynamique détecté.

Analyse des verrous Python ([account_move.py:L1-L87](file:///home/user/odoo-17.0/addons/hr_expense/models/account_move.py#L1-L87)) [Confiance: HIGH] :
- Aucun verrou spécifique ni incertitude dynamique détecté.

Analyse des verrous Python ([account_invoice.py:L1-L484](file:///home/user/odoo-17.0/addons/purchase/models/account_invoice.py#L1-L484)) [Confiance: HIGH] :
- Aucun verrou spécifique ni incertitude dynamique détecté.

Chaîne de surcharge de 'account.move._compute_commercial_partner_id' (2 modules, ordre d'exécution réel, pas l'ordre de dépendance) :
- ⚠️ SUPER() NON GARDÉ : '_compute_commercial_partner_id' (module 'hr_expense') contient une branche conditionnelle (`move.expense_sheet_id.payment_mode == 'own_account'`) qui modifie l'état sans `return` explicite, suivie d'un appel `super()._compute_commercial_partner_id(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par cette condition -- risque réel qu'elle soit silencieusement annulée. [Confiance: FAIBLE -- heuristique statique sur la forme exacte du contrôle de flux, ne détecte pas les gardes formulées autrement]

Chaîne de surcharge de 'account.move.action_valider_avoir' (3 modules, ordre d'exécution réel, pas l'ordre de dépendance) :
- 1. module 'custom_credit_note_approval_vip' -- [account_move.py:L7-L14](file:///home/user/odoo-17.0/addons/custom_credit_note_approval_vip/models/account_move.py#L7-L14)
  ⚠️ SUPER() NON GARDÉ : 'action_valider_avoir' (module 'custom_credit_note_approval_vip') contient une branche conditionnelle (`rec.partner_id.avoir_vip_exempt`) qui modifie l'état sans `return` explicite, suivie d'un appel `super().action_valider_avoir(...)` inconditionnel plus loin dans la méthode. La logique de la classe parente va se réappliquer sur TOUS les enregistrements, y compris ceux couverts par cette condition -- risque réel qu'elle soit silencieusement annulée. [Confiance: FAIBLE -- heuristique statique sur la forme exacte du contrôle de flux, ne détecte pas les gardes formulées autrement]

En conclusion, pour approuver un avoir pour un client VIP, il est nécessaire de vérifier les conditions spécifiques définies dans le module `custom_credit_note_approval_vip`. Cependant, il est important de noter que la chaîne de surcharge de `account.move.action_valider_avoir` peut potentiellement annuler les conditions spécifiques définies dans ce module, ce qui peut entraîner des risques de silencieuse annulation de la logique de la classe parente.

[Source: Graphe de Connaissances Code Intelligence]

--------------------------------------------------------------------------------
[OK ] expected marker: avoir_vip_exempt
[OK ] expected marker: super()
[RESULT] bloc9-01c-vip-trap: all expected markers present, no forbidden markers.

================================================================================
[BLOC 9 - 1/8] custom_credit_note_approval(+regional+vip): GAP FOUND -- see [MISSING] lines above.
(.venv) user@debian:~/odoo-ia-prototype$ 