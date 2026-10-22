import ast, re, sys
from pathlib import Path

I18N = Path("odoo_addons/miro_ai/i18n")
FR = {
 "AI Request Log": "Journal des requêtes IA",
 "AI answer (HTML / formatted)": "Réponse de l'IA (HTML / formatée)",
 "API secret token (JWT secret)": "Jeton secret API (secret JWT)",
 "Access management for the MIRO AI assistant": "Gestion des accès à l'assistant MIRO AI",
 "Active": "Actif",
 "Analysis in progress...": "Analyse en cours...",
 "Answer from the system's data and code": "Répondre à partir des données et du code du système",
 "Answer only from the internal documentation": "Répondre uniquement à partir de la documentation interne",
 "Ask a question from the MIRO AI assistant to see the history and audit metrics appear here.": "Posez une question depuis l'assistant MIRO AI pour voir apparaître ici l'historique et les métriques d'audit.",
 "Ask a question...": "Posez une question...",
 "Can configure the API and the skills, and view all logs.": "Peut configurer l'API, les compétences et consulter tous les journaux.",
 "Can query the MIRO assistant and view their own histories.": "Peut interroger l'assistant MIRO et consulter ses propres historiques.",
 "Cancel the current question": "Annuler la question en cours",
 "Cannot reach the server (%s). Check that the FastAPI backend is running.": "Impossible de contacter le serveur (%s). Vérifiez que le backend FastAPI est lancé.",
 "Close": "Fermer",
 "Company": "Société",
 "Configuration": "Configuration",
 "Configuration name": "Nom de configuration",
 "Configuration name...": "Nom de la configuration...",
 "Create a new configuration for the Miro AI server": "Créer une nouvelle configuration pour le serveur Miro AI",
 "Created by": "Créé par",
 "Created on": "Créé le",
 "Credentials & API connection": "Identifiants & connexion API",
 "Date": "Date",
 "Display Name": "Nom affiché",
 "Duration (ms)": "Durée (ms)",
 "Enable ORM and documentary search on the Accounting module": "Activer la recherche ORM et documentaire sur le module Comptabilité",
 "Enable ORM and documentary search on the Sales module": "Activer la recherche ORM et documentaire sur le module Ventes",
 "Enable ORM and documentary search on the Stock / Inventory module": "Activer la recherche ORM et documentaire sur le module Stocks / Inventaire",
 "Enable ORM and documentary search on the Support & Tickets module": "Activer la recherche ORM et documentaire sur le module Support & Tickets",
 "Enabled skill categories": "Catégories de compétences activées",
 "Error": "Erreur",
 "Errors": "Erreurs",
 "From the documentation": "D'après la documentation",
 "From the system": "D'après le système",
 "Generated answer": "Réponse générée",
 "Group by": "Regrouper par",
 "Hello! Ask me your question, or ask about the active document.": "Bonjour ! Posez votre question ou interrogez-moi sur le document actif.",
 "History": "Historique",
 "ID": "ID",
 "Investigation plan:": "Plan d'investigation :",
 "Last Updated by": "Dernière mise à jour par",
 "Last Updated on": "Dernière mise à jour le",
 "Loading...": "Chargement...",
 "MIRO AI": "MIRO AI",
 "MIRO AI - RAG Request Audit Log": "MIRO AI - Journal d'audit des requêtes RAG",
 "MIRO AI - Settings and Configuration": "MIRO AI - Paramètres et configuration",
 "MIRO AI Administrator": "Administrateur MIRO AI",
 "MIRO AI Assistant": "Assistant MIRO AI",
 "MIRO AI Request Detail": "Détail de la requête MIRO AI",
 "MIRO AI Request Log": "Journal des requêtes MIRO AI",
 "MIRO AI Settings": "Paramètres MIRO AI",
 "MIRO AI User": "Utilisateur MIRO AI",
 "MIRO Assistant": "Assistant MIRO",
 "MIRO RAG API URL": "URL de l'API MIRO RAG",
 "Markdown answer returned by the assistant.": "Réponse en Markdown renvoyée par l'assistant.",
 "Maximum response time (s)": "Délai maximal de réponse (s)",
 "Maximum time to wait for the backend response. In multi-worker mode, it must stay below Odoo's limit_time_real (120 s by default).": "Temps d'attente maximal de la réponse du backend. En mode multi-workers, il doit rester inférieur à limit_time_real d'Odoo (120 s par défaut).",
 "Metadata (raw JSON)": "Métadonnées (JSON brut)",
 "New conversation": "Nouvelle conversation",
 "No RAG request recorded in the log yet.": "Aucune requête RAG enregistrée dans le journal.",
 "No conversation recorded.": "Aucune conversation enregistrée.",
 "Number of documentary/code sources cited by the answer.": "Nombre de sources documentaires/code citées par la réponse.",
 "Please ask a question.": "Veuillez poser une question.",
 "Question & Answer": "Question & Réponse",
 "Question / Answer": "Question / Réponse",
 "Question asked": "Question posée",
 "Question cancelled.": "Question annulée.",
 "RAG server error (code %s). Please check that the FastAPI service is running.": "Erreur du serveur RAG (code %s). Veuillez vérifier que le service FastAPI est actif.",
 "Raw list of the cited documents or ORM excerpts.": "Liste brute des documents ou extraits ORM cités.",
 "Raw text of the question the user sent to the RAG.": "Texte brut de la question envoyée par l'utilisateur au RAG.",
 "Request Log": "Journal des requêtes",
 "Response time (ms)": "Temps de réponse (ms)",
 "Root address of the MIRO RAG FastAPI server (e.g. http://127.0.0.1:8000 or http://miro_rag:8000)": "Adresse racine du serveur FastAPI MIRO RAG (ex : http://127.0.0.1:8000 ou http://miro_rag:8000)",
 "Route, confidence, evidence status, investigation plan and omitted items, serialized as JSON.": "Route, confiance, statut de preuve, plan d'investigation et éléments masqués, sérialisés en JSON.",
 "Search the MIRO AI Log": "Rechercher dans le journal MIRO AI",
 "Secret shared with the RAG backend (the server's JWT_SECRET variable): random, at least 32 bytes, identical on both sides. Read and write restricted to administrators.": "Secret partagé avec le backend RAG (variable JWT_SECRET du serveur) : aléatoire, au moins 32 octets, identique des deux côtés. Lecture et écriture réservées aux administrateurs.",
 "Session ID": "ID de session",
 "Set the FastAPI server address and enable the ORM skill categories.": "Configurez l'adresse du serveur FastAPI et activez les catégories de compétences ORM.",
 "Settings": "Paramètres",
 "Skill: Accounting (account)": "Compétence : Comptabilité (account)",
 "Skill: Sales (sale)": "Compétence : Ventes (sale)",
 "Skill: Stock (stock)": "Compétence : Stocks (stock)",
 "Skill: Support / Tickets (helpdesk)": "Compétence : Support / Tickets (helpdesk)",
 "Sources": "Sources",
 "Sources & JSON metadata": "Sources & métadonnées JSON",
 "Sources (raw JSON)": "Sources (JSON brut)",
 "Sources count": "Nb de sources",
 "Sources:": "Sources :",
 "Status": "Statut",
 "Success": "Succès",
 "The MIRO AI signing secret is not configured: set a random secret of at least %s bytes in the MIRO AI settings, identical to the RAG server's JWT_SECRET.": "Le secret de signature MIRO AI n'est pas configuré : renseignez dans les paramètres MIRO AI un secret aléatoire d'au moins %s octets, identique à JWT_SECRET du serveur RAG.",
 "The backend returned no answer.": "Aucune réponse renvoyée par le backend.",
 "The maximum response time must be at least 10 seconds.": "Le délai maximal de réponse doit être d'au moins 10 secondes.",
 "The server (%(url)s) did not answer within %(timeout)s s: the answer is too slow. Try again, or increase the timeout in the MIRO AI settings.": "Le serveur (%(url)s) n'a pas répondu en %(timeout)s s : la réponse est trop lente. Réessayez, ou augmentez le délai dans les paramètres MIRO AI.",
 "Time taken to query the FastAPI RAG backend, in milliseconds.": "Durée d'interrogation du backend FastAPI RAG en millisecondes.",
 "Today": "Aujourd'hui",
 "Unique identifier of the RAG discussion session.": "Identifiant unique de la session de discussion RAG.",
 "User": "Utilisateur",
 "Unable to load the conversation history.": "Impossible de charger l'historique des conversations.",
 "Unable to load this conversation.": "Impossible de charger cette conversation.",
 "Error communicating with the MIRO AI assistant.": "Erreur de communication avec l'assistant MIRO AI.",
 "MIRO AI connection error.": "Erreur de connexion MIRO AI.",
 "You": "Vous",
 "%s exchange(s)": "%s échange(s)",
 "Evidence (%s)": "Preuves (%s)",
 "Code Intelligence": "Code Intelligence",
 "ERP data": "Données ERP",
 "Documentation": "Documentaire",
 "Hybrid": "Hybride",
 "General": "Général",
}

