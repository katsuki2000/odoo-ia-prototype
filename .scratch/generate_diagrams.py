#!/usr/bin/env python3
"""
Generate the 11 realistic UML diagrams for Chapter 5 using PlantUML.
"""

import os
import subprocess

PUML_DIR = ".scratch/diagrams_puml"
PNG_DIR = ".scratch/diagrams_png"
os.makedirs(PUML_DIR, exist_ok=True)
os.makedirs(PNG_DIR, exist_ok=True)

COMMON_HEADER = """@startuml
!pragma layout smetana
hide circle
skinparam classAttributeIconSize 0
skinparam backgroundColor white
skinparam shadowing false
skinparam defaultFontName sans-serif
skinparam defaultFontSize 11
skinparam roundCorner 4
skinparam ArrowColor #4B5563
skinparam ArrowFontColor #374151
skinparam ArrowFontSize 10

skinparam class {
    BorderColor #F87171
    BackgroundColor #FEF2F2
    HeaderBackgroundColor #FEE2E2
    FontColor #1F2937
    FontSize 11
}

skinparam usecase {
    BorderColor #F87171
    BackgroundColor #FEF2F2
    FontColor #1F2937
    FontSize 11
}

skinparam actor {
    BorderColor #EF4444
    BackgroundColor #FEE2E2
    FontColor #1F2937
}

skinparam package {
    BorderColor #F87171
    BackgroundColor #FFF5F5
    FontColor #1F2937
    FontSize 12
}

skinparam node {
    BorderColor #F87171
    BackgroundColor #FFF5F5
    FontColor #1F2937
}

skinparam component {
    BorderColor #F87171
    BackgroundColor #FEF2F2
    FontColor #1F2937
}
"""

COMMON_FOOTER = """
@enduml
"""

diagrams = {}

# -------------------------------------------------------------
# Figure 5.1: Use Case Diagram
# -------------------------------------------------------------
diagrams["fig5_1_usecase.puml"] = COMMON_HEADER + """
left to right direction

actor "Utilisateur Odoo\\n(Interne / Client)" as User
actor "Administrateur\\nSystème / Odoo" as Admin
actor "Système Odoo 17\\n(ERP & Sécurité)" as Odoo <<Système>>

rectangle "Assistant IA MIRO — Odoo 17" {
    usecase "Poser une question\\n(Widget Systray OWL)" as UC_Ask
    usecase "Choisir le mode de source\\n(Documentation / Système)" as UC_Mode
    usecase "Consulter les sources\\ndocumentaires (RAG hybride)" as UC_Rag
    usecase "Interroger les données\\nERP en temps réel (ORM)" as UC_Orm
    usecase "Visualiser le plan d'investigation\\net badges de confiance" as UC_Evidence
    usecase "Consulter l'historique\\ndes conversations" as UC_History
    usecase "S'authentifier\\nsur Odoo 17" as UC_Auth
    
    usecase "Configurer les paramètres\\nMIRO AI (miro.ai.settings)" as UC_Config
    usecase "Consulter le journal d'audit\\net requêtes (miro.ai.log)" as UC_Audit
    usecase "Gérer l'ingestion documentaire\\n(Corpus PDF / Wikis)" as UC_Ingest
    
    usecase "Fournir l'identité de session\\n(uid, company_id, groupes)" as UC_Scope
    usecase "Appliquer les droits d'accès\\n(ir.model.access & ir.rule)" as UC_Acl
}

User --> UC_Ask
User --> UC_History
User --> UC_Auth

UC_Ask ..> UC_Mode : «extend»
UC_Ask ..> UC_Rag : «include»
UC_Ask ..> UC_Orm : «include»
UC_Ask ..> UC_Evidence : «include»
UC_Ask ..> UC_Auth : «include»

Admin --> UC_Config
Admin --> UC_Audit
Admin --> UC_Ingest

Odoo --> UC_Scope
Odoo --> UC_Acl

UC_Orm ..> UC_Acl : «include»
UC_Auth ..> UC_Scope : «include»
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.2: Domain Model
# -------------------------------------------------------------
diagrams["fig5_2_domain.puml"] = COMMON_HEADER + """
class Utilisateur {
    + id: int
    + login: str
    + name: str
    + is_admin: bool
}

