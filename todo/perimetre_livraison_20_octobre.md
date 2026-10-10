# Périmètre de livraison MIRO — 20 octobre 2026

## Objectif

Livrer une première version fiable pour les utilisateurs métiers d'Odoo 17, sans prétendre couvrir tous les besoins de développement ou toutes les personnalisations possibles.

## Questions prioritaires

1. **Accès et approbations** — qui peut consulter, modifier, confirmer ou approuver ; pourquoi une action est-elle refusée ?
2. **Procédures métier** — comment saisir, confirmer, valider, payer ou annuler une opération dans l'interface.
3. **Explication des blocages** — pourquoi une facture, une commande ou une autre opération ne passe-t-elle pas à l'étape suivante ?
4. **État et indicateurs** — combien de ventes, quelles commandes, quels stocks ou quelles factures, dans le périmètre autorisé de l'utilisateur.

Les questions peuvent être formulées en français courant, sans connaître les noms techniques des modèles ou des champs. Si un terme métier est ambigu, MIRO doit demander une précision plutôt que choisir arbitrairement.

## Rôles des modèles

- **Qwen3** : compréhension de la formulation, classification de l'intention et rédaction à partir des éléments fournis par MIRO. Le modèle local est sélectionné par `LOCAL_LLM_MODEL` / `OLLAMA_MODEL` ; vérifier que le tag choisi est effectivement installé sur le serveur Ollama.
- **BGE-M3** : recherche sémantique multilingue et proposition de candidats pour résoudre les termes métier. Ce n'est pas un modèle de génération de réponses.
- **Code et règles déterministes** : validation des plans et outils, identité, société, autorisations, limites, provenance et vérification des faits. Un modèle ne remplace pas ces contrôles.

## Hors périmètre prioritaire de cette livraison

- Explications destinées aux développeurs sur des classes Python, des méthodes internes, le MRO ou la conception de modules.
- Génération ou exécution de code, SQL arbitraire, écritures ERP ou contournement des droits.
- Toute affirmation sur les données actuelles sans lecture autorisée de l'instance, ou sur le comportement personnalisé sans preuve issue de cette instance.

Les intentions techniques existantes restent nécessaires à l'orchestration interne et ne sont pas supprimées par ce cadrage. Cette tranche améliore le cadrage de la classification ; elle ne constitue pas à elle seule un blocage de sécurité exhaustif des demandes hors périmètre.

## Pipeline conservé

Question métier → classification/routage → résolution → plan d'investigation validé → outils autorisés → preuves → vérification → réponse métier ou abstention.

Les branches documentaire, Code Intelligence et runtime ERP restent séparées. Les lectures runtime restent soumises aux règles Odoo et à l'identité authentifiée.

## Critères de validation avant livraison

- Rejouer les tests unitaires ciblés de classification et les tests de non-régression du routage.
- Vérifier sur l'environnement local que le serveur d'inférence possède le modèle configuré ; sinon, choisir un modèle installé par une variable d'environnement, sans modifier le code.
- Rejouer le protocole d'évaluation gelé sans changer ses cas ni ses seuils.
- Ne pas déclarer une précision de 80 % ni une généralisation à toute instance Odoo 17 sans résultats de validation correspondants.
