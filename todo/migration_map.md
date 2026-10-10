# Carte de migration progressive

Branche cible : fix/local-test-failures

Cette carte est le registre de migration du code existant, pas une architecture parallèle. Aucun déplacement n'est autorisé sans mise à jour directe de tous les imports et des tests concernés dans le même lot.

## Garde-fous

- Garder les règles de todo/rules.md et consigner chaque changement dans todo/contexte.txt.
- Préserver les contrats publics, les points de monkeypatch utilisés par les tests, les comportements de sécurité et les limites de confiance.
- Ne pas créer de façades de compatibilité temporaires.
- Ne pas déplacer un module uniquement pour obtenir une arborescence plus jolie.
- Réutiliser les intégrations LLM/embeddings, le RAG et les fonctions natives Odoo 17 avant toute nouvelle dépendance.
- Le graphe actif décrit les modules effectivement installés dans l'instance. Les addons disponibles sur disque sont des sources potentielles, pas une preuve d'installation.
- Les modules OCA restent rangés sous odoo_addons/ selon la convention du projet, mais leur présence ne signifie pas qu'ils sont installés. addons_path désigne les répertoires parents des modules.

## Carte source → cible

| Périmètre actuel | Cible proposée | Action et dépendances à traiter | Risque |
|---|---|---|---|
| api/ | api/ (entrée HTTP) | Garder les routes et le cycle de vie FastAPI à la frontière. Extraire seulement la logique métier actuellement mêlée aux routes, après inventaire des imports. | Moyen : démarrage de l'indexation documentaire et configuration CORS sont des effets de bord sensibles. |
| config/settings.py | config/settings.py comme façade de configuration unique, avec sous-modules internes éventuels | Conserver une seule source .env; ne pas dupliquer la lecture des paramètres. Vérifier toutes les références directes à settings avant tout découpage. | Élevé : importé transversalement par les moteurs, les tests et les adaptateurs. |
| core/schemas.py et contrats de core/ | domain/contracts/ (à définir au moment de la migration) | Distinguer les contrats métier purs des types liés à LangGraph, LangChain ou au transport HTTP. Ne déplacer qu'après inventaire de tous les imports. | Élevé : contrats traversant plusieurs sous-systèmes. |
| core/routing/ | application/routing/ pour l'orchestration; règles pures vers domain/ | Séparer décision d'application et heuristiques pures. Éviter de réécrire le routage avant d'avoir les métriques du protocole gelé. | Élevé : routage transversal et nombreux imports. |
| core/graph/ | application/orchestration/ (candidat) | Comparer avec code_intelligence/graph/ : le premier orchestre le graphe LangGraph de requête, le second construit le graphe statique de l'instance. Ne pas les fusionner. Retirer les imports croisés uniquement après tests dédiés pour les monkeypatchs de get_retriever et search_retrieve. | Très élevé : imports croisés, monkeypatchs et dépendances runtime. |
| core/evidence/ | domain/evidence/ pour les contrats purs; collecte/orchestration dans application/evidence/ | Séparer modèle de preuve et collecte d'observations. Garder les vérifications d'accès déterministes. | Moyen/élevé : les résultats pilotent abstention et vérification. |
| core/llm/ | adapters/llm/ | Garder le contrat de génération séparé des clients fournisseurs, du rate limiting et des configurations. Réutiliser les intégrations existantes. | Moyen : config et appels partagés. |
| core/session/ | application/session/ ou adapters/session/ selon responsabilité | Séparer contexte de requête, identité et journalisation. Ne jamais déduire l'identité depuis le LLM; conserver le contexte de sécurité. | Élevé : identité, traçabilité et scopes multi-sociétés. |
| code_intelligence/agent/ | application/investigation/ + adapters/code_intelligence/ | Distinguer planification/outils d'investigation de l'analyse statique. Préserver les garde-fous de dispatch et les appels d'outils typés. | Élevé : nombreuses fonctions et tests de régression. |
| code_intelligence/extractor/ | adapters/code_intelligence/parsers/ | Regrouper les extracteurs par format, sans changer le schéma du graphe dans le même lot. | Moyen : couverture multi-formats. |
| code_intelligence/graph/ | adapters/code_intelligence/graph/ | Garder ici le graphe statique de modules installés. Préserver l'ordre effectif de addons_path, la résolution fail-closed en mode runtime et le fallback offline explicite. | Élevé : résolution de sources et empreinte d'instance. |
| code_intelligence/rules/ | domain/odoo_rules/ pour les règles pures; adaptateurs pour l'analyse AST/XML/CSV | Déplacer par familles, pas en bloc. Préserver les exports de package utilisés par des imports existants jusqu'à la migration atomique de leurs consommateurs. | Très élevé : sécurité, ACL, règles d'enregistrement, contraintes et parcours de boutons. |
| code_intelligence/evaluation/ et core/evaluation/ | evaluation/ unique, distinct du runtime | Inventorier les oracles, métriques, bancs de test et éventuels doublons avant de choisir la source de vérité. Ne pas confondre évaluation et vérification de réponse en production. | Moyen/élevé : protocole de mesure et données de référence. |
| document_rag/ingestion/ | application/ingestion/ + adapters/documents/ | Distinguer orchestration d'ingestion, lecture du corpus et indexation. Garder les chemins configurables et les tâches de scan hors des routes. | Élevé : effets de bord au démarrage et index existants. |
| document_rag/vectorstore/ | adapters/retrieval/ | Isoler Chroma/vector store et embeddings derrière les interfaces existantes. Ne pas créer un second moteur RAG; comparer lexical, vectoriel et reranking avant toute évolution. | Élevé : persistance, cache et comportement de recherche. |
| document_rag/verification.py | À arbitrer avec les vérificateurs de core/evaluation/ | Le module importe déjà les oracles et métriques d'évaluation. Avant de le déplacer, recenser les appels et décider si la vérification est une capacité runtime ou un oracle d'évaluation. | Moyen : sémantique production vs évaluation. |
| erp_data/ | adapters/odoo_runtime/ | Séparer client XML-RPC, outils ORM typés, identité/contexte de société et agent. Le runtime doit continuer à appliquer ACL/règles Odoo sous l'identité du demandeur; pas de SQL direct. | Très élevé : autorisations, API keys, limites et contexte multi-sociétés. |
| odoo_addons/miro_ai/ | Décision distincte, possiblement miro_ai_addons/miro_ai/ | Ne pas déplacer tant que addons_path, packaging, tests Odoo, assets et documentation d'installation n'ont pas été vérifiés ensemble. Le dossier d'un module n'est pas lui-même la racine à ajouter à addons_path. | Élevé : installation Odoo et découverte du module. |
| tests/, code_intelligence/tests/, erp_data/tests/, document_rag/tests/ | tests/unit/, tests/integration/, tests/odoo_addons/ (cible graduelle) | Centraliser par type et non par package uniquement. Conserver les tests natifs dans le module Odoo lorsque le runner Odoo les exige. Migrer un lot à la fois, avec commandes de test et imports corrigés ensemble. | Élevé : fixtures globales, markers d'intégration et collecte pytest. |
| scripts/ | scripts/diagnostics/, scripts/maintenance/, scripts/benchmarks/ | Classer par responsabilité après inventaire des points d'entrée et usages CI; éviter de renommer des scripts invoqués par documentation ou CI sans mise à jour atomique. | Faible/moyen. |