class Societe {
    + id: int
    + name: str
}

class ParametresMiroAI {
    + api_url: str
    + api_token: str
    + request_timeout: int
    + activer_ventes: bool
    + activer_stocks: bool
    + activer_comptabilite: bool
}

class JournalAudit {
    + question: str
    + answer: str
    + session_id: str
    + response_time_ms: int
    + sources_text: JSON
    + metadata_text: JSON
    + state: str
}

class SessionConversation {
    + session_id: str
    + date_creation: datetime
    + source_mode: str
}

class Message {
    + role: str
    + contenu: str
    + date_envoi: datetime
}

class SourceDocumentaire {
    + source: str
    + title: str
    + doc_type: str
    + snippet: str
    + score_pertinence: float
}

class ObservationORM {
    + modele: str
    + methode: str
    + enregistrements: list
    + uid_executant: int
}

class PreuveVerification {
    + source_type: str
    + statut: str
    + niveau_confiance: str
}

Utilisateur "1..*" -- "1..*" Societe : rattaché à >
Utilisateur "1" -- "0..*" SessionConversation : ouvre >
SessionConversation "1" *-- "1..*" Message : contient >

Message "0..1" -- "0..*" SourceDocumentaire : cite >
Message "0..1" -- "0..*" ObservationORM : s'appuie sur >
Message "1" -- "1" PreuveVerification : évalué par >

Utilisateur "1" -- "0..*" JournalAudit : trace >
Societe "1" -- "0..*" JournalAudit : cloisonne >
ParametresMiroAI "1" -- "1" Societe : configure >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.3: Sprint 1 - Infrastructure & Configuration
# -------------------------------------------------------------
diagrams["fig5_3_sprint1.puml"] = COMMON_HEADER + """
class Settings {
    + EMBEDDING_MODEL: str = "bge-m3"
    + OLLAMA_BASE_URL: str = "http://localhost:11434"
    + CHROMA_PATH: str = "vectorstore/chroma_db"
    + RAG_CHUNK_SIZE: int = 512
    + RAG_CHUNK_OVERLAP: int = 64
    + ODOO_URL_DEFAULT: str = "http://127.0.0.1:8069"
    + ODOO_DB_DEFAULT: str = "odoo-dev"
    --
    + resolve_allowed_models(): tuple
}

class OllamaEmbeddingFunction {
    + endpoint: str
    + model: str
    + api_key: str
    + timeout: float
    + max_retries: int
    + batch_size: int
    --
    + name(): str
    + _embed_batch(texts: list[str]): list[list[float]]
}

class FastAPIApp {
    + title: str = "MIRO AI Backend"
    + version: str = "1.0.0"
    --
    + health_check(): dict
    + startup_event(): void
    + shutdown_event(): void
}

FastAPIApp ..> Settings : charge la configuration >
OllamaEmbeddingFunction ..> Settings : initialise selon >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.4: Sprint 3 - Ingestion et Indexation Documentaire
# -------------------------------------------------------------
diagrams["fig5_4_sprint3.puml"] = COMMON_HEADER + """
class IngestionOrchestrator {
    + chunk_size: int = 512
    + chunk_overlap: int = 64
    + stats: dict
    --
    + ingest_all(docs_dir: str, incremental: bool): dict
    + _process_file(file_path: Path): list
}

abstract class DocumentLoader {
    + supported_extensions: list[str]
    --
    + extract_text(path: Path): str
    + load_directory(dir_path: Path): list
}

class PDFLoader {
    + extract_text(path: Path): str
    + extract_pages_with_metadata(path: Path): list[dict]
}

class WikiLoader {
    + load_markdown(path: Path): dict
    + extract_frontmatter(content: str): dict
}

class ChromaManager {
    + db_path: Path
    + collection_name: str = "odoo_docs"
    + embedding_model: str
    --
    + add_chunks(texts: list, metadatas: list, ids: list): list[str]
    + query(query_text: str, top_k: int, where: dict): dict
    + get_by_id(chunk_id: str): dict
}

