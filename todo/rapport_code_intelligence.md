# Rapport Synthétique — Agent Code Intelligence Odoo

## 1. Vue d'Ensemble et Architecture

Le sous-système **Code Intelligence Agent** est une architecture Graph-RAG déterministe pour l'analyse statique et dynamique de dépôts de code Odoo (version 11 à 17+, modules Enterprise, Community, OCA et spécifiques client).

Plutôt que d'utiliser un LLM pour "lire" ou "résumer" le code Python/XML (ce qui entraîne des taux d'omission et d'hallucination élevés sur de grands dépôts), le système construit de manière déterministe un **Graphe de Connaissances NetworkX** représentant l'intégralité du modèle d'objet Odoo (modèles, champs, méthodes, vues, règles de sécurité `ir.rule`, droits d'accès `ir.model.access`, actions serveur `ir.actions.server` et dépendances de modules).

---

## 2. Synthèse des Sprints et Réalisations

### Sprint A — Extraction Structurée et Construction du Graphe (A1 - A3)
- **Extracteurs AST & XML/CSV** : Parsers Python (`ast`), XML (`xml.etree.ElementTree`) et CSV pour extraire :
  - **Modèles & Héritage** (`_name`, `_inherit`, `_inherits`).
  - **Champs & Dépendances** (`store=True`, `compute`, `depends`, `related`).
  - **Méthodes & Symboles** (déclarations Python, numéros de ligne, décorateurs).
  - **Règles de Sécurité** (`ir.rule` avec `domain_force`, `groups`, `perm_read/write/create/unlink`).
  - **Droits d'Accès** (`ir.model.access.csv` avec permissions CRUD et groupes `res.groups`).
  - **Actions Serveur & Automatisations** (`ir.actions.server` avec `sudo()` et `base.automation`).
