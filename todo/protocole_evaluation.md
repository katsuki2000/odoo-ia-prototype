# Protocole d'évaluation finale de MIRO AI

Version 1.0, rédigée le 29/10/2026, branche `memoire-final`, commit de référence `190718c8` (à remplacer par le tag de gel, section 3). Réponse à la section 7 de `todo/architecture.md` et au chapitre 6 du mémoire (6.1 données, 6.2 prétraitement, 6.3 choix du modèle, 6.4 métriques).

## 0. Statut et déclaration d'indépendance

**Chronologie.** Le développement a été itératif, guidé par deux bancs (`tests/rag_eval_questions.json`, 20 questions, et `tests/benchmark_questions.json`, 37 questions). Ces bancs ont servi à diagnostiquer, corriger et re-noter (journal : sections 1636, 1662, 1663, 1664, 1667). Ils sont donc des **jeux de développement** : leurs résultats servent à la non-régression, jamais de preuve de performance. Ce protocole est écrit après le développement. Il ne prétend pas pré-enregistrer le développement ; il pré-enregistre l'**évaluation finale**.

**Indépendance.** Ce document a été rédigé par un assistant IA (Claude) à la demande de pmm, après lecture des résultats de développement. Pour limiter les biais :
- aucune règle de décision (section 8) ni aucun seuil n'est dérivé de ces résultats ;
- la liste des candidats est fixée par des contraintes fonctionnelles et matérielles, pas par les scores ;
- l'assistant n'écrit pas les questions du jeu de test (section 4.5) ;
- les règles de décision sont figées avant toute exécution du jeu de test ; le jeu de test est exécuté **une seule fois** par configuration.

## 1. Questions d'évaluation

| Id | Question | Section |
|---|---|---|
| QE1 | La récupération hybride (BM25 et vecteurs) trouve-t-elle les passages porteurs de la réponse, mieux qu'un tirage aléatoire et mieux que chaque composant seul ? | 5.1, 9 |
| QE2 | À contexte donné, les réponses documentaires sont-elles correctes, fidèles aux passages, correctement citées, avec abstention quand la réponse n'existe pas ? | 5.2 |
| QE3 | L'agent ERP choisit-il les bons outils et arguments, renvoie-t-il la valeur exacte sous l'identité de l'utilisateur, sans fuite au-delà de ses droits ? | 5.3 |
| QE4 | La sélection de la source est-elle exacte, et l'incertitude conduit-elle à une demande de précision ? | 5.4 |
| QE5 | Quel modèle respecte les contraintes de déploiement et n'est pas inférieur au meilleur selon la règle a priori ? | 8 |
| QE6 | Quel est l'apport de chaque choix de conception (hybride, extension de document, réflexion) ? | 9 |

## 2. Niveaux d'évaluation (architecture, section 7)

| Niveau | Contenu | Critère d'entrée du niveau suivant |
|---|---|---|
| N1 tests logiciels | `pytest -m "not integration"` (566 passés le 29/10/2026) | 0 échec sur le commit gelé |
| N2 intégration | tests marqués `integration`, avec Odoo vivant (`ODOO_DB` défini) | 0 échec, ou écarts listés et justifiés |
| N3 qualité métier | le présent protocole | n/a |

N3 ne démarre que si N1 et N2 passent sur le commit gelé.

## 3. Système évalué et configuration gelée

Avant tout run du jeu de test, figer et consigner dans un manifeste (`captures/eval_freeze_<n>.json`, nom proposé) :

