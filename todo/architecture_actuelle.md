# Architecture réelle du système MIRO AI

## 1. Vision et principes fondamentaux

### 1.1. Objectif
Le système MIRO AI est un assistant intelligent d'entreprise conçu pour expliquer le comportement réel, auditable et traçable d'une instance Odoo 17 (modules natifs Odoo, modules communautaires OCA et modules spécifiques custom), sans dépendre d'une documentation souvent obsolète ou inexistante.

Le système répond avec exactitude aux interrogations fonctionnelles, techniques et de gouvernance des utilisateurs :
- Règles d'accès et visibilité : "Pourquoi ce bouton est-il masqué ?", "Qui a le droit de valider cette commande ?"
- Blocages et contrôles métier : "Pourquoi cet avoir est-il bloqué ?", "Quelles conditions déclenchent cette alerte de risque ?"
- Règles de calcul et dépendances : "Comment ce score de risque est-il calculé ?", "Quel champ déclenche ce recalcul ?"
- Enchaînements de workflow : "Quelle est la procédure réelle d'approbation d'une demande d'achat ?"
- Données opérationnelles ERP : "Combien de ventes ont été enregistrées ce mois-ci ?", "Quels articles sont en rupture ?"
- Procédures documentaires : "Quelle est la politique interne de remboursement des frais de déplacement ?"

### 1.2. Hiérarchie des sources de vérité
Le principe cardinal de l'architecture est la subordination stricte des modèles de langage à la réalité du code et de la base de données :

```text
1. L'instance Odoo en exécution (base de données, registres runtime, permissions actives)
2. Le code source Odoo (modèles Python, vues XML, règles de sécurité, contrôleurs, manifests)
3. La configuration Odoo (paramètres généraux, automations, actions serveur, droits)
4. La documentation interne (guides, wikis, manuels - consultés en dernier recours ou sur demande explicite)
```

Le LLM n'est jamais la source de vérité : il ne déduit pas les règles de sécurité, ne devine pas les états de workflow et ne calcule pas les agrégats de données. Il formule et restitue en langage naturel des preuves collectées de façon déterministe.

### 1.3. Politique CI-First (Code Intelligence First)
Contrairement aux architectures RAG conventionnelles qui interrogent un corpus vectoriel documentaire, MIRO AI applique une stratégie **CI-First, RAG-as-last-resort** :
- Toute question structurelle, logique ou procédurale est orientée en priorité vers le moteur de Code Intelligence et le graphe de connaissances.
- La branche documentaire (`document_rag`) n'intervient que si l'utilisateur formule une demande explicitement documentaire (termes clés : *wiki*, *procédure*, *politique interne*, *guide*) ou si l'investigation dans le code confirme l'absence de toute logique applicative sur le sujet.

---

## 2. Architecture globale du pipeline (LangGraph)

L'orchestration globale repose sur un graphe d'états compilé (`StateGraph(RAGState)` dans `core/graph/graph.py`).

### 2.1. Schéma d'exécution du flux

```text
                           Question utilisateur
                                    │
                                    ▼
                          ┌──────────────────┐
                          │  smalltalk_gate  │
                          └─────────┬────────┘
                                    │
                    [smalltalk]     │     [autre]
             ┌──────────────────────┴──────────────────────┐
             │                                             ▼
             │                                   ┌────────────────────┐
             │                                   │ out_of_scope_gate  │
             │                                   └─────────┬──────────┘
             │                                             │
             │                             [hors sujet]    │    [dans périmètre]
             │                     ┌───────────────────────┴───────────────┐
             │                     │                                       ▼
             │                     │                             ┌───────────────────┐
             │                     │                             │     retrieve      │
             │                     │                             │  (Chroma + BM25)  │
             │                     │                             └─────────┬─────────┘
             │                     │                                       │
             │                     │                                       ▼
             │                     │                             ┌───────────────────┐
             │                     │                             │       route       │
             │                     │                             │ (Resolver + Plan) │
             │                     │                             └─────────┬─────────┘
             │                     │                                       │
             │                     │         ┌─────────────────────────────┼─────────────────────────────┐
             │                     │         │                             │                             │
             │                     │         ▼ [CODE_INTEL /               │                             ▼ [DONNEES_ERP]
             │                     │           DOCUMENTAIRE / HYBRIDE]     │                       ┌───────────┐
             │                     │   ┌───────────────────────────┐       │                       │ orm_agent │
             │                     │   │  code_intelligence_agent │       │                       │   _loop   │
             │                     │   └─────────────┬─────────────┘       │                       └─────┬─────┘
             │                     │                 │                     │                             │
             │                     │       [explicit │ [suffisant          │                             │
             │                     │         doc req]│  ou conflit]        │                             │
             │                     │                 ▼                     │                             │
             │                     │          ┌──────────────┐             │                             │
             │                     │          │   generate   │             │                             │
             │                     │          │  (Doc RAG)   │             │                             │
             │                     │          └──────┬───────┘             │                             │
             │                     │                 │                     │                             │
             │                     ▼                 ▼                     ▼                             │
             │               ┌──────────────────────────────────────────────────┐                        │
             └──────────────>│                  format_output                   │<───────────────────────┘
                             │  (Sanitisation, dossier de preuves, avertissements)│
                             └─────────────────────────┬────────────────────────┘
                                                       │
                                                       ▼
                                                      END
```

