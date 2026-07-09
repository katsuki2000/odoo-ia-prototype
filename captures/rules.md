# 🛠️ Guide Complet : IA, Codage Défensif & Bonnes Pratiques Odoo

> Ce guide couvre l'utilisation stratégique de l'IA pour le développement Odoo, les règles de codage défensif, les bonnes pratiques avancées et les templates prêts à l'emploi.

---

# Partie 1 — Protocole d'Utilisation de l'IA

Pour que l'IA soit un atout, précisez toujours votre **version d'Odoo** (par exemple, Odoo 16, 17 ou 18) dans vos prompts, car l'API et certains comportements changent d'une version à l'autre.

## Étape 1 : Conception et Architecture (Brainstorming)

L'IA excelle pour transformer un besoin fonctionnel en architecture de base de données.

- **Action :** Décrivez le besoin métier en langage naturel.
- **Prompt type :**
  > *"Je dois créer un module pour gérer des flottes de véhicules. Propose-moi les modèles Python nécessaires, avec les champs pertinents et les relations (Many2one, One2many) entre eux pour Odoo 17."*
- **Gain de temps :** Structuration mentale immédiate.

---

## Étape 2 : Génération du Boilerplate (Code de base)

Ne tapez plus jamais les structures de base.

- **Action :** Demandez à l'IA de générer le fichier `__manifest__.py`, les fichiers `__init__.py`, et les classes Python de base.
- **Prompt type :**
  > *"Génère le modèle Python `fleet.maintenance` avec les champs : date, description, coût, et une relation vers `fleet.vehicle`. Ajoute une méthode compute pour calculer le coût total."*

---

## Étape 3 : Création des Vues XML (Le point fort de l'IA)

L'écriture du XML (Tree, Form, Kanban, Search) est souvent chronophage. L'IA peut générer **90% de ce code**.

- **Action :** Fournissez le modèle Python à l'IA et demandez les vues.
- **Prompt type :**
  > *"Voici mon modèle `fleet.maintenance`. Génère une vue Form (avec un header pour les statuts), une vue Tree et une vue Search incluant un filtre pour les maintenances de ce mois-ci."*

---

## Étape 4 : Gestion de la Sécurité (Droits d'accès)

La création des fichiers `ir.model.access.csv` et des règles d'enregistrement (`ir.rule`) est fastidieuse et propice aux erreurs de frappe.

- **Action :** Demandez à l'IA de formater vos droits.
- **Prompt type :**
  > *"Génère le fichier `ir.model.access.csv` pour les modèles `fleet.vehicle` et `fleet.maintenance`. Les utilisateurs normaux peuvent lire, les managers peuvent tout faire."*

---

## Étape 5 : Débogage et Optimisation de l'ORM

L'IA est redoutable pour lire les **Tracebacks** (erreurs) ou optimiser des requêtes.

- **Action :** Collez l'erreur exacte ou votre code lent.
- **Prompt type :**
  > *"Voici une méthode Odoo qui boucle sur des records. Comment puis-je l'optimiser pour éviter le problème des requêtes N+1 en utilisant `mapped()` ou `filtered()` ?"*

---

## Stratégies de Prompting

* **Confidentialité des Données :** Ne copiez/collez **jamais** de clés API, de mots de passe dans l'IA.
* **Hallucinations Techniques :** L'IA peut inventer (halluciner) des méthodes ORM Odoo ou des champs qui n'existent pas. **Vérifiez toujours** les méthodes générées. Fournir le code source du modèle natif, du module existant ou du fichier concerné directement dans votre prompt réduit drastiquement le risque d'hallucination.
* **Gestion de la "Fatigue" de l'IA (Sessions Longues) :** Plus une conversation est longue, plus il y a de risque que l'IA s'embrouille, oublie les consignes initiales et génère du code de moins bonne qualité (dérive du contexte).
    * *Bonne pratique :* Ne gardez pas le même fil de discussion pour tout un projet. Dès que vous changez de tâche ou que l'IA commence à faire des erreurs répétitives, **ouvrez une nouvelle session de chat**. Copiez-collez uniquement le dernier code propre nécessaire pour repartir sur des bases saines.

---

# Partie 2 — Codage Défensif (Zero Crash)

Ces règles doivent être appliquées par les développeurs **et imposées à l'IA** lors de la génération de code pour garantir un code robuste.

> **Prompt de sécurité :** Toujours exiger de l'IA qu'elle applique les règles de codage défensif dans sa génération.

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

Pour accélérer la création, voici une structure standardisée.

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
