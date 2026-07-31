# Arborescence du Projet & Environnement Odoo

**Date de mise à jour** : 2026-07-31

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
│   ├── verbatim_responses_sprint2.md    # Rapport verbatim adversarial end-to-end (Sprint 2)
│   ├── verbatim_responses_sprint2.json  # Données brutes JSON du benchmark
│   └── benchmark_run_j7_*.log           # Logs d'exécution brute du benchmark
│
├── scripts/                             # Scripts d'exécution et harnais de test
│   ├── run_adversarial_benchmark.py     # Exécuteur du benchmark adversarial (9 questions)
│   └── run_adversarial_extraction.py    # Script d'extraction des modules depuis /home/user/odoo-17.0/addons
│
└── miro-rag/                            # Module principal RAG & Code Intelligence
    ├── rag/
    │   ├── graph.py                     # Routeur LangGraph, ReAct loop, pre-dispatch J8 & tags
    │   ├── schemas.py                   # Dataclasses de réponses & états RAG
    │   └── search.py                    # Recherche vectorielle
    │
    ├── code_intelligence/               # Cœur déterministe & outils Code Intelligence
    │   ├── deterministic_tools.py       # evaluer_regles_enregistrement & qui_a_acces_a (AND/OR, expansion)
    │   ├── business_resolver.py         # Résolveur nom métier -> nom technique (B0)
    │   ├── ci_agent_tools.py            # Wrappers LangChain @tool des 9 outils (avec set_llm_ref)
    │   ├── semgrep_locks_analyzer.py    # Analyseur de verrous Python (analyser_verrous_securite)
    │   ├── server_action_analyzer.py    # Analyseur d'actions serveur (interpret_server_action_with_llm)
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
    │       ├── test_s2_0_business_resolver.py
    │       ├── test_s2_1_record_rules.py
    │       ├── test_s2_3_server_actions.py
    │       ├── test_s2_5_semgrep_locks.py
    │       └── test_j8_llm_server_action_interpretation.py
    │
    ├── ingestion/                       # Ingestion documentaire & indexation
    ├── vectorstore/                     # Stockage ChromaDB local
    ├── tools/                           # Connecteurs & utilitaires Odoo
    └── ui/                              # Interface utilisateur web
```
