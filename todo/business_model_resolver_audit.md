# Audit du resolveur metier — 15 octobre 2026

## Perimetre et etat

Mandat : « Reviens sur le resolveur, cree une branche. Check ce qui ne va pas dans le code ». Branche `audit/business-model-resolver`, creee depuis `main` au commit `be82aa0489074e15a9c6c67e92fd2a2691f71de5`. Lecture de `todo/rules.md` et de la fin du journal principal, dont les sections 1397-1402. Audit du parcours question metier -> candidats BGE/lexicaux -> arbitrage -> modeles Odoo. Aucune modification de code de production, aucun changement des alias/seuils/protocole gele et aucun addon modifie.

Les observations ci-dessous sont des constats statiques sur ce commit. Aucun appel Odoo, BGE, LLM ou benchmark et aucune suite de tests n'ont ete executes. Il ne s'agit pas d'une preuve de qualite metier ni de mesures sur l'instance.

## Evolutions deja presentes : ne pas reprendre l'ancien diagnostic

`dense_lookup.py` ne transforme plus une forte similarite en resolution definitive : il fournit des candidats (top 10, seuil 0.25). `resolver.py` les transmet au resolveur lexical. Des chemins d'arbitrage existent pour les leaders lexical/semantique differents et pour les candidats semantiques sans correspondance lexicale stricte. La boucle CI appelle bien `resolve_business_term(..., llm=llm)`. L'absence totale de cablage LLM et l'ancienne selection directe par le score dense ne sont donc pas des descriptions exactes du code actuel.

L'arbitre verifie strictement l'appartenance de la sortie a la liste fermee et accepte NONE. C'est un garde-fou utile a conserver. Les mentions techniques explicites doivent garder un chemin deterministe, sans appel LLM obligatoire.

## 1 — P1 : selection du modele d'embeddings serveur non respectee

Sources : `code_intelligence/agent/semantic_retrieval.py::build_semantic_embedding_function`, `document_rag/vectorstore/embedding_functions.py::resolve_embedding_function`.

Le premier lit `RESOLVER_SEMANTIC_EMBEDDING_MODEL` et le transmet dans `embedding_model`. Pour les backends `local_server`, `ollama`, `openai_compatible`, `vllm`, `tei`, le second n'utilise pas cet argument : il construit le client avec `LOCAL_EMBEDDING_MODEL`.

Consequence certaine de configuration : l'override propre au resolveur est inoperant pour ces backends. Le modele reel n'est pas garanti par la variable documentee. Cela ne prouve pas que le modele est actuellement mauvais sur la machine de pmm : le fichier .env reel n'a pas ete lu. Risque : modifier la configuration generale pour forcer BGE touche aussi le RAG documentaire.

Correction a concevoir : priorite explicite de configuration propre au resolveur, sans changer silencieusement le modele des collections documentaires existantes. Tests de construction des clients et preservation des dimensions/identites des index avant migration.

## 2 — P1 : resolution et planification ne partagent pas une decision unique

Sources : `core/routing/routing.py::route`, `code_intelligence/agent/loop.py::CodeIntelligenceAgentRunner.run`, `code_intelligence/agent/tool_helpers.py::_resolve_model_param`.

Le routeur appelle le resolveur avec `llm=None`, puis classifie l'intention et genere le plan. La boucle CI, si elle est atteinte, recommence la resolution avec un LLM, mais conserve l'intention du plan deja present dans l'etat. Les outils relancent encore le resolveur sans LLM quand leur parametre n'est pas un nom technique existant.

Consequence : une question avec des candidats uniquement semantiques ou un conflit peut etre non resolue au routage, puis resolue dans l'agent. Le plan et l'intention peuvent alors provenir d'un autre etat de resolution que les modeles investigues. La seconde passe n'arrive pas si la route choisie contourne l'agent CI. Le chemin sans LLM des outils peut aussi ne pas resoudre un terme que l'agent sait arbitrer. Le nombre exact de mauvaises routes/reponses n'est pas mesure.

Correction a concevoir : une decision de resolution explicite partagee avec le routage, le plan et les outils; distinguer les candidats de la selection arbitree et ne pas reconstruire aveuglement des decisions a chaque etage. Ce n'est pas simplement remplacer tous les `llm=None` par un client global.

## 3 — P1 : une abstention peut etre remplacee par l'ancien sujet

Source : `core/routing/routing.py::_sticky_concept_or_resolve` et `route`.

La reutilisation retourne le concept precedent des que le nouveau n'est pas resolu et que le precedent l'etait. Elle ne distingue pas une vraie relance elliptique d'une nouvelle question ambigue ou d'un desaccord lexical/semantique. En outre, le dictionnaire de concept retourne peut etre remplace par l'ancien, alors que `generate_investigation_plan` recoit toujours l'objet courant, non remplace.

Deux problemes de contrat verifies : une abstention est masquee dans l'etat de routage; le concept publie et celui du plan peuvent etre differents. La boucle possede egalement une rehydratation de concept, dont les conditions ne sont pas auditees dans ce lot : ne pas conclure que toutes les reponses finales suivent necessairement l'ancien modele.

Correction a concevoir : reutilisation reservee a une continuite conversationnelle etablie, maintien de l'ambiguite explicite et construction du plan depuis le meme concept que celui publie.

## 4 — P2 : candidats alternatifs et vraies cibles multiples sont confondus

