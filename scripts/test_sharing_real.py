"""Real FFmpeg public preview strips source metadata without changing the original."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='ousepet-public-real-') as temporary:
    root=Path(temporary);os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m,sharing
    clip=root/'private-original.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=160x120:d=1:r=4','-c:v','libx264','-threads','1',
        '-metadata','title=PRIVATE TITLE','-metadata','location=+37.0000+127.0000/',str(clip)],check=True)
    digest=hashlib.sha256(clip.read_bytes()).hexdigest()
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('s','test',str(root),m.now()))
        storage=dict(c.execute("SELECT * FROM storages WHERE id='s'").fetchone())
    ident,_=m.index_file(storage,clip)
    with TestClient(m.app) as admin,TestClient(sharing.public_app) as visitor:
        album=admin.post('/api/albums',json={'name':'视频回忆','photo_ids':[ident]}).json()['id']
        share=admin.post('/api/albums/'+album+'/shares',json={}).json()
        prefix='/api/public/shares/'+share['token']+'/media/'+ident
        thumbnail=visitor.get(prefix+'/thumbnail');assert thumbnail.status_code==200 and thumbnail.headers['content-type']=='image/jpeg'
        response=visitor.get(prefix+'/preview',headers={'Range':'bytes=0-31'});assert response.status_code==206 and len(response.content)==32
        target=next((root/'data/share-cache').glob('*-web.mp4'))
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(target)]))
        assert 'PRIVATE TITLE' not in json.dumps(info) and 'location' not in info.get('format',{}).get('tags',{})
        assert info['streams'][0]['codec_name']=='h264'
        assert visitor.get(prefix+'/download').status_code==403
        assert hashlib.sha256(clip.read_bytes()).hexdigest()==digest
print('PASS public REAL FFmpeg: poster, H.264 preview, Range, no source title/GPS metadata, download enforcement and original bytes preserved')
