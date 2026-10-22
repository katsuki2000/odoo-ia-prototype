import sys
from pathlib import Path
A = Path("odoo_addons/miro_ai")
E = {}

# ---------------------------------------------------------------- Python
E["controllers/main.py"] = [
 ("from odoo import http\n", "from odoo import _, http\n"),
 ("""return {'answer': "Veuillez poser une question.", 'sources': []}""",
  """return {'answer': _("Please ask a question."), 'sources': []}"""),
 ("data.get('answer', 'Aucune réponse renvoyée par le RAG.')",
  "data.get('answer', _(\"The backend returned no answer.\"))"),
 ("""err_msg = f"Erreur du serveur RAG (code {resp.status_code}). Veuillez vérifier que le service FastAPI est actif.\"""",
  """err_msg = _(
                    "RAG server error (code %s). Please check that the FastAPI service is running.",
                    resp.status_code,
                )"""),
 ("""                err_msg = (
                    f"Le serveur ({api_url}) n'a pas répondu en {timeout} s : la réponse est trop lente. "
                    "Réessayez, ou augmentez le délai dans Paramètres MIRO AI."
                )""",
  """                err_msg = _(
                    "The server (%(url)s) did not answer within %(timeout)s s: the answer is too slow. "
                    "Try again, or increase the timeout in the MIRO AI settings.",
                    url=api_url, timeout=timeout,
                )"""),
 ("""err_msg = f"Impossible de contacter le serveur  ({api_url}). Vérifiez que le backend FastAPI est lancé.\"""",
  """err_msg = _(
                    "Cannot reach the server (%s). Check that the FastAPI backend is running.", api_url,
                )"""),
]
E["models/miro_ai_settings.py"] = [
 ("from odoo import models, fields, api\n", "from odoo import _, models, fields, api\n"),
 ("_description = 'MIRO AI - Paramètres et Configuration'", "_description = 'MIRO AI - Settings and Configuration'"),
 ("""        string='Nom de configuration',
        required=True,
        default='Configuration MIRO RAG principale'""",
  """        string='Configuration name',
        required=True,
        default='Main MIRO AI configuration'"""),
 ("        string='Actif',\n", "        string='Active',\n"),
 ("        string='Société',\n", "        string='Company',\n"),
 ("""        string='URL de l\\'API MIRO RAG',""", """        string='MIRO RAG API URL',"""),
 ("help='Adresse racine du serveur FastAPI MIRO RAG (ex: http://127.0.0.1:8000 ou http://miro_rag:8000)'",
  "help='Root address of the MIRO RAG FastAPI server (e.g. http://127.0.0.1:8000 or http://miro_rag:8000)'"),
 ("string='Délai maximal de réponse (s)',", "string='Maximum response time (s)',"),
 ("""        help='Temps d\\'attente maximal de la réponse du backend. En mode multi-workers, '
             'il doit rester inférieur à limit_time_real d\\'Odoo (120 s par défaut).'""",
  """        help='Maximum time to wait for the backend response. In multi-worker mode, '
             'it must stay below Odoo\\'s limit_time_real (120 s by default).'"""),
 ("string='Jeton Secret API (JWT Secret)',", "string='API secret token (JWT secret)',"),
 ("""        help='Secret partagé avec le backend RAG (variable JWT_SECRET du serveur) : '
             'aléatoire, au moins 32 octets, identique des deux côtés. '
             'Lecture et écriture réservées aux administrateurs.'""",
  """        help='Secret shared with the RAG backend (the server\\'s JWT_SECRET variable): '
             'random, at least 32 bytes, identical on both sides. '
             'Read and write restricted to administrators.'"""),
 ("""        string='Compétence : Ventes (sale)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Ventes'""",
  """        string='Skill: Sales (sale)',
        default=True,
        help='Enable ORM and documentary search on the Sales module'"""),
 ("""        string='Compétence : Stocks (stock)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Stocks / Inventaire'""",
  """        string='Skill: Stock (stock)',
        default=True,
        help='Enable ORM and documentary search on the Stock / Inventory module'"""),
 ("""        string='Compétence : Comptabilité (account)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Comptabilité'""",
  """        string='Skill: Accounting (account)',
        default=True,
        help='Enable ORM and documentary search on the Accounting module'"""),
 ("""        string='Compétence : Support / Tickets (helpdesk)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Support & Tickets'""",
  """        string='Skill: Support / Tickets (helpdesk)',
        default=True,
        help='Enable ORM and documentary search on the Support & Tickets module'"""),
 ("""         'Le délai maximal de réponse doit être d\\'au moins 10 secondes.'),""",
  """         'The maximum response time must be at least 10 seconds.'),"""),
 ("""            raise UserError(
                "Le secret de signature MIRO AI n'est pas configuré : renseignez dans les paramètres "
                f"MIRO AI un secret aléatoire d'au moins {MIN_SIGNING_SECRET_BYTES} octets, "
                "identique à JWT_SECRET du serveur RAG."
            )""",
  """            raise UserError(_(
                "The MIRO AI signing secret is not configured: set a random secret of at least "
                "%s bytes in the MIRO AI settings, identical to the RAG server's JWT_SECRET.",
                MIN_SIGNING_SECRET_BYTES,
            ))"""),
]
E["models/miro_ai_log.py"] = [
 ("_description = 'MIRO AI - Journal d\\'audit des requêtes RAG'", "_description = 'MIRO AI - RAG Request Audit Log'"),
 ("""        string='Question posée',
        required=True,
        readonly=True,
        help='Texte brut de la question envoyée par l\\'utilisateur au RAG.'""",
  """        string='Question asked',
        required=True,
        readonly=True,
        help='Raw text of the question the user sent to the RAG.'"""),
 ("""        string='Réponse générée',
        readonly=True,
        help='Réponse en Markdown renvoyée par l\\'assistant.'""",
  """        string='Generated answer',
        readonly=True,
        help='Markdown answer returned by the assistant.'"""),
 ("        string='Utilisateur',\n", "        string='User',\n"),
 ("        string='Société',\n", "        string='Company',\n"),
 ("""        string='ID de Session',
        readonly=True,
        index=True,
        help='Identifiant unique de la session de discussion RAG.'""",
  """        string='Session ID',
        readonly=True,
        index=True,
        help='Unique identifier of the RAG discussion session.'"""),
 ("""        string='Temps de réponse (ms)',
        readonly=True,
        help='Durée d\\'interrogation du backend FastAPI RAG en millisecondes.'""",
  """        string='Response time (ms)',
        readonly=True,
        help='Time taken to query the FastAPI RAG backend, in milliseconds.'"""),
 ("""        string='Sources (JSON brut)',
        readonly=True,
        help='Liste brute des documents ou extraits ORM cités.'""",
  """        string='Sources (raw JSON)',
        readonly=True,
        help='Raw list of the cited documents or ORM excerpts.'"""),
 ("""        string='Nb Sources',
        compute='_compute_sources_count',
        store=True,
        help='Nombre de sources documentaires/code citées par la réponse.'""",
  """        string='Sources count',
        compute='_compute_sources_count',
        store=True,
        help='Number of documentary/code sources cited by the answer.'"""),
 ("""        string='Métadonnées (JSON brut)',
        readonly=True,
        help="Route, confiance, statut de preuve, plan d'investigation et élements masqués, sérialisés en JSON.\"""",
  """        string='Metadata (raw JSON)',
        readonly=True,
        help="Route, confidence, evidence status, investigation plan and omitted items, serialized as JSON.\""""),
 ("""        ('success', 'Succès'),
        ('error', 'Erreur')
    ], string='Statut',""",
  """        ('success', 'Success'),
        ('error', 'Error')
    ], string='Status',"""),
]
E["__manifest__.py"] = [
 ("'summary': 'Assistant IA Intelligent pour Odoo (RAG + ORM)',", "'summary': 'Intelligent AI Assistant for Odoo (RAG + ORM)',"),
 ("""MIRO AI Assistant - Intégration RAG et LangChain pour Odoo 17
=============================================================

Fonctionnalités :
- Paramétrage de la connexion API vers FastAPI / ChromaDB
- Activation du périmètre d'action (Ventes, Stocks, Comptabilité, Tickets)
- Interface de chat et journal d'audit des requêtes""",
  """MIRO AI Assistant - RAG and LangChain integration for Odoo 17
==============================================================

Features:
- API connection settings towards FastAPI / ChromaDB
- Activation of the skill scope (Sales, Stock, Accounting, Tickets)
- Chat interface and request audit log"""),
]
# ---------------------------------------------------------------- XML
E["security/miro_ai_security.xml"] = [
 ("<!-- Catégorie pour MIRO AI -->", "<!-- MIRO AI category -->"),
 ('<field name="name">MIRO Assistant IA</field>', '<field name="name">MIRO AI Assistant</field>'),
 ("Gestion des accès à l'assistant MIRO IA", "Access management for the MIRO AI assistant"),
 ("<!-- Groupe Utilisateur MIRO AI -->", "<!-- MIRO AI User group -->"),
 ('<field name="name">Utilisateur MIRO AI</field>', '<field name="name">MIRO AI User</field>'),
 ("Peut interroger l'assistant MIRO et voir ses historiques.", "Can query the MIRO assistant and view their own histories."),
 ("<!-- Groupe Administrateur MIRO AI -->", "<!-- MIRO AI Administrator group -->"),
 ('<field name="name">Administrateur MIRO AI</field>', '<field name="name">MIRO AI Administrator</field>'),
 ("Peut configurer l'API, les compétences et consulter tous les journaux.", "Can configure the API and the skills, and view all logs."),
 ("<!-- Règle multi-sociétés pour les paramètres MIRO AI -->", "<!-- Multi-company rule for the MIRO AI settings -->"),
 ("<!-- Règle de visibilité du journal : Utilisateur voit ses propres requêtes de sa société -->",
  "<!-- Log visibility rule: a user sees their own requests within their companies -->"),
 ("MIRO AI Log : Voir ses requêtes", "MIRO AI Log: own requests"),
 ("<!-- Règle de visibilité du journal : Admin voit toutes les requêtes des sociétés autorisées -->",
  "<!-- Log visibility rule: an admin sees all requests of the allowed companies -->"),
 ("MIRO AI Log : Admin voit tout", "MIRO AI Log: admin sees all"),
]
E["views/miro_ai_menus.xml"] = [
 ("<!-- Menu Principal MIRO AI -->", "<!-- MIRO AI main menu -->"),
 ("<!-- Sous-menu Journal des requêtes IA -->", "<!-- AI request log sub-menu -->"),
 ('name="Journal des requêtes"', 'name="Request Log"'),
 ("<!-- Sous-menu Configuration -->", "<!-- Configuration sub-menu -->"),
 ("<!-- Option Paramètres sous Configuration -->", "<!-- Settings entry under Configuration -->"),
 ('name="Paramètres"', 'name="Settings"'),
]
E["views/miro_ai_settings_views.xml"] = [
 ("<!-- Vue Formulaire pour miro.ai.settings -->", "<!-- Form view for miro.ai.settings -->"),
 ('<form string="Paramètres MIRO AI">', '<form string="MIRO AI Settings">'),
 ('placeholder="Nom de la configuration..."', 'placeholder="Configuration name..."'),
 ('<group string="Identifiants &amp; Connexion API">', '<group string="Credentials &amp; API connection">'),
 ('<group string="Catégories de Compétences Activées">', '<group string="Enabled skill categories">'),
 ("<!-- Vue Arbre / Liste pour miro.ai.settings -->", "<!-- Tree / List view for miro.ai.settings -->"),
 ('<tree string="Paramètres MIRO AI">', '<tree string="MIRO AI Settings">'),
 ("<!-- Action de Fenêtre pour ouvrir les paramètres -->", "<!-- Window action opening the settings -->"),
 ('<field name="name">Paramètres MIRO AI</field>', '<field name="name">MIRO AI Settings</field>'),
 ("Créer une nouvelle configuration pour le serveur Miro AI", "Create a new configuration for the Miro AI server"),
 ("Configurez l'adresse du serveur FastAPI et activez les catégories de compétences ORM.",
  "Set the FastAPI server address and enable the ORM skill categories."),
]
E["views/miro_ai_log_views.xml"] = [
 ("<!-- Vue Liste (Tree) pour le Journal d'audit MIRO AI -->", "<!-- List (tree) view of the MIRO AI audit log -->"),
 ('<tree string="Journal des requêtes MIRO AI"', '<tree string="MIRO AI Request Log"'),
 ('string="Durée (ms)"', 'string="Duration (ms)"'),
 ("<!-- Vue Formulaire (Form) pour le Journal d'audit MIRO AI -->", "<!-- Form view of the MIRO AI audit log -->"),
 ('<form string="Détail de la requête MIRO AI"', '<form string="MIRO AI Request Detail"'),
 ('<page string="Question &amp; Réponse">', '<page string="Question &amp; Answer">'),
 ('<group string="Question posée">', '<group string="Question asked">'),
 ("""<group string="Réponse de l'IA (HTML / Formatté)">""", '<group string="AI answer (HTML / formatted)">'),
 ('<page string="Sources &amp; Métadonnées JSON">', '<page string="Sources &amp; JSON metadata">'),
 ("<!-- Vue Recherche (Search) pour le Journal d'audit -->", "<!-- Search view of the audit log -->"),
 ('<search string="Rechercher dans le Journal MIRO AI">', '<search string="Search the MIRO AI Log">'),
 ('string="Question / Réponse"', 'string="Question / Answer"'),
 ('<filter string="Succès"', '<filter string="Success"'),
 ('<filter string="Erreurs"', '<filter string="Errors"'),
 ("""<filter string="Aujourd'hui\"""", '<filter string="Today"'),
 ('<group expand="0" string="Regrouper par">', '<group expand="0" string="Group by">'),
 ('<filter string="Utilisateur" name="group_by_user"', '<filter string="User" name="group_by_user"'),
 ('<filter string="Statut" name="group_by_state"', '<filter string="Status" name="group_by_state"'),
 ('<filter string="Société" name="group_by_company"', '<filter string="Company" name="group_by_company"'),
 ("<!-- Action pour ouvrir le Journal d'audit -->", "<!-- Action opening the audit log -->"),
 ('<field name="name">Journal des requêtes IA</field>', '<field name="name">AI Request Log</field>'),
 ("Aucune requête RAG enregistrée dans le journal.", "No RAG request recorded in the log yet."),
 ("""Posez une question depuis l'interface "Discussion Assistant" pour voir apparaître l'historique et les métriques d'audit ici.""",
  "Ask a question from the MIRO AI assistant to see the history and audit metrics appear here."),
]
E["static/description/index.html"] = [
 ("MIRO AI Assistant pour Odoo 17", "MIRO AI Assistant for Odoo 17"),
 ("RAG Intelligent + Exploration ORM", "Smart RAG + ORM Exploration"),
 ("Intégration transparente entre Odoo 17 et le serveur de documentation vectorielle MIRO RAG.",
  "Seamless integration between Odoo 17 and the MIRO RAG vector documentation server."),
]
# ---------------------------------------------------------------- OWL template
E["static/src/xml/miro_ai_assistant.xml"] = [
 ('title="Assistant MIRO AI"', 'title="MIRO AI Assistant"'),
 ('title="Nouvelle conversation"', 'title="New conversation"'),
 ('title="Historique"', 'title="History"'),
 ('title="Fermer"', 'title="Close"'),
 ('<i class="fa fa-spinner fa-spin mr-1"/> Chargement...', '<i class="fa fa-spinner fa-spin mr-1"/> Loading...'),
 ("Aucune conversation enregistrée.", "No conversation recorded."),
 ("""<span t-esc="session.message_count + ' échange(s)'"/>""", """<span t-esc="getExchangeCountLabel(session.message_count)"/>"""),
 ("""t-esc="msg.sender === 'user' ? 'Vous' : 'MIRO AI'\"""", 't-esc="getSenderLabel(msg)"'),
 ("""<i class="fa fa-search mr-1 text-primary"/> Preuves (<t t-esc="msg.sources ? msg.sources.length : 0"/>)""",
  """<i class="fa fa-search mr-1 text-primary"/> <t t-esc="getEvidenceLabel(msg.sources ? msg.sources.length : 0)"/>"""),
 ("Plan d'investigation :", "Investigation plan:"),
 ("Sources :</div>", "Sources:</div>"),
 ("<span>Analyse en cours...</span>", "<span>Analysis in progress...</span>"),
 ('title="Répondre uniquement à partir de la documentation interne"', 'title="Answer only from the internal documentation"'),
 ("""<i class="fa fa-book"/> D'après la documentation""", '<i class="fa fa-book"/> From the documentation'),
 ('title="Répondre à partir des données et du code du système"', """title="Answer from the system's data and code\""""),
 ("""<i class="fa fa-cogs"/> D'après le système""", '<i class="fa fa-cogs"/> From the system'),
 ('placeholder="Posez une question..."', 'placeholder="Ask a question..."'),
 ('title="Annuler la question en cours"', 'title="Cancel the current question"'),
]
# ---------------------------------------------------------------- JS
E["static/src/js/miro_ai.js"] = [
 ('import { ConnectionAbortedError } from "@web/core/network/rpc_service";\n',
  'import { ConnectionAbortedError } from "@web/core/network/rpc_service";\nimport { _t } from "@web/core/l10n/translation";\n'),
 ('const SYSTRAY_INITIAL_CONTENT = "Bonjour ! Posez votre question ou interrogez-moi sur le document actif.";\nconst CANCELLED_CONTENT = "Question annulée.";',
  'const systrayInitialContent = () => _t("Hello! Ask me your question, or ask about the active document.");\nconst cancelledContent = () => _t("Question cancelled.");'),
 ('createMessage(1, "bot", SYSTRAY_INITIAL_CONTENT)', 'createMessage(1, "bot", systrayInitialContent())', 2),
 ('"bot", CANCELLED_CONTENT,', '"bot", cancelledContent(),'),
 ("""console.error("Erreur chargement historique MIRO AI Systray:", error);""", """console.error("MIRO AI Systray: loading the history failed:", error);"""),
 ("""this.notification.add("Impossible de charger l'historique des conversations.", { type: "danger" });""",
  """this.notification.add(_t("Unable to load the conversation history."), { type: "danger" });"""),
 ("""console.error("Erreur chargement session MIRO AI Systray:", error);""", """console.error("MIRO AI Systray: loading the session failed:", error);"""),
 ("""this.notification.add("Impossible de charger cette conversation.", { type: "danger" });""",
  """this.notification.add(_t("Unable to load this conversation."), { type: "danger" });"""),
 ('case "code_intelligence": return "Code Intelligence";', 'case "code_intelligence": return _t("Code Intelligence");'),
 ('case "donnees_erp": return "Données ERP";', 'case "donnees_erp": return _t("ERP data");'),
 ('case "documentaire": return "Documentaire";', 'case "documentaire": return _t("Documentation");'),
 ('case "hybride": return "Hybride";', 'case "hybride": return _t("Hybrid");'),
 ('default: return route || "Général";', 'default: return route || _t("General");'),
 ('throw new Error("Réponse vide de l\'assistant.");', 'throw new Error("Empty answer from the assistant.");'),
 ("""console.error("Erreur MIRO AI Systray:", error);""", """console.error("MIRO AI Systray error:", error);"""),
 ('const errMsg = "Erreur de communication avec l\'assistant MIRO AI.";', 'const errMsg = _t("Error communicating with the MIRO AI assistant.");'),
 ("""this.notification.add("Erreur de connexion MIRO AI.", { type: "danger" });""", """this.notification.add(_t("MIRO AI connection error."), { type: "danger" });"""),
 ("""    formatSessionDate(isoString) {
        return formatSessionDate(isoString);
    }
""",
  """    formatSessionDate(isoString) {
        return formatSessionDate(isoString);
    }

    getSenderLabel(msg) {
        return msg.sender === "user" ? _t("You") : "MIRO AI";
    }

    getExchangeCountLabel(count) {
        return _t("%s exchange(s)", count);
    }

    getEvidenceLabel(count) {
        return _t("Evidence (%s)", count);
    }
"""),
]

apply = "--apply" in sys.argv
bad, plan = [], {}
for rel, edits in E.items():
    t = (A / rel).read_text(encoding="utf-8"); n = t
    for ed in edits:
        old, new = ed[0], ed[1]
        want = ed[2] if len(ed) > 2 else 1
        c = n.count(old)
        if c != want: bad.append(f"{c}!={want} {rel}: {old[:70]!r}")
        else: n = n.replace(old, new)
    plan[rel] = (t, n)
for b in bad: print("PROBLEM", b)
if bad: sys.exit("ABORT: nothing written")
for rel, (t, n) in plan.items():
    print("CHANGE", rel)
    if apply: (A / rel).write_text(n, encoding="utf-8")
print("APPLIED" if apply else "DRY RUN")
