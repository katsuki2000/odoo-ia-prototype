# Plan d'implementation -- 4.1 : citation-as-constraint (fin de la fabrication de code)

Statut : PLAN uniquement, aucun code touche. Mandat pour l'implementation a demander
separement. Suite a la recherche externe (section 860) et au choix de pmm de commencer par
4.1 plutot que 4.2/4.5.

## 1. Etat actuel (verifie par lecture directe du code)

- Le prompt de synthese (`prompts.py`, fonction de build du prompt final) contient deja une
  `anti_fabrication_rule` (section 812/813) : instruction textuelle "NEVER write out a Python
  code block ... unless that exact code already appears, verbatim, in one of the observations
  above". C'est deja une tentative de contrainte -- mais seulement au niveau du prompt, donc
  non fiable (observe directement aujourd'hui : ACC-Q2 round 2, le LLM a quand meme ecrit un
  bloc de code paraphrase/reconstruit malgre cette instruction).
- Le garde `dispatch_guards.py::verify_citations` (section 814) est le filet de securite
  post-hoc : detecte un bloc ```...``` fenced, cherche une citation `file://...#Lx-Ly` scopee
  dans une fenetre de 500 caracteres autour, et si absente, AJOUTE un avertissement
  "SOURCING NON VERIFIE" -- mais laisse le bloc invente tel quel dans la reponse montree a
  l'utilisateur. Observe directement aujourd'hui (ACC-Q2, 3 rejeu, section 847) : le garde se
  declenche correctement, mais l'utilisateur voit quand meme le code fabrique, juste flagge.
- L'outil `read_source_code` (introspection.py) encapsule deja
  `read_precise_source_code(filepath, line_start, line_end, max_lines=200)` -- lit les VRAIES
  lignes du fichier reel (avec resolution de chemin relatif/absolu deja geree, cap 200 lignes,
  et marquage `SENSITIVE_BYPASS_MARKER` sur les lignes a pattern sensible). C'est exactement
  l'utilitaire de substitution dont 4.1 a besoin -- deja ecrit, deja teste, reutilisable tel
  quel.

## 2. Principe : substitution, pas juste detection

Ne PAS inventer une nouvelle syntaxe de citation -- le format `file:///...#Lstart-Lend` est
deja le format universel de citation dans tout le repo (`format_file_link`, partout). Au lieu
de detecter puis avertir, la fonction post-hoc doit VERIFIER PUIS CORRIGER :

1. Detecter chaque bloc `\`\`\`...\`\`\`` fenced dans la reponse finale (regex deja existante
   dans `dispatch_guards.py`).
2. Chercher les citations `file://...#Lstart-Lend` dans une fenetre autour du bloc (reutilise
   `_code_block_has_nearby_scoped_citation`, elargir eventuellement la fenetre -- voir section
   3 du plan 4.4-adjacent deja discute avec pmm, garde separement note).
3. Si UNE OU PLUSIEURS citations du MEME fichier sont trouvees : calculer l'union des plages
   (min ligne, max ligne), appeler `read_precise_source_code(filepath, min_line, max_line)`, et
   REMPLACER le contenu du bloc fenced par le texte reellement lu -- quel que soit ce que le
   LLM avait ecrit. Cas concret deja observe aujourd'hui (ACC-Q2) : le LLM citait separement
   L1987 et L1991 mais avait fusionne/invente un bloc combinant les deux -- l'union (L1987-1991)
   aurait produit le VRAI extrait (5 lignes, y compris le has_group entre les deux), strictement
   plus fidele que ce que le LLM avait ecrit.
4. Si les citations trouvees pointent vers PLUSIEURS fichiers differents, ou si aucune citation
   n'est trouvee, ou si `read_precise_source_code` retourne une erreur (fichier introuvable,
   plage > 200 lignes) : SUPPRIMER le bloc entierement et le remplacer par une note en texte
   clair ("code non disponible dans les observations pour cette reponse -- voir citation(s) X").
   Ne jamais laisser un bloc invente visible, meme avec avertissement.

