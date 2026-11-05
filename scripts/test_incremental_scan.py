"""Isolated scan integration checks; deterministic inference, actual files/DB/worker."""
import concurrent.futures
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

with tempfile.TemporaryDirectory(prefix='ousepet-incremental-') as temporary:
    base=Path(temporary);library=base/'photos';library.mkdir()
    os.environ.update(OUSEPET_DATA=str(base/'data'),OUSEPET_LIBRARY_ROOTS=str(library),OUSEPET_WATCH_INTERVAL='1',OUSEPET_DISCOVERY='0')
    from ousepet import api as module
    calls=[]
    def infer(ident):
        calls.append(ident)
        module.apply_recognition(ident,{'species':['cat'],'pets':[]})
    def photo(name,color):
        path=library/name;path.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(40,30),color).save(path)
        old=time.time()-30;os.utime(path,(old,old))
        return path
    def latest():return client.get('/api/state').json()['jobs'][0]
    def wait_job(ident,status='complete'):
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            with module.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
            if job['status']==status:return job
            assert job['status'] not in ('error','cancelled'),job
            time.sleep(.03)
        raise AssertionError(job)
    with patch.object(module,'infer_photo',side_effect=infer), TestClient(module.app) as client:
        original=photo('first.png','red')
        storage=client.post('/api/storages',json={'path':str(library),'name':'增量测试'}).json()
        sid=storage['id'];first=wait_job(storage['job_id'])
        assert first['total']==1 and len(calls)==1
        assert client.get('/api/state').json()['storages'][0]['auto_scan']==1
        # An explicit no-op scan must not hash or infer existing files.
        with patch.object(module.hashlib,'file_digest',side_effect=AssertionError('unchanged file hashed')):
            noop=client.post(f'/api/storages/{sid}/scan').json()['job_id']
            assert wait_job(noop)['total']==0
        assert len(calls)==1
        with module.db() as c:count=c.execute('SELECT count(*) FROM jobs').fetchone()[0]
        module.check_new_files()
        with module.db() as c:assert c.execute('SELECT count(*) FROM jobs').fetchone()[0]==count
        # The actual background watcher discovers a new nested file without API/UI activity.
        photo('nested/new.png','blue')
        deadline=time.monotonic()+12
        while len(calls)<2 and time.monotonic()<deadline:time.sleep(.05)
        assert len(calls)==2,'background watcher did not find new file'
        auto=wait_job(latest()['id']);assert auto['total']==1,auto
        # Duplicates are recorded as paths so later checks do not hash them repeatedly.
        shutil.copy2(original,library/'duplicate.png')
        duplicate=client.post(f'/api/storages/{sid}/scan').json()['job_id']
        assert wait_job(duplicate)['total']==1
        assert len(calls)==2
        with patch.object(module.hashlib,'file_digest',side_effect=AssertionError('duplicate rehashed')):
            module.check_new_files()
            assert module.pending_files({'id':sid,'path':str(library)})==[]
        # Same mtime, different size must still be detected and preserve photo identity/favorite.
        photo_id=calls[0]
        client.post('/api/photos/action',json={'ids':[photo_id],'action':'favorite'})
        before=original.stat();original.write_bytes(original.read_bytes()+b'changed-size')
        os.utime(original,(before.st_atime,before.st_mtime))
        modified=client.post(f'/api/storages/{sid}/scan').json()['job_id']
        assert wait_job(modified)['total']==1
        assert len(calls)==3 and calls[-1]==photo_id
        with module.db() as c:assert c.execute('SELECT favorite FROM photos WHERE id=?',(photo_id,)).fetchone()[0]==1
        # Turning the watcher off survives initialization and blocks automatic jobs.
        assert client.patch(f'/api/storages/{sid}',json={'auto_scan':False}).status_code==200
        photo('off.png','green');module.check_new_files()
        assert module.queue_scan(sid,[library/'off.png'],automatic=True) is None
        # Cancel during the final inference; it must not be overwritten by completion.
        started=threading.Event();release=threading.Event()
        def slow(ident):
            started.set();assert release.wait(10)
            infer(ident)
        with patch.object(module,'infer_photo',side_effect=slow):
            active=client.post(f'/api/storages/{sid}/scan').json()['job_id']
            assert started.wait(5)
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                queued=list(pool.map(lambda _:module.queue_scan(sid),range(10)))
            assert set(queued)=={active},queued
            assert client.post(f'/api/jobs/{active}/cancel').status_code==200
            cancelled=latest();assert cancelled['status']=='cancelled'
            release.set();module.POOL.submit(lambda:None).result(timeout=5)
            assert latest()['status']=='cancelled'
            with module.db() as c:
                row=c.execute('SELECT * FROM jobs WHERE id=?',(active,)).fetchone()
                assert row['finished_at'] and row['current_file']==''
            assert client.get('/api/state').json()['storages'][0]['auto_scan']==0
        # A queued job cancelled before it starts must not enumerate files at all.
        gate=threading.Event()
        blocker=module.POOL.submit(lambda:gate.wait(10))
        queued=client.post(f'/api/storages/{sid}/scan').json()['job_id']
        assert client.post(f'/api/jobs/{queued}/cancel').status_code==200
        with patch.object(module,'pending_files',side_effect=AssertionError('cancelled queue enumerated files')):
            gate.set();blocker.result(timeout=5);module.POOL.submit(lambda:None).result(timeout=5)
        assert latest()['status']=='cancelled'
        # Paused workers can be cancelled; manual scan still works with automatic mode off.
        paused=module.uid()
        with module.db() as c:c.execute('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',(paused,sid,'paused',module.now()))
        future=module.POOL.submit(module.scan_job,paused)
        assert client.post(f'/api/jobs/{paused}/cancel').status_code==200
        future.result(timeout=5)
        photo('after-cancel.png','yellow')
        resumed=client.post(f'/api/storages/{sid}/scan').json()['job_id'];wait_job(resumed)
        assert (library/'after-cancel.png').is_file()
        module.init()
        assert client.get('/api/state').json()['storages'][0]['auto_scan']==0
        # Re-enabling the watcher imports new photos, without resurrecting exclusions.
        client.post('/api/photos/action',json={'ids':[photo_id],'action':'reject'})
        photo('reenabled.png','purple')
        assert client.patch(f'/api/storages/{sid}',json={'auto_scan':True}).status_code==200
        module.check_new_files();wait_job(latest()['id'])
        with module.db() as c:assert c.execute('SELECT removed FROM photos WHERE id=?',(photo_id,)).fetchone()[0]==1
        assert client.get('/api/photos?view=all').json()['total']>=5
        # An existing path overwritten with duplicate content must not be rehashed forever.
        client.patch(f'/api/storages/{sid}',json={'auto_scan':False})
        target=library/'off.png'
        shutil.copyfile(library/'reenabled.png',target)
        changed=client.post(f'/api/storages/{sid}/scan').json()['job_id'];wait_job(changed)
        with patch.object(module.hashlib,'file_digest',side_effect=AssertionError('overwritten duplicate rehashed')):
            noop=client.post(f'/api/storages/{sid}/scan').json()['job_id']
            assert wait_job(noop)['total']==0
print('PASS: automatic nested discovery, no-op skips hashing/inference, duplicate tracking, size changes, persisted switch, cancellation during inference/queued/paused, queue race, exclusions preserved')