### 2.2. Description des nœuds et décisions du pipeline

| Nœud / Porte | Type | Rôle architectural |
|---|---|---|
| `smalltalk_gate` | Déterministe | Intercepte salutations, remerciements et politesses sans appel LLM ni recherche vectorielle (`core/session/smalltalk.py`). |
| `out_of_scope_gate` | Déterministe | Filtre les requêtes hors-sujet (météo, cuisine, questions d'ordre général) via `_is_out_of_scope()`. |
| `retrieve` | Hybride | Recherche préliminaire des 10 meilleurs passages documentaires combinant vectoriel ChromaDB (dense) et BM25 (sparse). |
| `route` | Hybride (Code + IA) | Identifie le concept technique via le `BusinessTermResolver`, résout l'intention, génère l'`InvestigationPlan` et détermine la route (`QueryRoute`). |
| `code_intelligence_agent` | Agentique borné | Analyse le code, les permissions, les règles et les overrides via graphe NetworkX, chaîne de pré-dispatch déterministe et boucle ReAct. |
| `orm_agent_loop` | Agentique ORM | Exécute des requêtes de données transactionnelles en temps réel via le connecteur XML-RPC sécurisé d'Odoo. |
| `generate` | Génératif | Synthétise une réponse structurée adossée aux chunks documentaires avec validation des citations. |
| `ci_evidence_decision` | Conditionnel post-CI | Si la question exige explicitement de la documentation, bascule sur `generate`. Sinon, maintient la réponse de Code Intelligence (`SUFFICIENT` ou `CONFLICTING`). |
| `format_output` | Post-traitement | Nettoie le format Markdown, injecte le dossier de preuves structuré, traite les avertissements OCR et les éléments masqués pour autorisation. |

---

## 3. Moteur de Code Intelligence (`code_intelligence/`)

Le sous-système de Code Intelligence constitue le cœur analytique de MIRO AI. Il modélise l'intégralité du code sous forme d'un graphe de connaissances orienté typé et propose des outils d'investigation spécialisés.

### 3.1. Knowledge Graph (NetworkX)

Le graphe est construit par extraction statique (AST Python, parsers XML, parsers CSV de droits d'accès) et sérialisé dans `active_graph.json`.

#### Types de nœuds (12 catégories) :
1. `Module` (`module:<nom>`) : Paquet Odoo avec ses dépendances déclarées dans `__manifest__.py`.
2. `Model` (`model:<technique>`) : Modèle ORM Odoo (ex: `sale.order`, `account.move`), stockant rôles de déclaration (`declares` vs `extends`), fichiers sources et descriptions.
3. `Field` (`field:<modele>.<champ>`) : Définition de champ avec type, relation (`comodel_name`), méthode de calcul (`compute`), inverse, champ lié (`related`) et étiquette UI (`string`).
4. `Method` (`method:<modele>.<nom>`) : Méthode Python avec décorateurs (`@api.depends`, `@api.constrains`, `@api.model`), limites de lignes et sites d'override.
5. `Group` (`group:<xml_id>`) : Groupe de sécurité Odoo (`res.groups`), qualifié en groupe de rôle métier ou groupe technique de configuration.
6. `Rule` (`rule:<xml_id>`) : Règle d'enregistrement (`ir.rule`) avec son filtre `domain_force` et ses drapeaux CRUD (`perm_read`, `perm_write`, `perm_create`, `perm_unlink`).
7. `AccessEntry` (`acl:<module>.<xml_id>`) : Ligne de contrôle d'accès (`ir.model.access.csv`) associant un modèle, un groupe et des permissions CRUD.
8. `ServerAction` (`server_action:<xml_id>`) : Action serveur (`ir.actions.server`) avec code Python exécuté et modèle cible.
9. `AutomationRule` (`automation:<xml_id>`) : Règle d'automatisation (`base.automation` ou cron) liée à un événement déclencheur et à une action serveur.
10. `Menu` (`menu:<xml_id>`) : Élément de navigation UI (`ir.ui.menu`), séquence, groupes associés et action déclenchée.
11. `WorkflowState` (`state:<modele>.<etat>`) : État possible du cycle de vie d'un enregistrement (ex: `draft`, `sent`, `sale`, `done`, `cancel`).
12. `Button` (`button:<modele>.<nom>`) : Bouton d'action dans les vues formulaire XML, avec libellé, méthode appelée, groupes requis et condition de visibilité (`invisible`).

#### Types d'arêtes (18 relations structurelles) :
- Modèles et modules : `DEFINED_IN` (attribut `role`: `declares` ou `extends`), `EXTENDS` (`_inherit`), `DELEGATES_TO` (`_inherits`).
- Modèles et champs : `HAS_FIELD`, `RELATES_TO` (One2many, Many2one, Many2many).
- Champs et méthodes : `COMPUTED_BY`, `DEPENDS_ON` (liant méthode aux champs déclencheurs).
- Sécurité : `RESTRICTED_BY` (Model -> Rule), `GRANTED_BY` (Model -> AccessEntry), `APPLIES_TO_GROUP` (Rule/AccessEntry/Menu -> Group), `IMPLIES` (hiérarchie Group -> Group), `IMPLIES_CONFIGURABLE` (Group -> Group conditionné par un booléen de `res.config.settings`).
- Automations : `TARGETS_MODEL` (ServerAction -> Model), `TRIGGERED_BY` (AutomationRule -> Model), `EXECUTES_ACTION` (AutomationRule -> ServerAction).
- Interface et Workflow : `CHILD_OF` (Menu -> Menu), `OPENS_MODEL` (Menu -> Model via action), `TRANSITIONS_VIA` (WorkflowState -> WorkflowState avec méthode et libellé), `HAS_BUTTON` (Model -> Button).

### 3.2. Instance-Awareness et cycle de vie du graphe
Le graphe n'est pas figé :
- **Inventaire dynamique d'instance** (`code_intelligence/graph/loader.py`) : interrogation de la table `ir.module.module` de l'instance Odoo connectée pour n'indexer que les modules réellement installés (`state = 'installed'`).
- **Empreinte d'instance** (`instance_fingerprint.py`) : calcul d'un hash SHA-256 combinant modules installés, versions, chemins d'accès aux addons et langues actives.
- **Détection d'obsolescence** (`staleness.py`) : détection de modifications sur le système de fichiers pour invalider le cache mémoire.
- **Remplacement atomique** (`atomic_swap.py`) : reconstruction hors ligne et permutation atomique du fichier JSON pour garantir zéro interruption de service.
- **Support multilingue** (`translations.py`, `runtime_translations.py`) : rattachement au graphe des termes traduits extraits des fichiers `.po` et des tables `ir.translation`.

### 3.3. Résolution des termes métier (Business Term Resolver)
Pour traduire le vocabulaire fonctionnel d'un utilisateur vers les modèles et modules techniques Odoo, `code_intelligence/agent/resolver.py` met en œuvre un pipeline hiérarchique à 6 niveaux :

```text
1. Détection de mention technique exacte : regex identifiant un nom formel (ex: 'sale.order', 'res.partner').
2. Alias statiques NFC : dictionnaire canonique normalisé (ex: 'avoir' -> 'account.move', 'note de frais' -> 'hr.expense').
3. Contexte UI actif : reprise du modèle actuellement ouvert dans Odoo (transmis par le widget Systray).
4. Recherche floue et score de spécificité : index rapide calculant un score de granularité sur les descriptions et libellés.
5. Recherche sémantique vectorielle : comparaison d'embeddings sur les libellés de l'instance.
6. Arbitrage LLM borné : en cas d'ambiguïté résiduelle, présentation d'un sous-ensemble strict de candidats au LLM avec départage déterministe.
```

### 3.4. Chaîne de pré-dispatch déterministe
Avant même d'activer la boucle de réflexion du LLM, le système exécute une séquence déterministe de 12 collecteurs d'investigation (`code_intelligence/agent/predispatch.py`) :
1. `dispatch_security_locks` : Détection statique des conditions de blocage (exceptions `UserError`, `ValidationError`) et des seuils monétaires (ex: validation requise au-delà de 5 000 €).
2. `dispatch_server_actions` : Analyse des actions serveur impactant le modèle.
3. `dispatch_override_chain` : Analyse des cascades d'héritage Python, des appels `super()` et des ruptures d'enchaînement (*unguarded super*).
4. `dispatch_who_has_access_to` : Évaluation formelle des matrices de droits CRUD (ACL).
5. `dispatch_evaluate_record_rules` : Évaluation des règles de filtrage par groupe pour le demandeur.
6. `dispatch_evaluate_record_rules_for_personas` : Évaluation isolée des règles pour les personas de test (ex: utilisateur portail vs commercial interne).
7. `dispatch_security_distinction_guard` : Analyse des restrictions spécifiques par rôle.
8. `dispatch_describe_workflow` : Cartographie des étapes et transitions de statuts.
9. `dispatch_inheritance` : Tracé complet des déclarations et extensions de modèles.
10. `dispatch_module_level_ui_inquiry` : Cartographie des points d'entrée menus et actions.
11. `dispatch_button_execution_path` : Extraction des conditions d'invisibilité et des méthodes des boutons de formulaire.
12. `dispatch_analyze_data_constraints` : Extraction des contraintes de base de données (`_sql_constraints`) et contraintes Python (`@api.constrains`).

Les observations issues de cette chaîne sont injectées directement dans le contexte d'analyse. Pour plus de 80 % des requêtes ciblées, ces observations déterministes suffisent à construire l'intégralité de la réponse.

### 3.5. Catalogue des 16 outils de Code Intelligence (`ALL_CI_TOOLS`)

Lorsque la boucle ReAct a besoin d'approfondir l'investigation, elle dispose de 16 outils spécialisés :

| Catégorie | Outil | Rôle fonctionnel |
|---|---|---|
| **Accès & Sécurité** | `who_has_access_to` | Liste les groupes disposant des droits CRUD sur un modèle. |
| | `evaluate_record_rules` | Évalue l'impact des `ir.rule` pour un ensemble de groupes donné. |
| | `evaluate_rules_raw` | Calculateur brut d'intersection de domaines Odoo. |
| **Structure & Flux** | `field_change_impact` | Détermine les méthodes et champs recalculés lors de la modification d'un champ. |
| | `button_execution_path` | Analyse le code déclenché par un bouton, ses restrictions et sa visibilité. |
| | `trace_full_inheritance` | Reconstitue l'arbre généalogique complet d'un modèle Odoo. |
| | `describe_workflow` | Expose la machine à états et les transitions d'un modèle. |
| | `describe_navigation_path` | Reconstitue le chemin de menu menant à une vue spécifique. |
| **Introspection** | `resolve_technical_name` | Résout un terme métier vers un identifiant technique. |
| | `list_involved_modules` | Identifie les modules qui déclarent ou étendent un modèle. |
| | `inspect_module_extensions` | Liste les modèles externes étendus par un module spécifique. |
| | `explain_decision_path` | Synthétise la chaîne de décision menant à un blocage ou un calcul. |
| | `read_source_code` | Lecture contrôlée et bornée d'un extrait de code source. |
| **Analyse Spécialisée** | `analyze_server_actions` | Analyse le code Python contenu dans les actions serveur. |
| | `analyze_security_locks` | Analyse statique AST/Semgrep des verrous de sécurité et seuils de validation. |
| | `analyze_method_override_chain` | Analyse fine des surcharges d'une méthode à travers les couches d'héritage. |
| | `analyze_data_constraints` | Analyse exhaustive des contraintes SQL et décorateurs `@api.constrains`. |

### 3.6. Filtrage de sécurité des observations (`gate_observation`)
Afin de préserver la sécurité de l'instance Odoo :
- Toute observation produite par un outil traverse `gate_observation()` avant d'atteindre le LLM ou le contexte.
- Les lignes décrivant des mécanismes sensibles de contournement (utilisation de `sudo()`, accès administrateur forcé, contournement d'ACL) sont automatiquement expurgées si le demandeur ne possède pas de droits élevés sur le modèle inspecté.
- Tout élément masqué est consigné dans la liste `omitted_for_authorization` de la réponse, garantissant une transparence totale sur les faits retenus.

### 3.7. Post-traitement et correction déterministe (`postprocess.py`)
Pour éliminer les risques d'inversion logique ou d'omission par le LLM, la réponse générée subit une passe de vérification algorithmique stricte :
- **Retries ciblés** : retry anti-répétition en cas de bégaiement textuel, retry de couverture d'extension si le LLM omet des modules déclarés dans les observations.
- **Correcteurs de contradictions** :
  - Inversion de seuil monétaire (ex: affirmer qu'un montant supérieur au plafond ne demande pas d'approbation).
  - Contradiction de permissions d'accès (ex: affirmer qu'un groupe n'a pas accès alors que l'ACL l'autorise).
  - Négation de chaînes d'héritage ou d'overrides constatés dans le graphe.
  - Inversion de visibilité d'un bouton de formulaire.
- **Réinjection déterministe de faits manquants (Backfilling)** : réinsertion automatique des montants exacts de seuil, des références d'exceptions, des groupes obligatoires et des contraintes d'unicité SQL si la synthèse textuelle du LLM les a omis.

---

## 4. Couche sémantique et ontologie métier

La couche sémantique formalise la passerelle entre les concepts fonctionnels et les mécanismes techniques d'Odoo (`code_intelligence/rules/ontology.py`).

### 4.1. Vocabulaire clos des tags sémantiques

#### Tags comportementaux (`BehavioralTag`) :
*Que fait la règle d'un point de vue métier ?*
- `visibility_rule` : Règle conditionnant l'affichage ou l'accès visuel à une donnée ou un écran.
- `blocking_rule` : Règle empêchant une validation ou levant une exception bloquante.
- `calculation_rule` : Règle calculant automatiquement une valeur ou appliquant une formule.
- `workflow_rule` : Règle orchestrant le passage d'un enregistrement d'un état à un autre.
- `approval_rule` : Règle exigeant l'approbation formelle d'un rôle ou responsable hiérarchique.
- `notification_rule` : Règle déclenchant un message, email ou rappel système.

#### Tags techniques (`TechnicalTag`) :
*Quel mécanisme Odoo implémente le comportement ?*
- `record_rule` : Règle de sécurité multi-société ou multi-utilisateur (`ir.rule`).
- `acl` : Droit d'accès global par modèle et groupe (`ir.model.access`).
- `constraint` : Contrainte d'intégrité Python (`@api.constrains`) ou SQL (`_sql_constraints`).
- `computed_field` : Champ calculé Odoo (`compute=`).
- `server_action` : Action automatisée serveur (`ir.actions.server`).
- `cron` : Tâche planifiée périodique (`ir.cron`).

### 4.2. Exploitation et couverture de l'ontologie
- **Traversée ciblée** : `get_tagged_nodes_for_model(G, model_name, ...)` permet aux outils de remonter instantanément les nœuds pertinents sans parcourir tout le graphe.
- **Audit de conformité** : `detect_unexpected_gaps(G)` vérifie qu'aucun nœud structurel (Rule, AccessEntry, ServerAction) ne se trouve dépourvu de ses étiquettes obligatoires.

---

## 5. Moteur Data Intelligence / Runtime Odoo (`erp_data/`)

Pour répondre aux questions portant sur les données opérationnelles en base ("combien", "liste", "qui"), MIRO AI interroge l'instance Odoo en temps réel.

### 5.1. Connecteur XML-RPC sécurisé (`OdooConnector`)
- Connexion native via les services web `/xmlrpc/2/common` et `/xmlrpc/2/object`.
- **Isolation d'authentification** : propagation par `ContextVar` (`odoo_uid_ctx`, `odoo_api_key_ctx`) assurant que chaque appel ERP s'exécute strictement sous l'identité et avec les droits Odoo de l'utilisateur demandeur (respect natif des ACL et règles multi-sociétés Odoo).
- **Gestionnaire de dates en français** (`date_utils.py`) : traduction automatique des expressions temporelles naturelles ("les 30 derniers jours", "depuis le 1er janvier", "ce mois-ci") en domaines de recherche Odoo conformes.

### 5.2. Outils de domaine ERP
- **Ventes (`erp_data/tools/sales.py`)** : total des commandes de vente, volumes d'affaires, moyennes de commandes, détails d'une commande.
- **Stocks (`erp_data/tools/inventory.py`)** : niveaux de stock physique et disponible par produit, statut de livraison, identification des ruptures de stock.
- **Comptabilité (`erp_data/tools/accounting.py`)** : décompte et montants des factures clients/fournisseurs, revenus sur une période.
- **CRM et Partenaires (`erp_data/tools/crm.py`)** : recherche de fiches contacts/sociétés, tickets d'assistance récents.

---

## 6. Moteur Documentary RAG (`document_rag/`)

La branche documentaire est strictement cantonnée aux connaissances procédurales et politiques d'entreprise non codées dans l'ERP.

### 6.1. Stockage vectoriel et recherche hybride
- **Base vectorielle** : ChromaDB local (`document_rag/vectorstore/chroma_db`).
- **Embeddings** : modèle ONNX exécuté localement sur CPU (`all-MiniLM-L6-v2`) via `local_light` ou modèle distant via Ollama.
- **Recherche hybride** : combinaison linéaire des scores vectoriels et des scores lexicaux BM25 (`document_rag/vectorstore/search_hybrid.py`).
- **Re-ranking optionnel** : Cross-Encoder activable via variable d'environnement (`USE_RERANKER=true`).

### 6.2. Pipeline d'ingestion multiformat
- **Formats supportés** : PDF textuels, PDF scannés avec extraction OCR Tesseract (`pdf_ocr.py`), fichiers Markdown et Wiki textuels (`wiki_loader.py`).
- **Ingestion incrémentale** (`incremental.py`) : détection de hachage MD5 évitant toute réindexation inutile des documents non modifiés.
- **Supervision d'ingestion** : watcher de système de fichiers (`watcher.py`) et ordonnanceur automatique de synchronisation toutes les 6 heures (`scheduler.py`).

### 6.3. Génération et contrôle des sources
Le nœud `generate` force une sortie structurée Pydantic (`LLMResponse`) exigeant pour chaque affirmation la mention de l'identifiant exact de la source utilisée. Toute source citée qui ne correspond pas à un chunk réellement récupéré est éliminée par `verify_used_sources()`.

---

## 7. Système de preuves et traçabilité (`core/evidence/`)

MIRO AI se distingue par la production d'un dossier de preuves vérifiable pour chaque conclusion émise.

### 7.1. Modèle canonique `Evidence`
Chaque fait découvert par un outil statique ou une requête ORM est matérialisé par un objet `Evidence` (`core/evidence/evidence.py`) :
- `evidence_id` : Empreinte cryptographique stable (SHA-256 tronqué à 32 caractères) calculée sur le contenu canonique du fait, garantissant la déduplication parfaite entre plusieurs outils.
- `source_type` : Origine du fait (`CODE` pour une règle issue du graphe/AST, `ORM` pour un relevé en base).
- `claim` : Formulation textuelle explicite de l'affirmation.
- `value` : Valeur brute constatée (seuil monétaire, booléen, liste d'identifiants).
- `source` : Provenance technique exacte (ex: `custom_credit_note.rule_credit_note_manager`, `sale.order.action_confirm`, fichier et numéro de ligne).
- `scope` : Contexte d'application du fait (société `company_id`, horodatage `read_at`, permissions de l'utilisateur).

### 7.2. Accumulateur de preuves par requête (`evidence_collector.py`)
Le cycle de collecte est totalement découplé de la chaîne de texte du LLM :
- `start_evidence_collection()` initialise un accumulateur thread-safe (`ContextVar`) au début de chaque tour.
- Les wrappers `@tool` enregistrent automatiquement leurs faits via `record_evidence()`.
- `collect_and_clear_evidence()` vide l'accumulateur et peuple l'attribut `evidence_dossier` de la réponse finale.

### 7.3. Suffisance des preuves (`evidence_sufficiency.py`)
En fin d'exécution de Code Intelligence, la fonction `assess_evidence_sufficiency()` évalue déterministement la solidité de la réponse :
- `SUFFICIENT` : Les outils ont fonctionné sans erreur et ont identifié des règles ou faits pertinents répondant directement à la question.
- `INSUFFICIENT` : Aucune preuve pertinente n'a pu être extraite du graphe ou une incertitude dynamique a été explicitement constatée.
- `CONFLICTING` : Deux modèles résolus ou deux sources valides produisent des verdicts contradictoires sur la même question (ex: désaccord de visibilité selon le canal).

### 7.4. Double niveau d'explication
Chaque réponse transmise à l'utilisateur (`AssistantResponse`) sépare strictement l'intelligibilité fonctionnelle et la vérifiabilité technique :
1. **Niveau Utilisateur (`response.answer`)** : Explication claire, pédagogique et exempte de jargon de développement (ex: "Le bouton de confirmation est indisponible car la commande contient des lignes non approvisionnées et votre profil n'a pas le rôle de gestionnaire des stocks").
2. **Niveau Vérification (`response.sources` et `response.evidence_dossier`)** : Volet technique dépliable pour les auditeurs et administrateurs, précisant le module Odoo, le fichier source, la ligne exacte de code, l'ID XML de la vue ou de la règle, et le contenu du `domain_force`.
3. **Niveau Gouvernance (`response.omitted_for_authorization`)** : Notification explicite et motivée des éléments d'analyse intentionnellement retenus pour des motifs d'habilitation insuffisante.

---

## 8. Sécurité, gouvernance et traçabilité de l'exécution

### 8.1. Garde d'exécution locale stricte (`core/llm/local_only.py`)
Pour répondre aux exigences de confidentialité industrielle, le système intègre un garde d'isolation réseau :
- Lorsque `LOCAL_ONLY=true`, tout appel sortant vers un fournisseur cloud (Groq, OpenRouter) ou vers une adresse IP qui ne figure pas dans `LOCAL_ALLOWED_HOSTS` (par défaut `localhost`, `127.0.0.1`, `::1`) est intercepté et rejeté immédiatement (`ExternalEndpointError`).
- Aucun secret, prompt ou extrait de code ne peut quitter l'infrastructure locale sans configuration délibérée.

### 8.2. Protections contre les injections et l'exfiltration
Dans `core/routing/routing_guards.py` :
- `_is_prompt_injection` : Détection par expressions régulières des tentatives d'altération du prompt système (*jailbreak*, demandes d'ignorer les règles précédentes).
- `_is_massive_extraction_request` : Interception des tentatives d'extraction en masse du schéma ou de la base de données (demandes d'export exhaustif de tables ou de dumps SQL).

### 8.3. Traçabilité des raisonnements (`ReasoningTraceLogger`)
Chaque requête se voit attribuer un identifiant unique de trace (`trace_id`). Toutes les étapes clés (décision de routage, sélection des outils, temps d'exécution de chaque hop, retries et synthèse) sont journalisées de manière structurée au format JSON Lines dans `captures/reasoning_trace.jsonl`.

---

## 9. Exposition API et intégration Odoo 17

### 9.1. Backend FastAPI (`api/`)
L'application expose une interface REST asynchrone complète (`api/main.py`) :
- `POST /api/v1/ask` : Point d'entrée principal. Gère les sessions de conversation (`core/session/session_store.py`), extrait l'identité de l'utilisateur depuis le token JWT, et exécute le pipeline.
- `GET /api/v1/health` : Bilan de santé opérationnel de l'API, de la base vectorielle ChromaDB, de la connexion XML-RPC Odoo et du fournisseur LLM.
- `GET /api/v1/modules` : Comparatif des modules Odoo installés par rapport aux capacités couvertes par l'assistant.
- `POST /api/v1/reindex` : Déclenchement de la réindexation documentaire (complète ou incrémentale).
- `GET /api/v1/ingestion/status` : Suivi en direct du watcher et du planificateur d'ingestion.

### 9.2. Addon Odoo 17 Web (`odoo_addons/miro_ai/`)
L'assistant est intégré nativement dans l'interface web d'Odoo 17 :
- **Widget Systray** : Bouton d'accès rapide violet situé dans la barre supérieure de navigation Odoo.
- **Tiroir contextuel coulissant** : L'interface de chat s'ouvre sur le côté de l'écran sans masquer le formulaire de travail.
- **Capture automatique de contexte** : Le widget interroge le contrôleur web JavaScript pour identifier automatiquement le modèle (`active_model`) et l'enregistrement (`active_id`) ouverts par l'utilisateur, et les transmet à l'API pour contextualiser immédiatement la réponse.
- **Historique en base** : Les échanges sont tracés dans le modèle Odoo `miro.ai.log` à des fins d'audit interne.

---

## 10. Matrice des composants et modularité

```text
odoo-ia-prototype/
├── api/                        # Exposition REST FastAPI
│   ├── main.py                 # Point d'entrée serveur, lifespan, middleware CORS
│   ├── auth.py                 # Authentification utilisateur et validation des tokens JWT
│   ├── routes_ask.py           # Endpoint /api/v1/ask et gestion des sessions
│   ├── routes_system.py        # Endpoints /health, /stats et couverture des modules
│   └── routes_ingestion.py     # Endpoints de réindexation et statut du watcher
├── code_intelligence/          # Bounded context Code Intelligence
│   ├── active_graph.json       # Graphe de connaissances sérialisé
│   ├── agent/                  # Boucle ReAct bornée, résolveur et pré-dispatch
│   │   ├── loop.py             # Exécuteur principal de l'agent de Code Intelligence
│   │   ├── resolver.py         # Résolveur multi-niveaux de termes métier
│   │   ├── predispatch.py      # Séquenceur des 12 analyses déterministes
│   │   ├── postprocess.py      # Correcteurs de contradictions et backfill de preuves
│   │   └── tools/              # Les 16 outils spécialisés d'investigation de code
│   ├── extractor/              # Analyseurs statiques (Python AST, XML views/rules, CSV)
│   ├── graph/                  # Construction, chargement dynamique et empreinte du graphe
│   ├── rules/                  # Ontologie, analyseurs de sécurité, d'overrides et de flux
│   └── semgrep_rules/          # Détecteurs statiques Semgrep pour contraintes et règles
├── config/                     # Configuration et budgets
│   └── settings.py             # Définition des variables d'environnement et seuils de latence
├── core/                       # Noyau partagé et orchestration
│   ├── graph/                  # Pipeline LangGraph (StateGraph, nœuds, décisions conditionnelles)
│   ├── routing/                # Classificateur d'intention et gardes d'injection
│   ├── evidence/               # Contrat Evidence unifié, collecteur ContextVar et suffisance
│   ├── llm/                    # Client multi-fournisseurs, rotation de clés et garde local_only
│   ├── session/                # Gestion des sessions de conversation et traces de raisonnement
│   └── schemas.py              # Modèles de données Pydantic canoniques
├── document_rag/               # Bounded context RAG Documentaire
│   ├── documents/              # Corpus documentaire source (PDFs, wikis internes)
│   ├── ingestion/              # Ingestion incrémentale, OCR Tesseract, watcher et cron
│   └── vectorstore/            # ChromaDB, recherche hybride BM25 et reranking
├── erp_data/                   # Bounded context Runtime Odoo
│   ├── odoo_connector.py       # Client XML-RPC multi-utilisateur isolé
│   ├── orm_agent_node.py       # Boucle d'agent ReAct pour données transactionnelles
│   ├── date_utils.py           # Analyseur sémantique de dates françaises
│   └── tools/                  # Outils ORM par domaine (Ventes, Stocks, Facturation, CRM)
├── odoo_addons/                # Modules Odoo 17 embarqués
│   ├── miro_ai/                # Module Odoo web (Systray, drawer, logs d'audit)
│   └── custom_*/               # 14 modules métier de test et de validation
└── scripts/                    # Scripts d'administration, seeding et bancs d'évaluation
```
