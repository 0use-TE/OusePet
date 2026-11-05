"""Integration check using an isolated database and actual local photo fixtures."""
import os,json,time,tempfile,shutil
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ousepet-api-') as temporary:
    base=Path(temporary);library=base/'photos';library.mkdir()
    prepared=json.loads((ROOT/'reports/pets/prepared.json').read_text(encoding='utf-8'))
    for ident,name in [('C09','cat.jpg'),('H34','hedgehog.jpg')]:
        source=next(r for r in prepared if r['id']==ident)
        shutil.copyfile(ROOT/source['path'],library/name)
    Image.new('RGB',(640,480),'white').save(library/'blank.png')
    os.environ['OUSEPET_DATA']=str(base/'data')
    os.environ['OUSEPET_LIBRARY_ROOTS']=str(library)
    import sys
    sys.path.insert(0,str(ROOT))
    from ousepet import api as module
    from fastapi.testclient import TestClient
    module.SEEDS.clear() # Exercise inference, rather than reusing earlier local results.
    with TestClient(module.app) as client:
        assert client.get('/api/state').json()['counts']['all']==0
        assert client.get('/api/settings').json()['gpu_enabled'] is True
        assert client.patch('/api/settings',json={'gpu_enabled':False}).status_code==200
        for _ in range(120):
            setting=client.get('/api/settings').json()
            if not setting['switching']:break
            time.sleep(.1)
        assert setting['gpu_enabled'] is False and setting['device']=='cpu',setting
        module.init()
        assert client.get('/api/settings').json()['gpu_enabled'] is False,'GPU setting was overwritten on initialization'
        client.patch('/api/settings',json={'gpu_enabled':True})
        for _ in range(120):
            setting=client.get('/api/settings').json()
            if not setting['switching']:break
            time.sleep(.1)
        assert setting['gpu_enabled'] is True and setting['device'] in ('cpu','cuda:0'),setting
        assert client.post('/api/storages',json={'path':str(base)}).status_code==403
        response=client.post('/api/storages',json={'path':str(library),'name':'测试照片'})
        assert response.status_code==200,response.text
        storage=response.json()['id']
        for _ in range(360):
            state=client.get('/api/state').json()
            if state['jobs'][0]['status'] not in ('running','queued'):break
            time.sleep(.25)
        assert state['jobs'][0]['status']=='complete',state['jobs']
        assert state['counts']['all']==2,state
        assert state['counts']['library']==3,state
        assert client.get('/api/photos?view=all').json()['total']==3
        assert any(p['name']=='blank.png' for p in client.get('/api/photos?view=all').json()['items'])
        assert state['counts']['cats']==1 and state['counts']['hedgehogs']==1,state
        items=client.get('/api/photos').json()['items']
        for photo in items:
            assert client.get(photo['thumb']).status_code==200
            assert client.get(photo['url']).status_code==200
        photo=items[0]
        assert client.post('/api/photos/action',json={'ids':[photo['id']],'action':'favorite'}).status_code==200
        assert client.get('/api/photos?view=favorites').json()['total']==1
        pet=client.post('/api/pets',json={'name':'测试猫咪','species':'cat'}).json()['id']
        assert client.post('/api/photos/action',json={'ids':[photo['id']],'action':'assign','pet_id':pet}).status_code==200
        assert client.get('/api/photos',params={'pet_id':pet}).json()['total']==1
        assert client.post('/api/photos/action',json={'ids':[photo['id']],'action':'unassign','pet_id':pet}).status_code==200
        assert client.get('/api/photos',params={'pet_id':pet}).json()['total']==0
        album=client.post('/api/albums',json={'name':'测试相册','photo_ids':[photo['id']]}).json()['id']
        assert client.get('/api/photos',params={'album_id':album}).json()['total']==1
        assert client.post('/api/photos/action',json={'ids':[photo['id']],'action':'hide'}).status_code==200
        assert Path(photo['path']).is_file()
        assert client.get('/api/photos').json()['total']==1
        assert client.post('/api/photos/action',json={'ids':[photo['id']],'action':'add','species':photo['species'][0]}).status_code==200
        assert client.get('/api/photos').json()['total']==2
        # Browsing indexes a file before the next scan: it must still receive inference.
        blank=next(p for p in client.get(f'/api/storages/{storage}/browse').json()['photos'] if p['name']=='blank.png')
        with module.db() as c:c.execute('UPDATE photos SET recognized=0 WHERE id=?',(blank['id'],))
        client.post(f'/api/storages/{storage}/scan')
        for _ in range(120):
            state=client.get('/api/state').json()
            if state['jobs'][0]['status'] not in ('running','queued'):break
            time.sleep(.25)
        with module.db() as c:assert c.execute('SELECT recognized FROM photos WHERE id=?',(blank['id'],)).fetchone()[0]==1
        assert state['counts']['all']==2
        assert client.get(f'/api/storages/{storage}/browse',params={'path':'..'}).status_code==404
        assert client.post('/api/photos/action',json={'ids':[p['id'] for p in items],'action':'reject'}).status_code==200
        assert client.get('/api/photos').json()['total']==0
        client.post(f'/api/storages/{storage}/scan')
        for _ in range(120):
            state=client.get('/api/state').json()
            if state['jobs'][0]['status'] not in ('running','queued'):break
            time.sleep(.25)
        assert state['counts']['all']==0,'Rejected photos reappeared after scanning'
        assert client.get('/api/photos?view=all').json()['total']==3,'Full library lost excluded photos'
        assert all(Path(p['path']).is_file() for p in items)
        # Recover interrupted scans, but preserve a user's paused state.
        interrupted=module.uid()
        with module.db() as c:c.execute('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',(interrupted,storage,'running',module.now()))
        module.init();module.recover_scans()
        for _ in range(120):
            latest=client.get('/api/state').json()['jobs'][0]
            if latest['status']=='complete':break
            time.sleep(.1)
        assert latest['id']!=interrupted and latest['status']=='complete',latest
        paused=module.uid()
        with module.db() as c:c.execute('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',(paused,storage,'paused',module.now()))
        module.init();module.recover_scans();time.sleep(.2)
        assert client.get('/api/state').json()['jobs'][0]['status']=='paused'
        assert client.post(f'/api/jobs/{paused}/resume').status_code==200
        for _ in range(120):
            latest=client.get('/api/state').json()['jobs'][0]
            if latest['status']=='complete':break
            time.sleep(.1)
        assert latest['id']==paused and latest['status']=='complete',latest
    module.POOL.shutdown(wait=True)
print('PASS: real cat + hedgehog inference, blank rejection, storage bounds, thumbnails, favorites, albums, manual import, rescan, originals preserved')