Sources : `resolution/fuzzy_lookup.py::_resolve_strict_candidates`, `resolve_fuzzy_match`; `resolution/arbitration.py::_build_arbitration_prompt`.

Si le top lexical depasse le suivant d'au moins 10 points, `_resolve_strict_candidates` marque la resolution reussie et retourne tous les resultats lexicaux, avec une confiance calculee a partir du seul premier. Exemple de branche : scores 95 et 80 -> deux modeles declares resolus, sans preuve que la question vise deux objets. Si les scores sont proches, le chemin arbitre demande au contraire UN SEUL modele. Si les leaders dense et lexical sont identiques, le code retourne sur cette logique stricte; l'accord des premiers ne valide pourtant pas tous les autres candidats.

Il faut conserver les vraies questions multi-cibles, par exemple deux modeles nommes explicitement. Le correctif n'est donc pas de tronquer partout au top 1. Il manque un contrat separant les mentions/cibles independantes des alternatives a departager. Les scores fuzzy/cosinus ne sont pas des probabilites de justesse metier.

## 5 — P2 : cache semantique insuffisamment identifie et invalide

Sources : `semantic_retrieval.py::_embedding_name`, `_query_embedding`, `rank_semantic_model_candidates_scored`; `semantic_index_store.py::SemanticIndexStore`; `embedding_functions.py::LocalServerEmbeddingFunction.name`.

Le nom du client serveur contient le tag du modele, pas l'endpoint ni une revision de l'espace vectoriel. Le cache requete et le fichier d'embeddings partagent cette identite. Deux services ou deux revisions differentes utilisant le meme tag peuvent donc reutiliser des vecteurs incompatibles. Le cache memoire est attache a l'objet graphe et au nom d'embedding sans verifier un digest du corpus : une mutation de labels/menus sur le meme objet n'invalide pas l'index. Un remplacement complet du graphe par un nouvel objet n'a pas ce dernier probleme.

Autre faiblesse : `_cosine_similarity` retourne 0 pour des dimensions incompatibles au lieu de signaler un index invalide. Les vecteurs non finis ne sont pas explicitement rejetes. Ces cas peuvent masquer une panne de donnees comme une mauvaise pertinence; leur occurrence reelle n'est pas mesuree.

Correction a concevoir : identite de configuration non secrete de l'espace vectoriel, digest/version du corpus et validation explicite des vecteurs. Ne jamais inclure de token/API key dans une cle ou les journaux.

## 6 — P2 : retrieval repete et politique de shortlist non uniforme

Sources : `resolver.py`, `resolution/dense_lookup.py`, `resolution/fuzzy_lookup.py::_resolve_strict_candidates`, `resolution/candidates.py::build_arbitration_shortlist`.

La premiere passe recupere les 10 candidats denses et filtre a 0.25. Quand le fuzzy reste ambigu et ne prend pas le chemin de desaccord des leaders, la shortlist reconstruit une recherche semantique jusqu'a 20 candidats, sans ce meme filtre. Elle recoit la question normalisee, contrairement a la premiere requete. Il y a donc au moins une repetition du classement; un second appel reseau d'embedding est possible si les textes different, mais pas certain grace au cache.

La shortlist peut ainsi varier selon la branche, et les scores denses sont perdus avant l'arbitrage. Ce n'est pas une fusion RRF; l'union de candidats n'est pas un bug en soi, mais les seuils et bornes devraient avoir un contrat commun et etre traces. Ne pas calibrer de nouveaux seuils sur le jeu held-out.

## 7 — P2 : les appels d'arbitrage sont sous-comptes

Source : `agent/loop.py::CodeIntelligenceAgentRunner.run`, branche suivant l'appel au resolveur.

Le compteur n'est incremente que lorsque `concept.source_step == 'llm_arbitration'`. Les sorties `hybrid_arbitration`, `semantic_candidate_arbitration`, `llm_arbitration_widened` et les arbitrages qui echouent/s'abstiennent ne sont pas comptes par cette condition. Les metriques cout/nombre d'appels ne representent donc pas toutes les tentatives. Un cache ou un banc d'essai ne doit pas interpretrer ces metriques comme une preuve de cout nul. La fonction de rate limit peut faire plusieurs tentatives : une trace d'execution est preferable a une deduction depuis l'issue finale.

## Ordre recommande pour les correctifs

1. Contrats et tests de configuration du vrai modele d'embeddings, en preservant le RAG documentaire.
2. Une resolution par tour partagee entre routeur, plan et agent; abstention/sticky separes.
3. Contrat explicite candidat alternatif vs cible multiple et arbitrage ferme coherent.
4. Identite/invalidation/validation du cache, puis suppression du retrieval repete et instrumentation des tentatives.
5. Tests unitaires hermetiques des branches; ensuite sondes BGE/LLM sur un jeu de calibrage distinct et validation de bout en bout. Aucun nouveau reglage sur le protocole gele dans cet audit.

## Journal et limites

Seuls ce rapport et son annexe de journal sont publies sur la nouvelle branche. L'exception d'annexe temporaire deja autorisee est utilisee; `todo/contexte.txt` distant n'est pas remplace ni tronque. Les constats de la section 1402 sur synthese/approbation sont distincts et ne sont pas declares corriges par ce diagnostic. Le travail Google Drive et les autres branches sont hors perimetre.