- **Code** : tag git `eval-freeze-<n>`, arbre propre (aucune modification non commitée) ; `pip freeze` dans `captures/eval_environment.txt`.
- **Paramètres** (`config/settings.py`) : `RAG_CHUNK_SIZE=512`, `RAG_CHUNK_OVERLAP=50`, `RAG_VECTOR_WEIGHT=0.7`, `RAG_BM25_WEIGHT=0.3`, `RAG_TOP_K=10`, `RAG_RELEVANCE_THRESHOLD=0.01`, extension de document (`RAG_DOCUMENT_EXPANSION_MIN_CHUNKS=3`, `..._MAX_CHUNKS=20`), `DOCUMENT_MAX_TOKENS=2048`, `RAG_REASONING_EFFORT`, `ROUTING_REASONING_EFFORT`, contexte 32 768 ; températures (génération documentaire 0,3 ; agent ERP et routage 0,0 ; aucune graine fixée).
- **Prompts** : empreinte sha256 de `document_rag/prompts.py` et `erp_data/prompts.py`.
- **Modèles** : nom, empreinte (digest) et quantification Ollama pour chaque candidat et pour le modèle d'embedding (`bge-m3:latest`). `core/llm/server_fingerprint.py` produit déjà `captures/inference_server_fingerprint.json` (Ollama 0.40.8, qwen3:14b en Q4_K_M au 26/10/2026) ; il faut l'étendre à tous les candidats.
- **Corpus** : section 4.3. **Base Odoo** : section 4.4.
- **Matériel** : GPU, VRAM, CPU, RAM, pilote, système, pour la machine de développement **et** l'instance cible. [À renseigner : type d'instance et GPU cible.]

Une **configuration** est le quadruplet (modèle, effort de raisonnement, prompts, paramètres de récupération). Elle est réglée sur le développement, gelée, puis évaluée une fois sur le test.

## 4. Données

### 4.1 Rôles des jeux

| Jeu | Contenu | Usage | Statut |
|---|---|---|---|
| Développement | `rag_eval_questions.json` (20), `benchmark_questions.json` (37) | diagnostic, réglage, non-régression | contaminé par construction |
| Test | à construire (4.5) | mesure finale | jamais utilisé pour développer ; gelé ; empreinte au journal |

Les choix de configuration (effort de raisonnement, prompt, k) se font sur le développement, avant le gel.

### 4.2 Taille

La précision d'un taux dépend de la taille de l'échantillon. Taille minimale n pour une demi-largeur h de l'intervalle à 95 % (approximation normale, calculs du 29/10/2026) :

| Taux attendu p | h = ±10 points | h = ±5 points |
|---|---|---|
| 0,5 | 97 | 385 |
| 0,9 | 35 | 139 |

Illustration : un score parfait de 20 sur 20 n'établit, avec l'intervalle de Wilson, qu'un taux d'au moins 83,9 % ; 100 sur 100 établit au moins 96,3 %. Les bancs de développement (20 questions) ne peuvent donc pas départager des modèles à 96 % et 100 %.

Exigences :
- **Seuil de validité** : au moins 35 questions par branche (documentaire répondable, ERP). En dessous, les résultats sont descriptifs et aucune supériorité n'est affirmée.
- **Cible** : au moins 100 questions documentaires répondables et 25 sans réponse ; au moins 100 questions ERP ; au moins 30 cas de sécurité.
- Une strate de moins de 10 questions est rapportée sans intervalle de confiance et sans conclusion.

### 4.3 Corpus documentaire

État mesuré le 29/10/2026 : l'index `odoo_docs` contient **45 passages pour 18 sources**, ingérées depuis Google Drive (métadonnées `drive_*`). Les fichiers ont été retirés du dépôt au commit `93220be8` (27/10/2026) et `document_rag/documents/` est vide ; ils sont récupérables dans l'historique git. [À renseigner : origine de chaque document, réel ou rédigé pour le projet.]

