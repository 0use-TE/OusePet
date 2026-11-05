"""Persistent ordering and independent membership for a cat/hedgehog shared frame."""
import os
from pathlib import Path
import sys
import tempfile
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='ousepet-order-') as temporary:
    root=Path(temporary)
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    with TestClient(m.app) as client:
        def pet(name,species='cat'):
            response=client.post('/api/pets',json={'name':name,'species':species})
            response.raise_for_status()
            return response.json()['id']
        other=pet('其他');cat=pet('基米');hedge=pet('扣嘚','hedgehog')
        assert client.post('/api/pets/order',json={'ids':[cat,hedge,other]}).status_code==200
        def order():return [p['id'] for p in client.get('/api/state').json()['pets']]
        assert order()==[cat,hedge,other]
        m.init()
        assert order()==[cat,hedge,other],'order lost on restart'
        extra=pet('新发现')
        assert order()==[cat,hedge,other,extra]
        for ids in ([cat,cat],[cat,'missing']):
            assert client.post('/api/pets/order',json={'ids':ids}).status_code==400
            assert order()==[cat,hedge,other,extra]
        sid=m.uid();pid=m.uid()
        with m.db() as c:
            c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'test',str(root),m.now()))
            c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized)
                VALUES(?,?,?,?,?,50,50,'2026-01-01',1,'[]',1,1)''',(pid,sid,str(root/'shared.jpg'),'shared.jpg',pid))
        for ident in (cat,hedge):
            client.post('/api/photos/action',json={'ids':[pid],'action':'assign','pet_id':ident}).raise_for_status()
        for ident in (cat,hedge):
            data=client.get('/api/photos',params={'pet_id':ident}).json()
            assert data['total']==1
            assert {p['id'] for p in data['items'][0]['pets']}=={cat,hedge}
            assert set(data['items'][0]['species'])=={'cat','hedgehog'}
            client.post('/api/photos/action',json={'ids':[pid],'action':'cover','pet_id':ident}).raise_for_status()
        m.init()
        for ident in (cat,hedge):
            record=next(p for p in client.get('/api/state').json()['pets'] if p['id']==ident)
            assert record['cover_id']==pid and pid in record['cover']
        for invalid in ({'ids':[pid,pid],'pet_id':cat},{'ids':[pid],'pet_id':extra},{'ids':['missing'],'pet_id':cat}):
            assert client.post('/api/photos/action',json={'action':'cover',**invalid}).status_code==400
        assert next(p for p in client.get('/api/state').json()['pets'] if p['id']==cat)['cover_id']==pid
        assert client.patch('/api/pets/'+cat,json={'name':'不应保存','species':'hedgehog','cover_id':'missing'}).status_code==400
        record=next(p for p in client.get('/api/state').json()['pets'] if p['id']==cat)
        assert record['name']=='基米' and record['species']=='cat' and record['cover_id']==pid
        client.patch('/api/pets/'+hedge,json={'name':'扣嘚','species':'hedgehog','cover_id':pid}).raise_for_status()
        assert next(p for p in client.get('/api/state').json()['pets'] if p['id']==hedge)['cover_id']==pid
        client.post('/api/photos/action',json={'ids':[pid],'action':'unassign','pet_id':cat}).raise_for_status()
        assert client.get('/api/photos',params={'pet_id':cat}).json()['total']==0
        assert client.get('/api/photos',params={'pet_id':hedge}).json()['total']==1
        client.delete('/api/pets/'+other).raise_for_status()
        assert order()==[cat,hedge,extra]
print('PASS: persisted order, new profiles append, invalid updates atomic, deleted IDs ignored, shared cat/hedgehog membership independent')
