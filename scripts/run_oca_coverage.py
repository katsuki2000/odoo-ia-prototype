import sys
import os
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.utils import discover_odoo_modules
from code_intelligence.ci_graph_loader import _load_module

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_oca_coverage.py <path_to_oca_repos>")
        sys.exit(1)
        
    base_path = Path(sys.argv[1]).resolve()
    if not base_path.exists():
        print(f"Error: Path {base_path} does not exist.")
        sys.exit(1)
        
    print(f"Scanning {base_path} for Odoo modules...")
    
    # We look for modules in subdirectories since we cloned repos like `sale-workflow`
    all_module_dirs = []
    for repo_dir in base_path.iterdir():
        if repo_dir.is_dir() and not repo_dir.name.startswith('.'):
            modules = discover_odoo_modules(repo_dir)
            all_module_dirs.extend([(repo_dir.name, repo_dir / m) for m in modules])
            
    print(f"Discovered {len(all_module_dirs)} modules.")
    
    total_modules = 0
    success_modules = 0
    failed_modules = []
    
    stats = {
        "models": 0,
        "rules": 0,
        "groups": 0,
        "server_actions": 0,
        "views": 0,
        "menuitems": 0,
        "acl_entries": 0,
    }
    
    for repo_name, mod_dir in all_module_dirs:
        total_modules += 1
        mod_name = mod_dir.name
        try:
            name, parsed_mod = _load_module(mod_dir)
            success_modules += 1
            stats["models"] += len(parsed_mod.models)
            stats["rules"] += len(parsed_mod.rules)
            stats["groups"] += len(parsed_mod.groups)
            stats["server_actions"] += len(parsed_mod.server_actions)
            stats["views"] += len(parsed_mod.views)
            stats["menuitems"] += len(parsed_mod.menuitems)
            stats["acl_entries"] += len(parsed_mod.acl_entries)
        except Exception as e:
            failed_modules.append((f"{repo_name}/{mod_name}", str(e)))
            
    print("\n" + "="*50)
    print(" OCA COVERAGE REPORT ".center(50, "="))
    print("="*50)
    print(f"Total modules discovered: {total_modules}")
    print(f"Successfully extracted:   {success_modules} ({(success_modules/total_modules)*100 if total_modules else 0:.1f}%)")
    print(f"Failed extraction:        {len(failed_modules)} ({(len(failed_modules)/total_modules)*100 if total_modules else 0:.1f}%)")
    print("\n--- Entities Extracted ---")
    print(f"Models:           {stats['models']}")
    print(f"Rules:            {stats['rules']}")
    print(f"Groups:           {stats['groups']}")
    print(f"Server Actions:   {stats['server_actions']}")
    print(f"Views:            {stats['views']}")
    print(f"Menuitems:        {stats['menuitems']}")
    print(f"ACL Entries:      {stats['acl_entries']}")
    
    if failed_modules:
        print("\n--- Failed Modules ---")
        for name, err in failed_modules:
            print(f"- {name}: {err}")
            
    if failed_modules:
        sys.exit(1)

if __name__ == "__main__":
    main()
