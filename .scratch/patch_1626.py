"""Section 1626: align tests and README with the deletion of miro_ai_discuss and the odoo_addons modules."""
t = "tests/test_miro_ai_signing_secret.py"
s = open(t, encoding="utf-8").read()

old1 = '''        "odoo_addons/miro_ai/controllers/main.py",
        "odoo_addons/miro_ai_discuss/models/miro_ai_bot.py",
    ):
        assert "default_insecure_secret_for_dev"'''
new1 = '''        "odoo_addons/miro_ai/controllers/main.py",
    ):
        assert "default_insecure_secret_for_dev"'''
assert s.count(old1) == 1
s = s.replace(old1, new1)

old2 = '''    bot = (root / "odoo_addons/miro_ai_discuss/models/miro_ai_bot.py").read_text(encoding="utf-8")
    assert '"exp": int(time.time()) + 300' in bot
'''
assert s.count(old2) == 1
s = s.replace(old2, "")

old3 = '''        "odoo_addons/miro_ai/controllers/ask_flow.py",
        "odoo_addons/miro_ai_discuss/models/miro_ai_bot.py",
    ):'''
new3 = '''        "odoo_addons/miro_ai/controllers/ask_flow.py",
    ):'''
assert s.count(old3) == 1
s = s.replace(old3, new3)
assert "miro_ai_discuss" not in s
open(t, "w", encoding="utf-8").write(s)

r = "README.md"
c = open(r, encoding="utf-8").read()

old4 = "All custom modules (`miro_ai`, `miro_ai_discuss`, the business modules and the bundled OCA modules) are bundled inside this repository in `odoo_addons/`, one folder per module."
assert c.count(old4) == 1
i = c.index(old4)
j = c.index("\n", i)
line = c[i:j]
print("LIGNE ETAPE 7 ORIGINALE:", line)
new_line = "The custom module `miro_ai` is bundled inside this repository in `odoo_addons/`. Because you added that folder to `addons_path` in Step 6, Odoo detects it automatically."
c = c[:i] + new_line + c[j:]

old5 = '''# Install maintenance, the business modules and the OCA modules that have all their dependencies here
# (list: scripts/odoo_modules_to_install.txt ; external Python packages first:
#  pip install cryptography mako odoo_test_helper odoorpc openupgradelib 'paramiko<4.0.0' pygount pysftp 'sentry_sdk<=1.9.0')
python3 odoo-bin -c odoo.conf -d odoo-dev -i "$(paste -sd, ~/odoo-ia-prototype/scripts/odoo_modules_to_install.txt)" --stop-after-init
'''
new5 = '''# Install the native maintenance module (used by the benchmark questions)
python3 odoo-bin -c odoo.conf -d odoo-dev -i maintenance --stop-after-init
'''
assert c.count(old5) == 1
c = c.replace(old5, new5)
assert "miro_ai_discuss" not in c and "odoo_modules_to_install" not in c
open(r, "w", encoding="utf-8").write(c)
print("ok")