## Ordre d'exécution

1. P0 — rendre la CI représentative : déclencher les tests sur tout changement, exécuter la suite pytest configurée, garder la couverture OCA comme contrôle séparé.
2. P1 — établir l'inventaire des imports et contrats : construire les graphes de dépendances réels; noter les imports de package, les monkeypatchs et les effets de bord.
3. P2 — premier lot à faible risque : sélectionner un sous-module feuille dont les consommateurs sont identifiés, déplacer le code et ses tests ensemble, mettre à jour tous les imports sans façade.
4. P3 — migrer les familles transversales : evidence/routing/LLM/session seulement avec tests de contrat ciblés.
5. P4 — traiter les deux graphes séparément : graphe d'orchestration de requête et graphe statique de l'instance restent des concepts distincts.
6. P5 — migrer les adaptateurs : RAG documentaire puis runtime Odoo, avec tests de sécurité et d'isolation.
7. P6 — centraliser les tests par type : après la CI élargie, sans déplacer les tests Odoo natifs hors des emplacements exigés.
8. P7 — traiter miro_ai séparément : seulement après validation de la convention OCA et de l'addons_path réel.

## Contrôles obligatoires par lot

- Tous les imports entrants et sortants du périmètre sont recensés, y compris les imports dynamiques et exports de __init__.py.
- Les points de monkeypatch utilisés dans les tests restent valides ou sont mis à jour dans le même changement.
- Les tests unitaires du périmètre et les tests de sécurité passent; la suite complète est lancée avant fusion.
- Les nouveaux packages/dépendances ne dupliquent aucune capacité existante.
- todo/contexte.txt consigne les fichiers modifiés, les commandes exécutées et les limites de validation.
- Aucun déplacement de fichier généré, de corpus privé ou de cache runtime n'est inclus dans une migration de code.
