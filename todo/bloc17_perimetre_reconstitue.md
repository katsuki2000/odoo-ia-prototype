# Bloc 17 — Périmètre reconstitué (10/09/2026)

**Avertissement** : ce document n'est PAS la source originale. Le fichier
`todo/bloc17_jour1_perimetre.md`, cité par le code et les tests comme la
référence du "Jour 1" (choix du périmètre + critère de triage
FOUND/EMPTY/NOT_FOUND), est introuvable sur ce poste. Ce qui suit est une
reconstitution a posteriori, déduite exclusivement de code déjà écrit et
fonctionnel (docstrings, tests, structure), pas d'un souvenir de la décision
produit originale. À confirmer ou corriger par Trunk avant de faire foi.

## Objectif du bloc

Répondre à la sous-partie **statiquement dérivable** des questions
"comment faire pour X" / "où se trouve X" côté utilisateur final Odoo :
retrouver le **chemin d'interface** (menu → action → vue → bouton) pour
atteindre un modèle ou déclencher une transition, en réutilisant le
sous-graphe Menu/Model/Button déjà construit par l'extraction
(`ir.ui.menu`, `ir.actions.act_window`, boutons de vue formulaire).

**Périmètre explicitement exclu** (docstring `navigation_path.py`) :
aucune analyse OWL/JavaScript — seul le déclaratif XML/Python statique
compte, cohérent avec le reste du projet (`architecture.md`, PARTIE 7
"Suggestion 5" de `plan.md` : périmètre JS/OWL non tranché, resté hors
scope ici aussi).

## Découpage en jours (déduit des docstrings de test, pas d'une source
écrite du plan)

| Jour | Contenu | État constaté ce tour |
|---|---|---|
| Jour 1 | Choix du périmètre + critère de triage à 3 verdicts (FOUND / EMPTY "aucun chemin UI" / NOT_FOUND) | Décision déjà actée dans le code (`QueryStatus`), mais le document source manque |
| Jour 2-3 | Moteur déterministe `describe_navigation_path()` | Fait, testé (`test_bloc17_navigation_path.py`, 9/9 verts) |
| Jour 4 | (a) Câblage `@tool` LangChain + `record_evidence()` (Bloc B2) ; (b) `QuestionIntent.NAVIGATION_HOWTO` (classification + routage) | (a) déjà fait et testé ; (b) manquait, fermé ce tour (Section 646) |
| Jour 5+ / Étage 2 | Aucune trace trouvée nulle part sur le disque | Non commencé, existence même non confirmée |

## Composants livrés (vérifiés sur disque, tous fonctionnels)

- `code_intelligence/deterministic/navigation/navigation_path.py` —
  `describe_navigation_path(G, model_name, button_label_or_name="", user_groups=None)` :
  - `NOT_FOUND` : le modèle n'est pas dans le graphe.
  - `EMPTY` : le modèle existe mais aucun `ir.ui.menu` ne l'ouvre — verdict
    honnête ("aucun chemin UI"), pas une erreur à masquer.
  - `FOUND` : breadcrumb complet (racine → feuille), xml_id du menu,
    groupes requis, délégation à `button_execution_path()` si un bouton
    est demandé, disponibilité calculée pour un demandeur donné
    (`available_to_requester`).
  - Préfère un menu non restreint à un menu restreint quand plusieurs
    menus ouvrent le même modèle.
- `code_intelligence/ci_agent_node/tools/structure.py::describe_navigation_path`
  — wrapper `@tool`, retourne une chaîne (contrat LangChain), enregistré
  dans `ALL_CI_TOOLS`, câble l'Evidence via `record_evidence()` (convention
  Bloc B2, identique aux autres outils composites).
- `code_intelligence/investigation/schemas.py` /
  `code_intelligence/investigation/classifier.py` — `QuestionIntent.NAVIGATION_HOWTO`,
  routé vers `CODE_INTELLIGENCE`, classifié par 5 motifs de vocabulaire de
  localisation UI ("où se trouve", "où puis-je trouver", "comment
  accéder à", "dans quel onglet", "comment naviguer"), vérifié
  additif-pur (aucune régression sur governance/workflow/le benchmark
  documentaire DOC-01/02/03/04/10).

## Non couvert par cette reconstitution

- Toute décision produit sur une suite du bloc (Jour 5+) — aucune trace,
  aucune supposition faite ici.
- Le prompt système LLM (`prompts.py`) mentionné comme "non testable sans
  appel LLM réel" dans le docstring du test d'intent — à vérifier si une
  mise à jour du system prompt CI est également attendue pour ce bloc.
