# Declenchement semantique des analyses — bilan du 15 octobre 2026

Mandat : correction demandee a 19:11 pour les modules personnalises et les formulations non prevues. Branche audit/business-model-resolver; main et .env non modifies. Pas de merge ni de deploiement.

## Commits

- 473a9cad04cf15d2f75e33122f0321675539ec44 : catalogue derive du graphe et selection semantique fermee.
- fde0bc33de049c8e325cd452abfb7c07d496d261 : raccordement routeur/runner, execution gardee, suivis a partir des observations et budget des tentatives.
- Present commit : 26 nouveaux tests et ce bilan. Les 22 regressions precedentes restent presentes.

## Changement de fonctionnement

La chaine active n'utilise plus les predicats lexicaux pour decider quelles analyses CI lancer. Le LLM choisit parmi des appels generes cote serveur depuis les entites du graphe. Ni nom de modele standard ni nom de methode conventionnel ne sont necessaires pour proposer une methode personnalisee. Les cibles peuvent etre plusieurs modeles, y compris ceux seulement etendus par un module selectionne.

Le plan contient des arguments concrets et des identifiants de capacites. Chaque tour est revalide sur le graphe courant, execute par le meme executor de tools et peut etre complete a partir des observations obtenues. Les tentatives en echec consomment le budget CI_MAX_HOPS; une iteration sans progression s'arrete. La selection libre ReAct est desactivee sur ce parcours afin de ne pas court-circuiter la liste fermee. La synthese et ses verifications existantes restent en place.

BGE sert au shortlist lorsque l'inventaire depasse 128 candidats; le LLM arbitre ensuite. En cas de panne, repli explicite et conservateur selon l'intention. Les mots-cles des anciens classifieurs de secours et des gardes de synthese n'ont pas ete tous supprimes du depot. Les anciens modules predispatch_* sont conserves pour compatibilite mais ne sont plus appeles par la chaine active.

## Validation executee

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
python3 -m compileall -q code_intelligence core tests
```

Dans le sandbox de ce lot : 48 tests isoles reussis (22 precedents + 26 nouveaux), compilation reussie. Ce comptage porte sur les fichiers presents dans ce sandbox, pas sur toute la suite du depot.

Tests avec Pydantic reel, graphe/LLM/tools/ontologie/contexte simules explicitement. Le corps de execute_tool_calls est execute par extraction AST; le raccordement final du runner est teste structurellement. Le schema de base du sandbox est une transcription equivalente du contrat distant; investigation_schemas.py distant n'est pas modifie. Les fixtures de retrieval sont hors ligne et n'appellent aucun endpoint, meme si la suite est lancee dans un environnement equipe de Chroma.

Cas couverts : methode custom a un seul site; champ custom; modele standard non presume; module avec uniquement des extensions; inventaire multi-modeles; source sans plage inventee; preservation des arguments; absence de re-filtrage lexical; selection hors liste; plan falsifie/perime; echec, dedup et budget; suivi depuis observation; navigation avec groupes reels et identite inconnue.

## Limites avant integration

- Aucun replay reel Kaggle/BGE/Odoo ni suite complete du projet. Les tests injectent des selections LLM : ils ne mesurent pas la comprehension des paraphrases ou l'exactitude metier.
- Inventaire limite aux cibles resolues et aux informations effectivement indexees. Pas d'elargissement autonome a n'importe quel comodele; un sujet mal resolu, une methode absente du graphe, un bouton non indexe ou du code dynamique restent des limites reelles.
- Comparaisons de personas du harness : leurs gardes restent presentes, mais le nouveau catalogue ne propose pas encore de candidats distincts par persona. Ne pas annoncer les anciens benchmarks de ce domaine valides.
- Les budgets bornent les tentatives d'outils de l'executor, pas tous les appels LLM internes aux outils composites. Le cold start du cache BGE, le cout de parcours du graphe et la latence des suivis doivent etre mesures.
- Le remaniement precedent de loop.py n'a pas ete restaure dans ce lot. Une regression globale de synthese ou de politique d'acces n'est pas exclue sans la suite complete; ne pas deployer comme version validee.
- Les globals historiques des wrappers de tools ne sont pas refactores ici; aucune garantie nouvelle d'isolation multi-requetes n'est revendiquee.

Journalisation : semantic_dispatch_catalogue_log.md, semantic_dispatch_execution_log.md et ce bilan, selon l'exception d'annexe deja autorisee. Le journal d'audit et les annexes precedentes sont preserves. todo/contexte.txt principal distant non remplace, non tronque; aucune affirmation d'ajout des nouvelles corrections dans ce principal.