def esc(s): return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
def msgid_of(block):
    m = re.search(r'^msgid ((?:".*"\n?)+)', block, re.M)
    return "".join(ast.literal_eval(x) for x in m.group(1).strip().split("\n")) if m else None
PH = re.compile(r"%\(\w+\)s|%s|%d")

pot = (I18N / "miro_ai.pot").read_text(encoding="utf-8")
blocks = pot.split("\n\n")
out, seen, problems = [blocks[0]], set(), []
for b in blocks[1:]:
    if not b.strip(): continue
    mid = msgid_of(b)
    if mid is None: out.append(b); continue
    if mid not in FR:
        problems.append(f"NON TRADUIT: {mid!r}"); continue
    tr = FR[mid]; seen.add(mid)
    if sorted(PH.findall(mid)) != sorted(PH.findall(tr)):
        problems.append(f"PLACEHOLDERS: {mid!r} -> {tr!r}")
    out.append(re.sub(r'msgstr ""\s*$', lambda _: f'msgstr "{esc(tr)}"', b.rstrip("\n")))
for k in FR:
    if k not in seen: problems.append(f"INUTILISE (absent du .pot): {k!r}")
for p in problems: print(p)
if problems: sys.exit("ABORT")

head = out[0].replace('"Plural-Forms: \\n"', '"Language: fr\\n"\n"Plural-Forms: nplurals=2; plural=(n > 1);\\n"')
head = head.replace("# Translation of Odoo Server.", "# French translation of Odoo Server (module miro_ai).")
(I18N / "fr.po").write_text("\n\n".join([head] + out[1:]) + "\n", encoding="utf-8")
print("fr.po ecrit :", len(seen), "termes traduits")
