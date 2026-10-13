# Architecture cible de MIRO AI
## 1. Objectif

Mettre en place un PoC d'IA privée qui explique le fonctionnement d'un ERP Odoo 17 à n'importe quel utilisateur, en termes métier, avec des réponses vérifiables, sans dépendre nécessairement de la documentation.
Livrer une première version fiable pour les utilisateurs métiers d'Odoo 17, sans prétendre couvrir tous les besoins de développement ou toutes les personnalisations possibles.

Elle répond soit sur le fonctionnement métier de l'instance en utilisant des termes visibles sur l'interface de la personne qui pose la question  , les données accessibles à l'utilisateur soit sur des documents qui expliquent les procédures internes.

### Questions prioritaires

1. **Accès et approbations** — qui peut consulter, modifier, confirmer ou approuver ; pourquoi une action est-elle refusée ?
2. **Procédures métier** — comment saisir, confirmer, valider, payer ou annuler une opération dans l'interface.
3. **Explication des blocages** — pourquoi une facture, une commande ou une autre opération ne passe-t-elle pas à l'étape suivante ?
4. **État et indicateurs** — combien de ventes, quelles commandes, quels stocks ou quelles factures, dans le périmètre autorisé de l'utilisateur.

Les questions peuvent être formulées en français courant, sans connaître les noms techniques des modèles ou des champs. Si un terme métier est ambigu, MIRO doit demander une précision plutôt que choisir arbitrairement.

**Critère de réussite** : Ceci est un PoC , tant que ça fonctionne sur une partie du code(ou 3à 5 modules), ça va
**Cadrage** : le llm ne repond pas à partir de ses propres connaissances tant que ce n'est pas explicitement demandé par l'utilisateur, meme dans ce cas , il doit le preciser

## Critères de validation avant livraison

- Rejouer les tests unitaires ciblés de classification et les tests de non-régression du routage.
- Rejouer le protocole d'évaluation gelé sans changer ses cas ni ses seuils.
- ÇA MARCHE SUR DES INSTANCES ODOO differentes


## 2. Principes

1. **Le LLM n'est pas la source de vérité.** Le LLM connaît Odoo 17 mais pas ce qui est spécifique à l'ERP. Les faits établis en consultant l'ERP et les documents sont injectés au prompt : le LLM s'appuie sur ses connaissances générales pour comprendre la question, formuler des hypothèses et orienter l'investigation, mais ne répond sur l'instance qu'à partir de ce qui a été trouvé. 
2. **L'autorité dépend du type d'affirmation à établir**, pas d'un classement fixe des sources :

   | Affirmation à établir | Source faisant autorité |
   |---|---|
   | Valeur, volume ou statut actuel | Runtime, sous l'identité du demandeur |
   | Ce que le demandeur voit ou peut faire | Runtime, ACL, règles d'enregistrement, groupes |
   | Pourquoi un bouton, un blocage ou un calcul se comporte ainsi | Code installé, vues et actions, confirmés par le runtime quand l'état compte |
   | Règle de sécurité applicable | ACL, règles, groupes, code |
   | Procédure ou politique interne | Documentation interne |
   

3. **Un routage de sources explicite.** 
Le choix vient de l'utilisateur (mode choisi dans l'interface« selon le système » ou
« d'après la documentation »). si l'utilisateur n'a pas choisi, laisser le llm decider. Le LLM n'est qu'un signal de plus, avec un score de confiance : quand la confiance est faible, MIRO AI demande une clarification au lieu de deviner. Les sources effectivement utilisées sont affichées avec la réponse.

4. **Toute lecture de données se fait sous l'identité du demandeur**, par l'ORM d'Odoo : jamais d'élévation de privilèges implicite. L'utilisateur et la société viennent de la session authentifiée, jamais d'une sortie du LLM. 

5. **Le côté privé** : aucun prompt, secret, extrait de code ou donnée ne quitte l'infrastructure prévue (Kaggle en test et développement, AWS en production, Passer en local  à l'avenir). 

6. **Réutiliser l'existant avant de réimplémenter.** Avant d'ajouter une bibliothèque, un service ou un moteur,inventorier les capacités déjà présentes dans le projet et celles de l'écosystème retenu. Réutiliser les intégrations LLM et embeddings, le RAG existant, les mécanismes d'agentic AI et les fonctions natives d'Odoo 17 (ORM, manifests, dépendances, ACL, règles d'enregistrement, modules et contexte utilisateur), le RPC de Odoo 17



