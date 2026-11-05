"""Preserve existing Docker settings while enabling the local development proxy."""
import json
import shutil
from pathlib import Path

path = Path('/etc/docker/daemon.json')
settings = json.loads(path.read_text()) if path.exists() else {}
if path.exists():
    backup = path.with_name('daemon.json.before-ousepet')
    if not backup.exists():
        shutil.copy2(path, backup)
settings.setdefault('proxies', {}).update({
    'http-proxy': 'http://127.0.0.1:7897',
    'https-proxy': 'http://127.0.0.1:7897',
    'no-proxy': 'localhost,127.0.0.1,::1',
})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(settings, indent=2) + '\n')
print('Docker daemon proxy configured; existing settings preserved.')
