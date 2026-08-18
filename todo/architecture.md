# Architecture cible du projet

## Vision

Construire une IA capable d'expliquer le comportement réel d'une instance Odoo(17 pour l'instant), y compris ses modules natifs, OCA et custom, sans dépendre de la documentation existante.

L'IA doit pouvoir répondre à :

```text
Pourquoi ce bouton est grisé ?
Pourquoi cet avoir est bloqué ?
Qui peut approuver cette demande ?
Comment est calculé ce score ?
Quelle est la procédure réelle d'achat ?
Pourquoi ce montant n'est pas visible ?
Combien me reste-t-il de congés ?
Qui sont les nouveaux clients du mois ?
```

même lorsque :

* aucun document n'existe ;
* la documentation est obsolète ;
* la logique est répartie entre plusieurs modules ;
* les règles sont implémentées dans le code.

---

# Principe fondamental

La source de vérité est :

```text
1. L'instance Odoo
2. Le code Odoo
3. La configuration Odoo
4. La documentation (optionnelle)
```

et non :

```text
1. Documentation
2. LLM
```

---

# Architecture globale

```text
                         Question utilisateur
                                  │
                                  ▼

                      Semantic Understanding
                                  │
                                  ▼

                        Investigation Planner
                                  │
                                  ▼

                    Code Intelligence Engine
                                  │

      ┌───────────────┬───────────────┬───────────────┐
      │               │               │               │
      ▼               ▼               ▼               ▼

 Knowledge      Semantic Layer    Runtime Odoo      Docs
   Graph         + Ontology          (RPC)          (RAG)

      │               │               │               │
      └───────────────┴───────┬───────┴───────────────┘
                              ▼

                     Evidence Builder
                              │
                              ▼

                   Deterministic Reasoning
                              │
                              ▼

                        LLM Writer
                              │
                              ▼

                       Réponse finale
```

---

# Couche 1 — Extraction du système

Extraction automatique de :

```text
Modèles
Champs
Méthodes
Menus
Actions
Vues
ACL
Record Rules
Server Actions
Automations
Cron
Workflows
```

Objectif :

Construire une représentation exhaustive du système.

---

# Couche 2 — Knowledge Graph

Le graphe représente les relations structurelles.

Exemples :

```text
inherits
depends
calls
opens
writes
reads
triggers
defined_in
```

Le graphe sert à répondre :

```text
Une fois le sujet identifié,
comment fonctionne réellement le système ?
```

---

# Couche 3 — Couche sémantique

Cette couche sert à généraliser sur des modules inconnus.

Exemple :

```text
avoir
note de crédit
credit note
```

↓

```text
account.move
```

---

Exemple :

```text
mise à disposition
prêt matériel
ordinateur portable
```

↓

```text
custom.asset.loan
```

---

Cette couche contient :

### Ontologie métier

```text
invoice
credit_note
purchase
expense
asset
leave
risk
approval
```

### Tags comportementaux

```text
visibility_rule
blocking_rule
calculation_rule
workflow_rule
approval_rule
notification_rule
```

### Tags techniques

```text
record_rule
acl
constraint
computed_field
server_action
cron
```

Objectif :

Faire le lien entre :

```text
Langage utilisateur
↓
Concepts métier
↓
Artefacts Odoo
```

---

# Couche 4 — Runtime Odoo

Le code ne suffit pas.

Certaines réponses nécessitent :

```python
env.user.has_group(...)
```

```python
record rules
```

```python
company_id
```

```python
context
```

```python
données métier
```

Cette couche interroge l'instance réelle.

Objectif :

Valider la réalité avant de répondre.

---

# Planner d'investigation

Le système ne repose pas sur un énorme prompt.

Il produit un plan.

Exemple :

Question :

```text
Pourquoi le montant est caché ?
```

Plan :

```text
1. Rechercher les règles de visibilité
2. Identifier les groupes
3. Identifier les record rules
4. Vérifier les ACL
5. Vérifier le contexte runtime
6. Construire les preuves
```

---

# Raisonnement déterministe

Les conclusions critiques sont produites par du code.

Exemples :

### Accès

```text
ACL
+
Record Rules
+
Groupes
```

↓

```text
Peut voir / Ne peut pas voir
```

---

### Workflow

```text
Actions
+
États
+
Automations
```

↓

```text
Processus réel
```

---

### Calcul

```text
Fields
+
Depends
+
Overrides
```

↓

```text
Comment la valeur est calculée
```

---

Le LLM n'effectue pas ces calculs.

---

# Evidence Builder (nouvelle brique essentielle)

C'est probablement la brique la plus importante pour l'adoption.

Chaque affirmation doit être traçable.

Le système ne produit pas :

```text
Le montant est caché à cause d'une règle.
```

mais :

```text
Le montant est caché car :

- record rule X
- groupe Y
- méthode Z
```

avec les preuves.

---

**Ne pas confondre** :

- **Evidence Builder** (post-analyse) — construction des preuves pour expliquer la réponse, décrit ci-dessus.
- **Evidence Check** (pré-analyse) — validation des hypothèses avant l'analyse. Correspond à H3 dans `plan_architecture_cible.md` (conceptuel, non implémenté à ce jour).

Ce sont deux concepts différents, même si Evidence Check (H3) n'est pas encore implémenté.

---

# Système de preuves

Chaque réponse est accompagnée d'un dossier de preuves.

Exemple :

```text
Pourquoi le bouton est grisé ?
```

Preuves :

```text
Vue XML :
purchase_request_view.xml:128

Attribut :
attrs="{'readonly': [('state', '!=', 'draft')]}"
```

---

Exemple :

```text
Pourquoi l'avoir est bloqué ?
```

Preuves :

```text
custom_credit_note/models/account_move.py:84

if amount_total > 50000:
    raise ValidationError(...)
```

---

Exemple :

```text
Qui peut approuver ?
```

Preuves :

```text
security/credit_note_rule.xml:42

group_finance_manager
```

---

# Double niveau d'explication

## Niveau utilisateur

```text
Le montant est masqué car seuls les responsables financiers peuvent consulter les avoirs supérieurs à 50 000 €.
```

---

## Niveau vérification

Dépliable :

```text
Source :

Module :
custom_credit_note

Fichier :
security/credit_note_rule.xml

Ligne :
42

Groupe :
group_finance_manager
```

---

# Cas particulier : Documentation

Le RAG n'est pas le moteur principal.

Le RAG intervient uniquement lorsque :

```text
Le système ne contient pas la réponse
```

ou

```text
La documentation apporte un complément utile
```

---

# Domaines supportés

L'architecture couvre naturellement trois familles de questions.

## A. Code Intelligence

```text
Pourquoi ?
Comment ?
Qui peut ?
Quel impact ?
```

---

## B. Data Intelligence

```text
Combien ?
Qui ?
Quand ?
Liste-moi ?
```

via runtime Odoo.

---

## C. Documentation Intelligence

```text
Procédure
Politique
Guide utilisateur
```

uniquement lorsque nécessaire.

---

# Résumé final

L'architecture devient :

```text
Question utilisateur
        │
        ▼

Compréhension métier
        │
        ▼

Investigation automatique
        │
        ▼

Graphe
+
Ontologie métier
+
Tags comportementaux
+
Runtime Odoo
        │
        ▼

Construction des preuves
        │
        ▼

Raisonnement déterministe
        │
        ▼

Réponse
+
Sources exactes
+
Éléments de vérification
```

L'objectif n'est donc plus seulement de **retrouver du code**, mais de produire une **réponse explicable, vérifiable et traçable**, où chaque conclusion peut être reliée à une source précise : code Python, vue XML, ACL, record rule, workflow, donnée runtime ou document métier. C'est cette traçabilité qui permettra à des utilisateurs non techniques d'accorder leur confiance au système.
