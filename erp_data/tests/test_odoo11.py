import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_intelligence.utils import discover_odoo_modules
from core.graph import _load_module

import os
def main():
    addons_path = Path(os.getenv("ODOO_11_ADDONS_PATH") or (Path(__file__).resolve().parent.parent.parent.parent / "odoo-11.0" / "addons"))
    if not addons_path.exists():
        print(f"Odoo 11 addons path '{addons_path}' does not exist, skipping.")
        return
    print(f"Discovering modules in {addons_path}...")
    modules = discover_odoo_modules(addons_path)
    print(f"Discovered {len(modules)} modules.")
    
    # Let's test extraction on a few core Odoo 11 modules to see if A1 pipeline crashes
    test_modules = ["sale", "account", "purchase", "hr"]
    
    for mod_name in test_modules:
        mod_dir = addons_path / mod_name
        if not mod_dir.exists():
            print(f"Module {mod_name} not found.")
            continue
            
        print(f"\n--- Extracting module: {mod_name} ---")
        try:
            name, parsed_mod = _load_module(mod_dir)
            print(f"Successfully parsed {name}")
            print(f"Models extracted: {len(parsed_mod.models)}")
            print(f"IR rules: {len(parsed_mod.rules)}")
            print(f"Groups: {len(parsed_mod.groups)}")
            print(f"Server actions: {len(parsed_mod.server_actions)}")
            print(f"Views: {len(parsed_mod.views)}")
            print(f"Menuitems: {len(parsed_mod.menuitems)}")
            print(f"ACL entries: {len(parsed_mod.acl_entries)}")
        except Exception as e:
            import traceback
            print(f"Error parsing {mod_name}:")
            traceback.print_exc()

if __name__ == "__main__":
    main()
