"""Video scan, sampling, identity, cancellation and preservation; --real decodes FFmpeg fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));REAL='--real' in sys.argv
with tempfile.TemporaryDirectory(prefix='ousepet-video-') as temporary:
    root=Path(temporary);library=root/'media';library.mkdir()
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(library),OUSEPET_DISCOVERY='0')
    from ousepet import api as m,video,identity
    path=library/'VID_20261105_120000.mp4';quiet=library/'quiet.mp4'
    if REAL:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:s=96x64:d=2:r=4','-f','lavfi','-i','color=red:s=96x64:d=2:r=4',
            '-f','lavfi','-i','color=blue:s=96x64:d=4:r=4','-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]','-map','[v]',
            '-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(path)],check=True)
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:s=96x64:d=1:r=4','-c:v','libx264','-threads','1',str(quiet)],check=True)
    else:
        path.write_bytes(b'video-fixture');quiet.write_bytes(b'quiet-fixture')
        video.probe=lambda p:{'width':96,'height':64,'duration':1 if 'quiet' in str(p) else 8,'date':None}
        video.frame=lambda p,t,ready=None:Image.new('RGB',(96,64),'black' if 'quiet' in str(p) or t<2 else 'red' if t<4 else 'blue')
        video.compatible=lambda p,target,ready=None:shutil.copyfile(p,target)
    def detect(image):
        red,green,blue=image.getpixel((30,30));kinds=[]
        if red>100:kinds=['cat']
        elif blue>100:kinds=['cat','hedgehog']
        return kinds,[{'species':kind,'box':[0,0,90,60],'vector':np.eye(384,dtype=np.float32)[0 if kind=='cat' else 1]} for kind in kinds]
    m.detect_identity=detect
    with TestClient(m.app) as client:
        sid='storage'
        with m.db() as c:
            c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'test',str(library),m.now()))
            for ident,kind,index,name in [('cat','cat',0,'基米'),('hedge','hedgehog',1,'扣嘚')]:
                image=library/(ident+'.jpg');Image.new('RGB',(96,64),'red').save(image)
                c.execute('INSERT INTO pets(id,name,species,created_at) VALUES(?,?,?,?)',(ident,name,kind,m.now()))
                c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized)
                    VALUES(?,?,?,?,?,96,64,'2026-11-05',1,?,1,1)''',(ident,sid,str(image),image.name,ident,json.dumps([kind])))
                vector=np.eye(384,dtype=np.float32)[index]
                c.execute('INSERT INTO identity_clusters(id,species,anchor,pet_id) VALUES(?,?,?,?)',(ident,kind,vector.tobytes(),ident))
                c.execute('INSERT INTO identity_observations VALUES(?,?,?,?,?,?,0)',(ident,ident,kind,'[0,0,90,60]',vector.tobytes(),ident))
            storage=dict(c.execute('SELECT * FROM storages WHERE id=?',(sid,)).fetchone())
        ident,created=m.index_file(storage,path);assert created
        m.infer_photo(ident)
        data=next(p for p in client.get('/api/photos?view=videos').json()['items'] if p['id']==ident)
        assert data['media_type']=='video' and 7.9<data['duration']<8.1
        assert {p['name'] for p in data['pets']}=={'基米','扣嘚'},data
        assert {h['pet_id'] for h in data['video_hits']}=={'cat','hedge'}
        assert all(h['seconds']>=1.9 for h in data['video_hits'])
        with m.db() as c:
            assert c.execute('SELECT count(*) FROM pets').fetchone()[0]==2
            assert c.execute('SELECT count(*) FROM identity_observations WHERE photo_id=?',(ident,)).fetchone()[0]<=16
            before=c.execute('SELECT count(*) FROM video_hits WHERE photo_id=?',(ident,)).fetchone()[0]
        assert m.index_file(storage,path)==(ident,False)
        client.get('/api/photos/'+ident+'/thumbnail').raise_for_status()
        raw=client.get('/api/photos/'+ident+'/image',headers={'Range':'bytes=0-3'});assert raw.status_code==206 and len(raw.content)==4
        client.patch('/api/photos/'+ident+'/video-cover',json={'seconds':3}).raise_for_status()
        assert client.patch('/api/photos/'+ident+'/video-cover',json={'seconds':80}).status_code==400
        client.get('/api/photos/'+ident+'/play',headers={'Range':'bytes=0-3'}).raise_for_status()
        m.infer_photo(ident)
        with m.db() as c:
            assert c.execute('SELECT video_cover FROM photos WHERE id=?',(ident,)).fetchone()[0]==3
            assert c.execute('SELECT count(*) FROM video_hits WHERE photo_id=?',(ident,)).fetchone()[0]==before
        # A quiet video is indexed in the complete library, never auto-added to pets.
        qid,_=m.index_file(storage,quiet);m.infer_photo(qid)
        assert client.get('/api/photos?view=videos').json()['total']==2
        assert client.get('/api/photos?view=all&media=video').json()['total']==2
        assert client.get('/api/photos?view=all&media=image').json()['total']==2
        assert client.get('/api/photos/timeline?view=all&media=video').json()['total']==2
        assert client.get('/api/photos?view=all&media=invalid').status_code==400
        assert qid not in {p['id'] for p in client.get('/api/photos?view=gallery').json()['items']}
        # Explicit fine rescan is a cancellable standard scan job, preserving a chosen poster.
        response=client.post('/api/photos/'+ident+'/video-rescan');response.raise_for_status()
        job=response.json()['job_id']
        for _ in range(300):
            with m.db() as c:status=c.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]
            if status not in ('running','queued'):break
            time.sleep(.1)
        assert status=='complete',status
        client.post('/api/photos/action',json={'ids':[ident],'action':'unassign','pet_id':'cat'}).raise_for_status()
        client.post('/api/photos/action',json={'ids':[ident],'action':'assign','pet_id':'hedge'}).raise_for_status()
        m.infer_photo(ident)
        data=next(p for p in client.get('/api/photos?view=videos').json()['items'] if p['id']==ident)
        assert [p['id'] for p in data['pets']]==['hedge'] and data['video_cover']==3
        assert client.post('/api/photos/'+ident+'/video-rescan').status_code==409
        with m.db() as c:row=c.execute('SELECT * FROM photos WHERE id=?',(qid,)).fetchone()
        try:m.infer_video(row,ready=lambda:False);raise AssertionError('Cancellation ignored')
        except video.Cancelled:pass
        assert max(len(video.sample_times(60000)),len(video.sample_times(60000,True)))<=120
        assert len(video.refinement_times(60000,list(range(0,500,5)),[]))<=60
        started=time.monotonic()
        try:
            video.run([sys.executable,'-c','import time;time.sleep(20)'],ready=lambda:time.monotonic()-started<.1)
            raise AssertionError('Decoder subprocess cancellation ignored')
        except video.Cancelled:assert time.monotonic()-started<3
        # Many frames of one unknown animal cannot create a five-media profile.
        with m.db() as c:
            c.execute("UPDATE photos SET visible=1,manual=0,identity_hash=NULL WHERE id=?",(qid,))
            det=[{'species':'cat','box':[0,0,20,20],'vector':np.eye(384,dtype=np.float32)[3],'seconds':float(i)} for i in range(20)]
            identity.store(c,qid,row['content_hash'],det,m.now())
            assert c.execute('SELECT count(*) FROM pets').fetchone()[0]==2
        client.delete('/api/storages/'+sid).raise_for_status()
        assert client.get('/api/photos?view=videos').json()['total']==0
        assert path.exists() and quiet.exists()
print('PASS videos'+(' REAL FFmpeg' if REAL else '')+': bounded/refined sampling, multi-pet timestamps, no frame inflation, incremental cache, poster preservation, range/compatible playback, fine job, correction, cancellation and detached storage')