class OllamaEmbeddingFunction {
    + model: str = "bge-m3"
    --
    + _embed_batch(texts: list): list
}

DocumentLoader <|-- PDFLoader
DocumentLoader <|-- WikiLoader
IngestionOrchestrator o-- DocumentLoader : utilise >
IngestionOrchestrator --> ChromaManager : stocke vecteurs >
ChromaManager --> OllamaEmbeddingFunction : génère embeddings >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.5: Sprint 4 - Recherche Sémantique et Lexicale Hybride
# -------------------------------------------------------------
diagrams["fig5_5_sprint4.puml"] = COMMON_HEADER + """
class RequeteRecherche {
    + query: str
    + top_k: int = 5
    + source_mode: str
    + where: dict
}

class ChromaManager {
    + query(query_text: str, top_k: int): dict
}

class BM25Index {
    + corpus: list[str]
    + bm25: BM25Okapi
    --
    + build_from_chroma(manager: ChromaManager): void
    + tokenize(text: str): list[str]
    + search(query: str, top_k: int): list[dict]
}

class SearchHybrid {
    + RAG_VECTOR_WEIGHT: float = 0.6
    + RAG_BM25_WEIGHT: float = 0.4
    + RAG_RELEVANCE_THRESHOLD: float = 0.35
    --
    + vector_search(manager, query, top_k): list
    + bm25_search(index, query, top_k): list
    + reciprocal_rank_fusion(vec_res, bm25_res): list
    + retrieve(query: str, top_k: int): list[dict]
}

class ResultatFiltre {
    + id: str
    + document: str
    + metadata: dict
    + score_rrf: float
}

SearchHybrid ..> RequeteRecherche : traite >
SearchHybrid --> ChromaManager : recherche vectorielle dense >
SearchHybrid --> BM25Index : recherche lexicale exacte >
SearchHybrid ..> ResultatFiltre : produit top-k passages >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.6: Sprint 5 - Génération et Vérification Anti-Hallucination
# -------------------------------------------------------------
diagrams["fig5_6_sprint5.puml"] = COMMON_HEADER + """
class GenerateNode {
    + prompt_template: str
    --
    + generate(state: RAGState): dict
    + _assemble_context(chunks: list): str
    + _invoke_llm(prompt: str): LLMResponse
}

class VerifyAnswerNode {
    --
    + verify_answer(state: RAGState): dict
    + check_claim_support(answer: str, sources: list): VerificationReport
    + sanitize_unsupported_facts(answer: str): str
}

class AssistantResponse {
    + answer: str
    + sources: list[SourceReference]
    + confidence: float
    + route: QueryRoute
}

class SourceReference {
    + source: str
    + doc_type: str
    + title: str
    + snippet: str
    + page: int
}

class VerificationReport {
    + is_grounded: bool
    + unsupported_claims: list[str]
    + verified_citations: list[str]
    + confidence_adjustment: float
}

GenerateNode ..> AssistantResponse : synthétise >
GenerateNode --> VerifyAnswerNode : soumet pour vérification >
VerifyAnswerNode ..> VerificationReport : produit rapport >
AssistantResponse *-- SourceReference : contient >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.7: Sprint 7 - Module d'Intégration Odoo OWL (miro_ai)
# -------------------------------------------------------------
diagrams["fig5_7_sprint7.puml"] = COMMON_HEADER + """
class MiroAiSystray <<Component OWL 2.0>> {
    + isOpen: bool
    + loading: bool
    + sourceMode: str
    + sessionId: str
    + messages: list
    --
    + setup(): void
    + toggleDrawer(): void
    + toggleSourceMode(mode: str): void
    + sendMessage(): void
    + askAndWait(payload: dict): Promise
    + loadSessions(): Promise
    + loadSession(sessionId: str): Promise
}

class MiroAiController <<http.Controller>> {
    --
    + health_check(): dict
    + ask(question, session_id, source_mode): dict
    + ask_result(job_id, session_id): dict
    + sessions(limit: int): dict
    + history(session_id: str): dict
    - _fetch_answer(job_id, session_id): dict
}

class AskFlow {
    + KEY_PREFIX: str = "MIRO AI - "
    + JWT_LIFETIME_SECONDS: int = 300
    --
    + generate_jwt_token(payload: dict, secret: str): str
    + requester_scope(env: Environment): tuple
    + issue_requester_key(env: Environment, job_id: str): str
    + revoke_requester_keys(env: Environment, job_id: str): void
}

class BackendClient {
    + candidate_urls_for(api_url: str): list[str]
    --
    + post_with_failover(urls, path, headers, payload): tuple
    + get_with_failover(urls, path, headers): tuple
}

MiroAiSystray --> MiroAiController : RPC POST (json) >
MiroAiController --> AskFlow : signe JWT & émet clé éphémère >
MiroAiController --> BackendClient : relaie vers FastAPI (Job Polling) >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.8: Sprint 9 - Sécurité, Données ERP et Audit
# -------------------------------------------------------------
diagrams["fig5_8_sprint9.puml"] = COMMON_HEADER + """
class MiroAiSettings <<models.Model>> {
    + name: Char
    + api_url: Char
    + api_token: Char (JWT Secret)
    + request_timeout: Integer
    + activer_ventes: Boolean
    + activer_stocks: Boolean
    + activer_comptabilite: Boolean
    + activer_tickets: Boolean
    --
    + get_signing_secret(): str
    + get_active_settings(): record
}

