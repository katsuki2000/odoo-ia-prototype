INTRO_PART3 = (
    "Après avoir mené l'analyse préalable des besoins et formalisé la conception conceptuelle et technique des composants "
    "d'intelligence artificielle, cette troisième partie est consacrée à la réalisation du système au sein de l'écosystème "
    "Odoo 17. Elle s'articule autour de quatre chapitres : l'environnement de mise en œuvre (Chapitre 7), le développement "
    "du module Odoo miro_ai et des moteurs documentaire et ORM (Chapitre 8), les tests et l'évaluation des résultats "
    "(Chapitre 9) et, en perspective, l'approche Code Intelligence, dont la réalisation reste partielle (Chapitre 10)."
)

BLOCKS = [
    ('h2', 'Chapitre 7. Environnement de mise en œuvre'),
    ('p', "Ce chapitre décrit l'environnement technique dans lequel MIRO AI a été développé et exécuté, l'organisation du dépôt "
          "de code et de sa configuration, ainsi que la procédure de mise en place sur un nouveau poste. L'objectif est la "
          "reproductibilité : le projet ne doit dépendre d'aucun chemin absolu ni d'aucun réglage propre à une machine."),
    ('h3', '7.1. Environnement technique'),
    ('p', "Le Tableau 37 recense les composants utilisés. L'ensemble tourne sous Linux (Debian) dans un environnement virtuel "
          "Python, et l'inférence est confiée à un serveur privé compatible avec l'API OpenAI (Ollama ou vLLM), sans repli vers "
          "un fournisseur d'IA externe."),
    ('table', 'Tableau 37. Composants de l\'environnement de développement et d\'exécution',
     ['Composant', 'Choix retenu', 'Rôle dans le système'],
     [
         ['Système d\'exploitation', 'Debian GNU/Linux', 'Poste de développement et serveur applicatif'],
         ['Langage', 'Python 3.11 en environnement virtuel (venv)', 'Backend IA, ingestion, outils de lecture'],
         ['ERP', 'Odoo 17 Community, installé depuis les sources', 'Instance cible et hébergement du module miro_ai'],
         ['Base de données', 'PostgreSQL 14 ou supérieur', 'Stockage des données d\'Odoo'],
         ['Interface de service', 'FastAPI exécuté par uvicorn', 'Middleware d\'orchestration et points d\'accès'],
         ['Orchestration', 'LangGraph', 'Classification, routage et vérification des réponses'],
         ['Serveur d\'inférence', 'Ollama ou vLLM sur un serveur privé', 'Génération de texte et calcul des embeddings'],
         ['Modèle de génération', 'qwen3:14b', 'Rédaction des réponses et choix des outils'],
         ['Modèle d\'embedding', 'bge-m3', 'Vectorisation des passages documentaires'],
         ['Base vectorielle', 'ChromaDB (stockage local persistant)', 'Index dense des passages'],
         ['Index lexical', 'rank_bm25 (BM25Okapi)', 'Recherche par mots-clés'],
         ['Gestion de versions', 'Git, dépôt GitHub', 'Historique des modifications'],
     ],
     [2300, 3300, 3760]),
    ('h3', '7.2. Organisation du dépôt et configuration'),
    ('p', "Le dépôt regroupe, dans un même ensemble versionné, le module Odoo, le backend et les moteurs de réponse. Chaque "
          "répertoire correspond à une responsabilité :"),
    ('b', 'api', "points d'accès FastAPI, authentification et traitement des demandes longues"),
    ('b', 'core', "graphe LangGraph principal, routage de la question et vérification finale, collecte des preuves"),
    ('b', 'document_rag', "ingestion, recherche et génération pour les documents internes"),
    ('b', 'erp_data', "outils typés de lecture des données d'Odoo"),
    ('b', 'odoo_addons/miro_ai', "module Odoo 17 : interface de conversation et client du backend"),
    ('b', 'code_intelligence', "analyse du code source d'Odoo (présentée au Chapitre 10)"),
    ('b', 'config, scripts, tests', "constantes de configuration, utilitaires d'installation et d'évaluation, tests automatisés"),
    ('p', "La configuration obéit à une règle simple. Le fichier d'environnement (.env) ne contient que ce qui change d'un poste ou "
          "d'un déploiement à l'autre : secrets, adresses du serveur d'inférence et de l'instance Odoo, emplacement des "
          "installations externes, chacun avec une valeur par défaut portable. Tout le reste (modèles, seuils, limites, "
          "comportement) est une constante du fichier config/settings.py. Les dépendances installées sont toutes consignées "
          "dans requirements.txt, et chaque modification du projet est inscrite dans un journal de travail horodaté "
          "(todo/contexte.txt), ce qui assure la traçabilité des décisions."),
    ('h3', '7.3. Procédure de mise en place'),
    ('p', "Le Tableau 38 résume les étapes d'installation sur un nouveau poste, telles que décrites dans le fichier README du projet."),
    ('table', "Tableau 38. Étapes de mise en place du système sur un nouveau poste",
     ['Étape', 'Action', 'Résultat attendu'],
     [
         ['1. Dépendances et dépôt', 'Installation des paquets système, clonage du dépôt, création du venv, installation de requirements.txt', 'Environnement Python reproductible'],
         ['2. Configuration', 'Copie de .env.example vers .env : adresse du serveur d\'inférence, mot de passe du compte de service Odoo', 'Secrets conservés hors du dépôt'],
         ['3. Odoo', 'Installation des sources 17.0, création de la base PostgreSQL, odoo.conf avec odoo_addons dans addons_path', 'Instance Odoo démarrable'],
         ['4. Modules', 'Installation de miro_ai et des modules métiers listés dans scripts/odoo_modules_to_install.txt', 'Modules disponibles dans Odoo'],
         ['5. Données de test', 'Exécution du script full_setup.py (société, journaux, utilisateurs, produits)', 'Instance de démonstration'],
         ['6. Index documentaire', 'Exécution de document_rag.ingestion.ingest_all', 'Base ChromaDB et index BM25 construits'],
         ['7. Démarrage', 'Lancement d\'Odoo puis de uvicorn (api.main:app)', 'Bouton MIRO AI visible dans la barre supérieure'],
     ],
     [2000, 4560, 2800]),

    ('h2', 'Chapitre 8. Développement des composants'),
    ('p', "Ce chapitre présente les composants effectivement développés : le module Odoo miro_ai, le backend d'orchestration, "
          "le moteur de recherche documentaire et les outils de lecture des données de l'ERP. Les choix de conception justifiés "
          "au Chapitre 6 n'y sont pas répétés ; on y décrit ce que le code réalise."),
    ('h3', '8.1. Module Odoo miro_ai'),
    ('p', "Le module miro_ai s'installe comme n'importe quel module Odoo 17. Il se compose des éléments suivants :"),
    ('b', 'Contrôleurs', "réception de la question, signature de la requête, transmission au backend et suivi de la tâche (fichiers main.py, ask_flow.py et backend_client.py)"),
    ('b', 'Modèles', "paramètres du module (adresse du backend, secret de signature) et journal d'audit des échanges (miro_ai_settings, miro_ai_log)"),
    ('b', 'Interface', "composant OWL accessible depuis la barre supérieure, gabarit XML, feuille de style et libellés traduits ; traduction française fournie dans le répertoire i18n"),
    ('b', 'Sécurité', "groupes et droits d'accès propres au module"),
    ('fig', "[À insérer : capture d'écran du bouton MIRO AI dans la barre supérieure d'Odoo et du panneau de conversation ouvert]",
     "Figure 8.1 — Interface de conversation du module miro_ai dans Odoo 17"),
    ('h3', '8.2. Backend d\'orchestration'),
    ('p', "Le backend FastAPI expose les points d'accès décrits au Tableau 36. La demande de réponse est asynchrone : le point "
          "d'accès de création de tâche renvoie immédiatement un identifiant avec le code 202, puis un second point d'accès "
          "permet de consulter l'état de la tâche jusqu'à la réponse complète. Des points d'accès complémentaires permettent de "
          "relancer l'indexation documentaire, de consulter son état, de déclencher un balayage planifié, de contrôler la santé "
          "du service et de lister les modules couverts."),
    ('p', "Pour chaque question, le graphe LangGraph choisit d'abord la source : le choix explicite de l'utilisateur est "
          "prioritaire ; à défaut, une classification détermine la source la plus probable, et le système demande une précision "
          "lorsque la confiance est insuffisante au lieu de choisir silencieusement. La question suit ensuite l'un des deux "
          "chemins (documentation ou système Odoo), les observations collectées sont rassemblées dans un dossier de preuves, "
          "puis une vérification finale précède la réponse."),
    ('h3', '8.3. Moteur de recherche documentaire'),
    ('h4', '8.3.1. Ingestion des documents'),
    ('p', "L'ingestion lit les fichiers PDF, DOCX, Markdown et texte. Les PDF numérisés peuvent être traités par reconnaissance "
          "optique de caractères (pytesseract et pdf2image). Chaque document est découpé en passages de 512 unités avec un "
          "recouvrement de 50, et chaque passage reçoit des métadonnées (position dans le document, empreinte du contenu). "
          "L'empreinte permet une ingestion incrémentale : seuls les fichiers modifiés sont réindexés. Un observateur de "
          "dossier réagit aux ajouts et modifications, et un balayage périodique (toutes les six heures) rattrape les "
          "changements manqués."),
    ('p', "Le corpus de démonstration compte dix-huit documents (six PDF, deux DOCX, trois fichiers Markdown et sept fichiers "
          "texte) couvrant les achats, la facturation, la clôture comptable, les notes de frais, les ressources humaines, la "
          "sécurité informatique et le support. En production, le corpus est destiné à vivre dans un dossier Google Drive "
          "partagé : un compte de service en lecture seule lit les dossiers approuvés, un corpus approuvé correspond à une "
          "collection, et la synchronisation supprime les passages dont le document n'est plus dans le périmètre."),
    ('h4', '8.3.2. Recherche hybride'),
    ('p', "La recherche combine une recherche vectorielle dans ChromaDB (embeddings bge-m3) et une recherche lexicale BM25 avec "
          "normalisation Unicode et suppression des mots vides français et anglais. Les deux classements sont fusionnés par "
          "Reciprocal Rank Fusion pondérée. Le jeu de candidats est volontairement large avant la sélection finale, les "
          "passages contigus des passages retenus sont ajoutés pour restituer le contexte, et les passages issus d'un "
          "document Drive qui n'existe plus sont écartés. Un reclasseur de type cross-encoder a été essayé puis retiré, ce qui "
          "a permis de supprimer la pile PyTorch des dépendances. Le Tableau 39 donne les paramètres effectifs."),
    ('table', "Tableau 39. Paramètres effectifs du moteur de recherche documentaire",
     ['Paramètre', 'Valeur', 'Remarque'],
     [
         ['Taille des passages', '512', 'Recouvrement de 50'],
         ['Modèle d\'embedding', 'bge-m3', 'Vecteurs denses, collection dédiée en 1024 dimensions'],
         ['Index lexical', 'BM25Okapi', 'Mots vides français et anglais'],
         ['Fusion', 'Reciprocal Rank Fusion', 'Poids 0,6 (vectoriel) et 0,3 (lexical)'],
         ['Passages retournés', '5 par défaut', 'Candidats : 20 fois ce nombre, au moins 100'],
         ['Extension du contexte', 'Passages contigus', 'Ajoutés après la sélection'],
     ],
     [2700, 2700, 3960]),
    ('h4', '8.3.3. Génération et vérification'),
    ('p', "Le modèle de génération reçoit les passages numérotés par des alias courts (S1, S2, ...) propres au tour de "
          "conversation. Les consignes lui imposent de citer les sources, de ne déclarer que les alias réellement utilisés, "
          "de restituer intégralement les listes, tableaux et étapes présents dans les passages, de signaler les "
          "contradictions entre documents et d'indiquer un niveau de confiance. Une vérification déterministe contrôle "
          "ensuite que les éléments des listes et tableaux des passages cités figurent bien dans la réponse, et calcule un "
          "taux de restitution."),
    ('fig', "[À insérer : capture d'une réponse documentaire avec ses sources citées et son badge de confiance]",
     "Figure 8.2 — Réponse documentaire avec citation des sources"),
    ('h3', '8.4. Lecture des données de l\'ERP'),
    ('p', "Les questions portant sur des valeurs actuelles (statut, nombre, liste, agrégation) sont traitées par sept outils "
          "typés de lecture, présentés au Tableau 40."),
    ('table', "Tableau 40. Outils typés de lecture des données d'Odoo",
     ['Outil', 'Fonction'],
     [
         ['orm_fields_get', "Décrire les champs d'un modèle"],
         ['orm_search', 'Retrouver des identifiants selon un domaine de recherche'],
         ['orm_read', "Lire des champs d'enregistrements connus"],
         ['orm_search_read', 'Rechercher et lire en une seule opération'],
         ['orm_search_count', 'Compter les enregistrements correspondant à un domaine'],
         ['orm_read_group', 'Agréger et regrouper (par jour, semaine, mois, trimestre, année)'],
         ['orm_name_search', 'Retrouver un enregistrement à partir de son nom'],
     ],
     [3000, 6360]),
    ('p', "Ces outils offrent plusieurs garanties. Aucune opération de création, de modification ou de suppression n'est "
          "exposée. Les entrées (nom de modèle, domaine, champs, tri, regroupement) sont validées par des expressions "
          "régulières et une liste fermée d'opérateurs. Le nombre de lignes retournées est plafonné par une constante de "
          "configuration. L'exécution se fait sous l'identifiant de l'utilisateur authentifié et dans le contexte de sa "
          "société, sans élévation de privilèges : l'identité ne provient jamais du modèle de langage. Chaque résultat est "
          "renvoyé sous forme structurée et horodatée."),

    ('h2', 'Chapitre 9. Tests et évaluation'),
    ('p', "Ce chapitre rend compte des vérifications effectuées. Il distingue les tests logiciels, qui établissent que le code "
          "fait ce qui est prévu, de l'évaluation de la qualité des réponses, qui ne s'en déduit pas. Un test logiciel réussi "
          "ne prouve pas la justesse métier des réponses sur toutes les instances Odoo 17."),
    ('h3', '9.1. Tests automatisés'),
    ('p', "Les tests, écrits avec pytest, couvrent le routage, la résolution des termes, les outils, la construction du graphe, "
          "l'ingestion et la recherche documentaires, et les outils de lecture ORM. Les tests d'intégration exigent une "
          "instance Odoo démarrée et des utilisateurs de test ; ils sont séparés des tests unitaires par un marqueur. "
          "Lors de la dernière exécution complète, le 27 octobre 2026, la suite a donné 1 036 tests réussis, 17 ignorés, "
          "9 échecs et 23 erreurs. Les 23 erreurs proviennent d'utilisateurs de test absents de l'instance (problème "
          "d'environnement, non de code). Parmi les 9 échecs, quatre étaient des tests devenus périmés après une "
          "simplification du code ; ils ont été corrigés, sans que la suite complète ait été rejouée depuis."),
    ('h3', '9.2. Banque de questions de référence'),
    ('p', "Une banque de 37 questions, répartie en quatre catégories (Tableau 41), sert à mesurer la proportion de réponses "
          "correctement sourcées et contenant les éléments attendus. L'objectif fixé est d'au moins 90 % de réponses correctes."),
    ('table', "Tableau 41. Composition de la banque de questions de référence",
     ['Catégorie', 'Questions', 'Ce que la catégorie vérifie'],
     [
         ['Documentaire', '10', 'Retrouver une procédure dans les documents indexés et la restituer avec ses sources'],
         ['Données ERP chiffrées', '15', 'Obtenir une valeur actuelle par les outils de lecture ORM'],
         ['Code source', '8', 'Expliquer un comportement établi par le code d\'Odoo'],
         ['Hors périmètre', '4', 'Signaler la limite au lieu d\'inventer une réponse'],
         ['Total', '37', ''],
     ],
     [2700, 1500, 5160]),
    ('ph', "[À compléter : résultat de tests/eval_rag.py (réponses correctes sur 37, par catégorie), à lancer avec Odoo et le serveur d'inférence en marche]"),
    ('h3', '9.3. Séries de conversation'),
    ('p', "Une série de dix questions métier (droits de validation, états d'un processus, circuit d'approbation d'un achat, "
          "question sur un sujet absent des documents) a été rejouée de bout en bout le 14 octobre 2026 avec deux profils : un "
          "administrateur et un employé ne disposant pas des droits de validation. Le second profil sert à distinguer un refus "
          "légitime d'un refus erroné. Les dix questions ont obtenu une réponse sans tentative invalidée, neuf par le chemin "
          "d'analyse du système et une par le chemin documentaire."),
    ('p', "La durée de traitement a varié de 44 à 116 secondes par question, soit une moyenne d'environ 90 secondes. Ce délai "
          "est très supérieur à celui d'un appel d'inférence simple évoqué à la section 6.4, car le chemin d'analyse enchaîne "
          "plusieurs appels d'outils et de modèle. Il constitue une limite d'usage actuelle."),
    ('h3', '9.4. Budget de contexte'),
    ('p', "Le modèle de génération dispose d'une fenêtre de 32 768 unités. Sur trois questions de test (achats, stock, ventes), "
          "les observations injectées ont occupé respectivement 38,4 %, 39,4 % et 21,1 % de cette fenêtre, sans qu'aucune "
          "coupe ni réduction ne soit nécessaire."),
    ('h3', '9.5. Limites de l\'évaluation'),
    ('b', '', "chaque question a été rejouée une seule fois, alors que les réponses du modèle ne sont pas déterministes"),
    ('b', '', "la latence du chemin documentaire n'a pas fait l'objet d'une mesure séparée"),
    ('b', '', "les tests d'intégration dépendent d'une instance Odoo et d'utilisateurs de test qui ne sont pas fournis avec le dépôt"),
    ('b', '', "la justesse métier n'a été relue manuellement que sur un échantillon de questions (voir Chapitre 10)"),

    ('h2', 'Chapitre 10. Perspectives : l\'agent Code Intelligence'),
    ('p', "Le temps imparti n'a pas permis de mener l'agent Code Intelligence au niveau de maturité d'une réalisation livrée. "
          "Il est présenté ici comme une perspective : on expose son approche, ce qui a été validé et ce qui reste à faire."),
    ('h3', '10.1. Problème et objectif'),
    ('p', "Un assistant fondé sur un modèle de langage peut formuler une réponse plausible sans qu'aucune source ne l'étaie, "
          "par exemple affirmer qu'un module est absent d'une instance parce qu'une recherche n'a rien retourné. "
          "Pour un utilisateur métier, une telle réponse est plus dangereuse qu'un aveu d'ignorance. Code Intelligence vise "
          "à répondre aux questions sur le fonctionnement réel d'une instance Odoo en s'appuyant sur le code, la "
          "configuration et, lorsque la question l'exige, les données de l'instance, et à signaler explicitement les limites "
          "de ce qu'il a pu établir."),
    ('h3', '10.2. Approche'),
    ('p', "L'approche repose sur quatre éléments. Un extracteur lit le code Python, les vues XML et les fichiers de droits des "
          "modules installés. Un graphe de connaissances relie modèles, champs, vues, boutons, menus, groupes, règles d'accès, "
          "états et méthodes. Des analyses déterministes (sans modèle de langage) calculent ce que le code établit : droits "
          "d'accès, chemins de navigation, états et transitions d'un processus, chaîne de surcharge d'une méthode, verrous de "
          "validation. Enfin un agent unique, qui ne dispose que d'un ensemble borné d'outils, enchaîne ces analyses "
          "et rédige l'explication, chaque affirmation devant s'appuyer sur une observation collectée."),
    ('p', "Sur l'instance de développement, le graphe actif compte 25 235 nœuds et 25 670 arêtes. Il couvre 288 des 289 modules "
          "déclarés installés, soit 17 452 fichiers source indexés ; le module dont le code source est absent est signalé "
          "comme écart de couverture. Les outils exposés à l'agent sont regroupés par famille de questions dans le Tableau 42."),
    ('table', "Tableau 42. Familles de questions et outils de Code Intelligence",
     ['Famille de questions', 'Outils exposés à l\'agent'],
     [
         ['Découverte et lecture du code', 'search_system, read_source_fragment'],
         ['Droits et visibilité', 'who_has_access_to, evaluate_record_rules, describe_navigation_path, button_execution_path, analyze_security_locks'],
         ['Approbations et processus', 'describe_workflow, analyze_method_override_chain, analyze_server_actions'],
         ['Saisie et validations', 'analyze_data_constraints'],
         ['Données actuelles', 'Outils de lecture ORM du Tableau 40'],
     ],
     [3000, 6360]),
    ('h3', '10.3. Principes de fiabilité'),
    ('b', 'Preuve avant affirmation', "une résultat de recherche sert à découvrir ; une affirmation s'appuie sur une inspection ou une lecture du code"),
    ('b', 'Code et exécution distingués', "le code montre les mécanismes déclarés ; seules les données de l'instance montrent l'effet pour un utilisateur donné"),
    ('b', 'Prudence sur les cibles', "un terme métier ambigu déclenche une demande de précision plutôt qu'un choix arbitraire"),
    ('b', 'Honnêteté sur la couverture', "une recherche vide n'est pas une preuve d'absence lorsque la couverture est incomplète"),
    ('b', 'Respect des accès', "le modèle de langage ne choisit ni l'utilisateur ni la société, et les lectures restent en lecture seule"),
    ('h3', '10.4. Illustration'),
    ('p', "À la question « demande d'achat », l'agent a décrit le processus de validation d'une demande dans un module "
          "personnalisé : seul un membre du groupe des gestionnaires d'achats ou un utilisateur d'une liste d'exceptions peut "
          "valider ; au-delà de 10 000 euros, seuls les utilisateurs de la liste restreinte le peuvent ; sinon un message "
          "d'erreur est affiché. Ces règles proviennent de la méthode de validation du module, dont la réponse cite le fichier "
          "et les lignes, ainsi que la chaîne de surcharge correspondante. L'état de la demande (brouillon, à valider, "
          "validé, refusé) et les deux méthodes qui l'écrivent sont également restitués."),
    ('fig', "[À insérer : capture de la réponse de MIRO à « demande d'achat » avec la section Sources]",
     "Figure 10.1 — Réponse de Code Intelligence sur la validation d'une demande d'achat"),
    ('h3', '10.5. État d\'avancement'),
    ('table', "Tableau 43. Bilan de Code Intelligence à la date de rédaction",
     ['Élément', 'État'],
     [
         ['Construction du graphe sur les modules installés', 'Validée : couverture de 288 modules sur 289 déclarés'],
         ['États et méthodes qui écrivent l\'état d\'un processus', 'Validés, correction apportée le 27 octobre 2026'],
         ['Chaîne de surcharge et verrous de validation', 'Validés sur des cas réels, avec citation du fichier et des lignes'],
         ['Chemin de navigation, champs et boutons d\'un modèle', 'Correction codée le 27 octobre 2026, à rejouer sur l\'instance'],
         ['Résolution d\'un terme métier vers le bon modèle', 'Partielle : 31 cibles exactes sur 48 questions (audit du 18 octobre 2026)'],
         ['Justesse des réponses relues le 22 octobre 2026 (achats, ventes, stock)', 'Contrastée : trois réponses exactes, six partielles, trois fausses, une sans réponse, les autres mêlant bonne conclusion et justification contaminée'],
         ['Refus en l\'absence de preuve', 'Insuffisant : une question sur les articles achetés a reçu une réponse sans source affirmant que le module Achats est absent'],
     ],
     [4300, 5060]),
    ('h3', '10.6. Suite envisagée'),
    ('b', '', "transformer l'absence de preuve en refus ou en demande de précision, au lieu d'une réponse rédigée de mémoire"),
    ('b', '', "relier les questions de données aux outils de lecture ORM, sous l'identité du demandeur"),
    ('b', '', "améliorer la résolution des termes métier vers les modèles Odoo, mesurée sur une banque de questions à vérité établie"),
    ('b', '', "rejouer un protocole d'évaluation figé sur des instances et des cas de test définis avant tout objectif chiffré de précision"),
    ('b', '', "étendre l'approche aux versions plus anciennes d'Odoo rencontrées chez d'autres clients, qui exigeront de nouveaux extracteurs"),
]
