# Arbitrage inter-branches : RAG documentaire / Function Calling ERP / Code Intelligence

*Document de travail — sujet mis de côté volontairement pour être traité séparément, une fois les trois branches individuellement stabilisées.*

---

## Le problème

Le routeur doit choisir, pour chaque question utilisateur, quelle(s) branche(s) interroger :

- **RAG documentaire** — procédures internes formalisées, politique RH générale, tout ce qui est correctement écrit ailleurs.
- **Function Calling ERP** — données réelles en base (montants, statuts d'un dossier précis, historique).
- **Code Intelligence** — droits d'accès, structure des processus métier, dépendances entre modules, tel que réellement configuré dans le code.

Le problème n'est pas seulement "choisir la bonne branche" : plusieurs branches peuvent légitimement répondre à la même question, avec des réponses potentiellement différentes si les sources divergent (le wiki dit une chose, le code en fait une autre).

---

## Cas ambigus à couvrir (liste de départ, à enrichir)

- **Question à la frontière RAG / Code Intelligence** : *"Qui peut approuver un avoir de plus de 500 000 Ar ?"* — c'est une question de gouvernance (nécessite le graphe de code pour le seuil réel et le groupe requis), mais potentiellement aussi documentée dans le wiki interne. Si les deux sources existent et divergent, laquelle prime ?
- **Question à la frontière Code Intelligence / Function Calling** : *"Est-ce que ma demande de congé est en attente d'approbation ?"* — le *statut réel* du dossier vient du Function Calling (donnée), mais *qui* doit encore l'approuver et *pourquoi ça bloque* peut nécessiter le graphe de processus (structure). Une réponse complète peut demander les deux branches en séquence, pas une seule.
- **Question à la frontière RAG / Function Calling** : *"Quelle est la politique de remboursement des notes de frais ?"* (RAG, politique générale) vs *"Ma note de frais du 12 juillet est-elle remboursée ?"* (Function Calling, donnée précise) — même thème, deux branches différentes selon que la question est générale ou instanciée.
- **Cas où aucune branche ne devrait répondre seule** : question mêlant donnée + règle + procédure dans la même phrase (ex: *"Pourquoi ma demande d'achat de 2M Ar est bloquée, et qui dois-je relancer ?"* — nécessite le statut réel ET la règle de seuil ET le nom du rôle correspondant).

---

## Axes de décision à trancher

1. **Politique de résolution de conflit** : quand deux branches donnent des réponses différentes sur le même fait (ex: RAG dit "groupe A approuve", code dit "groupe B"), quelle source fait autorité par défaut ? (Piste évoquée dans le plan principal : le code prime comme source de vérité pour tout ce qui touche au fonctionnement réel du système — à confirmer/nuancer ici.)
2. **Séquençage vs sélection unique** : le routeur choisit-il une seule branche par question, ou orchestre-t-il un appel séquentiel à plusieurs branches quand la question le justifie (ex: Function Calling pour la donnée, puis Code Intelligence pour l'explication) ?
3. **Niveau de détail de la réponse selon le profil utilisateur** : un utilisateur métier attend une réponse en rôles humains sans jargon technique, un consultant attend des identifiants précis. Les outils composites de Code Intelligence exposent déjà les deux niveaux (`roles` et `groupes_avec_hierarchie`) — reste à définir qui décide du niveau à restituer : le routeur en amont, ou le prompt de synthèse en aval ?
4. **Détection de la divergence elle-même** : le routeur doit-il systématiquement croiser RAG et Code Intelligence sur les questions de gouvernance pour détecter une divergence, ou seulement sur demande explicite de l'utilisateur (type `comparer_regles_statique_vs_live`, mais appliqué ici à la comparaison RAG vs code plutôt que code vs base live) ?
5. **Jeu d'exemples few-shot** : construire un jeu de cas ambigus représentatifs (au-delà des 4 listés ci-dessus) pour entraîner/valider le classifieur du routeur — à faire une fois les trois branches individuellement stables, pour éviter de calibrer le routeur sur des branches encore mouvantes.

---

## Ce qui n'est pas encore décidé (à ne pas sur-interpréter comme tranché)

Aucun des axes ci-dessus n'a de réponse arrêtée pour l'instant. Ce document sert à ne pas perdre la liste des cas et des questions identifiées, pas à documenter une décision.