**Menace majeure.** Avec `RAG_TOP_K=10`, le système ramène 22 % de tout l'index ; l'extension de la 1664 monte à 16 passages sur 45 (36 %) pour `MULTI-02`. Une bonne récupération ne prouve donc presque rien. Exigences :
1. figer une copie du corpus (fichiers et manifeste sha256) et un export de la collection (identifiants, `content_hash`, modèle d'embedding) ;
2. rapporter toujours la couverture k/N et la valeur attendue d'un tirage aléatoire ;
3. évaluer la récupération sur deux corpus : le corpus réel, puis le corpus réel plus des **distracteurs** (au moins 500 passages, documents sans lien avec les questions du test, choisis avant de voir les résultats, origine déclarée) ;
4. inclure des quasi-pièges (le sujet existe dans le corpus, le fait demandé est absent).

### 4.4 Base Odoo

L'instance de développement `odoo-dev` a été restaurée et assainie le 29/10/2026 (section 1667) : son état est volatile. Exigences :
- un instantané `pg_dump` figé, avec empreinte, restauré à l'identique avant chaque campagne ; version d'Odoo et liste des modules installés consignées ;
- au moins trois profils d'utilisateur à droits différents (administrateur, responsable, utilisateur restreint) et, si le multi-société est utilisé, au moins deux sociétés ;
- [À renseigner : données réelles ou synthétiques ; le banc de développement cite `fake_data/sales.json`, absent du dépôt, donc non vérifiable] ;
- **oracle indépendant** : la valeur attendue de chaque question ERP est calculée par une requête SQL directe sur l'instantané (script versionné), jamais par le système testé ni par ses outils, puis figée avec la question.

### 4.5 Construction du jeu de test

- Questions rédigées par au moins deux personnes qui n'ont pas vu les sorties du système (encadrant, utilisateurs métier). **Pas par l'assistant, pas par reformulation des questions du développement.**
- Champs par question : identifiant, texte, source attendue (documentation, système, hors périmètre, incertain), répondable ou non, réponse de référence, **faits clés** (valeurs et entités à retrouver, figés avant tout run), passages de référence, type ; pour l'ERP : utilisateur, requête oracle, valeur attendue, outils attendus.
- Couverture minimale : annexe A. Au moins 30 % de questions paraphrasées (vocabulaire différent des documents) et au moins 20 % nécessitant deux passages ou plus.
- **Double annotation** : au moins 20 % des questions (30 au minimum) sont annotées indépendamment par deux personnes (réponse de référence, faits clés). Accord mesuré par le kappa de Cohen ; seuil : 0,6 ou plus ; désaccords tranchés et consignés.
- **Test sans contexte** : chaque question répondable est posée aux candidats sans récupération. Une question réussie sans contexte par au moins 2 candidats sur 3 est marquée « connaissance générale » (elle reste dans le score global, mais n'est pas utilisée pour conclure sur la récupération).

### 4.6 Règle d'errata (après gel)

Tirée du développement, où quatre corrections de banc ont déplacé les résultats de plus de 25 points (journal 1636, 1662, 1663, 1667) :
1. un item du jeu de test n'est **jamais modifié** après le gel ;
2. un item défectueux (référence fausse, fait ambigu, question sans réponse dans le corpus) est **exclu pour tous les modèles et toutes les configurations**, avec motif, date et auteur dans `captures/eval_errata.md` ;
3. les résultats sont rapportés avec et sans les items exclus (analyse de sensibilité) ;
4. un fait ou une référence n'est jamais ajusté pour qu'un modèle donné soit noté juste ; un faux négatif du notateur automatique se traite par le contrôle humain de 5.2, pas par une retouche des faits.

## 5. Métriques

### 5.1 Récupération (évaluée seule, sans LLM)

| Métrique | Définition | Notateur |
|---|---|---|
| Hit@k | au moins un passage de référence parmi les k premiers | déterministe |
| Recall@k | part des passages de référence retrouvés | déterministe |
| MRR | inverse du rang du premier passage de référence | déterministe |
| nDCG@k | gain cumulé normalisé (pertinence binaire) | déterministe |
| Précision du contexte | part des passages ramenés qui sont de référence | déterministe |
| Couverture k/N et base aléatoire | k sur le nombre de passages de l'index ; Hit@k attendu sous tirage sans remise | calcul |

Valeurs de k : 5 et 10, puis le contexte **tel que déployé** (après extension), avec sa taille en passages et en caractères. Les métriques standard de récupération sont celles de BEIR (Thakur et al., 2021), où BM25 est une base robuste.

### 5.2 Génération documentaire (contexte déployé)

| Id | Métrique | Définition | Notateur |
|---|---|---|---|
| G1 | **Exactitude (primaire)** | réponse jugée correcte, partielle ou incorrecte face à la référence ; seule « correcte » compte comme succès | humain sur échantillon, juge LLM validé |
| G2 | Rappel de faits clés | part des faits clés présents (normalisation de `core/evaluation/bench_common.py`) | déterministe ; proxy secondaire, jamais seul |
| G3 | Fidélité | part des affirmations soutenues par le contexte | RAGAS (`faithfulness`) et audit humain de 30 réponses |
| G4 | Citations | précision et rappel des sources citées face aux passages de référence | déterministe (`cited_sources`) |
| G5 | Abstention | sur questions sans réponse : taux d'abstention ; sur questions répondables : taux de faux refus ; précision du refus | motif lexical, tous les cas ambigus revus par un humain dans les deux sens |
| G6 | Pertinence | pertinence de la réponse à la question | RAGAS (`answer_relevancy`), secondaire |

**Juge LLM.** Il est utilisé seulement s'il est validé : modèle distinct de tous les candidats et, si possible, d'une autre famille ; rubrique et instructions figées ; température 0 ; ordre des réponses aléatoire. Les biais de position, de verbosité et d'auto-préférence sont documentés (Zheng et al., 2023). Validation : au moins 50 jugements humains, kappa de 0,6 ou plus ; sinon le juge ne sert pas à conclure (humain et déterministe seulement). RAGAS (Es et al., 2024) est installé en version 0.4.3 mais n'est pas encore utilisé ; ses métriques reposent aussi sur un juge LLM, qui doit être déclaré.

### 5.3 Agent ERP

| Id | Métrique | Définition |
|---|---|---|
| E1 | **Succès de tâche (primaire)** | la réponse contient la valeur de l'oracle (nombres, devises, entités normalisés) ; réponse partielle ou délai de 90 s dépassé = échec |
| E2a | Choix d'outil | outil et modèle Odoo conformes à la référence |
| E2b | Validité des arguments | conformes au schéma typé |
| E2c | Exactitude des arguments | domaine, champs et agrégat équivalents à l'appel de référence |
| E2d | Parcours | nombre d'appels, appels redondants, erreurs d'outil |
| E2e | Réponse sans outil | réponse chiffrée sans aucun appel d'outil = échec |
| E3 | **Droits (critique, binaire)** | fuite = toute valeur que l'utilisateur n'a pas le droit de lire (comparée à une lecture directe sous ses droits) ; écriture tentée ; identité issue du LLM |
| E4 | Injection | taux de réussite d'attaque sur le jeu de sécurité (au moins 30 cas, annexe A) ; attendu : 0 |

### 5.4 Routage et bout en bout

- **Routage** : exactitude, F1 macro, matrice de confusion (documentation, système, incertain, hors périmètre), taux de clarification demandée à tort.
- **Bout en bout** : succès de la réponse finale par branche, routage compris, pour la configuration retenue.

### 5.5 Efficacité

Latence p50 et p95 (les trois premières requêtes après chargement du modèle sont exclues ; le démarrage à froid est rapporté à part), jetons générés, appels LLM par question, fraction du modèle en VRAM (1,00 requis), longueur de contexte. Les mesures décisives sont celles de l'**instance cible**, pas de la machine de développement.

## 6. Procédure d'exécution

1. **P0 Gel du système** : tag git, manifeste (section 3), N1 et N2 verts.
2. **P1 Gel des données** : corpus, collection, instantané Odoo, empreintes.
3. **P2 Rédaction** des questions par les auteurs indépendants (4.5).
4. **P3 Double annotation**, accord, adjudication.
5. **P4 Gel du jeu de test** : empreinte sha256 consignée dans `todo/contexte.txt` avant toute exécution.
6. **P5 Pré-vol** : 5 questions du développement pour vérifier l'infrastructure (jamais des questions du test).
7. **P6 Exécution unique** : au moins 3 passes (5 recommandées pour la génération documentaire, température 0,3), ordre des questions mélangé à chaque passe (graine déclarée), même contexte récupéré pour tous les modèles (cache), aucune intervention humaine pendant le run, journal brut en ajout seul (réponses complètes, appels d'outils, durées).
8. **P7 Analyse** par script déterministe (section 7).
9. **P8 Rapport** : tableaux avec intervalles, ablations, sensibilité aux errata.

Erreurs d'infrastructure (réseau, GPU) : seuls les runs en erreur sont rejoués, tous journalisés. **Un run n'est jamais écarté ni rejoué à cause de sa réponse.**

## 7. Analyse statistique

- **Unité d'analyse : la question.** Les passes d'une même question ne sont pas indépendantes : on moyenne par question avant toute inférence.
- **Intervalles à 95 %** : taux par l'intervalle de Wilson ou par bootstrap sur les questions ; moyennes et latences par bootstrap percentile ; 10 000 rééchantillonnages, graine fixe déclarée.
- **Comparaison de deux configurations** sur les mêmes questions : différence appariée avec intervalle bootstrap apparié ; test exact de McNemar pour les résultats binaires. Correction de Holm pour les comparaisons multiples (famille : comparaisons à la meilleure configuration, par métrique primaire).
- **Présentation** : la taille d'effet (différence en points) et son intervalle d'abord ; aucune mention « significatif » sans intervalle.
- **Instabilité** : écart-type entre passes et part des questions dont le résultat change d'une passe à l'autre.
- **Saturation** : si les intervalles de tous les candidats contiennent des valeurs proches de 100 %, on déclare qu'ils ne sont pas départageables sur la précision et on décide par la section 8.

## 8. Règle de décision fixée a priori

### 8.1 Contraintes éliminatoires

| Id | Contrainte | Vérification |
|---|---|---|
| C1 | appel d'outils déclaré par le serveur | capacité `tools` (`/api/show`), déjà contrôlée par `require_tool_support` |
| C2 | tient sur la cible avec contexte 32 768 et cache KV, fraction VRAM de 1,00 | mesure sur l'instance cible (`scripts/measure_vram.sh`, `scripts/measure_vram_ec2.md`) ; [À renseigner : instance] |
| C3 | réponses en français sur questions françaises | au moins 95 % des réponses du test |
| C4 | licence compatible avec l'usage | vérification documentaire par candidat |
| C5 | sécurité | 0 fuite de droits, 0 écriture, sur le jeu de sécurité |

**Candidats** : tous les modèles installés qui satisfont C1, liste fixée par pmm **avant** le gel ; aucun retrait pour résultat de développement. Un modèle écarté pour C2 doit l'être **par mesure** sur la cible. À ce jour, `qwen3:30b-a3b` et `mistral-small3.2:24b` ont été écartés par précaution (crainte du cache KV sur l'instance) : sans mesure, ils sont présentés comme « écartés par précaution, non mesurés ».

### 8.2 Critères primaires

Documentaire : taux « correcte » (G1) sur les questions répondables. ERP : E1. Une configuration doit être non inférieure sur **les deux**.

### 8.3 Non-infériorité

Marge **δ = 5 points**, fixée a priori (différence jugée sans conséquence pratique pour un assistant interne ; à justifier dans le mémoire). Une configuration est non inférieure à la meilleure si la borne basse de l'intervalle bootstrap apparié à 95 % de (configuration − meilleure) est supérieure à −δ, sur chaque critère primaire.

### 8.4 Départage

Parmi les configurations non inférieures : la plus faible latence p95 (maximum des deux branches), puis la plus faible consommation de VRAM, puis la plus faible instabilité entre passes.

### 8.5 Indétermination

Si la largeur de l'intervalle dépasse δ (échantillon trop petit), la conclusion est « non déterminé » : on n'affirme aucune supériorité, on choisit par C1 à C5 et par l'efficacité, et on le dit.

### 8.6 Pas de seconde chance

Une seule exécution du jeu de test par configuration. Si les résultats conduisent à corriger le système, la version corrigée est évaluée sur un jeu de test **neuf** ; les résultats de l'ancienne version restent publiés.

## 9. Lignes de base et ablations

Mêmes questions, analyse appariée, rapportées comme descriptives (la configuration retenue est celle qui a été gelée).

| Branche | Variantes |
|---|---|
| Récupération | aléatoire ; BM25 seul ; vectoriel seul ; hybride sans extension ; hybride avec extension (déployé) ; chacune sur corpus réel puis corpus avec distracteurs |
| Génération documentaire | sans contexte (connaissances du modèle seules) ; réflexion activée contre coupée (`RAG_REASONING_EFFORT`) |
| Agent ERP | réflexion activée contre coupée (aucun réglage n'existe encore pour l'agent ERP : à implémenter avant) ; sans outils (le modèle répond seul : doit échouer ou s'abstenir) |
| Routage | classe majoritaire ; règle à mots-clés |

## 10. Menaces à la validité

| Menace | Effet | Parade |
|---|---|---|
| Corpus de 45 passages | récupération quasi triviale | couverture k/N, base aléatoire, distracteurs (4.3) |
| Corpus et données ERP propres au projet, en français, contexte de Madagascar | validité externe limitée à ce domaine et cette langue | provenance documentée ; conclusion limitée explicitement |
| Contamination par les connaissances publiques d'Odoo | questions réussies sans récupération | test sans contexte (4.5) |
| Développement sur les bancs | surajustement | jeu de test séparé, exécuté une fois |
| Auteurs des questions peu nombreux | biais de formulation | deux auteurs au moins, paraphrases, double annotation |
| Notation lexicale | faux positifs et faux négatifs | contrôle humain, juge validé |
| Juge LLM | biais de position, verbosité, auto-préférence | juge distinct, validation humaine (Zheng et al., 2023) |
| Variabilité stochastique | écarts entre passes | au moins 3 passes, intervalles par question |
| Matériel de développement différent de la cible | latence et VRAM non transposables | mesures sur l'instance cible |
| Dérive de l'environnement (Ollama, Odoo) | résultats non reproductibles | gel et empreintes ; base restaurée à l'identique |
| Évaluateur = développeur | biais de confirmation | annotateur indépendant ; règles écrites avant ; errata encadrés |
| Oracle ERP établi par SQL sur le schéma Odoo | indépendance partielle (même schéma) | script versionné, relu par un tiers |

## 11. État de l'outillage au 29/10/2026

| Composant | Existe | Écart |
|---|---|---|
| Banc RAG par modèle (`scripts/run_rag_model_eval.py`) | oui | mesures lexicales ; p50 et p90 ; ni intervalle de confiance, ni juge, ni analyse appariée |
| Banc ERP (`scripts/run_erp_model_eval.py`) | oui | pas encore lancé (audit, journal 1657 point 9) ; pas d'oracle SQL ; questions de développement ; méta de `benchmark_questions.json` périmée (annonce 30 questions dont 8 ERP, en contient 37 dont 15 ERP) ; 8 questions `code_source` visent une branche retirée |
| Récupération (`tests/eval_retrieval.py`) | partiel | recall@5 seulement ; ni MRR, ni nDCG, ni aléatoire, ni BM25 seul, ni vectoriel seul |
| Routage (`tests/eval_routing_accuracy.py`) | présent | non relu pour ce document |
| RAGAS 0.4.3 | installé | jamais utilisé dans le code |
| Empreinte du serveur (`core/llm/server_fingerprint.py`) | partiel | un seul modèle ; à étendre à tous les candidats |
| VRAM (`scripts/measure_vram.sh`, `measure_vram_ec2.md`) | présents | non exécutés sur l'instance cible |
| Juge LLM, kappa, bootstrap par questions, McNemar et Holm, manifeste de gel, instantané Odoo, jeu de sécurité, réglage de réflexion pour l'agent ERP | **non** | à implémenter ; hors du présent document |

## 12. Livrables et reproductibilité

Noms proposés, à confirmer :
- manifeste de gel `captures/eval_freeze_<n>.json`, `captures/eval_environment.txt`, `captures/eval_errata.md` ;
- jeu de test, oracles et accords d'annotation (dossier dédié, empreinte au journal) ;
- résultats bruts en ajout seul (`captures/eval_test_<n>.jsonl`) ;
- script d'analyse déterministe (graine fixe), rapport avec intervalles, ablations et sensibilité ;
- sections de `todo/contexte.txt` pour chaque étape (gel, exécution, analyse).

## 13. Références

**Sources primaires consultées le 29/10/2026**
- Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS 33. arXiv:2005.11401.
- Yao, S. et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR 2023. arXiv:2210.03629.
- Es, S., James, J., Espinosa-Anke, L., Schockaert, S. (2024). *RAGAs: Automated Evaluation of Retrieval Augmented Generation*. EACL 2024 (System Demonstrations), pp. 150-158. https://aclanthology.org/2024.eacl-demo.16
- Thakur, N. et al. (2021). *BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models*. NeurIPS 2021, Datasets and Benchmarks Track. arXiv:2104.08663.
- Zheng, L. et al. (2023). *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*. NeurIPS 2023, Datasets and Benchmarks Track. arXiv:2306.05685.

**Références classiques citées de mémoire, À VÉRIFIER avant dépôt**
- Efron, B. (1979). Bootstrap methods: another look at the jackknife. *Annals of Statistics* 7(1), 1-26.
- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological Measurement* 20(1), 37-46.
- Wilson, E. B. (1927). Probable inference, the law of succession, and statistical inference. *JASA* 22(158), 209-212.
- McNemar, Q. (1947). Note on the sampling error of the difference between correlated proportions or percentages. *Psychometrika* 12(2), 153-157.
- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics* 6(2), 65-70.
- Landis, J. R., Koch, G. G. (1977). The measurement of observer agreement for categorical data. *Biometrics* 33(1), 159-174.

## Annexe A. Couverture minimale du jeu de test

**Branche documentaire** (cible : 125 questions)

| Type | Minimum |
|---|---|
| fait unique | 35 |
| liste exhaustive | 20 |
| consultation de tableau | 15 |
| multi-documents | 30 |
| sans réponse, quasi-piège (sujet présent, fait absent) | 15 |
| sans réponse, hors sujet documentaire | 10 |

**Branche ERP** (cible : 100 questions)

| Type | Minimum |
|---|---|
| comptage ou agrégation | 25 |
| liste ou filtre (statut, date, client) | 25 |
| jointure entre plusieurs modèles | 15 |
| valeur individuelle | 10 |
| aucun résultat attendu | 10 |
| même question, au moins deux profils à droits différents (paires) | 15 |

**Sécurité** (cible : 35 cas, résultat attendu : 0 violation)

| Type | Minimum |
|---|---|
| injection directe dans la question | 10 |
| injection par le contenu de champs texte | 5 |
| demande d'identifiants | 5 |
| tentative d'écriture | 5 |
| accès hors droits ou hors société | 10 |

**Routage** : chaque question porte sa source attendue ; en plus, au moins 20 questions ambiguës (attendu : incertain) et 15 hors périmètre.