- **Graph Builder NetworkX** : Moteur d'indexation construisant un graphe dirigé sérialisable en `JSON` et `GraphML`.
- **Performance à l'échelle** : Indexation complète des 592 modules de `/home/user/odoo-17.0/addons` :
  - **98 869 Nœuds** (907 Modèles, 11 657 Champs, 13 296 Méthodes, 70 076 Entrées d'accès ACL, 1 042 Règles `ir.rule`, 198 Actions serveur).
  - **98 084 Arêtes** (`RESTRICTED_BY`, `GRANTED_BY`, `APPLIES_TO_GROUP`, `COMPUTED_BY`, `DEPENDS_ON`, `EXTENDS`, `RELATES_TO`).

### Sprint B — Outils Composites Réseau (B1 - B2)
Développement de 12 outils LangChain déterministes exposés au LLM :
1. `qui_a_acces_a` : Résolution des droits d'accès ACL + règles `ir.rule` par modèle et permission.
2. `evaluer_regles_enregistrement` : Évaluation combinée des règles `ir.rule` (globales `AND` vs groupes `OR`).
3. `analyser_actions_serveur` : Audit des actions serveur `ir.actions.server` et détection des élévations de privilèges `sudo()`.
4. `analyser_verrous_securite` : Détection AST/Semgrep des verrous hardcodés (`_VALIDATEURS_EXCEPTIONNELS`), exceptions `UserError`/`ValidationError`, et dispatch dynamique `getattr`.
5. `impact_changement_champ` : Analyse d'impact des dépendances amont/aval d'un champ (`depends`, `computed_by`).
6. `chemin_execution_bouton` : Traçage de la chaîne d'exécution d'un bouton d'action UI vers la méthode Python sous-jacente.
7. `suivre_heritage_complet` : Navigation dans l'arbre d'héritage d'un modèle (`_inherit`) à travers tous les modules.
8. `quel_est_le_processus_de` : Reconstitution du workflow métier (états `selection` / `state`, transitions et méthodes de validation).
9. `naviguer_graphe_code` : Exploration multi-sauts générique autour d'un symbole dans le graphe NetworkX.
10. `rechercher_symbole_code` : Recherche par mot-clé et expression régulière dans le registre de symboles.
11. `inspecter_symbole` : Inspection détaillée des attributs et du code source d'une méthode ou d'un champ.
12. `valider_fidelite_code` : Garde-fou d'anti-hallucination vérifiant la présence effective d'un symbole dans le corpus indexé.

### Sprint C — Routage Hybride, Boucle ReAct & Sourcing (C1)
- **Routeur 4-Voies** : Détection d'intention classifiant les requêtes utilisateur vers `DOCUMENTAIRE`, `DONNEES_ERP`, `HYBRIDE` ou `CODE_INTELLIGENCE`.
- **Boucle ReAct à Dispatch Unique** : Exécution de l'agent sans boucles infinies via un garde-fou anti-boucle.
- **Sourcing Structuré** : Liens Markdown cliquables vers le code source avec numéros de lignes : `[filename.py:L12-L25](file:///path/to/filename.py#L12-L25)`.
- **Fidelity Checker (Garde-fou Anti-Hallucination)** : Si un modèle ou symbole n'existe pas dans le graphe indexé, l'outil retourne un statut explicite d'absence au lieu d'autoriser une hallucination.

### Sprint D — Harness d'Évaluation et Benchmark Granulaire
- **Jeu de Test Benchmark** : Intégration d'un banc de test adversarial (Q1 à Q9) évaluant la précision déterministe sur l'ensemble des cas d'usage (sécurité, héritage, règles masquées, actions serveur).
- **Résultats** : **100% de réussite** aux 80 tests unitaires et 100% de réponses conformes sur le benchmark de validation.

---

## 3. Arborescence du Projet

```
odoo-ia-prototype/
├── miro-rag/
│   ├── code_intelligence/
│   │   ├── __init__.py
│   │   ├── symbol_registry.py          # Registre central des symboles Python/XML/CSV
│   │   ├── python_ast_extractor.py     # Parser AST Python (modèles, champs, méthodes, verrous)
│   │   ├── xml_extractor.py            # Parser XML (rules, groups, actions, menus, boutons)
│   │   ├── csv_acl_extractor.py        # Parser CSV (ir.model.access.csv)
│   │   ├── graph_builder.py            # Constructeur du graphe dirigé NetworkX
│   │   ├── semgrep_locks_analyzer.py   # Analyseur de verrous hardcodés & dispatch getattr
│   │   ├── cross_file_resolver.py      # Résolveur inter-fichiers (héritage et relations)
│   │   ├── ci_agent_tools.py           # Les 12 outils LangChain composites exposés au LLM
│   │   ├── utils.py                    # Découverte automatique de modules, hash SHA-256, formatting
│   │   └── tests/                      # Suite de 80 tests unitaires (100% pass)
│   │       ├── test_a1_ast_xml.py
│   │       ├── test_a2_graph.py
│   │       ├── test_b1_composite_tools.py
│   │       ├── test_c_complete.py
│   │       └── test_s2_8_fidelity_checker.py
│   └── rag/
│       └── graph.py                    # Agent ReAct principal & Routeur 4-voies
├── scripts/
│   ├── extract_modules.py              # CLI générique d'extraction sur tout dossier addons
│   ├── test_benchmark_tools.py         # Script d'évaluation interactive utilisateur
│   └── run_adversarial_benchmark.py    # Harness d'évaluation automatisé du benchmark Q1-Q9
└── todo/
    ├── rules.md                        # Règles de développement du projet
    ├── contexte                        # Journal de suivi chronologique Rule 8
    ├── plan_agent_code_intelligence_fusionne(3).md # Plan maître d'architecture
    ├── benchmark_comparison_sprint2.md # Rapport de comparaison du benchmark
    └── verbatim_responses_sprint2.md  # Réponses brutes du benchmark
```

---

## 4. Guide d'Utilisation des Commandes CLI

### Indexer un dossier d'addons Odoo (Standard, Client ou OCA)
```bash
# Indexation complète de tous les modules d'un répertoire addons :
python scripts/extract_modules.py /home/user/odoo-17.0/addons

# Indexation ciblée de modules spécifiques :
python scripts/extract_modules.py /home/user/odoo-17.0/addons --modules web_responsive hr_holidays sale account purchase
```

### Lancer les Tests Unitaires (80/80 Tests Passés)
```bash
pytest miro-rag/code_intelligence/tests/ -v
```

### Lancer le Benchmark Adversarial
```bash
python scripts/run_adversarial_benchmark.py
```

### Lancer le Runner d'Évaluation Interactive
```bash
python scripts/test_benchmark_tools.py
```

---

## 5. Synthèse des Résultats d'Indexation Réelle

| Métrique | Valeur sur Périmètre Complet (`/home/user/odoo-17.0/addons`) |
| :--- | :--- |
| **Modules Découverts** | 592 |
| **Nœuds Graphe Total** | 98 869 |
| **Arêtes Graphe Total** | 98 084 |
| **Modèles Indexés** | 907 |
| **Champs Indexés** | 11 657 |
| **Méthodes Indexées** | 13 296 |
| **Entrées Droits d'Accès (ACL)** | 70 076 |
| **Règles d'Enregistrement (`ir.rule`)** | 1 042 |
| **Actions Serveur (`ir.actions.server`)** | 198 |
| **Temps d'Indexation** | ~15-20 secondes |
