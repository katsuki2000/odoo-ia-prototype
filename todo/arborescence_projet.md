# Arborescence du Projet & Environnement Odoo

**Date de mise à jour** : 2026-08-04

---

## 1. Environnement Odoo Runtime

> **Emplacement du serveur Odoo 17** : `/home/user/odoo-17.0`
> 
> Odoo est exécuté **en natif (sans Docker)** depuis `/home/user/odoo-17.0`.
> - **Dossier des modules (Addons)** : `/home/user/odoo-17.0/addons` (contient à la fois les modules Odoo standards et les modules custom du projet : `miro_ai`, `ai_erp_core`, `estate`, `custom_*`, etc.)
> - **URL du serveur live** : `http://localhost:8069` (base de données `odoo-dev`)

---

## 2. Arborescence du dépôt (`/home/user/odoo-ia-prototype`)

```text
odoo-ia-prototype/
├── README.md                            # Documentation générale & guide de réplication
├── requirements.txt                     # Dépendances Python du projet RAG
│
├── todo/                                # Documents de cadrage, logs et rapports de benchmark
│   ├── real plan.md                     # Plan d'exécution jour par jour (Blocs 0 à 16)
│   ├── arborescence_projet.md           # Ce fichier (arborescence & doc environnement Odoo)
│   ├── j7_security_review.md            # Rapport de revue de sécurité ligne à ligne (J7)
│   ├── j13_semgrep_precision_review.md  # Rapport de revue de précision des règles Semgrep (J13)
│   ├── j16_rapport_consolide_e1_e2.md   # Rapport consolidé de clôture du cycle E1/E2 (J16)
│   ├── verbatim_responses_sprint2.md    # Rapport verbatim adversarial end-to-end (Sprint 2)
│   ├── verbatim_responses_sprint2.json  # Données brutes JSON du benchmark
│   └── benchmark_run_*.log              # Logs d'exécution brute du benchmark
│
├── scripts/                             # Scripts d'exécution et harnais de test
│   ├── run_adversarial_benchmark.py     # Exécuteur du benchmark adversarial (9 questions)
│   └── run_adversarial_extraction.py    # Script d'extraction des modules depuis /home/user/odoo-17.0/addons
│
└── miro-rag/                            # Module principal RAG & Code Intelligence
    ├── rag/
    │   ├── graph.py                     # Routeur LangGraph (J18-J19 politique de conflits), ReAct loop, pre-dispatch J8/J9/J15 & tags
    │   ├── schemas.py                   # Dataclasses de réponses & états RAG (QueryRoute, etc.)
    │   └── search.py                    # Recherche vectorielle
    │
    ├── code_intelligence/               # Cœur déterministe & outils Code Intelligence
    │   ├── deterministic_tools.py       # evaluer_regles_enregistrement & qui_a_acces_a (AND/OR, expansion)
    │   ├── business_resolver.py         # Résolveur nom métier -> nom technique (B0)
    │   ├── ci_agent_tools.py            # Wrappers LangChain @tool (find_server_action_nodes, set_llm_ref)
    │   ├── semgrep_locks_analyzer.py    # Analyseur de verrous Python (analyser_verrous_securite)
    │   ├── server_action_analyzer.py    # Analyseur d'actions serveur (interpret_server_action_with_llm)
    │   ├── sourcing_guard.py            # Contrôleur mécanique de sûreté de sourcing (Bloc 4 / J14)
    │   ├── semgrep_runner.py            # Runner Semgrep subprocess --json & slicing lignes/fichiers (J12)
    │   ├── semgrep_rules/               # Dossier des règles Semgrep & fixtures TDD (Bloc 3)
    │   │   ├── sql_constraints.yaml     # Règle Semgrep odoo-sql-constraints-declaration (J11)
    │   │   ├── sql_constraints.py       # Fixture TDD # ruleid: / # ok: pour _sql_constraints (J11)
    │   │   ├── domain_relational.yaml   # Règle Semgrep odoo-relational-domain-declaration (J12)
    │   │   └── domain_relational.py     # Fixture TDD # ruleid: / # ok: pour domain= (J12)
    │   ├── graph_builder.py             # Construction du graphe NetworkX
    │   ├── odoo_rpc_client.py           # Client XML-RPC Odoo live (J5/J6)
    │   ├── live_rule_validator.py       # Validateur live vs déterministe (J5)
    │   ├── cross_file_resolver.py       # Registre des symboles cross-fichiers
    │   ├── xml_extractor.py             # Extrait ir.rule, res.groups, actions depuis XML
    │   ├── csv_extractor.py             # Extrait ACLs depuis ir.model.access.csv
    │   │
    │   └── tests/                       # Suite de tests unitaires & d'intégration
    │       ├── conftest.py              # Fixtures pytest partagées (live_client)
    │       ├── test_j5_live_validation.py
    │       ├── test_j6_context_validation.py
    │       ├── test_j8_deterministic_dispatch.py # Tests unitaires des déclencheurs déterministes J8
    │       ├── test_semgrep_runner.py   # Tests unitaires du runner Semgrep (J12)
    │       ├── test_analyser_contraintes_donnees.py # Tests unitaires du tool analyser_contraintes_donnees (J13-bis)
    │       ├── test_j14_sourcing_guard.py # Tests unitaires du contrôleur de sûreté de sourcing (J14)
    │       ├── test_s2_0_business_resolver.py
    │       ├── test_s2_1_record_rules.py
    │       ├── test_s2_3_server_actions.py
    │       ├── test_s2_5_semgrep_locks.py
    │       └── test_s2_8_fidelity_checker.py
    │
    ├── tests/                           # Suite de tests niveau module RAG
    │   ├── few_shot_routing_examples.py # Dataset de 16 exemples few-shot aux frontières des branches (J18-J19)
    │   ├── test_j18_routing_fewshot.py  # Tests unitaires du routeur vs dataset few-shot (J18-J19)
    │   └── test_j8_llm_server_action_interpretation.py # Tests d'interprétation LLM bornée des actions serveur
    │
    ├── ingestion/                       # Ingestion documentaire & indexation
    ├── vectorstore/                     # Stockage ChromaDB local
    ├── tools/                           # Connecteurs & utilitaires Odoo
    └── ui/                              # Interface utilisateur web
```