class MiroAiLog <<models.Model>> {
    + question: Text
    + answer: Text
    + user_id: Many2one(res.users)
    + company_id: Many2one(res.company)
    + session_id: Char
    + response_time_ms: Integer
    + sources_text: Text (JSON)
    + metadata_text: Text (JSON)
    + state: Selection (success/error)
    --
    + log_query(question, answer, ...): record
    + get_sessions(limit): list
    + get_session_history(session_id): list
}

class OdooConnector {
    + url: str
    + db: str
    + username: str
    + common: ServerProxy
    + models: ServerProxy
    --
    + execute_kw(model, method, args, kwargs): Any
}

class OrmRuntimeReadTools {
    --
    + orm_fields_get(model: str): OrmToolResult
    + orm_search(model: str, domain: list): OrmToolResult
    + orm_read(model: str, ids: list, fields: list): OrmToolResult
    + orm_search_read(model, domain, fields, limit): OrmToolResult
    + orm_search_count(model, domain): OrmToolResult
    + orm_read_group(model, domain, groupby): OrmToolResult
}

MiroAiLog ..> MiroAiSettings : contrôlé sous >
OrmRuntimeReadTools --> OdooConnector : exécute sous uid strict >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.9: Global Class Diagram (Consolidated)
# -------------------------------------------------------------
diagrams["fig5_9_global_classes.puml"] = COMMON_HEADER + """
package "Client Odoo 17 (miro_ai)" {
    class MiroAiSystray <<Component OWL 2.0>> {
        + isOpen: bool
        + loading: bool
        + sourceMode: str
        + sessionId: str
        + sendMessage(): void
        + askAndWait(): Promise
    }
    
    class MiroAiController <<http.Controller>> {
        + ask(question, session_id): dict
        + ask_result(job_id): dict
        + history(session_id): dict
    }
    
    class AskFlow {
        + generate_jwt_token(): str
        + issue_requester_key(): str
        + revoke_requester_keys(): void
    }
    
    class MiroAiSettings <<models.Model>> {
        + api_url: Char
        + api_token: Char
        + get_signing_secret(): str
    }
    
    class MiroAiLog <<models.Model>> {
        + question: Text
        + answer: Text
        + log_query(): record
    }
}

package "Middleware IA (FastAPI & LangGraph)" {
    class FastAPIApp {
        + post_ask_job(): dict
        + get_job_result(): dict
    }
    
    class AskJobsManager {
        + submit_job(payload): str
        + get_job_status(id): dict
    }
    
    class LangGraphPipeline {
        + workflow: StateGraph
        + build_graph(): CompiledGraph
        + query_graph(question, uid, ...): AssistantResponse
    }
    
    class RouteNode {
        + select_source(question): Selection
        + route(state: RAGState): dict
    }
    
    class AssistantResponse {
        + answer: str
        + sources: list[SourceReference]
        + confidence: float
    }
}

package "Moteur RAG Documentaire Hybride" {
    class IngestionOrchestrator {
        + ingest_all(): dict
    }
    class ChromaManager {
        + query(text, top_k): dict
        + add_chunks(): list
    }
    class BM25Index {
        + search(query, top_k): list
    }
    class SearchHybrid {
        + retrieve(query, top_k): list
        + reciprocal_rank_fusion(): list
    }
    class GenerateNode {
        + generate(state): dict
    }
    class VerifyAnswerNode {
        + verify_answer(state): dict
    }
}

package "Accès ERP & Sécurité Runtime" {
    class OrmAgentLoop {
        + orm_agent_loop(state: RAGState): dict
    }
    class OrmRuntimeReadTools {
        + orm_search_read(): OrmToolResult
        + orm_search_count(): OrmToolResult
        + orm_read_group(): OrmToolResult
    }
    class OdooConnector {
        + url: str
        + db: str
        + execute_kw(model, method, args, kw): Any
    }
}

MiroAiSystray --> MiroAiController : RPC JSON >
MiroAiController --> AskFlow : prépare JWT & clé >
MiroAiController --> MiroAiLog : journalise audit >
MiroAiController --> MiroAiSettings : lit paramètres >
MiroAiController ..> FastAPIApp : REST asynchrone (HTTP 202) >

FastAPIApp --> AskJobsManager : gère file d'attente >
AskJobsManager --> LangGraphPipeline : exécute tâche de fond >

LangGraphPipeline --> RouteNode : oriente requête >
RouteNode --> SearchHybrid : branche documentaire >
RouteNode --> OrmAgentLoop : branche système ERP >

SearchHybrid --> ChromaManager : dense BGE-M3 >
SearchHybrid --> BM25Index : lexical exact >
SearchHybrid --> GenerateNode : passages récupérés >
GenerateNode --> VerifyAnswerNode : synthèse sourcée >
VerifyAnswerNode ..> AssistantResponse : réponse validée >

OrmAgentLoop --> OrmRuntimeReadTools : inspection & lecture >
OrmRuntimeReadTools --> OdooConnector : XML-RPC sous uid demandeur >
OdooConnector ..> "Client Odoo 17 (miro_ai)" : interroge instance Odoo >
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.10: Package Diagram
# -------------------------------------------------------------
diagrams["fig5_10_package.puml"] = COMMON_HEADER + """
package "odoo_addons.miro_ai\\n(Module Odoo 17)" as pkg_miro_ai {
    [Composant OWL Systray]
    [Contrôleur Asynchrone HTTP]
    [Modèles Odoo (Settings & Log)]
    [Sécurité & Règles de Cloisonnement]
}

