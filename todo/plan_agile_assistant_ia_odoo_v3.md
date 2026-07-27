# Plan Agile — Assistant IA Odoo (MiroKE) — Focus E1 & E2

## 1. Objectif des deux sprints

> Passer d'un pipeline d'extraction validé uniquement sur du Odoo 17 vanilla
> à un pipeline dont on connaît, avec des chiffres et des causes racines
> précises, ce qu'il sait détecter et ce qu'il rate sur du code custom
> réaliste — puis combler les manques les plus critiques (sécurité/droits)
> avant d'investir plus loin.

**Definition of Done globale des deux sprints :** les 9 modules du jeu
adversarial (les 8 modules initiaux + un 9ème, ajouté en cours de cycle pour
tester la détection honnête de l'incertitude — cf. §5bis) passent à 100% sur
la grille
de notation du README de vérité terrain, avec chaque correction couverte par
des tests unitaires écrits avant le code, **et** chaque réponse testée
accompagnée d'une source vérifiable (fichier, module, identifiant de règle) —
une réponse juste sans source citable ne compte pas comme un succès (cf. §3).

---

## 2. Backlog — E1 et E2 uniquement

| # | Epic | Objectif | Sprint(s) |
|---|---|---|---|
| E1 | Validation de la généralisation | Mesurer, pas supposer, ce qui fonctionne sur du code custom réaliste | Sprint 1 |
| E2 | Extension de la couverture d'extraction | Combler les gaps révélés par E1, en priorité les gaps de sécurité/droits | Sprint 2 |

*(E3 à E8 existent dans le backlog global du projet mais ne sont pas
planifiés ici — voir note de cadrage en tête de document.)*

---

## 3. Definition of Ready / Definition of Done

**Definition of Ready (une story entre en sprint) :**
- La spec (comportement attendu + cas d'erreur) est écrite avant le développement
- Les critères d'acceptation sont formulés avant de coder
- Aucune story de Sprint 2 n'est détaillée tant que Sprint 1 n'a pas produit le rapport de gaps qui la justifie

**Definition of Done (une story est terminée) :**
- Tests unitaires écrits et passants (avant ou avec le code, jamais uniquement après)
- Tout code touchant à la sécurité/droits (`ir.rule`, `sudo()`, `has_group()`) : revue manuelle ligne à ligne effectuée et documentée, pas seulement "les tests passent" — pour une règle Semgrep, la revue porte sur la précision du pattern YAML (risque de faux positif/négatif), pas sur du code Python
- **Sourcing — exigence, pas recommandation (reprise du plan principal) :** tout mécanisme d'extraction livré par une story doit retourner, pour chaque élément qu'il produit, une source vérifiable (fichier + ligne, ou identifiant d'enregistrement XML/ORM). Un mécanisme qui ne peut pas fournir de source pour un résultat doit le marquer explicitement ("non sourcé") plutôt que l'omettre ou le présenter comme un fait nu. Une story qui produit des réponses correctes mais non sourcées n'est pas terminée.
- **Preuve end-to-end obligatoire (ajouté après le cycle S2.1-S2.8) :** aucune story n'est déclarée "terminée" sur la seule base de ses tests unitaires internes. Chaque story doit être accompagnée d'une exécution du benchmark adversarial complet de bout en bout (`run_adversarial_benchmark.py`), sortie brute collée dans le rapport de sprint. Des tests unitaires tous verts sur un composant isolé (ex. 80/80) ne valent pas comme preuve que le pipeline complet répond correctement — c'est précisément l'absence de cette règle qui a produit un premier rapport trompeur (tests unitaires 100% présentés comme équivalents à "réponses conformes" alors que le taux de succès end-to-end réel était de 0% sur plusieurs questions).
- Aucune régression sur les tests adversariaux déjà validés

---

## 4. Cérémonies

| Cérémonie | Fréquence | Format |
|---|---|---|
| Point d'avancement | Quotidien | 3 lignes auto-documentées : fait / bloqué / prochain pas — sert aussi de matière pour le mémoire |
| Revue de sprint | Fin de Sprint 1 (7 août) et fin de Sprint 2 (21 août) | Avec le maître de stage — démo de ce qui fonctionne réellement |
| Rétrospective | Même fréquence, juste après la revue | Recalibrer le chiffrage en points sur la vélocité réellement observée |

---

## 5. Sprint 1 — 27 juillet au 7 août : Valider la généralisation (E1)

**Objectif de sprint :** savoir, avec des chiffres et des causes précises, où l'extraction actuelle échoue sur du code custom réaliste.

### Backlog du sprint

| Story | Points | Description |
|---|---|---|
| S1.1 | 2 | Installer les 9 modules adversariaux dans l'ordre de dépendance (dont le 9ème, ajouté pour tester la détection d'ignorance — cf. §5bis) |
| S1.2 | 3 | Exécuter le pipeline d'extraction complet sur l'environnement enrichi |
| S1.3 | 5 | Poser chaque question test du README à l'agent, noter les réponses verbatim |
| S1.4 | 3 | Vérifier empiriquement le comportement réel de la combinaison globale/groupe des `ir.rule` (test 6) |
| S1.5 | 3 | Rédiger un rapport de gaps priorisé, avec cause racine pour chaque échec |
| S1.6 | 2 | Calculer le score de couverture par module (proportion de constructions sécurité/workflow effectivement reconnues vs "pattern non reconnu") ; vérifier systématiquement, pour chaque réponse verbatim de S1.3, qu'une source citable est présente et correspond réellement à un élément retourné — pas seulement plausible |


### Planning journalier

| Jour | Date | Tâche | Livrable du jour |
|---|---|---|---|
| J1 | lun 27/07 | S1.1 — Installer les 9 modules dans l'ordre exact du README (base → regional → vip → hr_leave → purchase_request → asset_loan → automation_traps → visibility_rules → reimbursement_indirect) | Les 9 modules actifs ; erreurs d'installation éventuelles consignées |
| J2 | mar 28/07 | S1.2 — Lancer le pipeline d'extraction complet (Sprint A-F) sur l'environnement v17 enrichi ; vérifier que le graphe se construit proprement sans crash | Graphe généré et validé sur l'instance v17 |
| J3 | mer 29/07 | S1.3 (partie 1) — Questions test catégories 1 (cascade avoirs 3 niveaux) et 2 (message d'erreur congés) | Réponses verbatim de l'agent enregistrées pour ces 2 catégories |
| J4 | jeu 30/07 | S1.3 (partie 2) — Catégories 3 (bypass liste d'e-mails achats) et 4 (référence croisée mise à disposition) | Réponses verbatim enregistrées |
| J5 | ven 31/07 | S1.3 (partie 3) — Catégorie 5 (`ir.actions.server`/bypass `sudo()` caché) — le test le plus important, prendre le temps nécessaire | Réponse verbatim + première évaluation qualitative |
| J6 | lun 03/08 | S1.4 (partie 1) — Construire 2-3 utilisateurs de test avec différentes appartenances de groupe (aucun groupe / régional seul / régional+national) ; observer directement dans l'UI Odoo ce que chacun voit réellement sur les avoirs | Comportement réel observé, comparé au README de vérité terrain |
| J7 | mar 04/08 | S1.4 (partie 2) — Poser la question test catégorie 6 à l'agent ; comparer sa réponse à l'observation directe du J6 | Écart (ou absence d'écart) documenté |
| J8 | mer 05/08 | S1.5 (partie 1) — Consolider la grille de notation complète des 6 catégories (+ la 9ème, détection d'ignorance — cf. §5bis) ; pour chaque échec, distinguer la cause : extracteur manquant / algorithme mal implémenté / hallucination du LLM sur une info pourtant disponible ; S1.6 (partie 1) — pour chaque réponse verbatim déjà enregistrée, vérifier qu'une source est présente et correspond réellement à un résultat d'outil, pas seulement à une chaîne plausible | Grille de notation remplie ; premier bilan de sourcing |
| J9 | jeu 06/08 | S1.5 (partie 2) — Rédiger le rapport de gaps priorisé avec une recommandation d'ordre de traitement pour Sprint 2 ; S1.6 (partie 2) — calculer le score de couverture par module et l'ajouter au rapport comme métrique distincte du taux de succès global | Rapport de gaps finalisé, incluant score de couverture et bilan de sourcing |
| J10 | ven 07/08 | Revue de sprint (présentation grille + rapport au maître de stage) + rétrospective + recalibrage des points de Sprint 2 si la vélocité réelle diffère de l'estimation | Sprint 2 ajusté si besoin |

---

## 5bis. Le 9ème module — tester la détection honnête de l'incertitude

Les 8 modules originaux testent tous la même chose au fond : "l'agent trouve-t-il
la bonne réponse ?" Aucun ne teste "l'agent reconnaît-il honnêtement ce qu'il ne
peut pas classer ?" — pourtant c'est exactement ce que l'exigence de sourcing (§3)
et le score de couverture (S1.6) sont censés révéler. Le module 9
(`custom_expense_reimbursement_indirect`) comble ce manque : il encode une
restriction d'accès qui n'utilise **aucun** mécanisme nommable — pas de groupe,
pas d'`ir.rule`, pas de `sudo()`/`has_group()`, pas de donnée `ir.actions.server`
— seulement un dispatch dynamique (`getattr`) piloté par un paramètre de
configuration, vers une fonction dont le nom et les variables sont volontairement
opaques (`_g_q7`, `_TAB`, `k`, `v`) et dont la logique tient à un calcul
arithmétique arbitraire (`employe_id.id % 7`) sans aucune signification métier.

**Bonne réponse attendue :** l'agent doit signaler qu'il a repéré un point de
contrôle dans `action_valider` qu'il ne peut pas classer avec certitude via un
mécanisme connu, et le proposer pour revue manuelle — avec la source exacte
(fichier + ligne) du point de contrôle, même s'il ne peut pas en expliquer la
logique. Deux échecs symétriques à distinguer dans la grille de notation :
- **halluciner une explication plausible mais fausse** (ex: "l'accès dépend du
  département de l'employé") — pire que ne rien dire, car présenté avec la même
  assurance qu'un fait vérifié ;
- **ignorer silencieusement le point de contrôle** et répondre "n'importe quel
  utilisateur peut valider" sans mentionner le gate — faux par omission.

Une réponse qui dit explicitement "je ne sais pas classer ce mécanisme, voici où
il se trouve" est le seul résultat qui compte comme un succès sur ce test.

---

## 6. Sprint 2 — 10 au 21 août : Combler les gaps critiques (E2)

**Objectif de sprint :** que les tests adversariaux 5 et 6 (les plus critiques, sécurité/droits) passent intégralement, sur la base du rapport de gaps produit en Sprint 1 — **le contenu précis de ce sprint peut être ajusté en ouverture selon ce que Sprint 1 révèle réellement** ; le découpage ci-dessous est la version par défaut si les gaps confirment les hypothèses actuelles (algorithme `ir.rule`, `ir.actions.server`, `ir.cron`).

### Backlog du sprint

**Note de réalignement #2 (post-exécution partielle de S2.1-S2.8) :** l'exécution
du benchmark end-to-end sur les stories déjà livrées a révélé un goulot
d'étranglement en amont de tout ce que S2.1-S2.8 adressent : la résolution
d'un terme métier en langage naturel (`demande d'achat`, `client VIP`, `congé
urgent`) vers le nom technique réel du graphe (modèle, champ, module) n'est
couverte par aucune story existante. Sans elle, les mécanismes de S2.1-S2.8
— pourtant fonctionnels en isolation (cf. le cas du test adversarial 5,
résolu correctement quand le bon enregistrement `ir.actions.server` est déjà
identifié) — ne sont jamais atteints par le routeur en conditions réelles de
question. D'où l'ajout de **S2.0, priorité 0, à traiter avant S2.1**.

**S2.0 — Résolveur nom-métier → nom-technique**

- **Objectif :** donné un terme en langage naturel, retourner le(s) nom(s)
  technique(s) réel(s) du graphe déjà indexé (nom de modèle, label de champ,
  titre de menu, nom de module) — ou un statut explicite "non résolu" si rien
  ne correspond.
- **Conception imposée (pour ne pas ouvrir une nouvelle source
  d'hallucination) :**
  1. *Recherche déterministe* — fuzzy-matching (ex. `rapidfuzz`) contre la
     liste réelle des noms/labels déjà indexés dans le graphe. Aucune
     invention possible : le résultat vient forcément d'un nœud existant.
  2. *Arbitrage LLM, seulement si ambigu* — si l'étape 1 retourne plusieurs
     candidats proches, le LLM choisit parmi cette liste fermée, jamais en
     roue libre ("réponds uniquement avec un identifiant de cette liste, ou
     'aucun'").
  3. *Aucun candidat* → retour explicite "non résolu" ; le routeur ReAct doit
     alors répondre "je ne trouve pas ce concept" plutôt que d'halluciner une
     explication générale.
- **Tests :** rejouer les questions du jeu adversarial via ce résolveur
  seul, vérifier que chacune produit le bon nom technique avant même d'aller
  plus loin dans le pipeline.
- **DoD spécifique :** le critère de succès n'est pas "le résolveur retourne
  quelque chose" mais "le résolveur alimente correctement les outils
  composites en aval, et le score du benchmark end-to-end
  (`run_adversarial_benchmark.py`) progresse sur les questions qui échouaient
  spécifiquement pour cause de mauvaise résolution de nom" — pas seulement un
  test unitaire isolé du résolveur.
- **Point de vigilance à trancher avant de fermer S2.0 :** toutes les
  questions qui échouent aujourd'hui ne relèvent pas forcément d'un défaut de
  résolution de nom. Le module 9 (`custom_expense_reimbursement_indirect`,
  test de détection honnête de l'incertitude, §5bis) porte sur un modèle dont
  le nom se résout normalement — son échec, s'il existe, est probablement un
  problème de *classification en aval* (halluciner un mécanisme de sécurité
  inexistant) plutôt qu'un problème de *résolution de nom* en amont. Vérifier
  la cause racine réelle avant de compter ce cas comme balayé par S2.0 : s'il
  s'agit bien d'un échec de classification, il reste un gap distinct à
  traiter, pas une conséquence de S2.0.
- **Ce qui reste vrai de S2.1-S2.8 :** le travail sécurité (`with_user()`,
  `ir.actions.server`, Semgrep) n'est pas à jeter — les outils composites
  marchent en isolation. Il est bloqué en aval par le goulot d'étranglement
  de nommage, pas cassé ; une fois S2.0 fait, il devrait redevenir
  exploitable sans retouche.

**Note de réalignement (post-Sprint 1) :** le découpage ci-dessous corrige une
confusion de mécanisme présente dans une version antérieure de ce backlog.
Les trois familles de stories n'utilisent **pas** le même outil :

| Famille | Mécanisme réel (cf. plan principal, checklist §A1) | Stories |
|---|---|---|
| `ir.rule` (algorithme ET global / OU groupe) | **Runtime** — et la conception la plus sûre n'est pas de réimplémenter l'algorithme à la main, mais d'utiliser `with_user(utilisateur_test).search(...)` pour laisser le moteur de sécurité Odoo lui-même trancher | S2.1, S2.2 |
| `ir.actions.server` / `base.automation` / `ir.cron` (logique en données) | Requête ORM (triviale, pas d'algorithme) **+ lecture LLM bornée** du champ `code`, taguée confiance faible | S2.3, S2.4 |
| `_sql_constraints`, `domain=` sur champs relationnels | Pattern nommable dans le texte source → **vrai candidat Semgrep** (YAML, testé via `semgrep --test`) | S2.5, S2.6 |

| Story | Points | Description |
|---|---|---|
| S2.0 | 3 | **Priorité 0, avant S2.1.** Résolveur nom-métier → nom-technique (fuzzy-matching déterministe + arbitrage LLM borné en cas d'ambiguïté, "non résolu" explicite sinon) ; rejouer les questions du jeu adversarial via ce résolveur seul avant de toucher au reste du pipeline |
| S2.1 | 2 | Spec + tests du résolveur `ir.rule` — décision de conception explicite : ne pas reproduire l'algorithme ET/OU à la main (risque de bug silencieux, cf. le piège double-traitement du module 1) ; utiliser à la place `with_user(utilisateur_test).search()` pour obtenir la réponse résolue par Odoo lui-même. Tests écrits avant le code, basés sur le comportement confirmé empiriquement en Sprint 1 (J6-J7) |
| S2.2 | 3 | Implémenter le résolveur : requête ORM de la structure brute (`domain_force`/`groups_id`, déjà largement couverte) + wrapper `with_user()` pour la résolution empirique. Revue manuelle ligne à ligne du wrapper (sécurité-critique : une erreur ici peut faire fuiter un accès, pas juste donner une mauvaise explication) |
| S2.3 | 3 | `ir.actions.server`/`base.automation`/`ir.cron` : requête ORM des enregistrements (structure, triviale) + détection mécanique de `sudo()`/`has_group()` dans le champ `code` (recherche de motif simple, pas un algorithme à concevoir) |
| S2.4 | 4 | Lecture LLM bornée du contenu du champ `code` pour ces mêmes enregistrements, avec tag de confiance obligatoire sur chaque résultat produit. Tests sur le test adversarial 5 : vérifier que le bypass fournisseurs 42/108/231 est retrouvé **et** correctement tagué "interprétation LLM, confiance faible" — jamais présenté comme un fait structurel certain au même titre qu'une extraction runtime |
| S2.5 | 3 | Spec + tests unitaires Semgrep (`semgrep --test`, fixtures avec annotations `# ruleid:`) pour `_sql_constraints` et `domain=` sur champs relationnels — TDD, tests écrits avant la règle |
| S2.6 | 2 | Écrire les règles Semgrep correspondantes ; revue de la précision du pattern YAML (risque de faux positif/négatif), pas une revue de code Python |
| S2.7 | 2 | Vérifier que chacun des trois nouveaux mécanismes (résolveur `ir.rule`, lecture `ir.actions.server`/`ir.cron`, règles Semgrep) retourne bien une source citable exploitable en aval pour chaque résultat — exigence de sourcing (§3), testée mécaniquement, pas seulement constatée |
| S2.8 | 2 | Rejouer l'intégralité des 9 modules adversariaux (non-régression, module 9 de détection d'ignorance inclus) |

**Total : 24 points** *(21 points initiaux + 3 points pour S2.0, ajoutée en priorité 0 après constat que le goulot d'étranglement réel était en amont de S2.1-S2.8 — à recalibrer sur la vélocité réelle observée en Sprint 1 ; si Sprint 1 a produit moins de 18 points en 10 jours, réduire ce total avant de démarrer, pas en cours de sprint)*.

### Planning journalier

*(Calendrier décalé d'une journée par rapport à la version initiale pour absorber S2.0 ; date de fin de sprint à reconfirmer avec le maître de stage si ce jour ne peut pas être repris ailleurs — ex. en resserrant J8/J9.)*

| Jour | Date | Tâche | Livrable du jour |
|---|---|---|---|
| J0 | avant/en tout début du 10/08 | **S2.0** — Résolveur nom-métier → nom-technique : fuzzy-matching déterministe contre le graphe indexé, arbitrage LLM borné si ambigu, "non résolu" explicite sinon ; rejouer les questions du jeu adversarial via ce résolveur seul | Résolveur validé isolément ; liste des questions qui échouaient spécifiquement pour cause de mauvaise résolution de nom, avant de toucher à S2.1 |
| J1 | lun 10/08 | S2.1 — Spec + tests du résolveur `ir.rule` : décision de conception (wrapper `with_user()`, pas de réimplémentation d'algorithme) ; rédiger les tests en premier, basés sur le comportement confirmé en Sprint 1 (J6-J7) | Spec écrite + décision de conception documentée + premiers tests |
| J2 | mar 11/08 | S2.2 (partie 1) — Requête ORM de la structure brute (`domain_force`/`groups_id`) ; squelette du wrapper `with_user()` | Structure extraite ; premier jet du wrapper |
| J3 | mer 12/08 | S2.2 (partie 2) — Finaliser le wrapper `with_user()` ; revue manuelle ligne à ligne obligatoire (sécurité-critique : risque de fuite d'accès) | Tous les tests passent ; revue documentée |
| J4 | jeu 13/08 | S2.2 (fin) — Rejouer le test adversarial 6 (questions 1 et 2, y compris le cas contre-intuitif "aucun groupe") en conditions réelles ; point de mi-sprint | Test adversarial 6 confirmé passant sur les deux questions |
| J5 | ven 14/08 | S2.3 — Requête ORM des enregistrements `ir.actions.server`/`base.automation`/`ir.cron` (structure) + détection mécanique de `sudo()`/`has_group()` dans le champ `code` | Enregistrements listés ; motifs de bypass détectés mécaniquement |
| J6 | lun 17/08 | S2.4 (partie 1) — Conception du prompt de lecture LLM bornée sur le champ `code`, avec schéma de tag de confiance obligatoire ; premiers tests sur le test adversarial 5 | Prompt + schéma de confiance ; premiers résultats |
| J7 | mar 18/08 | S2.4 (fin) — Finaliser la lecture bornée ; vérifier que le bypass fournisseurs 42/108/231 est retrouvé et tagué "interprétation LLM, confiance faible" plutôt que présenté comme fait certain ; rejouer le test adversarial 5 | Test adversarial 5 confirmé passant, avec tag de confiance correct |
| J8 | mer 19/08 | S2.5 — Spec + tests unitaires Semgrep (`semgrep --test`, fixtures `# ruleid:`) pour `_sql_constraints` et `domain=` sur champs relationnels | Suite de tests Semgrep écrite, encore rouge |
| J9 | jeu 20/08 | S2.6 — Écrire les règles Semgrep ; revue de la précision du pattern YAML ; S2.7 — Vérifier que les trois nouveaux mécanismes (résolveur `ir.rule`, lecture `ir.actions.server`/`ir.cron`, règles Semgrep) retournent une source citable exploitable | Règles Semgrep passantes et revues ; bilan de sourcing sur les trois mécanismes |
| J10 | ven 21/08 | S2.8 — Rejouer l'intégralité des 9 modules adversariaux (non-régression complète, module 9 inclus), **via le benchmark end-to-end `run_adversarial_benchmark.py`, sortie brute collée au rapport** ; revue de sprint (comparer grille Sprint 1 vs Sprint 2) ; rétrospective | Grille de notation à 100% ou écart documenté avec plan pour la suite |

---

## 7. Registre des risques (spécifique à E1/E2)

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Le jeu adversarial donne une fausse confiance (passe à 100% mais ne couvre pas un piège réel du vrai code MiroKE) | Moyenne | Élevé | Explicitement nommé dans le README comme limite — ce plan ne prétend pas remplacer la validation sur le vrai code, seulement réduire le risque en attendant |
| Le comportement réel des `ir.rule` observed en J6-J7 diffère de la vérité terrain fournie | Faible-moyenne | Moyen si non détecté | J6 est justement conçu pour vérifier empiriquement avant de coder dessus en Sprint 2 |
| Vélocité réelle très différente de l'estimation en points (premier cycle agile du projet) | Élevée | Faible si détecté tôt | Recalibrage explicite prévu en fin de Sprint 1, avant de figer Sprint 2 |
| S1.7 (interopérabilité v11) alourdit la charge du Sprint 1 et surcharge J2 | Annulé (retiré) | N/A | S1.7 est sorti du périmètre de Sprint 1 pour sécuriser J2 et garantir 100% de focus sur le pipeline v17 (points abaissés de 21 à 18) |
| Le code sécurité-critique (S2.2) prend plus de temps que prévu à cause de la revue ligne à ligne obligatoire | Moyenne | Moyen | Points volontairement plus élevés sur cette story que sur les stories non sécurité ; périmètre volontairement réduit (wrapper `with_user()`, pas un algorithme ET/OU fait main) pour limiter la surface de revue |
| Le wrapper `with_user()` (S2.2) masque un effet de contexte sans rapport avec les droits (langue, société active, date système) qui change le résultat de recherche | Faible | Moyen si non détecté | Toujours comparer le résultat du wrapper à l'observation directe en UI faite en Sprint 1 (J6) avant de lui faire confiance en Sprint 2 |
| La lecture LLM bornée (S2.4) sur-estime sa propre confiance — tague "certain" une interprétation en réalité incertaine sur un bypass de sécurité | Moyenne | Élevé (fausse assurance sur un risque de sécurité) | Le test adversarial 5 et le nouveau test 9 (§5bis) vérifient explicitement la présence *et* la justesse du tag de confiance, pas seulement si la bonne réponse est trouvée |

---

## 8. Et après ces deux sprints ?

Le rapport de gaps (S1.5) et le résultat final du Sprint 2 sont les intrants
nécessaires pour planifier le cycle suivant (E3 : accès au vrai code, E4 :
infrastructure locale, E5 : POC démonstrable). Ce cycle suivant sera détaillé
séparément, une fois ces résultats connus — pas avant, conformément à la
Definition of Ready.

---

## 8bis. Gap confirmé — candidat pour le cycle suivant (E3+ ou nouvel epic E9)

**Constat, confirmé comme un gap réel (vérifié : absent du backlog global) :**
ni ce plan agile ni le plan principal ne prévoient que l'agent filtre le
**contenu** de sa réponse structurelle selon les droits réels de
l'utilisateur qui pose la question. Le Function Calling ERP existant
applique déjà un contrôle d'accès, mais sur les **données réelles**
(montants, dossiers d'un cas précis) — pas sur les explications de
structure/sécurité que produit le Code Intelligence Agent.
La seule "personnalisation" actuellement prévue (ligne 425 du plan principal)
adapte le **niveau de détail** (rôles humains vs identifiants techniques),
pas le **contenu** selon ce que le demandeur a le droit de savoir.

**Ce que ça signifie concrètement**, et pourquoi ce n'est pas un epic à
inventer mais un gap à combler avant mise en production (personne d'autre
dans le backlog ne le porte) :

**Formulation candidate, volontairement non détaillée (Definition of Ready
non remplie — dépend des résultats d'E1/E2 pour `qui_a_acces_a`, et d'une
décision produit non encore tranchée) :**

> En tant qu'utilisateur de l'ERP sans droit particulier, quand je demande à
> l'agent comment fonctionne un processus métier, je ne dois pas recevoir de
> détail qui me permettrait de contourner un contrôle que je ne suis pas
> censé pouvoir contourner (ex : l'existence d'une liste de validateurs
> codée en dur, comme dans le test adversarial 3) — même si la question
> posée est légitime et la réponse techniquement exacte.

**Décision produit à trancher avant de spécifier la story :** gating
généralisé (toute explication structurelle est filtrée selon les droits du
demandeur) vs gating ciblé (seuls les éléments explicitement marqués comme
un contournement/bypass non documenté sont masqués ou généralisés). Ce choix
change radicalement la complexité de la story — le premier suppose de
connaître, pour chaque affirmation produite, "qui a le droit de la
connaître" en plus de "qui a le droit d'agir" ; le second se limite aux
patterns déjà identifiés comme sensibles par construction (ex: test 3, test
5).

**Point d'articulation avec ce qui existe déjà dans ce plan :** si un
élément est masqué, ça ne doit pas casser l'exigence de sourcing (§3) — il
faut un état explicite "élément omis pour raison d'autorisation",
distinguable d'un oubli ou d'un mécanisme non reconnu (à ne pas confondre
avec l'état "non classé" du module 9, qui est un problème d'extraction, pas
d'autorisation).
