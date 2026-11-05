"""Transactional multi-profile merging and persistent species correction."""
import json
import os
from pathlib import Path
import sys
import tempfile
import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='ousepet-bulk-species-') as temporary:
    root=Path(temporary);os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m,identity
    sid=m.uid()
    with m.db() as c:c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'fixture',str(root),m.now()))
    def pet(name,species='cat',unnamed=0):
        ident=m.uid()
        with m.db() as c:c.execute('INSERT INTO pets(id,name,species,created_at,unnamed) VALUES(?,?,?,?,?)',(ident,name,species,m.now(),unnamed))
        return ident
    def photo():
        ident=m.uid()
        with m.db() as c:c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized,identity_hash)
            VALUES(?,?,?,?,?,50,50,'2026-01-01',1,'["cat"]',1,1,?)''',(ident,sid,str(root/(ident+'.jpg')),ident+'.jpg',ident,identity.MODEL_VERSION+':'+ident))
        return ident
    def group(pet_id,photos,species='cat',index=0):
        gid=m.uid();vector=np.eye(384,dtype=np.float32)[index]
        with m.db() as c:
            c.execute('INSERT INTO identity_clusters(id,species,anchor,pet_id) VALUES(?,?,?,?)',(gid,species,vector.tobytes(),pet_id))
            for ident in photos:
                c.execute('INSERT INTO identity_observations VALUES(?,?,?,?,?,?,0)',(m.uid(),ident,species,'[0,0,50,50]',vector.tobytes(),gid))
                c.execute("INSERT INTO photo_pets VALUES(?,?,'suggested')",(ident,pet_id))
        return gid
    with TestClient(m.app) as client:
        target=pet('保留名字');a=pet('来源一');b=pet('来源二');hedge=pet('刺猬','hedgehog')
        shared=photo();one=photo();two=photo()
        group(target,[one]);group(a,[shared]);group(b,[shared,two])
        body={'source_ids':[a,b],'target_id':target}
        response=client.post('/api/pets/merge',json=body)
        assert response.status_code==409 and response.json()['detail']['photos']==[{'id':shared,'name':shared+'.jpg'}]
        assert len(client.get('/api/state').json()['pets'])==4,'conflict partially merged sources'
        assert client.post('/api/pets/merge',json={**body,'source_ids':[a,'missing']}).status_code==400
        assert client.post('/api/pets/merge',json={**body,'source_ids':[a,hedge],'confirm_conflicts':True}).status_code==400
        assert client.post('/api/pets/merge',json={**body,'source_ids':[target]}).status_code==400
        assert len(client.get('/api/state').json()['pets'])==4
        response=client.post('/api/pets/merge',json={**body,'confirm_conflicts':True});assert response.status_code==200,response.text
        result=client.get('/api/state').json();survivor=next(p for p in result['pets'] if p['id']==target)
        assert survivor['name']=='保留名字' and survivor['count']==3
        assert not any(p['id'] in (a,b) for p in result['pets'])
        # Correct a misclassified hedgehog, retaining independent cats in a shared frame.
        wrong=pet('未命名猫咪',unnamed=1);real_cat=pet('同框的猫')
        solo=photo();both=photo();gid=group(wrong,[solo,both]);group(real_cat,[both],index=1)
        album=client.post('/api/albums',json={'name':'保持相册','photo_ids':[solo,both]}).json()['id']
        client.post('/api/photos/action',json={'ids':[solo],'action':'favorite'}).raise_for_status()
        changed=client.patch('/api/pets/'+wrong,json={'name':'未命名猫咪','species':'hedgehog'});assert changed.status_code==200,changed.text
        corrected=next(p for p in client.get('/api/state').json()['pets'] if p['id']==wrong)
        assert corrected['species']=='hedgehog' and corrected['unnamed'] and corrected['name']=='未命名刺猬'
        with m.db() as c:
            assert c.execute('SELECT species FROM identity_clusters WHERE id=?',(gid,)).fetchone()[0]=='hedgehog'
            assert c.execute('SELECT count(*) FROM identity_observations WHERE cluster_id=? AND species=?',(gid,'hedgehog')).fetchone()[0]==2
            assert json.loads(c.execute('SELECT species FROM photos WHERE id=?',(solo,)).fetchone()[0])==['hedgehog']
            assert set(json.loads(c.execute('SELECT species FROM photos WHERE id=?',(both,)).fetchone()[0]))=={'cat','hedgehog'}
            c.execute('UPDATE photos SET identity_hash=NULL WHERE id=?',(solo,))
        m.apply_recognition(solo,{'species':['cat'],'pets':[]})
        with m.db() as c:row=c.execute('SELECT * FROM photos WHERE id=?',(solo,)).fetchone()
        m.store_identity(row,[{'species':'cat','box':[0,0,50,50],'vector':np.eye(384,dtype=np.float32)[0]}])
        m.init()
        with m.db() as c:
            assert json.loads(c.execute('SELECT species FROM photos WHERE id=?',(solo,)).fetchone()[0])==['hedgehog']
            assert c.execute('SELECT species FROM identity_observations WHERE photo_id=?',(solo,)).fetchone()[0]=='hedgehog'
        assert client.get('/api/photos',params={'album_id':album}).json()['total']==2
        assert client.get('/api/photos?view=favorites').json()['total']==1
        assert client.get('/api/photos',params={'pet_id':real_cat}).json()['total']==1
        assert client.patch('/api/pets/'+wrong,json={'name':'刺猬名字','species':'dog'}).status_code==400
        assert client.patch('/api/pets/'+wrong,json={'name':'刺猬名字','species':'hedgehog'}).status_code==200
        assert not next(p for p in client.get('/api/state').json()['pets'] if p['id']==wrong)['unnamed']
print('PASS: atomic 3-way merge, source-source conflicts and override, stale/mixed validation, target name/dedup, species correction, shared cats, manual persistence, albums/favorites and unnamed naming')
