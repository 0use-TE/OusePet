"""Real NAS GPU inference on an isolated, encoded cat/hedgehog video."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from PIL import Image, ImageOps

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='ousepet-real-video-') as temporary:
    root=Path(temporary);os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root)+':/test-photos',OUSEPET_DISCOVERY='0')
    from ousepet import api as m,identity
    started=time.monotonic();chosen={}
    for species,word in [('cat','猫咪'),('hedgehog','刺猬')]:
        files=sorted(p for p in Path('/test-photos').rglob('*.jpg') if word in str(p))
        assert files,word
        for path in files[len(files)//2:len(files)//2+5]+files[:3]:
            with Image.open(path) as raw:image=ImageOps.exif_transpose(raw).convert('RGB')
            kinds,detections=m.detect_identity(image)
            if any(d['species']==species for d in detections):chosen[species]=(path,image,detections);break
        assert species in chosen,(species,kinds)
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('fixture','fixture','/test-photos',m.now()))
        storage=dict(c.execute("SELECT * FROM storages WHERE id='fixture'").fetchone())
    for species,(path,image,detections) in chosen.items():
        ident,_=m.index_file(storage,path)
        m.apply_recognition(ident,{'species':[species],'pets':[]})
        with m.db() as c:
            identity.store(c,ident,c.execute('SELECT content_hash FROM photos WHERE id=?',(ident,)).fetchone()[0],[d for d in detections if d['species']==species],m.now())
            c.execute('INSERT INTO pets(id,name,species,created_at) VALUES(?,?,?,?)',(species,'基米' if species=='cat' else '扣嘚',species,m.now()))
            c.execute('UPDATE identity_clusters SET pet_id=? WHERE id IN (SELECT cluster_id FROM identity_observations WHERE photo_id=?)',(species,ident))
            c.execute("INSERT INTO photo_pets VALUES(?,?,'confirmed')",(ident,species))
        ImageOps.pad(image,(640,480)).save(root/(species+'.jpg'))
    Image.new('RGB',(640,480),'black').save(root/'black.jpg')
    clip=root/'pet-video.mp4'
    args=['ffmpeg','-v','error']
    for name,duration in [('black',1),('cat',2),('hedgehog',2)]:args+=['-loop','1','-t',str(duration),'-i',str(root/(name+'.jpg'))]
    args+=['-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]','-map','[v]','-r','4','-c:v','libx264','-pix_fmt','yuv420p','-threads','2',str(clip)]
    subprocess.run(args,check=True)
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('video','video',str(root),m.now()))
        storage=dict(c.execute("SELECT * FROM storages WHERE id='video'").fetchone())
    ident,_=m.index_file(storage,clip);m.infer_photo(ident)
    with m.db() as c:result=m.serialize_photo(c,c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone())
    assert set(result['species'])=={'cat','hedgehog'},result['species']
    assert {p['name'] for p in result['pets']}=={'基米','扣嘚'},result['pets']
    assert result['video_cover']>0 and len(result['video_hits'])==2,result
    report={'device':m.RUNTIME['device'],'gpu':m.RUNTIME['gpu_name'],'seconds':round(time.monotonic()-started,2),
        'duration':result['duration'],'species':result['species'],'pets':result['pets'],'hits':result['video_hits'],'cover_seconds':result['video_cover']}
    print(json.dumps(report,ensure_ascii=False))
print('PASS real encoded video + real GPU: black opening skipped, cat and hedgehog detected, both named identities assigned, timestamp and cover selected; production data untouched')