package "api\\n(Serveur FastAPI)" as pkg_api {
    [Routes REST /ask/jobs]
    [Gestionnaire de Jobs Asynchrones]
    [Authentification JWT HMAC]
}

package "core\\n(Orchestration LangGraph)" as pkg_core {
    [Graphe Décisionnel LangGraph]
    [Routeur Sémantique de Sources]
    [Collecteur de Preuves (Evidence)]
    [Vérificateur Anti-Hallucination]
}

package "document_rag\\n(Moteur RAG Hybride)" as pkg_rag {
    [Ingestion Multi-Format (PDF, Wiki)]
    [Vectorstore ChromaDB (BGE-M3)]
    [Index Lexical BM25]
    [Fusion RRF & Expansion de Contexte]
}

package "erp_data\\n(Agent ORM Temps Réel)" as pkg_erp {
    [Connecteur XML-RPC Odoo]
    [Outils Typés de Lecture Seule]
    [Boucle ReAct Agent Système]
    [Contexte de Sécurité (uid / société)]
}

package "config\\n(Configuration & Environnement)" as pkg_config {
    [Paramètres Système (settings.py)]
    [Identifiants Odoo & LLM]
}

pkg_miro_ai ..> pkg_api : «REST asynchrone / HMAC»
pkg_api ..> pkg_core : «invoque pipeline»
pkg_core ..> pkg_rag : «recherche documentaire»
pkg_core ..> pkg_erp : «requêtes système ERP»
pkg_core ..> pkg_config : «charge constantes»

