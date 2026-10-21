
---

# D. Audit du resolveur du 15/10/2026 (branche `audit/business-model-resolver`) : constats et statut

Audit statique (aucun appel Odoo / BGE / LLM), puis trois lots de correction ; les 5 commits (`2612cbe`, `5c5bdad`, `62b4831`, `473a9ca`, `fde0bc3`) sont dans HEAD (fusion de la branche : section 1406). Validation de l'epoque : 22 + 26 tests isoles (fixtures, sans services reels) ; la suite complete a ete rejouee depuis (voir A.7).

| # | Constat de l'audit | Correction | Reste |
|---|---|---|---|
| 1 | Le modele d'embeddings serveur choisi par `RESOLVER_SEMANTIC_EMBEDDING_MODEL` n'etait pas respecte pour les backends serveur (le RAG documentaire lit `LOCAL_EMBEDDING_MODEL`) | Override respecte ; defaut Chroma serveur conserve ; `RESOLVER_SEMANTIC_EMBEDDING_REVISION` pour invalider les vecteurs sous un meme tag | Le nouveau namespace de cache provoque une re-embedding initiale |
| 2 | Routeur (`llm=None`), boucle et outils decidaient chacun leur resolution | `resolve_turn` : decision partagee par tour (question, langue, historique, configuration, snapshot du graphe) ; abstention reutilisee, plan regenere si le graphe change | Chemin des arguments de `tool_helpers` encore distinct |
| 3 | Une abstention pouvait etre remplacee par l'ancien sujet (« sticky ») | Remplacements sticky retires (1409, 1410, 1412) | -- |
| 4 | Candidats alternatifs et vraies cibles multiples confondus (le lexical promouvait tous ses resultats) | Contrat de choix ferme JSON mono / multi-cibles et abstention ; une candidature stricte sans concurrent peut etre deterministe | Qualite des selections multiples non mesuree |
| 5 | Cache semantique mal identifie et non invalide (nom du client sans endpoint ni revision, pas de digest du corpus, vecteurs non finis acceptes) | Identite de configuration du cache, digest du corpus, validation des vecteurs (jamais de secret dans une cle) | Verrouillage interprocessus du cache disque |
| 6 | Retrieval repete, shortlist non uniforme | Pool de candidats unique dans le chemin actif | Helpers exportes de `candidates.py` hors chemin actif non supprimes |
| 7 | Appels d'arbitrage sous-comptes (compteur limite a `llm_arbitration`) | Trace des tentatives d'arbitrage ; compteurs reportes | Budget strict d'appels LLM non implemente |

Planification semantique des analyses (lot du 15/10, 19:11) : le LLM choisit parmi des appels generes cote serveur depuis les entites du graphe (`capability_catalogue.py`, `capability_planner.py`), ce qui supprime la dependance aux mots-cles et aux conventions de modeles / methodes standards pour les modules personnalises ; chaque tour est revalide sur le graphe courant, execute par le meme executeur, les echecs consomment `CI_MAX_HOPS`, la selection libre ReAct est desactivee sur ce parcours. Limites : voir A (points techniques ouverts).

---

# E. Lots de branches deja fusionnes (memoire, un lot par ligne)

- **`fix/ci-api-errors`, frontiere d'erreurs API (14/10)** : `api/public_errors.py` (classificateur commun, messages publics fixes, 503 pour les pannes de connexion / timeout / HTTP 429-5xx XML-RPC, 500 sinon), `routes_ask.py` et `routes_system.py` utilisent la frontiere ; `/api/v1/health` detaille reserve aux administrateurs, `/health` leger public, endpoint LLM retire de la reponse ; 14 tests unitaires + 5 structurels.
- **`fix/ci-source-evidence-boundary` (14/10)** : rendu des sources en preuve uniquement (blocs numerotes contigus observes), jamais de code reconstruit depuis le disque, bornes invalides rejetees avant tout acces fichier ; commits `76ff66d`, `fe87cb6` ; 19 regressions.
- **Suite de la frontiere de sources (14/10)** : plages de provenance validees (lignes positives croissantes ; commit `8ffd672`), scanner de blocs de code ferme / ouvert / indente / CRLF pour fermer les contournements (27 tests au total) ; la verification de citations de `dispatch_guards.py` est restee inchangee.
- **Resolution des references de modeles indexee (14/10)** : index deterministe du corpus de references de modeles (`code_intelligence/model_references.py`) ; commit `5abd815`, partie de la tranche B (section 1338) ; `resolve_model_xmlref` retire (code mort, 1359).
- **Construction du graphe (section 1338, 14/10)** : garde-fous de construction et rapport d'integrite (`graph/integrity_report.py`, `scripts/check_graph_integrity.py`) ; anomalies `unresolved_endpoint` / `untyped_node` traitees en 1384-1387 ; langues du graphe pilotees par `GRAPH_TRANSLATION_LANGUAGES` (1388).
- **`feat/document-rag-google-drive` (14/10)** : connecteur Drive API v3 en lecture seule (ADC), inventaire recursif, formats PDF / TXT / MD / DOCX, sources stables, chunks deterministes ; corpus partage approuve par pmm (`GOOGLE_DRIVE_APPROVED_FOR_RAG=true` obligatoire), garde de disponibilite avant reranking, coordinateur de reconciliation avec purge seulement apres inventaire complet (404 racine = purge du corpus Drive de la collection, jamais des documents locaux), `--watch` avec `GOOGLE_DRIVE_SYNC_INTERVAL_SECONDS` ; commits `ff074d3`, `a08df4e`, `288fffb`, `72772fa`.
- **Resolveur du 15/10** : audit, corrections et planification semantique : voir D.
