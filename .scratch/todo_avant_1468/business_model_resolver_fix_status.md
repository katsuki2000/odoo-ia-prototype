# Corrections du resolveur metier — 15 octobre 2026

Branche : `audit/business-model-resolver`. Base : main `be82aa0489074e15a9c6c67e92fd2a2691f71de5`. Aucun merge ni deploiement.

## Lots publies

1. `2612cbe7e2d68d97daff74de39df5649d1eccb29` : override embeddings serveur, maintien du defaut Chroma serveur, identite/invalidation des caches et validation des vecteurs.
2. `5c5bdad61af5aad7e729a61f8c88d20668687eb5` : pool de candidats unique dans le chemin actif, choix ferme JSON mono/multi-cibles et abstention, trace des tentatives d'arbitrage.
3. `62b4831405a9a83211fef386f8e23b3b68c5ea8f` : partage de la decision du tour entre routeur/plan/runner, retrait des remplacements sticky automatiques, report des compteurs d'arbitrage.
4. Present commit : 22 regressions isolees et bilan des validations/limites.

## Validation effectuee

```bash
python3 -m unittest discover -s tests -p test_resolver_decision_regressions.py -v
python3 -m compileall -q code_intelligence core document_rag tests
```

Resultat local : 22 tests reussis, compilation reussie. Les tests chargent les vrais corps de fonctions, mais remplacent explicitement les imports et interfaces externes par des fixtures; le raccordement du runner est teste structurellement. Ce n'est pas la suite complete du projet. Dans le sandbox : networkx, rapidfuzz, pytest, langchain_core et chromadb indisponibles; aucun paquet installe. Aucun appel reel BGE, LLM ou Odoo.

Le LLM et BGE restent ceux configures dans `.env`; aucune valeur Kaggle n'est imposee et aucun secret n'est lu/publie. Le nouveau namespace du cache semantique peut provoquer une re-embedding initiale. Une revision d'un modele sous le meme tag/endpoint doit etre signalee via `RESOLVER_SEMANTIC_EMBEDDING_REVISION` pour invalider ses vecteurs.

## Reste a verifier ou terminer

- Suite complete avec les dependances du projet, puis replay des questions FR/EN mono/multi-modeles sur Kaggle et l'instance Odoo. Les anciens tests qui attendent la promotion de toutes les alternatives ou une reutilisation sticky automatique peuvent necessiter une mise a jour explicite du contrat; ils n'ont pas ete declares verts.
- Chemin des arguments metier de tool_helpers : reste distinct et sans arbitrage partage. Ne pas declarer le constat routeur/agent/outils totalement clos.
- loop.py a ete compacte au cours du raccordement; textes de retry et logs simplifies. Les gardes et flux generaux sont maintenus, mais une regression de synthese/securite de bout en bout n'est pas exclue sans les tests complets. Ne pas deployer cette branche comme version validee.
- Mesurer cout de l'empreinte du graphe a chaque verification, latence/retries Kaggle et qualite des selections multiples. Les limites quantitatives de candidats existantes restent bornees; aucune precision metier garantie par les seuls tests de parsing.
- Budget strict d'appels, attente des appels totalement echoues, verrouillage/fusion interprocessus du cache disque et suppression des anciens helpers hors chemin actif non implementes.

Journalisation : `todo/resolver_fix_change_log.md`, `todo/resolver_decision_change_log.md`, `todo/resolver_turn_change_log.md` et ce bilan, en plus du journal d'audit conserve intact. Exception d'annexe deja autorisee; `todo/contexte.txt` distant non remplace ni tronque. Les nouvelles corrections ne sont pas annoncees comme ajoutees au principal.