pkg_rag ..> pkg_config : «chemins & hyperparamètres»
pkg_erp ..> pkg_config : «adresses connexion»
pkg_erp ..> pkg_miro_ai : «XML-RPC sous uid demandeur»
""" + COMMON_FOOTER

# -------------------------------------------------------------
# Figure 5.11: Deployment Diagram
# -------------------------------------------------------------
diagrams["fig5_11_deployment.puml"] = COMMON_HEADER + """
node "<<device>>\\nPoste Utilisateur (Client Web)" as NodeClient {
    node "<<execution environment>>\\nNavigateur Web (Chrome / Firefox)" {
        component [<<component>>\\nInterface Client Odoo 17\\n(Composant OWL 2.0 miro_ai)] as CompOWL
    }
}

node "<<device>>\\nServeur ERP d'Entreprise\\n(on-premise / cloud privé Miro K.E.)" as NodeOdoo {
    node "<<execution environment>>\\nRuntime Odoo 17 (Python 3.11)" {
        component [<<component>>\\nAddon Odoo miro_ai\\n(Contrôleur, Log, Settings)] as CompMiroAddon
        component [<<component>>\\nMoteur Odoo 17 Core\\n(ORM, Sécurité RBAC, XML-RPC)] as CompOdooCore
    }
    node "<<execution environment>>\\nServeur Base de Données" {
        database "<<database>>\\nPostgreSQL 16\\n(Base odoo-dev)" as DBPostgres
    }
}

node "<<device>>\\nServeur IA Dédié Souverain\\n(on-premise Miro K.E.)" as NodeAI {
    node "<<execution environment>>\\nConteneur Docker : Backend IA" {
        component [<<component>>\\nMiddleware FastAPI & LangGraph\\n(Port 8000, Uvicorn)] as CompFastAPI
        database "<<filesystem>>\\nStockage ChromaDB\\n(Embeddings BGE-M3 1024d)" as DBChroma
        folder "<<filesystem>>\\nCorpus Documentaire\\n(docs/ PDF, Wikis Markdown)" as FolderDocs
    }
    
    node "<<execution environment>>\\nConteneur Docker : Moteur LLM" {
        component [<<component>>\\nServeur d'Inférence Ollama / vLLM\\n(Port 11434)] as CompOllama
    }
    
    node "<<device>>\\nAccélération Matérielle" {
        component [<<hardware>>\\nCarte GPU NVIDIA RTX\\n(12 / 16 Go VRAM)] as CompGPU
    }
}

CompOWL -- CompMiroAddon : HTTPS / RPC\\n(Port 8069)
CompMiroAddon -- CompFastAPI : HTTP REST asynchrone (Job Polling)\\n(Port 8000, Signature HMAC SHA-256 JWT)
CompFastAPI -- CompOdooCore : XML-RPC /xmlrpc/2/object\\n(Port 8069, lecture seule sous uid demandeur)

CompMiroAddon -- CompOdooCore : appels internes Python
CompOdooCore -- DBPostgres : SQL TCP/IP (Port 5432)

CompFastAPI -- CompOllama : HTTP REST API (Port 11434)
CompOllama .. CompGPU : Inférence CUDA Tensor Cores

CompFastAPI -- DBChroma : requêtes vectorielles (ChromaDB API)
CompFastAPI -- FolderDocs : ingestion & tokenisation
""" + COMMON_FOOTER

# Write all files and render
for filename, content in diagrams.items():
    filepath = os.path.join(PUML_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print(f"Wrote {filepath}")

# Render one by one to see detailed output
for filename in diagrams.keys():
    puml_path = os.path.join(PUML_DIR, filename)
    cmd = ["java", "-jar", ".scratch/plantuml.jar", "-o", os.path.abspath(PNG_DIR), puml_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error rendering {filename}: rc={res.returncode}")
        print(res.stderr)
    else:
        png_name = filename.replace(".puml", ".png")
        png_path = os.path.join(PNG_DIR, png_name)
        size = os.path.getsize(png_path) if os.path.exists(png_path) else 0
        print(f"Successfully rendered {png_name} ({size} bytes)")
