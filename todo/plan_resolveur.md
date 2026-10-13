# Plan R -- Resolveur metier : le graphe borne, le LLM choisit (brouillon v2, 13/10/2026)

Statut : brouillon valide par pmm le 13/10/2026 (section 1278) ; seuils R6 encore a fixer ; rien d'applique au code. A valider par pmm avant tout mandat. Echeance de reference : livraison du 20/10/2026
(`todo/perimetre_livraison_20_octobre.md`). Lie a P4 / E1 (section 1227) et aux points (4)-(5) de la section 1277.
Nommage : phases du plan = PR0 a PR4 ; systemes experimentaux E1 = R0 a R6 (R6 = R4 + arbitrage LLM, a creer).
v2 : integre une relecture externe, chaque point verifie dans le code local (branche `main`, HEAD e42dadf).

## 1. Constats lus dans le code

1. `resolve_business_term` : mention exacte -> [alias si `use_static_aliases`] -> dense (decide seul si score >= 0.25 et ecart
   >= 0.10) -> fuzzy + departage deterministe + arbitrage LLM borne. Un dense confiant n'est jamais verifie par le LLM.
2. L'arbitrage LLM est une liste fermee (hors liste = rejet) ; sa shortlist combine fuzzy et candidats semantiques si un client LLM
   est fourni. Sorties admises aujourd'hui : un candidat exact ou `NONE`. `AMBIGU` n'existe pas : il est traite comme hors liste.
3. Trois appelants, deux comportements : `core/routing/routing.py:103` (`llm=None`), `agent/loop.py:592` (LLM passe),
   `agent/tool_helpers.py:86` (sans LLM).
4. `conftest.py` force `RESOLVER_SEMANTIC_RETRIEVAL_ENABLED=false` (autouse) : les 2 tests `plan_steps` en echec mesurent exact +
   fuzzy, sans dense ni arbitrage. A requalifier, pas a « corriger » par un retour des alias.
5. Le harnais E1 n'a pas de client LLM : R0 a R4 mesurent la generation de candidats, jamais le choix LLM.
6. Calibrage E1 : 8 cas, `status: seed_incomplete`. Cible deja inscrite en 1227 : >= 20 cas par famille, >= 120 au total, seconde
   instance `en_US` ouverte. `frozen_cases.json` : 249 cas, tous `held_out`.
7. Mesure dense deja faite (sondes /tmp, section 1277) : sur 4 formulations de « conges », `hr.leave` n'est dans aucun top 6.
   Preuve negative sur le dense seul uniquement.
8. Aucune etape deterministe de libelle metier exact : `exact_mention.py` ne traite que les noms techniques de modeles et de
   modules (les libelles d'instance ne servent qu'aux heuristiques de rarete de `matching.py` et au dense). « Conges » -> `hr.leave`
   n'est donc pas garanti sans alias.
9. Metriques E1 (`metrics.py`) : `recall_at_k` mesure le classement, pas la decision ; `silent_false_resolution` se calcule sur
   `candidates[0]`, pas sur le choix rendu ; `clarify_correct` est vrai des qu'il y a >= 2 candidats distincts (propriete des
   candidats, pas une vraie demande de precision) ; `run.py` ne charge que le calibrage.
10. Contradiction D1 : `config.json` D1 contient `held_out_recall_at_5_R4_ge_R0_minus_points`, alors que le `held_out` doit rester
    intact jusqu'a un passage unique. Et `run.py` ne calcule rien sur le `held_out`.
11. `card_node_types` (config E1) inclut deja Model, Menu, Field, Method, Group, Rule, Button : les mesures E1 portent deja sur ces
    types. Ce qui n'existe pas, c'est leur exploitation en production : `ResolvedConcept` ne rend que modeles et modules.

## 2. Principe

