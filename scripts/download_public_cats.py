"""Download a small identity-labelled diagnostic subset from public Kaggle files."""
import concurrent.futures
import hashlib
import io
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
os.environ['NO_PROXY'] = ''
opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': 'http://127.0.0.1:7897'}))
data = json.loads((ROOT / 'reports/pets/public-files.json').read_text(encoding='utf-8'))
groups = {}
for entry in data['datasetFiles']:
    groups.setdefault(entry['name'].split('/')[1], []).append(entry)
selected = []
for identity, entries in sorted(groups.items()):
    count = min(10 if identity != '0007' else 8, len(entries))
    indices = sorted({round(i * (len(entries) - 1) / (count - 1)) for i in range(count)})
    for position, index in enumerate(indices):
        selected.append({'identity': 'public-' + identity, 'entry': entries[index], 'role': 'unknown' if identity == '0007' else ('reference' if position in (0, 3, 6) else 'query')})


def fetch(record):
    source = record['entry']['name']
    path = ROOT / 'samples/public-cats' / record['identity'] / Path(source).name
    path.parent.mkdir(parents=True, exist_ok=True)
    url = 'https://www.kaggle.com/api/v1/datasets/download/timost1234/cat-individuals/' + urllib.parse.quote(source, safe='')
    for attempt in range(3):
        try:
            if path.exists():
                content = path.read_bytes()
            else:
                with opener.open(url, timeout=30) as response:
                    content = response.read()
            if content[:2] == b'PK':
                import zipfile
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    members = [n for n in archive.namelist() if Path(n).name == Path(source).name]
                    assert len(members) == 1, members
                    content = archive.read(members[0])
            assert len(content) == record['entry']['totalBytes'], f"{source}: expected {record['entry']['totalBytes']} bytes, got {len(content)}, prefix={content[:50]!r}"
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            path.write_bytes(content)
            return {'identity': record['identity'], 'role': record['role'], 'path': str(path.relative_to(ROOT)), 'source_file': source, 'source_url': url, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    records = []
    for i, record in enumerate(pool.map(fetch, selected), 1):
        records.append(record)
        if i % 10 == 0 or i == len(selected):
            print(f'Downloaded {i}/{len(selected)} labelled cat images', flush=True)
manifest = {
    'source': 'https://www.kaggle.com/datasets/timost1234/cat-individuals',
    'limitation': 'pet-recognition-base was trained on this dataset; identity overlap with its training split is unknown. This subset is diagnostic, not an independent generalisation benchmark. Public photo sessions are not known.',
    'records': records,
}
(ROOT / 'samples/public-cats/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print('Saved public-cats/manifest.json', flush=True)
