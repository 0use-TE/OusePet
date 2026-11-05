"""Storage detach/reimport integration: retained edits, duplicate sources and cancellation."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='ousepet-storage-') as temporary:
    root=Path(temporary);library=root/'photos';library.mkdir();other=root/'other';other.mkdir()
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0',OUSEPET_WATCH_INTERVAL='3600')
    from ousepet import api as m
    calls=[]
    def infer(ident):
        calls.append(ident);m.apply_recognition(ident,{'species':['cat'],'pets':[]})
    def photo(path,color):
        Image.new('RGB',(40,30),color).save(path);old=time.time()-30;os.utime(path,(old,old))
    def wait(job):
        for _ in range(300):
            with m.db() as c:r=dict(c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone())
            if r['status']=='complete':return r
            assert r['status'] not in ('error','cancelled'),r
            time.sleep(.02)
        raise AssertionError(r)
    with patch.object(m,'infer_photo',side_effect=infer),TestClient(m.app) as client:
        photo(library/'a.png','red');photo(library/'b.png','blue')
        added=client.post('/api/storages',json={'path':str(library),'name':'照片'}).json();sid=added['id'];wait(added['job_id'])
        ids=[p['id'] for p in client.get('/api/photos?view=all').json()['items']];assert len(calls)==2
        pet=client.post('/api/pets',json={'name':'小猫','species':'cat'}).json()['id']
        album=client.post('/api/albums',json={'name':'收藏相册','photo_ids':[ids[0]]}).json()['id']
        for ident in ids:client.post('/api/photos/action',json={'ids':[ident],'action':'assign','pet_id':pet}).raise_for_status()
        client.post('/api/photos/action',json={'ids':[ids[1]],'action':'unassign','pet_id':pet}).raise_for_status()
        client.post('/api/photos/action',json={'ids':[ids[0]],'action':'favorite'}).raise_for_status()
        assert client.delete('/api/storages/'+sid).status_code==200
        for view in ('all','gallery','favorites','cats'):
            assert client.get('/api/photos',params={'view':view}).json()['total']==0
        assert client.get('/api/photos',params={'album_id':album}).json()['total']==0
        state=client.get('/api/state').json();assert state['counts']['library']==0 and not state['storages'] and not state['jobs']
        assert state['pets'][0]['count']==0 and state['albums'][0]['count']==0
        assert client.post('/api/storages/'+sid+'/scan',json={}).status_code==404
        assert client.patch('/api/storages/'+sid,json={'auto_scan':True}).status_code==404
        assert client.get('/api/storages/'+sid+'/browse').status_code==404
        m.init()  # Restart migration must retain detachment and edits.
        with patch.object(m.hashlib,'file_digest',side_effect=AssertionError('unchanged file rehashed')):
            added=client.post('/api/storages',json={'path':str(library),'name':'恢复'}).json()
            assert added['id']==sid and wait(added['job_id'])['total']==0
        assert len(calls)==2 and all(path.exists() for path in library.iterdir())
        assert client.get('/api/photos',params={'pet_id':pet}).json()['total']==1
        assert client.get('/api/photos?view=favorites').json()['total']==1
        assert client.get('/api/photos',params={'album_id':album}).json()['total']==1
        with m.db() as c:assert c.execute('SELECT 1 FROM identity_exclusions WHERE photo_id=? AND pet_id=?',(ids[1],pet)).fetchone()
        # Changed files reprocess; new files process; unchanged manual edits remain untouched.
        photo(library/'c.png','green')
        job=client.post('/api/storages/'+sid+'/scan',json={}).json()['job_id'];assert wait(job)['total']==1 and len(calls)==3
        # Duplicate content in a second source remains available after the first source detaches.
        shutil.copy2(library/'a.png',other/'copy.png')
        second=client.post('/api/storages',json={'path':str(other),'name':'副本'}).json();wait(second['job_id'])
        assert len(calls)==3
        client.delete('/api/storages/'+sid).raise_for_status()
        assert client.get('/api/photos?view=all').json()['total']==1
        client.delete('/api/storages/'+second['id']).raise_for_status()
        assert client.get('/api/photos?view=all').json()['total']==0
        # Importing a parent folder links cached paths without hashing/inference.
        with patch.object(m.hashlib,'file_digest',side_effect=AssertionError('cached child rehashed')):
            parent=client.post('/api/storages',json={'path':str(root),'name':'父目录'}).json();wait(parent['job_id'])
        assert client.get('/api/photos?view=all').json()['total']==3 and len(calls)==3
        photo(library/'c.png','orange')
        changed=client.post('/api/storages/'+parent['id']+'/scan',json={}).json()['job_id']
        assert wait(changed)['total']==1 and len(calls)==4
        assert client.get('/api/photos',params={'pet_id':pet}).json()['total']==1
        # Detach while inference is in-flight: finish this photo only, never resume hidden jobs.
        started=threading.Event();release=threading.Event()
        def slow(ident):
            started.set();assert release.wait(5);infer(ident)
        photo(library/'d.png','yellow');photo(library/'e.png','purple')
        with patch.object(m,'infer_photo',side_effect=slow):
            job=client.post('/api/storages/'+parent['id']+'/scan',json={}).json()['job_id'];assert started.wait(3)
            client.delete('/api/storages/'+parent['id']).raise_for_status();release.set()
            m.POOL.submit(lambda:None).result(timeout=8)
        with m.db() as c:assert c.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]=='cancelled'
        assert client.get('/api/photos?view=all').json()['total']==0
print('PASS: detach hides all views, reimport retains edits/exclusions/albums/favorites, no unchanged hashing, duplicates/parent import, active cancellation and restart')