Consequence directe : l'avertissement actuel "SOURCING NON VERIFIE" (qui reste dans
`SourcingVerificationResult.uncited_code_blocks` pour les AUTRES cas -- citations XML,
fichiers non scopes) perd sa raison d'etre specifiquement pour les blocs de code : soit le
bloc devient reel (substitue), soit il disparait (strip). Le champ `uncited_code_blocks` du
guard peut rester pour la telemetrie/tests existants, mais son effet sur la reponse montree a
l'utilisateur change.

## 3. Ou implementer

Nouvelle fonction dans `dispatch_guards.py` (meme fichier que `verify_citations`), par exemple
`substitute_or_strip_code_blocks(final_answer: str) -> str`, appelee dans `postprocess.py`
AVANT `verify_citations` (ou en remplacement du traitement actuel de
`uncited_code_blocks` dans le pipeline de post-traitement -- a verifier precisement l'ordre
d'appel actuel avant de coder). Reutilise directement `read_precise_source_code` (aucune
nouvelle IO a ecrire).

## 4. Verification / tests

- Reproduction directe : reinjecter le texte exact du round 2 d'ACC-Q2 (deja capture dans
  cette session, section 847) dans la nouvelle fonction et verifier qu'elle produit soit le
  vrai extrait L1987-L1991 substitue, soit un strip propre -- pas le texte fabrique tel quel.
- Tests existants a revoir avant tout commit : `test_bug4_synthesis_anti_hallucination.py`,
  `test_j14_sourcing_guard.py`, `test_bug1_xml_id_citation_wiring.py`,
  `test_bug2_backfill_scoped_output_wiring.py` -- certains asserent probablement le
  comportement ACTUEL (avertissement + bloc conserve), a mettre a jour vers le nouveau
  comportement (substitution/strip) plutot que casse silencieuse.
- Suite cible (`-k "sourcing or citation or guard or bug4 or bug1 or bug2 or j14"`) puis suite
  complete, meme standard qu'aujourd'hui (846-863).

## 5. Risques / a valider avant de coder

- `dispatch_guards.py` est sur le chemin de CHAQUE reponse finale (comme `access_guards.py`
  aujourd'hui) -- fort rayon d'impact, suite complete obligatoire.
- Ambiguite multi-fichiers (section 2, point 4) : decision deliberement conservatrice (strip
  plutot que deviner) -- a confirmer que c'est le bon compromis avant de coder, plutot qu'une
  tentative plus fine de matching par fichier le plus proche.
- Le prompt actuel (anti_fabrication_rule) reste utile en complement (reduit le nombre de cas
  ou la substitution/strip doit intervenir) -- ne pas le retirer, la contrainte mecanique
  s'ajoute au-dessus, ne le remplace pas.
- Question ouverte, pas tranchee ici : faut-il aussi elargir la fenetre de proximite de
  citation (500 car., deja discutee avec pmm ce jour, laissee en l'etat faute de donnees) en
  meme temps que ce chantier ? Recommandation : NON, faire 4.1 seul d'abord, la substitution
  rend la fenetre de detection moins critique de toute facon (un faux negatif de proximite
  devient juste un strip un peu trop agressif, pas une hallucination qui passe).

## 6. Sequencement propose

1. Ecrire `substitute_or_strip_code_blocks`, la brancher dans le pipeline post-traitement.
2. Reproduire le cas ACC-Q2 round 2 en dur pour valider le comportement avant tout rejeu reel.
3. Mettre a jour les 4 fichiers de test existants identifies en section 4.
4. Suite cible puis complete.
5. Rejeu reel (ACC-Q2 en priorite, deja un cas connu de bloc invente) x2-3, confirmer que le
   bloc affiche est desormais soit reel soit absent, jamais fabrique.

Principe general, identique a 4.4 : deplacer la contrainte du prompt (deja tente, insuffisant
seul) vers le code (verification + correction mecanique), sans reecrire l'architecture -- une
seule fonction nouvelle, reutilisant un outil de lecture deja existant et deja teste.
