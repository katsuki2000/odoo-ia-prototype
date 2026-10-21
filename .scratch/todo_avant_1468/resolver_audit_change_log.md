# Journal annexe — audit du resolveur metier

Date : 15/10/2026. Mandat : « Reviens sur le resolveur, cree une branche. Check ce qui ne va pas dans le code ».

Rules relues, ainsi que les dernieres sections du principal distant (1397-1402; blob `62a4aedf9380cd8cc713d131672b8197b2b935bc`). Nouvelle branche `audit/business-model-resolver` creee depuis main `be82aa0489074e15a9c6c67e92fd2a2691f71de5`, sans fusion des autres branches. Rapport : `todo/business_model_resolver_audit.md`.

Lectures : resolver.py; resolution/{dense_lookup,fuzzy_lookup,arbitration,candidates,exact_mention}.py; matching.py; semantic_retrieval.py; semantic_index_store.py; tool_helpers.py; loop.py; core/routing/routing.py; document_rag/vectorstore/embedding_functions.py. Recherche des appels au resolveur dans le depot; sites routeur, agent et outils relus dans leurs sources epinglees au meme commit.

Constats : override du modele d'embeddings serveur ignore; decisions de resolution distinctes entre routeur/agent/outils; reutilisation conversationnelle pouvant masquer une abstention et desynchroniser le concept publie du plan; candidats alternatifs confondus avec cibles multiples; identite/invalidation des caches et validation des vecteurs insuffisantes; recherche dense repetee avec politique de seuils differente; compteur d'appels d'arbitrage incomplet. Detail, limites et ordre de correction dans le rapport.

Correction du diagnostic historique : le dense ne resout plus seul au score et le runner CI passe bien un client LLM. Ne pas annoncer une absence totale d'arbitrage. Aucun code de production ni test modifie; aucun paquet installe, aucun appel BGE/LLM/Odoo, aucune mesure ou validation de runtime revendiquee. Main, Drive et addons inchanges.

Annexe selon l'exception temporaire deja autorisee; aucun remplacement/troncature de todo/contexte.txt distant. L'audit est journalise ici, pas dans le principal distant.
