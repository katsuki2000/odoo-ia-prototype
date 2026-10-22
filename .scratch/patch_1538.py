from pathlib import Path
p = Path('config/settings.py'); c = p.read_text(encoding='utf-8')
old = "LOCAL_ONLY = os.getenv('LOCAL_ONLY', 'true').lower() in ('true', '1', 'yes')\n"
assert c.count(old) == 1
p.write_text(c.replace(old, ''), encoding='utf-8')
print('ok')
