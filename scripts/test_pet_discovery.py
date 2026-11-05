"""Isolated database/API tests for threshold, corrections, merges and background discovery."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
with tempfile.TemporaryDirectory(prefix='ousepet-identity-') as temporary:
    base=Path(temporary);library=base/'photos';library.mkdir()
    os.environ.update(OUSEPET_DATA=str(base/'data'),OUSEPET_LIBRARY_ROOTS=str(library),OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    from ousepet import identity
    # Similarity constraints: a strong neighbour alone cannot bridge different anchors.
    basis=np.eye(384,dtype=np.float32)
    close=basis[0]*.9+basis[1]*np.sqrt(1-.9**2)
    candidate={'id':'a','pet_id':'pet-a','anchor':basis[1],'samples':np.asarray([close]*3)}
    assert identity.choose_cluster(basis[0],[candidate]) is None
    candidate['anchor']=basis[0];candidate['samples']=np.asarray([basis[0]]*3)
    competitor={**candidate,'id':'b','pet_id':'pet-b'}
    assert identity.choose_cluster(basis[0],[candidate,competitor]) is None
    competitor['pet_id']='pet-a'
    assert identity.choose_cluster(basis[0],[candidate,competitor]) is not None
    sid=m.uid()
    with m.db() as c:c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'Identity fixtures',str(library),m.now()))
    storage={'id':sid,'path':str(library)}
    number=0
    def vector(index):
        v=np.zeros(384,dtype=np.float32);v[index]=1;return v
    def detection(index,species='cat'):
        return {'species':species,'box':[0,0,50,50],'vector':vector(index)}
    def photo(detections=None):
        global number
        number+=1;path=library/f'{number}.png'
        Image.new('RGB',(60,60),(number%255,number//255,7)).save(path)
        ident,_=m.index_file(storage,path)
        with m.db() as c:
            c.execute("UPDATE photos SET visible=1,recognized=1,species='[\"cat\"]' WHERE id=?",(ident,))
            row=c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
        if detections is not None:m.store_identity(row,detections)
        return ident
    def pets():return client.get('/api/state').json()['pets']
    def wait_discovery():
        end=time.monotonic()+8
        while time.monotonic()<end:
            status=client.get('/api/state').json()['discovery']
            if status['status'] in ('complete','cancelled'):return status
            time.sleep(.02)
        raise AssertionError(status)
    with TestClient(m.app) as client:
        ids=[photo([detection(0)]) for _ in range(4)]
        assert not any(p['unnamed'] for p in pets()),'fewer than five photos published'
        ids.append(photo([detection(0)]))
        group=next(p for p in pets() if p['unnamed'])
        assert group['count']==5
        with m.db() as c:row=c.execute('SELECT * FROM photos WHERE id=?',(ids[0],)).fetchone()
        m.store_identity(row,[detection(0)]);assert next(p for p in pets() if p['id']==group['id'])['count']==5
        assert client.patch('/api/pets/'+group['id'],json={'name':' ','species':'cat'}).status_code==400
        assert client.patch('/api/pets/'+group['id'],json={'name':'小橘','species':'cat'}).status_code==200
        sixth=photo([detection(0)])
        named=next(p for p in pets() if p['id']==group['id'])
        assert named['name']=='小橘' and not named['unnamed'] and named['count']==6
        assert client.get('/api/photos',params={'pet_id':group['id']}).json()['total']==6
        # Remove a wrong suggestion, then force re-extraction: it must stay excluded from that pet.
        client.post('/api/photos/action',json={'ids':[sixth],'action':'unassign','pet_id':group['id']}).raise_for_status()
        with m.db() as c:
            c.execute('UPDATE photos SET identity_hash=NULL WHERE id=?',(sixth,))
            row=c.execute('SELECT * FROM photos WHERE id=?',(sixth,)).fetchone()
        m.store_identity(row,[detection(0)])
        assert client.get('/api/photos',params={'pet_id':group['id']}).json()['total']==5
        # Separate species, even with identical embeddings.
        for _ in range(5):photo([detection(0,'hedgehog')])
        hedge=next(p for p in pets() if p['unnamed'] and p['species']=='hedgehog')
        assert hedge['count']==5
        assert client.post('/api/pets/'+hedge['id']+'/merge',json={'target_id':group['id']}).status_code==400
        # A visually different group can be explicitly merged; both reference groups stay usable.
        for _ in range(5):photo([detection(2)])
        other=next(p for p in pets() if p['unnamed'] and p['species']=='cat')
        assert client.post('/api/pets/'+other['id']+'/merge',json={'target_id':group['id']}).status_code==200
        photo([detection(2)])
        assert client.get('/api/photos',params={'pet_id':group['id']}).json()['total']==11
        assert not any(p['id']==other['id'] for p in pets())
        # Co-occurrence requires review; explicit confirmation overrides a mistaken split.
        for _ in range(5):photo([detection(8),detection(9)])
        pair=[p for p in pets() if p['unnamed'] and p['species']=='cat']
        assert len(pair)==2 and all(p['count']==5 for p in pair)
        merge_url='/api/pets/'+pair[0]['id']+'/merge'
        conflict=client.post(merge_url,json={'target_id':pair[1]['id']})
        assert conflict.status_code==409 and conflict.json()['detail']['code']=='merge_conflict'
        assert len(conflict.json()['detail']['photos'])==5
        assert all('name' in photo for photo in conflict.json()['detail']['photos'])
        assert all(any(p['id']==pet['id'] for p in pets()) for pet in pair),'review mutated profiles'
        assert client.post(merge_url,json={'target_id':pair[1]['id'],'confirm_conflicts':True}).status_code==200
        assert not any(p['id']==pair[0]['id'] for p in pets())
        assert next(p for p in pets() if p['id']==pair[1]['id'])['count']==5,'shared photos duplicated'
        assert client.post('/api/pets/'+hedge['id']+'/merge',json={'target_id':group['id'],'confirm_conflicts':True}).status_code==400
        # Even identical vectors from the same frame cannot share a cluster.
        multi=photo([detection(16),detection(16)])
        with m.db() as c:
            assert c.execute('SELECT count(DISTINCT cluster_id) FROM identity_observations WHERE photo_id=?',(multi,)).fetchone()[0]==2
        # Background backfill, with deterministic extraction, and resume after cancellation.
        pending=photo()
        with patch.object(m,'detect_identity',return_value=(['cat'],[detection(0)])):
            client.post('/api/discovery/start').raise_for_status()
            status=wait_discovery();assert status['status']=='complete' and status['processed']==status['total'] and status['errors']==0,status
        assert client.get('/api/photos',params={'pet_id':group['id']}).json()['total']==12
        pending=photo();started=threading.Event();release=threading.Event()
        def slow(_):
            started.set();assert release.wait(5);return ['cat'],[detection(0)]
        with patch.object(m,'detect_identity',side_effect=slow):
            client.post('/api/discovery/start');assert started.wait(3)
            client.post('/api/discovery/cancel');release.set()
            m.POOL.submit(lambda:None).result(timeout=5)
            assert wait_discovery()['status']=='cancelled'
        with m.db() as c:
            assert c.execute('SELECT count(*) FROM identity_observations').fetchone()[0]>20
        # Delete empty profiles and populated, merged profiles; originals and albums survive.
        empty=client.post('/api/pets',json={'name':'空档案','species':'cat'}).json()['id']
        assert client.delete('/api/pets/'+empty).status_code==200
        assert client.delete('/api/pets/'+empty).status_code==404
        album=client.post('/api/albums',json={'name':'保留相册','photo_ids':ids}).json()['id']
        total=client.get('/api/photos?view=all').json()['total']
        assert client.delete('/api/pets/'+group['id']).status_code==200
        assert not any(p['id']==group['id'] for p in pets())
        assert client.get('/api/photos?view=all').json()['total']==total
        assert client.get('/api/photos',params={'album_id':album}).json()['total']==5
        with m.db() as c:
            assert c.execute('SELECT count(*) FROM identity_clusters WHERE dismissed=1').fetchone()[0]>=2
            assert c.execute('SELECT count(*) FROM photo_pets WHERE pet_id=?',(group['id'],)).fetchone()[0]==0
        before={p['id'] for p in pets()}
        m.init() # Restart migrations must not recreate deleted names/groups.
        for _ in range(6):photo([detection(0)]);photo([detection(2)])
        assert {p['id'] for p in pets()}==before,'deleted groups reappeared'
        assert all(Path(p['path']).exists() for p in client.get('/api/photos?view=all').json()['items'])
print('PASS: five distinct photos, idempotency, naming, named matching, exclusions, species separation, merges, co-occurrence guard, backfill/cancellation and original preservation')
