import hashlib, sys
from config import settings as s
SECRET = ('PASSWORD', 'SECRET', 'API_KEY')
for name in sorted(n for n in dir(s) if n.isupper()):
    value = getattr(s, name)
    if any(part in name for part in SECRET):
        value = 'sha256:' + hashlib.sha256(str(value).encode()).hexdigest()[:8]
    print(f'{name}={value!r}')
