# Journal annexe — execution semantique bornee

## 15 octobre 2026 — suite du mandat de 19:11

Suite du catalogue 473a9cad04cf15d2f75e33122f0321675539ec44. Rules et dernier bilan relus; exception d'annexe deja autorisee. Principal distant non remplace ni tronque.

Raccordement : routeur et runner utilisent capability_planner; les anciens generateurs restent importables pour compatibilite mais ne pilotent plus ce parcours. predispatch execute le plan valide au lieu de relancer la chaine des predicats a mots-cles.

Execution : chaque etape est confrontee au catalogue du graphe courant (identifiant, action, cible, arguments). Aucune mutation d'arguments par le LLM n'est acceptee. L'execution passe par execute_tool_calls et ses gardes existantes. Navigation : injection de l'identite reelle/None quand inconnue, au lieu du defaut [] du wrapper. Les refus/erreurs et couvertures partielles ne valent pas absence de comportement.

Suivis : les observations peuvent produire un nouveau plan ferme, avec exclusion des appels tentes et budget restant. Chaque tour doit consommer un appel pour continuer, sinon arret; un repli heuristique ne relance pas le LLM en boucle. Les etapes ajoutees et compteurs sont reportes dans le plan renvoye. La selection libre ReAct est desactivee pour ce parcours; la synthese existante reste utilisee apres investigation.

Budget : une tentative d'outil consomme un hop avant invoke, y compris en echec; les appels echoues ne sont pas rejoues en boucle. Le plafond est verifie avant chaque appel. Cela ne borne pas encore les appels LLM internes aux outils composites, ni tous les temps reseau. Les groupes du demandeur ne sont pas fournis par le LLM.

Validation locale : 48 tests isoles et compilation reussis. Cas custom sans convention standard, modele etendu seulement, plusieurs cibles, source exacte, plan falsifie/perime, echec/dedup/budget, suivi depuis observations et identite de navigation. Interfaces externes simulees; pas de test complet de production ni de benchmark semantique Kaggle. La suite complete et les comparaisons de personas declarees par le harness doivent etre rejouees : le catalogue de ce lot ne propose pas encore d'etapes distinctes par persona.

Aucun changement de .env, provider LLM, endpoint BGE, main, Drive ou addon. Pas de deploiement. Le remaniement anterieur de loop.py n'est pas annonce comme restaure; cette intervention ajoute le raccordement borne et les tests, sans revendiquer l'absence de regression globale.
