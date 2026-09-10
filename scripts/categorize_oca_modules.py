"""
scripts/categorize_oca_modules.py

selection
semi-systematique de modules OCA candidats pour le premier banc de
questions CI (10 modules x 5 questions = 50 cas), stratifie par
categorie fonctionnelle plutot que choisi a la main sur des noms
familiers (biais explicitement signale par San Goku : les modules dont
le nom "sonne" workflow/securite sont deja ceux ou CI est le plus
susceptible d'etre deja fort -> benchmark optimiste).

Lecture seule : extrait des SIGNAUX STRUCTURELS deja disponibles via le
meme chargeur que scripts/run_oca_coverage.py
(code_intelligence.ci_graph_loader._load_module) et classe les modules
par categorie. Aucune question n'est posee a l'agent CI ici -- c'est une
etape de SELECTION, pas d'evaluation. Aucun fichier de production touche.

Categories et signal utilise (heuristique explicite, pas de devinette) :
  - securite       : nombre de ir.rule (poids x2) + ir.model.access
  - workflow       : au moins un champ Selection nomme 'state' sur un
                      modele du module (proxy standard Odoo pour une
                      machine a etats/workflow)
  - heritage       : nombre de classes modeles en EXTENSION pure
                      (_inherit sans _name -- modifie un modele existant,
                      donc surcharge potentielle de methode)
  - server_actions : nombre de ir.actions.server declares
  - contraintes    : nombre de methodes decorees @api.constrains
  - vue_ui         : modules a vues/groupes nombreux mais SANS ir.rule
                      ni @api.constrains (faible logique metier ailleurs)
  - reporting      : modules du depot 'reporting-engine' uniquement (peu
                      de logique metier par construction du depot)

Usage :
    python scripts/categorize_oca_modules.py tests/oca_sample

Sortie : pour chaque categorie, les modules les mieux classes (score +
detail), pour choisir les 1-2 modules par categorie a retenir dans le
lot de 10 du premier passage P3.1.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.utils import discover_odoo_modules
from code_intelligence.knowledge_rules.graph import _load_module
from code_intelligence.knowledge_rules.extractor.python_extractor import ModelRelationType


def score_module(mod):
    n_acl = len(mod.acl_entries)
    n_rules = len(mod.rules)
    n_server_actions = len(mod.server_actions)
    n_views = len(mod.views)
    n_groups = len(mod.groups)

    n_extension_models = 0
    n_constrains = 0
    has_state_selection = False
    for model in mod.models:
        if ModelRelationType.EXTENSION in model.relation_types:
            n_extension_models += 1
        for f in model.fields:
            if f.field_type == "Selection" and f.name == "state":
                has_state_selection = True
        for m in model.methods:
            for d in m.decorators:
                if d.decorator_type == "constrains":
                    n_constrains += 1

    return {
        "acl": n_acl,
        "rules": n_rules,
        "server_actions": n_server_actions,
        "views": n_views,
        "groups": n_groups,
        "extension_models": n_extension_models,
        "constrains": n_constrains,
        "has_state": has_state_selection,
        "security_score": n_rules * 2 + n_acl,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python categorize_oca_modules.py <path_to_oca_repos>")
        sys.exit(1)

    base_path = Path(sys.argv[1]).resolve()
    all_module_dirs = []
    for repo_dir in base_path.iterdir():
        if repo_dir.is_dir() and not repo_dir.name.startswith('.'):
            modules = discover_odoo_modules(repo_dir)
            all_module_dirs.extend([(repo_dir.name, repo_dir / m) for m in modules])

    print(f"Scanning {len(all_module_dirs)} modules across {base_path}...\n")

    rows = []
    failed = 0
    for repo_name, mod_dir in all_module_dirs:
        try:
            name, mod = _load_module(mod_dir)
        except Exception:
            failed += 1
            continue
        s = score_module(mod)
        rows.append((repo_name, name, s))

    def top(key_fn, n=8, filter_fn=None):
        candidates = rows if filter_fn is None else [r for r in rows if filter_fn(r)]
        return sorted(candidates, key=key_fn, reverse=True)[:n]

    print("=" * 74)
    print(" CATEGORIE : SECURITE (rules x2 + acl) ".center(74, "="))
    print("=" * 74)
    for repo, name, s in top(lambda r: r[2]["security_score"]):
        print(f"  {repo}/{name:38s} rules={s['rules']:3d} acl={s['acl']:4d} score={s['security_score']}")

    print("\n" + "=" * 74)
    print(" CATEGORIE : WORKFLOW (champ Selection 'state') ".center(74, "="))
    print("=" * 74)
    for repo, name, s in top(
        lambda r: r[2]["server_actions"] + r[2]["extension_models"],
        filter_fn=lambda r: r[2]["has_state"],
    ):
        print(f"  {repo}/{name:38s} server_actions={s['server_actions']:3d} extension_models={s['extension_models']:3d}")

    print("\n" + "=" * 74)
    print(" CATEGORIE : HERITAGE (classes EXTENSION pure) ".center(74, "="))
    print("=" * 74)
    for repo, name, s in top(lambda r: r[2]["extension_models"]):
        print(f"  {repo}/{name:38s} extension_models={s['extension_models']}")

    print("\n" + "=" * 74)
    print(" CATEGORIE : SERVER ACTIONS ".center(74, "="))
    print("=" * 74)
    for repo, name, s in top(lambda r: r[2]["server_actions"], filter_fn=lambda r: r[2]["server_actions"] > 0):
        print(f"  {repo}/{name:38s} server_actions={s['server_actions']}")

    print("\n" + "=" * 74)
    print(" CATEGORIE : CONTRAINTES (@api.constrains) ".center(74, "="))
    print("=" * 74)
    for repo, name, s in top(lambda r: r[2]["constrains"], filter_fn=lambda r: r[2]["constrains"] > 0):
        print(f"  {repo}/{name:38s} constrains={s['constrains']}")

    print("\n" + "=" * 74)
    print(" CATEGORIE : VUE/UI (vues+groupes, sans rule ni constrains) ".center(74, "="))
    print("=" * 74)
    ui_candidates = [r for r in rows if r[2]["views"] > 0 and r[2]["rules"] == 0 and r[2]["constrains"] == 0]
    for repo, name, s in sorted(ui_candidates, key=lambda r: r[2]["views"] + r[2]["groups"], reverse=True)[:8]:
        print(f"  {repo}/{name:38s} views={s['views']:3d} groups={s['groups']:3d}")

    print("\n" + "=" * 74)
    print(" CATEGORIE : REPORTING (depot reporting-engine) ".center(74, "="))
    print("=" * 74)
    for repo, name, s in [r for r in rows if r[0] == "reporting-engine"][:8]:
        print(f"  {repo}/{name:38s} views={s['views']:3d} rules={s['rules']:3d}")

    print(f"\nTotal modules analyses : {len(rows)} / {len(all_module_dirs)} decouverts ({failed} echecs de chargement)")


if __name__ == "__main__":
    main()
