"""Recall tuning invariants with isolated cached vectors; no models/user data."""
import os
from pathlib import Path
import sys
import tempfile
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='ousepet-recall-') as temporary:
    root=Path(temporary);os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m,identity
    basis=np.eye(384,dtype=np.float32)
    def vector(a,b,similarity):return identity.normalized(basis[a]*similarity+basis[b]*np.sqrt(1-similarity**2))
    with m.db() as c:
        sid=m.uid();c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'fixture',str(root),m.now()))
        def group(v,n,species='cat',pet=None,shared=None,dismissed=False):
            gid=m.uid();c.execute('INSERT INTO identity_clusters(id,species,anchor,pet_id,dismissed) VALUES(?,?,?,?,?)',(gid,species,v.tobytes(),pet,int(dismissed)))
            photos=[]
            for i in range(n):
                photo=shared if i==0 and shared else m.uid()
                if photo!=shared:
                    c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized,identity_hash)
                        VALUES(?,?,?,?,?,50,50,'2026-01-01',1,?,1,1,?)''',(photo,sid,str(root/(photo+'.jpg')),photo+'.jpg',photo,'["'+species+'"]',identity.MODEL_VERSION+':'+photo))
                c.execute('INSERT INTO identity_observations VALUES(?,?,?,?,?,?,0)',(m.uid(),photo,species,'[0,0,50,50]',v.tobytes(),gid));photos.append(photo)
                if pet:c.execute("INSERT OR IGNORE INTO photo_pets VALUES(?,?,'suggested')",(photo,pet))
            return gid,photos
        named=m.uid();c.execute('INSERT INTO pets(id,name,species,created_at,unnamed) VALUES(?,?,?,?,0)',(named,'基米','cat',m.now()))
        original,original_photos=group(basis[0],5,pet=named)
        loose,loose_photos=group(vector(0,1,.81),3)
        excluded,excluded_photos=group(vector(0,2,.82),2)
        c.execute('INSERT INTO identity_exclusions VALUES(?,?)',(excluded_photos[0],named))
        concurrent,concurrent_photos=group(basis[0],2,shared=original_photos[0])
        # Two related sub-threshold groups together have enough distinct photos.
        first,first_photos=group(basis[10],3)
        second,second_photos=group(vector(10,11,.81),3)
        dismissed,_=group(basis[20],6,dismissed=True)
        # A new manual reference can anchor a profile without an existing cluster.
        manual=m.uid();c.execute('INSERT INTO pets(id,name,species,created_at,unnamed) VALUES(?,?,?,?,0)',(manual,'手动参考','cat',m.now()))
        manual_group,manual_photos=group(basis[30],1)
        c.execute("INSERT INTO photo_pets VALUES(?,?,'confirmed')",(manual_photos[0],manual))
        manual_more,manual_more_photos=group(vector(30,31,.81),3)
        # A point close only to an auto-added sample must not become a new trusted bridge.
        bridge,bridge_photos=group(vector(0,1,.4),2)
        hedge,hedge_photos=group(basis[0],5,species='hedgehog')
        result=identity.regroup(c,m.now())
        assert c.execute('SELECT name FROM pets WHERE id=?',(named,)).fetchone()[0]=='基米'
        assert c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(loose,)).fetchone()[0]==named
        assert c.execute('SELECT reference_seed FROM identity_clusters WHERE id=?',(loose,)).fetchone()[0]==0
        assert not c.execute('SELECT 1 FROM photo_pets WHERE pet_id=? AND photo_id=?',(named,excluded_photos[0])).fetchone()
        assert c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(concurrent,)).fetchone()[0]!=named
        p1=c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(first,)).fetchone()[0]
        p2=c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(second,)).fetchone()[0]
        assert p1 and p1==p2
        assert c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(dismissed,)).fetchone()[0] is None
        assert c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(manual_group,)).fetchone()[0]==manual
        assert c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(manual_more,)).fetchone()[0]==manual
        for _ in range(3):identity.regroup(c,m.now())
        assert c.execute('SELECT pet_id FROM identity_clusters WHERE id=?',(bridge,)).fetchone()[0]!=named
        assert c.execute("SELECT status FROM photo_pets WHERE photo_id=? AND pet_id=?",(manual_photos[0],manual)).fetchone()[0]=='confirmed'
        assert c.execute('SELECT species FROM pets WHERE id=(SELECT pet_id FROM identity_clusters WHERE id=?)',(hedge,)).fetchone()[0]=='hedgehog'
        assert c.execute('SELECT count(*) FROM photos WHERE identity_hash IS NULL').fetchone()[0]==0
print('PASS: relaxed existing matching, small-group families, named/manual references, exclusions, co-occurrence, deleted groups, frozen reference anti-chain, species and cached features')
