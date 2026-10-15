# Journal annexe — corrections du resolveur metier

## 2026-10-15 — mandat et lot embeddings/caches

Mandat de 18:36 : corriger l'audit sur `audit/business-model-resolver`; LLM et BGE deja heberges sur Kaggle et configures dans `.env`. Rules `68bcf0e99080b140a2e58844e653ca917ae52bde` et journal principal jusqu'a 1402 relus pendant cette intervention. Le journal d'audit preexistant reste intact. Annexe selon l'exception temporaire deja autorisee; aucun remplacement du principal distant.

- L'override explicite du modele serveur est respecte. ChromaManager garde le defaut serveur configure, sans le remplacer implicitement par le nom du modele local.
- Identite du cache semantique : nom du fournisseur, endpoint sans authentification ni query string, revision optionnelle `RESOLVER_SEMANTIC_EMBEDDING_REVISION`. Nouveau namespace v2 : premiere utilisation froide possible; les anciens fichiers ne sont pas supprimes.
- Index memoire invalide si les documents derives du graphe changent. Vecteurs finis, non nuls et de dimensions coherentes obligatoires; une incompatibilite remonte en statut ERROR au lieu d'un score zero trompeur.
- Pas de verrou global tenu pendant un appel reseau. Des constructions concurrentes identiques peuvent encore dupliquer du travail; fusion interprocessus du cache disque non ajoutee.
- Aucun endpoint/tag Kaggle impose, aucun `.env` lu ou modifie par l'assistant, aucun appel reel Kaggle/Odoo. Les defauts historiques localhost du client generique restent des defauts, pas une configuration de deploiement.

Validation locale preparee et executee : 22 regressions isolees reussies et compilation des fichiers modifies. Fixtures explicites pour graphe, Chroma et interfaces LangChain; ce n'est ni la suite complete du depot, ni un test d'integration Kaggle/Odoo. Aucun paquet installe. Les tests et les lots de decision suivent dans des commits separes.
