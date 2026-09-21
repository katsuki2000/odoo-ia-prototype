# Plan d'implementation -- 4.4 : contrat de couverture d'outils + trajectory recall

Statut : PLAN uniquement, aucun code touche. Suite a la recherche externe (section 860 de
`contexte.txt`) et au "vas y" de pmm en reponse a la question ouverte "transformer 4.4 en
plan d'implementation detaille". Reste a mandater explicitement avant toute implementation.

## 1. Etat actuel (verifie par lecture directe du code, pas suppose)

- `predispatch.py::run_predispatch_chain(ctx)` appelle 11 `dispatch_X(ctx)` en sequence
  (security_locks, server_actions, override_chain, who_has_access_to, evaluate_record_rules,
  security_distinction_guard, describe_workflow, inheritance, module_level_ui_inquiry,
  button_execution_path, analyze_data_constraints). Chaque predicat matche-et-force son(ses)
  outil(s), ou ne fait rien silencieusement.
- `DispatchContext` (`context.py`) n'a AUCUN champ enregistrant quel(s) predicat(s) ont ete
  evalues ni lesquels ont matche -- si aucun des 11 ne matche, rien ne le signale, l'agent
  passe en ReAct libre sans trace de cette transition.
- `reasoning_trace.jsonl` loggue deja chaque hop (`tool_name`, `tool_args`,
  `observation_summary`) -- aucun record de niveau "decision de routage".
- `scripts/run_bloc_n1_benchmark.py` calcule deja, PAR QUESTION, `tool_coverage_ok` /
  `missing_tools` (`expected_tools` du banc vs `tools_used` reellement invoques) -- c'est deja
  une version ad hoc du "trajectory recall", jamais agregee au niveau du banc entier, et sans
  distinction "route forcee par predispatch" vs "route choisie librement par le LLM".

## 2. Schema du contrat de couverture

### 2a. Log binaire de routage -- primitive de base, peu invasive

Ajouter a `DispatchContext` :
```python
matched_dispatchers: List[str] = field(default_factory=list)
```
Chaque `dispatch_X(ctx)` (11 sites, patch mecanique repete) ajoute son propre nom a
`ctx.matched_dispatchers` quand son predicat matche, en plus de forcer l'outil comme
aujourd'hui. Apres `run_predispatch_chain(ctx)`, un log explicite (nouveau
`record_type: "routing_decision"` dans `reasoning_trace.jsonl`, un par tour de question) :
```python
if ctx.matched_dispatchers:
    trace_logger.log_routing(trace_id, matched=ctx.matched_dispatchers, open_routing=False)
else:
    trace_logger.log_routing(trace_id, matched=[], open_routing=True)
```
Remplace le "saut silencieux" actuel par une trace explicite -- correspond directement au
principe du research doc ("chaque echec est un reroutage journalise ou une escalade
explicite, jamais un saut silencieux"). Aucun changement de comportement fonctionnel : la
route reste identique, seule la tracabilite est ajoutee.

### 2b. Contrat declaratif (2e etape, seulement si 2a s'avere insuffisant)

Ne PAS dupliquer `expected_tools` du banc de questions (verite-terrain humaine, reste
separee). Plutot : un registre `CAPABILITY_TOOL_CONTRACT: Dict[str, Set[str]]` associant
chaque predicat de dispatch a l'ensemble minimal d'outils qu'il DOIT produire pour etre
considere couvert -- auto-verification deterministe independante du LLM : si
`dispatch_security_locks` matche mais qu'`analyze_security_locks` n'apparait jamais dans
`ctx.tool_observation_tools` pour ce tour, c'est une anomalie interne au dispatch (bug de
cablage, pas un probleme de couverture LLM) a logger separement de l'ouverture de routage.

## 3. Instrumentation du banc N1

- Agregat en fin de run (`run_bloc_n1_benchmark.py`) :
  - Trajectory recall micro = somme(|expected inter used|) / somme(|expected|) sur tout le
    banc filtre.
  - Trajectory recall macro = moyenne de `tool_coverage_ok` (deja booleen par question).
- Croiser avec `routing_decision` (2a) par question dans le rapport JSON/MD : les questions a
  faible couverture sont-elles correlees a `open_routing=True` (signal : renforcer le
  predispatch) ou pas (signal : le predispatch force bien le bon outil, mais le LLM ne
  l'exploite pas correctement -- probleme de synthese, pas de routage) ? Cette distinction
  n'existe dans aucune donnee actuelle du projet.
- Transforme "chaque nouvelle formulation revele un trou" (etat actuel, constate empiriquement
  toute cette session) en regression chiffree suivie dans le temps.

## 4. Explicitement hors perimetre de ce mandat (pistes separees, non tranchees)

- **4.1** (chevauchement d'intervalles / citation-as-constraint, empecher le LLM d'emettre des
  blocs de code du tout) -- changement du contrat de sortie du LLM, portee bien plus large,
  mandat separe.
- **4.2** (abstention structurelle / etendre `assess_evidence_sufficiency` a la qualification
  de la conclusion CI, pas seulement au routage RAG) -- deja identifie comme piste au tour
  precedent (voir section 860), mandat separe.
- **4.5** (typage des questions, cascade normalisation->regex->rapidfuzz->defaut-sur) -- la
  cascade existe deja en gros (chaque `dispatch_X` EST un predicat regex/mots-cles cible) ;
  reste a verifier si un "defaut sur explicite" existe deja en cas de non-match -- a priori
  non, et 2a comble ce trou par la meme occasion (l'ouverture de routage devient visible au
  lieu d'etre silencieuse).

## 5. Risques / a valider avant tout code

- Toucher 11 fonctions `dispatch_X` dans un fichier charge sur CHAQUE question du banc :
  changement mecanique mais fort rayon d'impact -- suite complete + rejeu cible obligatoires
  avant tout commit, meme standard qu'aujourd'hui (846-849).
- Nouveau `record_type` dans `reasoning_trace.jsonl` : verifier qu'aucun parseur existant
  (`scripts/_diag_*.py` notamment) ne suppose un schema fixe de ce fichier avant d'y ajouter
  un type de ligne.

## 6. Sequencement propose

1. **2a seule d'abord** -- log binaire, non-invasif, zero changement de comportement
   fonctionnel, juste de la tracabilite. Mandat de portee reduite, risque faible.
2. Mesurer sur le banc N1 complet la proportion de questions en `open_routing=True`
   aujourd'hui, et croiser avec les echecs deja catalogues (813-860) -- donnee jamais
   disponible formellement jusqu'ici.
3. Decider ENSUITE, sur la base de mesures reelles plutot que de la litterature seule, si 2b
   (contrat declaratif) et l'agregat trajectory recall (section 3) valent la peine.

Principe general : pas de nouvel index, pas de refonte -- une seule nouvelle primitive (log
binaire de routage) qui rend mesurable ce qui est aujourd'hui invisible, avant de decider s'il
faut aller plus loin.
