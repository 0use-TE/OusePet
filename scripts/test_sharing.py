"""Sharing boundaries: no management routes, scoped files, PIN, expiry and revocation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
with tempfile.TemporaryDirectory(prefix='ousepet-share-') as temporary:
    root=Path(temporary);os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m,sharing,video
    calls=[]
    def compatible(path,target,ready=None,strip_metadata=False):calls.append(strip_metadata);target.write_bytes(b'public-video-preview')
    video.compatible=compatible;video.frame=lambda *args:Image.new('RGB',(160,120),'blue')
    with TestClient(m.app) as admin,TestClient(sharing.public_app) as guest:
        with m.db() as c:
            c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('s','test',str(root),m.now()))
            storage=dict(c.execute("SELECT * FROM storages WHERE id='s'").fetchone())
        ids=[]
        for index in range(3):
            path=root/f'photo{index}.jpg';exif=Image.Exif();exif[315]='PRIVATE OWNER'
            Image.new('RGB',(2200,1300),'#947da1').save(path,exif=exif)
            # Make bytes distinct, including the excluded photograph.
            path.write_bytes(path.read_bytes()+bytes([index]))
            ident,_=m.index_file(storage,path);ids.append(ident)
        vid=root/'video.mp4';vid.write_bytes(b'video-original')
        with m.db() as c:
            c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,media_type,duration)
                VALUES('video','s',?,'video.mp4','video-hash',160,120,'2026-01-01',1,'video',4)''',(str(vid),))
        album=admin.post('/api/albums',json={'name':'旅行回忆','photo_ids':ids[:2]+['video']}).json()['id']
        plain=admin.post('/api/albums/'+album+'/shares',json={}).json();token=plain['token'];prefix='/api/public/shares/'+token
        assert len(token)>=40 and not plain['allow_download'] and not plain['code_required']
        data=guest.get(prefix).json();assert data['name']=='旅行回忆' and data['total']==3
        assert not any(key in str(data) for key in ('content_hash','storage_id','pin_hash','PRIVATE OWNER'))
        assert str(root) not in json.dumps(data)
        for endpoint in ('/api/state','/api/shares','/api/share-settings','/api/photos/'+ids[0]+'/image','/'):
            assert guest.get(endpoint).status_code==404,endpoint
        assert guest.post('/api/library/reset',json={}).status_code==404
        assert guest.get(prefix+'/media/'+ids[2]+'/thumbnail').status_code==404
        assert guest.get(prefix+'/media/'+ids[0]+'/download').status_code==403
        response=guest.get(prefix+'/media/'+ids[0]+'/preview');assert response.status_code==200
        with Image.open(BytesIO(response.content)) as image:assert not image.getexif() and max(image.size)<=1920
        assert response.headers['cache-control']=='no-store' and response.headers['referrer-policy']=='no-referrer'
        assert guest.get(prefix+'/media/video/preview',headers={'Range':'bytes=0-5'}).status_code==206
        assert calls==[True],'Public transcode retained source metadata'
        protected=admin.post('/api/albums/'+album+'/shares',json={'pin':'123456','days':30,'allow_download':True}).json()
        secure='/api/public/shares/'+protected['token']
        assert guest.get(secure).status_code==401
        for kind in ('thumbnail','preview','download'):assert guest.get(secure+'/media/'+ids[0]+'/'+kind).status_code==401
        for _ in range(10):assert guest.post(secure+'/unlock',json={'pin':'wrong'}).status_code==403
        assert guest.post(secure+'/unlock',json={'pin':'123456'}).status_code==429
        with m.db() as c:c.execute('UPDATE share_attempts SET started=?',(time.time()-61,))
        unlocked=guest.post(secure+'/unlock',json={'pin':'123456'});assert unlocked.status_code==200
        assert 'HttpOnly' in unlocked.headers['set-cookie']
        assert guest.get(secure).status_code==200
        assert guest.get(secure,headers={'Cookie':sharing.cookie_name(protected['token'])+'=not-a-valid-session'}).status_code==401
        assert guest.get(secure+'/media/'+ids[0]+'/download').content==Path(root/'photo0.jpg').read_bytes()
        # Every request rechecks membership even if an existing thumbnail is cached.
        admin.post('/api/photos/action',json={'ids':[ids[0]],'action':'remove_album','album_id':album}).raise_for_status()
        assert guest.get(prefix+'/media/'+ids[0]+'/preview').status_code==404
        assert guest.get(prefix).json()['total']==2
        admin.delete('/api/shares/'+protected['id']).raise_for_status()
        assert guest.get(secure).status_code==404 and guest.get(secure+'/media/'+ids[1]+'/download').status_code==404
        with m.db() as c:c.execute('UPDATE memory_shares SET expires_at=? WHERE id=?',(time.time()-1,plain['id']))
        assert guest.get(prefix).status_code==404
        cfg=admin.get('/api/share-settings').json();assert cfg['base_url']=='' and cfg['public_port']==8767
        assert admin.patch('/api/share-settings',json={'base_url':'photos.example.com/'}).json()['base_url']=='https://photos.example.com'
        for domain in ('javascript:alert(1)','https://user:pass@example.com','https://example.com/path','https://example.com?x=1','https://bad host','https://example.com?','https://example.com#'):
            assert admin.patch('/api/share-settings',json={'base_url':domain}).status_code==400,domain
        assert admin.patch('/api/share-settings',json={'base_url':''}).json()['base_url']==''
        # A link closed while a preview is being prepared must not return the new file.
        midway=admin.post('/api/albums/'+album+'/shares',json={'days':0}).json()
        with m.db() as c:
            c.execute("INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,media_type,duration) VALUES('v2','s',?,'v2.mp4','v2',160,120,'2026-01-01',1,'video',4)",(str(vid),))
            c.execute('INSERT INTO album_photos VALUES(?,?)',(album,'v2'))
        def interrupted(path,target,ready=None,strip_metadata=False):
            with m.db() as c:c.execute('UPDATE memory_shares SET enabled=0 WHERE id=?',(midway['id'],))
            assert ready is not None and not ready();target.write_bytes(b'must-not-be-served')
        video.compatible=interrupted
        assert guest.get('/api/public/shares/'+midway['token']+'/media/v2/preview').status_code==404
        video.compatible=compatible
        # Delete active and closed records without touching another link or its memory.
        for closed in (False,True):
            doomed=admin.post('/api/albums/'+album+'/shares',json={'days':0}).json()
            doomed_prefix='/api/public/shares/'+doomed['token']
            assert guest.get(doomed_prefix).status_code==200
            if closed:admin.delete('/api/shares/'+doomed['id']).raise_for_status()
            admin.delete('/api/shares/'+doomed['id']+'?permanent=true').raise_for_status()
            assert all(item['id']!=doomed['id'] for item in admin.get('/api/shares').json()['items'])
            assert guest.get(doomed_prefix).status_code==404
            assert guest.get(doomed_prefix+'/media/'+ids[1]+'/preview').status_code==404
            assert admin.delete('/api/shares/'+doomed['id']+'?permanent=true').status_code==404
            assert any(item['id']==album for item in admin.get('/api/state').json()['albums'])
        remaining=admin.post('/api/albums/'+album+'/shares',json={'days':0}).json()
        assert guest.get('/api/public/shares/'+remaining['token']).status_code==200
        admin.delete('/api/albums/'+album).raise_for_status()
        assert guest.get('/api/public/shares/'+remaining['token']).status_code==404
        assert vid.exists() and (root/'photo0.jpg').exists()
print('PASS sharing: read-only listener, token/file scope, metadata stripping, bounded previews, download permission, PIN/rate limit, membership updates, expiry/revocation, domain validation and deletion cascade')