- Le graphe (lexique d'instance, BM25, BGE-M3, fusion RRF) **genere des candidats** ; il ne decide pas.
- Le LLM (Qwen3) **choisit dans une liste fermee** de candidats annotes (libelle d'instance, module, description, source du
  libelle) ou repond `NONE` / `AMBIGU`. Toute autre sortie = invalide = aucune resolution automatique, jamais de choix par defaut.
- `NONE`, `AMBIGU` ou sortie invalide -> clarification avec 2 ou 3 libelles metier de l'instance, sans noms techniques.
- Aucune table d'alias manuelle requise. Un libelle d'instance exact et unique decide sans LLM (regle a creer, constat 8).
- Le prompt dit que l'instance prime sur la connaissance d'Odoo ; chaque candidat porte son module (standard / OCA / specifique).

## 3. Phases (chacune = un mandat, une validation, un journal)

### PR0 -- Rendre la mesure possible (aucun changement de comportement MIRO)
- M1 : `DenseCardIndex.build` ecrit le cache apres chaque lot ; `run.py` persiste le resultat de chaque systeme des qu'il termine.
  Test hermetique (embedding factice qui echoue au milieu : la seconde construction ne recalcule que les cartes manquantes).
- M2 : client LLM injectable dans le harnais E1 + systeme R6, avec le contrat `NONE`/`AMBIGU`/invalide. Amendement a 1227 :
  journalise et fige avant tout calcul.
- M3 : metriques de decision, definies **avec leurs denominateurs avant calcul** :
  recall du candidat correct dans la liste (@1/@5/@10) ; decision correcte (choix rendu = attendu) ; faux choix silencieux calcule
  sur le choix rendu, parmi les cas resolus et parmi tous les cas ; clarification correcte stricte (MIRO demande vraiment) sur les
  cas ambigus ou absents ; taux de recours au LLM, latence, erreurs d'appel LLM et d'embeddings.
- M4 : calibrage. Decision de pmm requise : (a) viser la cible 1227 (>= 120 cas, >= 20 par famille, instance `en_US`) ou (b) une
  tranche partielle de ~60 cas, etiquetee « calibrage partiel », utilisable pour deboguer R6 mais **pas** pour la decision D1
  (risque d'une confiance artificielle).
  DECIDE par pmm (13/10/2026) : (b) calibrage partiel d'abord ; completer vers 120 avant la decision D1. Verite terrain par oracle Odoo ou relecture humaine, jamais
  deduite d'un systeme compare. Aucun cas pris dans les `held_out`. Inclure `adversarial_custom` (modele ou libelle renomme).
- Sortie : tableau R0..R4 + R6 sur le calibrage, par famille et par langue.
- Requalifier les 2 tests `plan_steps` ; reecrire `test_j6_context_validation` sans figer les langues actives.

### PR1 -- Decision (criteres ecrits avant calcul)
- D1 a D3 de `config.json` repris, sauf la clause `held_out` de D1 : retiree par amendement (DECIDE par pmm le 13/10/2026, section
  1278), a appliquer dans `config.json` et a journaliser avant tout calcul. D1 se decide sur le calibrage seul (>= 120 cas) ; le
  `held_out` n'est touche qu'en PR4.
- Pour R6 (seuils a fixer par pmm avant de lancer) : faux choix silencieux de R6 <= celui de R4, meme cas, meme definition ;
  decision correcte sur les cas non ambigus ; clarification stricte attendue sur les cas ambigus et absents.
- Si D1 echoue : le resolveur reste en l'etat, la limite est documentee, pas de retour aux alias sans decision explicite.

### PR2 -- Implementation (seulement si PR1 est favorable)
- Regle deterministe de libelle exact : normaliser (casse, accents, langue demandee) ; un seul modele -> resolu sans LLM ; plusieurs
  -> clarification ; aucun -> candidats puis arbitrage. Tests : « Conges » -> `hr.leave` alias desactives ; deux objets de meme libelle.
- Contrat d'arbitrage `NONE` / `AMBIGU` / invalide / panne LLM : quatre tests distincts, quatre statuts distincts dans `diagnostics`.
- Un seul point d'entree, appele avec le meme LLM par routage, boucle et `tool_helpers` ; resultat conserve dans l'etat de session.
- Retirer ou requalifier le « dense decide seul » (constat 1).
- Cache : cle = question normalisee + empreinte du graphe/instance + langue + version de configuration du resolveur ; invalide si
  modele LLM, prompt ou contrat de sortie changent.
- Panne BGE-M3 ou LLM : visible dans `diagnostics`, resolution degradee signalee ou clarification, jamais de choix par defaut.

### PR3 -- Cibles hors modeles en production (menus, champs, boutons, groupes)
- Les mesures E1 couvrent deja ces types (constat 11). PR3 n'est lance que si D2 passe et consiste a faire rendre ces cibles par
  `ResolvedConcept`, meme principe, memes garde-fous.

### PR4 -- Un seul passage held_out
- Configuration figee, protocole gele rejoue tel quel, sans toucher cas ni seuils. Aucun reglage apres ce passage.

### Note (13/10/2026, section 1281) -- index dense de production
- E1 reste sur une matrice numpy en memoire (cosinus exact). Chroma ou matrice pour un index dense de production sur les cartes du
  graphe : a trancher apres PR1, selon les besoins de persistance, de mise a jour incrementale et de filtre par type de noeud.

## 4. Risques et garde-fous
- Fuite du `held_out` : tout reglage se fait sur le calibrage ; un echec held_out n'autorise aucun reglage sur ce meme jeu.
- Cout : arbitrage seulement sans libelle exact unique ; taux de recours et latence mesures en PR0 (M3).
- Biais « modele qui connait Odoo » : famille de surcharge/renommage sur `adversarial_custom`.
- Echeance du 20/10 : seules PR0 et PR1 sont realistes avant ; PR2 seulement si PR1 est favorable. Sinon la livraison documente que
  la resolution des termes ambigus passe par clarification.
- Ce brouillon n'est pas dans `perimetre_livraison_20_octobre.md` ; il vit ici tant que pmm ne l'a pas figé.

## 5. A executer par pmm (long ou dependant du tunnel)
Runs E1 (`python -m code_intelligence.evaluation.e1.run --systems ...`), suite pytest complete, reconstruction du graphe,
passage held_out. 
