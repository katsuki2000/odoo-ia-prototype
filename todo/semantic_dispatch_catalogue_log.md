# Journal annexe — catalogue et planification semantique

## 15 octobre 2026 — mandat de 19:11

Corriger la dependance du declenchement des outils aux mots-cles et aux conventions de modeles/methodes standards, pour les modules personnalises. Rules relues (68bcf0e99080b140a2e58844e653ca917ae52bde); historique principal connu jusqu'a 1402 et dernier bilan de branche relu. Base de ce lot : 0a4f8d13489228cb5e6cc02369cd1aa18cad32b9 sur audit/business-model-resolver. Annexe selon exception deja autorisee; principal distant preserve, pas de main ni miro_ai_discuss.

Nouveaux modules capability_catalogue.py et capability_planner.py :
- Appels candidats generes depuis les vrais modeles, methodes, champs, boutons eventuellement indexes et plages source completes. Pas de methode standard inventee. Un module qui etend seulement un modele existant est inclus via DEFINED_IN/extends, pas seulement declares.
- Le LLM choisit des identifiants d'appels fermes via une sortie structuree Pydantic/json_schema. Arguments fabriques cote serveur depuis le graphe; une selection hors inventaire ou budget est refusee.
- Au-dela de 128 candidats, reutilisation du fournisseur BGE et du cache configure pour un shortlist, repartie entre cibles. Si retrieval indisponible, inventaire borne equitable et limite explicite. Aucun nouveau endpoint/tag/secret ou paquet.
- Repli conservateur par intention deja resolue, pas par mots-cles de la question. Les anciens classifieurs de secours peuvent encore employer des heuristiques quand le LLM d'intention est indisponible; ne pas annoncer zero regex dans tout le projet.
- Plan serialisable et arguments conserves pour execution; suivi possible depuis observations, exclusion des appels deja tentes et budget restant.

Validation locale avant publication : 48 tests isoles au total (22 anterieurs + 26 nouveaux), compilation reussie. Pydantic reel; graphe, services LLM, outils et contexte externes remplaces par fixtures. Le schema de base local utilise pour le sandbox est une transcription equivalente de ses contrats; investigation_schemas.py distant n'est pas modifie. La suite du depot avec ses imports/dependances reels, BGE/LLM Kaggle et Odoo ne sont pas declares testes. Tests et raccordement publies dans les lots suivants.
