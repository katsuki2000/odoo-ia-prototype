# Journal annexe — resolution partagee du tour

## 2026-10-15 — partage routeur/plan/runner

Suite du mandat de 18:36 et des journaux `resolver_fix_change_log.md` et `resolver_decision_change_log.md`. Rules relues; journal principal distant conserve selon l'exception annexe autorisee.

- resolve_turn lie la decision a la question, langue, historique, configuration pertinente et snapshot du graphe. Le runner reutilise une copie de cette decision, y compris une abstention, au lieu de refaire un arbitrage different. Changement de snapshot : nouvelle resolution, et regeneration du plan existant dans le runner.
- Routeur : client d'arbitrage charge paresseusement. Les mentions techniques exactes ne forcent donc pas un appel LLM de resolution. Mode documentation conserve sans resolution.
- Le plan et le concept publie sont construits depuis la meme decision. Plus de remplacement automatique par last_resolved_concept dans le routeur, ni de rehydratation automatique par ancien module/concept dans le runner. Les suivis elliptiques peuvent donc demander une clarification plutot que reutiliser aveuglement un sujet precedent.
- Le runner reprend le nombre de tentatives d'arbitrage et l'attente connue depuis la decision partagee; il ne deduit plus ce nombre du seul nom source_step. Ce n'est pas un nouveau budget strict ni une mesure exhaustive de tous les appels de la pipeline.
- loop.py est aussi compacte dans cette version; execution des outils, gardes de principals, plafonds, synthese et retries sont conserves dans leur structure generale, mais logs et textes de retry ont ete simplifies. Cette partie n'a pas de validation d'integration complete dans cet environnement.
- Limites : les arguments metier de tool_helpers utilisent encore leur chemin de resolution strict separe. Les referencias techniques deja choisies prennent le chemin exact; aucune garantie de decision partagee pour une nouvelle formulation vague fournie par le LLM a un outil. Cette partie de l'audit n'est pas declaree totalement corrigee.
- Identite du graphe dans la signature : reutilisation seulement dans le processus courant; pas de cache de decision distribue. Calcul d'empreinte lineaire sur le graphe a chaque verification, a mesurer sur le corpus reel.

Validation : 22 tests isoles reussis avant publication, dont la reutilisation d'une abstention et l'absence d'appel a _rehydrate_sticky_concept dans le runner. Test runner de raccordement structurel seulement; pas de suite complete LangGraph/Chroma/Odoo/Kaggle. Aucune modification de `.env`, de main, de Drive ou des addons. Tests publies dans le commit suivant.
