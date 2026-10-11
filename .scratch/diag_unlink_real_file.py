import sys
sys.path.insert(0, "/media/donnee/projets/odoo-ia-prototype")
from code_intelligence.rules.security import analyze_python_security_locks

path = "/media/donnee/Programs/odoo-17.0/addons/purchase/models/purchase_order.py"
code = open(path).read()
result = analyze_python_security_locks(code, path)
print("TOTAL exception_messages:", len(result.exception_messages))
for i, msg in enumerate(result.exception_messages):
    if "cancel" in msg.lower() or "delete" in msg.lower():
        print(i, repr(msg), "| method:", result.exception_methods[i], "| cond:", result.exception_conditions[i])
print("methods containing unlink/cancel:", [m for m in result.exception_methods if "unlink" in m or "cancel" in m])
