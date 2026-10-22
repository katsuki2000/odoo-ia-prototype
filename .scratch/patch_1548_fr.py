import shutil, sys
from pathlib import Path
ROOT = Path("."); BACKUP = ROOT/".scratch"/"avant_1548_suite"
E = {
"core/__init__.py": [(
'"""core: pipeline LangGraph, routage, schemas, client LLM.\n\n__init__.py ajoute (2026-08-24) pour uniformiser avec code_intelligence/\n(seul package du depot a en avoir un jusque-la) -- ce package fonctionnait\ndeja comme namespace package Python 3 implicite via `pythonpath = .` dans\npytest.ini, ce fichier ne change aucun comportement d\'import existant.\n"""',
'"""core: LangGraph pipeline, routing, schemas, LLM client.\n\n__init__.py added (2026-08-24) to match code_intelligence/ (the only package in\nthe repository to have one until then) -- this package already worked as an\nimplicit Python 3 namespace package through `pythonpath = .` in pytest.ini, so\nthis file changes no existing import behaviour.\n"""')],
"document_rag/__init__.py": [(
'"""document_rag: RAG documentaire (ingestion, vectorstore, recherche hybride).\n\n__init__.py ajoute pour uniformiser avec code_intelligence/\n(seul package du depot a en avoir un jusque-la) -- ce package fonctionnait\ndeja comme namespace package Python 3 implicite via `pythonpath = .` dans\npytest.ini, ce fichier ne change aucun comportement d\'import existant.\n"""',
'"""document_rag: documentary RAG (ingestion, vectorstore, hybrid search).\n\n__init__.py added to match code_intelligence/ (the only package in the\nrepository to have one until then) -- this package already worked as an\nimplicit Python 3 namespace package through `pythonpath = .` in pytest.ini, so\nthis file changes no existing import behaviour.\n"""')],
"core/evaluation/expected_models.py": [
 ('"""Modeles attendus par question et classement d\'une resolution.\n\nMesure l\'exactitude d\'une resolution, pas seulement le fait qu\'elle ait abouti : un assistant\nchoisi a la place du bon modele est « resolu » pour l\'audit mais « faux » ici.\n"""',
  '"""Expected models per question, and classification of a resolution.\n\nMeasures whether a resolution is exact, not just whether it succeeded: an assistant model\nchosen in place of the right one counts as "resolved" for the audit but as "wrong" here.\n"""'),
 ('"""Retourne (attendus, toleres) par identifiant de question ; les cles `_...` sont reservees."""',
  '"""Return (expected, tolerated) by question id; keys starting with `_` are reserved."""'),
 ('"""exact : tous les attendus et rien hors attendus + toleres ; partiel : rien de faux mais des\n    attendus manquent (au moins un present) ; abstention : vide ; faux : le reste."""',
  '"""exact: every expected model and nothing outside expected + tolerated; partial: nothing wrong\n    but some expected models are missing (at least one present); abstention: empty; wrong: the rest."""'),
],
"core/evaluation/resolution_score.py": [
 ('"""Verdict d\'exactitude d\'une resolution de sujet contre les modeles attendus d\'une question de banque."""',
  '"""Exactness verdict of a subject resolution against the expected models of a bank question."""'),
],
"core/llm/server_fingerprint.py": [
 ('"""Empreinte du serveur d\'inference : permet de comparer des mesures a serveur constant.\n\nLes reponses de l\'arbitre changent d\'une session de serveur a l\'autre ; une\nmesure n\'est comparable a une autre que si l\'empreinte est la meme. L\'empreinte ne prouve pas\nl\'identite du serveur : elle detecte les changements visibles par l\'API (modele servi,\nmetadonnees du modele, `system_fingerprint`). Ne leve jamais d\'exception ; ne contient ni URL\nni cle d\'API (l\'hote du endpoint n\'apparait que sous forme hachee).\n"""',
  '"""Inference server fingerprint: lets measurements be compared on a constant server.\n\nThe arbiter\'s answers change from one server session to another, so a measurement is only\ncomparable to another when the fingerprint is the same. The fingerprint does not prove the\nserver\'s identity: it detects the changes visible through the API (served model, model\nmetadata, `system_fingerprint`). Never raises; contains neither a URL nor an API key (the\nendpoint host only appears in hashed form).\n"""'),
 ('"""Hash des seuls champs qui caracterisent le modele servi.\n\n    Exclut l\'hote du endpoint et l\'horodatage : un tunnel qui redemarre change l\'adresse sans\n    changer le modele, et inversement un meme tag peut changer de contenu (d\'ou `created`,\n    `max_model_len` et `system_fingerprint` quand le serveur les fournit).\n    """',
  '"""Hash of the only fields that characterise the served model.\n\n    Excludes the endpoint host and the timestamp: a restarted tunnel changes the address without\n    changing the model, and conversely the same tag can change content (hence `created`,\n    `max_model_len` and `system_fingerprint` when the server provides them).\n    """'),
],
"code_intelligence/semgrep_rules/raw_sql_constraints.py": [
 ("# le parseur de tests scanne tous les commentaires du fichier et\n# confond une explication en prose avec une vraie annotation.",
  "# the test parser scans every comment in the file and\n# mistakes a prose explanation for a real annotation."),
 ("# .execute() sans rapport avec du SQL -- l'argument n'est pas une\n        # chaine contenant \"CREATE UNIQUE INDEX\", ne doit PAS matcher.",
  "# .execute() unrelated to SQL -- the argument is not a\n        # string containing \"CREATE UNIQUE INDEX\", must NOT match."),
],
"code_intelligence/semgrep_rules/sql_constraints.py": [
 ("# le parseur de tests scanne tous les commentaires du fichier et\n# confond une explication en prose avec une vraie annotation.",
  "# the test parser scans every comment in the file and\n# mistakes a prose explanation for a real annotation."),
 ("# Lecture (attribute access), pas une déclaration — ne doit PAS\n        # matcher.",
  "# Read (attribute access), not a declaration -- must NOT\n        # match."),
 ("# Nom différent (suffixe _backup) — ne doit PAS matcher : le token\n    # exact `_sql_constraints` est requis.",
  "# Different name (_backup suffix) -- must NOT match: the exact\n    # `_sql_constraints` token is required."),
 ("# Surcharge dynamique par compréhension + concaténation — HORS\n    # (gap documenté dans sql_constraints.yaml), ne doit\n    # donc PAS matcher pour l'instant.",
  "# Dynamic override through comprehension + concatenation -- OUT OF SCOPE\n    # (gap documented in sql_constraints.yaml), so it must\n    # NOT match for now."),
],
}
apply = "--apply" in sys.argv
bad = []; plan = {}
for rel, edits in E.items():
    t = (ROOT/rel).read_text(encoding="utf-8"); n = t
    for old, new in edits:
        c = n.count(old)
        if c != 1: bad.append(f"{c}x {rel}: {old[:55]!r}")
        else: n = n.replace(old, new)
    plan[rel] = (t, n)
for b in bad: print("PROBLEM", b)
if bad: sys.exit("ABORT")
for rel, (t, n) in plan.items():
    print("CHANGE", rel, f"lines {t.count(chr(10))}->{n.count(chr(10))}")
    if apply:
        d = BACKUP/rel; d.parent.mkdir(parents=True, exist_ok=True)
        if not d.exists(): shutil.copy2(ROOT/rel, d)
        (ROOT/rel).write_text(n, encoding="utf-8")
print("APPLIED" if apply else "DRY")
