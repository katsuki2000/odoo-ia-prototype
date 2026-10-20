# Une boucle d'investigation systeme

## Mandat du 20 octobre 2026

Branche dediee depuis integration/fusion-15oct, base 228f3b9d2d7066504f0c9fdf03099bef3159c1e9. Simplifier le moteur selon todo/architecture.md, sans migrer dans Odoo ni ajouter MCP. Dernieres lignes du principal lues jusqu'a 1442 et aux notes finales (blob 79fc5d10bada5048923550aa7608576c23fcba9d). Ce mandat autorise l'experimentation d'orchestration sur cette nouvelle branche; les protocoles E1/E2 geles ne sont pas modifies. Annexe selon exception deja autorisee, principal preserve.

## Parcours retenu

Interface Odoo -> FastAPI (identite et session) -> choix documentation/systeme -> une boucle standard d'appels d'outils -> verifications existantes -> reponse et preuves.

- Documentation : retrieval et generation existants, sans chargement du graphe de code.
- Systeme explicite : aucun classifieur d'intention, resolveur bloquant, arbitrage de modele ou planificateur LLM avant l'agent.
- Sans choix de source : classification existante uniquement pour documentation/systeme; la distinction donnees/code n'impose plus deux agents.
- L'investigation utilise la boucle preconstruite de LangGraph, les outils CI et les sept primitives ORM read-only existantes. Un seul point d'execution applique identite, budgets, deduplication et filtrage des observations.
- La recherche de symboles retourne des candidats, jamais des preuves de comportement. Elle reutilise les labels du graphe, RapidFuzz et la recherche semantique de modeles existante; pas d'arbitrage LLM distinct. Une recherche semantique du corps du code reste un chantier distinct, non revendique dans ce lot.
- Graphe, client LLM et question sont confines au contexte courant; les consommateurs directs des anciennes references doivent etre adaptes, sans facade magique de module.

## Ce qui ne change pas

FastAPI/JWT, connecteur et politique ORM, sources autorisees, verifications de citations, preuves et gardes metier, fournisseurs LLM/BGE et .env. Aucun travail sur miro_ai_discuss. Aucun changement du modele d'inference ou des cas d'evaluation geles.

Les anciens composants de planification sont retires du chemin actif, pas effaces en masse avant inventaire de leurs tests et autres consommateurs. Leur presence historique ne doit pas devenir une deuxieme orchestration de production.

## Validation et journalisation

Tests hors ligne du routage, de l'execution gardee, des candidats non bloquants et du contexte concurrent. Tester le composant LangGraph reel si ses dependances peuvent etre installees dans le venv isole; sinon signaler explicitement la limite. Aucun resultat complet ni qualite semantique Kaggle/Odoo ne sera deduit des fixtures. Le bilan d'implementation et les limites seront ajoutes dans cette annexe.
