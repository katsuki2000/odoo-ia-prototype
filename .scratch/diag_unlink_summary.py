import sys
sys.path.insert(0, "/media/donnee/projets/odoo-ia-prototype")
from code_intelligence.rules.security import analyze_python_security_locks

path = "/media/donnee/Programs/odoo-17.0/addons/purchase/models/purchase_order.py"
code = open(path).read()
result = analyze_python_security_locks(code, path)
print("=== summary_text (no question set) ===")
print(result.summary_text)
print(f"[len={len(result.summary_text)}]")
