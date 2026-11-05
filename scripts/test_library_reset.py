"""Isolated destructive-operation tests. Never operates on NAS/user data."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='ousepet-reset-') as temporary:
    root=Path(temporary);library=root/'photos';library.mkdir()
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0',OUSEPET_WATCH_INTERVAL='3600')
    from ousepet import api as m
    calls=[]
    def infer(ident):
        calls.append(ident);m.apply_recognition(ident,{'species':['cat'],'pets':[]})
    def photo(name,color):Image.new('RGB',(40,30),color).save(library/name)
    def drain():m.POOL.submit(lambda:None).result(timeout=10)
    def state():return client.get('/api/state').json()
    with patch.object(m,'infer_photo',side_effect=infer),TestClient(m.app) as client:
        assert client.post('/api/library/scan',json={}).status_code==400
        photo('a.png','red');photo('b.png','blue')
        sid=client.post('/api/storages',json={'path':str(library),'name':'照片'}).json()['id'];drain()
        old_ids={p['id'] for p in client.get('/api/photos?view=all').json()['items']}
        pet=client.post('/api/pets',json={'name':'旧命名','species':'cat'}).json()['id']
        client.post('/api/photos/action',json={'ids':list(old_ids),'action':'assign','pet_id':pet}).raise_for_status()
        client.post('/api/photos/action',json={'ids':[next(iter(old_ids))],'action':'favorite'}).raise_for_status()
        client.post('/api/albums',json={'name':'旧相册','photo_ids':list(old_ids)}).raise_for_status()
        with m.db() as c:c.execute("UPDATE settings SET value='false' WHERE key='gpu_enabled'")
        thumb=m.DATA/'thumbnails'/'old.jpg';thumb.write_bytes(b'cached thumbnail')
        assert client.post('/api/library/reset',json={'confirmation':'清空'}).status_code==400
        assert len(state()['pets'])==1 and thumb.exists()
        # Incremental rescan preserves curation and identifies only new content.
        photo('c.png','green');assert client.post('/api/library/scan',json={}).status_code==200;drain()
        assert len(calls)==3 and len(state()['pets'])==1 and len(state()['albums'])==1
        # An inference still in flight must finish BEFORE cleanup, not resurrect old rows.
        started=threading.Event();release=threading.Event()
        def slow(ident):started.set();assert release.wait(5);infer(ident)
        photo('d.png','yellow')
        originals={p.name:p.read_bytes() for p in library.iterdir()}
        with patch.object(m,'infer_photo',side_effect=slow):
            client.post('/api/library/scan',json={}).raise_for_status();assert started.wait(3)
            with m.db() as c:
                for status in ('queued','paused'):
                    c.execute('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',(m.uid(),sid,status,m.now()))
            response=client.post('/api/library/reset',json={'confirmation':'清空并重新识别'})
            assert response.status_code==200 and state()['reset_task']['status']=='queued'
            assert client.post('/api/library/reset',json={'confirmation':'清空并重新识别'}).status_code==409
            assert client.post('/api/library/scan',json={}).status_code==409
            assert client.post('/api/pets',json={'name':'禁止旧写入','species':'cat'}).status_code==409
            assert client.get('/api/storages/'+sid+'/browse').status_code==409
            release.set()
            # The reset worker queues new scans behind this barrier; drain twice.
            drain();drain()
        result=state();assert result['reset_task']['status']=='complete',result['reset_task']
        assert not result['pets'] and not result['albums'] and not thumb.exists()
        assert result['counts']['library']==4 and result['counts']['all']==4
        assert len(result['jobs'])==1 and result['jobs'][0]['total']==4 and result['jobs'][0]['status']=='complete'
        new_ids={p['id'] for p in client.get('/api/photos?view=all').json()['items']};assert not old_ids & new_ids
        assert result['storages'][0]['id']==sid and m.settings()['gpu_enabled'] is False
        assert originals=={p.name:p.read_bytes() for p in library.iterdir()}
        backups=list((m.DATA/'backups').glob('*.sqlite3'));assert len(backups)==1
        with closing(sqlite3.connect(backups[0])) as c:
            assert c.execute('SELECT name FROM pets').fetchone()[0]=='旧命名'
            assert c.execute("SELECT 1 FROM settings WHERE key='reset_task'").fetchone() is None
        # Persisted interrupted reset is recovered on startup and retains folder configuration.
        with m.db() as c:m.save_reset_task(c,{'status':'queued'})
        m.recover_scans();drain();drain()
        assert state()['reset_task']['status']=='complete' and state()['counts']['library']==4
        assert state()['storages'][0]['id']==sid
print('PASS: incremental rescan, typed confirmation, active/queued/paused cancellation, stale-write guard, full rebuild, backup, original/config preservation and reset recovery')
