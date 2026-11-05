"""Recall-oriented visual groups with persistent user corrections."""
import json
import uuid

import numpy as np

MIN_PHOTOS = 5
MODEL_VERSION = 'dinov2-crop-v1'
NEAREST = .78
CENTROID = .70
ANCHOR = .66
MARGIN = .004
BATCH_NEAREST = .76
BATCH_CENTROID = .68
BATCH_ANCHOR = .64
GROUPING_VERSION = 'recall-v2'


def init_schema(c):
    for table,column,definition in [('pets','unnamed','INTEGER NOT NULL DEFAULT 0'),
                                    ('photos','identity_hash','TEXT')]:
        if column not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}:
            c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS identity_clusters(
      id TEXT PRIMARY KEY,species TEXT NOT NULL,anchor BLOB NOT NULL,
      pet_id TEXT REFERENCES pets(id));
    CREATE TABLE IF NOT EXISTS identity_observations(
      id TEXT PRIMARY KEY,photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
      species TEXT NOT NULL,box TEXT NOT NULL,vector BLOB NOT NULL,
      cluster_id TEXT REFERENCES identity_clusters(id),excluded INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS identity_photo ON identity_observations(photo_id);
    CREATE INDEX IF NOT EXISTS identity_cluster ON identity_observations(cluster_id);
    CREATE TABLE IF NOT EXISTS video_observation_times(observation_id TEXT PRIMARY KEY REFERENCES identity_observations(id) ON DELETE CASCADE,seconds REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS video_hits(photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE,seconds REAL NOT NULL,species TEXT NOT NULL,
      cluster_id TEXT REFERENCES identity_clusters(id) ON DELETE CASCADE,PRIMARY KEY(photo_id,seconds,cluster_id));
    CREATE TABLE IF NOT EXISTS identity_exclusions(
      photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE,pet_id TEXT REFERENCES pets(id) ON DELETE CASCADE,
      PRIMARY KEY(photo_id,pet_id));
    CREATE TABLE IF NOT EXISTS discovery(
      id INTEGER PRIMARY KEY CHECK(id=1),status TEXT,total INTEGER DEFAULT 0,
      processed INTEGER DEFAULT 0,errors INTEGER DEFAULT 0,error TEXT);
    INSERT OR IGNORE INTO discovery(id,status) VALUES(1,'idle');
    UPDATE discovery SET status='interrupted' WHERE status IN ('queued','running');
    ''')
    if 'dismissed' not in {r['name'] for r in c.execute('PRAGMA table_info(identity_clusters)')}:
        c.execute('ALTER TABLE identity_clusters ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0')
    if 'reference_seed' not in {r['name'] for r in c.execute('PRAGMA table_info(identity_clusters)')}:
        c.execute('ALTER TABLE identity_clusters ADD COLUMN reference_seed INTEGER NOT NULL DEFAULT 1')
    if 'phase' not in {r['name'] for r in c.execute('PRAGMA table_info(discovery)')}:
        c.execute("ALTER TABLE discovery ADD COLUMN phase TEXT NOT NULL DEFAULT 'features'")


def normalized(vector):
    vector=np.asarray(vector,dtype=np.float32)
    if vector.shape!=(384,) or not np.isfinite(vector).all() or np.linalg.norm(vector)<1e-8:
        raise ValueError('Invalid identity embedding')
    return vector/np.linalg.norm(vector)


def choose_cluster(vector,candidates):
    """Fixed anchor and centroid prevent single-link chains from joining different pets."""
    scores=[]
    for candidate in candidates:
        samples=candidate['samples']
        if not len(samples):continue
        near=float(np.max(samples@vector))
        center=normalized(samples.mean(axis=0))
        central=float(center@vector)
        anchor=float(candidate['anchor']@vector)
        if near>=NEAREST and central>=CENTROID and anchor>=ANCHOR:
            scores.append((.6*near+.4*central,candidate))
    scores.sort(key=lambda item:(item[0],bool(item[1].get('pet_id')),len(item[1]['samples'])),reverse=True)
    if not scores:return None
    best=scores[0]
    # Two user-merged groups represent one pet, so they do not compete.
    other=next((score for score,c in scores[1:]
                if (not best[1].get('pet_id') or c.get('pet_id')!=best[1]['pet_id'])
                and (c.get('pet_id') or len(c['samples'])>=3)),None)
    if other is not None and best[0]-other<MARGIN:return None
    return best[1]['id']


def candidates(c,species,photo_id,seconds=None):
    groups={}
    for row in c.execute('''SELECT o.cluster_id,o.vector,g.anchor,g.pet_id,g.dismissed,g.reference_seed,o.photo_id,t.seconds
      FROM identity_observations o JOIN identity_clusters g ON g.id=o.cluster_id
      LEFT JOIN video_observation_times t ON t.observation_id=o.id
      JOIN available_photos p ON p.id=o.photo_id
      WHERE o.species=? AND o.excluded=0 AND p.visible=1 AND p.removed=0''',(species,)):
        group=groups.setdefault(row['cluster_id'],{'id':row['cluster_id'],'pet_id':row['pet_id'],
              'dismissed':bool(row['dismissed']),'reference_seed':bool(row['reference_seed']),'anchor':np.frombuffer(row['anchor'],dtype=np.float32),'samples':[],'same_photo':False})
        group['same_photo'] |= row['photo_id']==photo_id and (seconds is None or row['seconds'] is None or row['seconds']==seconds)
        group['samples'].append(np.frombuffer(row['vector'],dtype=np.float32))
    result=[]
    for row in c.execute('SELECT * FROM identity_clusters WHERE species=? AND dismissed=1',(species,)):
        if row['id'] not in groups:
            anchor=np.frombuffer(row['anchor'],dtype=np.float32)
            groups[row['id']]={'id':row['id'],'pet_id':None,'dismissed':True,'anchor':anchor,'samples':[anchor],'same_photo':False}
    occupied={g['pet_id'] for g in groups.values() if g['same_photo'] and g['pet_id']}
    for group in groups.values():
        if group['same_photo'] or group['pet_id'] in occupied:continue
        if group['pet_id'] and not group.get('reference_seed',True):continue
        if group['pet_id'] and c.execute('SELECT 1 FROM identity_exclusions WHERE photo_id=? AND pet_id=?',
                                        (photo_id,group['pet_id'])).fetchone():continue
        group['samples']=np.asarray(group['samples'])
        result.append(group)
    return result


def publish(c,cluster_id,now):
    group=c.execute('SELECT * FROM identity_clusters WHERE id=?',(cluster_id,)).fetchone()
    if group['dismissed']:return
    members=[r['photo_id'] for r in c.execute('''SELECT DISTINCT o.photo_id
      FROM identity_observations o JOIN available_photos p ON p.id=o.photo_id
      WHERE o.cluster_id=? AND o.excluded=0 AND p.visible=1 AND p.removed=0''',(cluster_id,))]
    pet_id=group['pet_id']
    if not pet_id and len(members)>=MIN_PHOTOS:
        pet_id=uuid.uuid4().hex
        c.execute('INSERT INTO pets(id,name,species,cover_id,created_at,unnamed) VALUES(?,?,?,?,?,1)',
                  (pet_id,'未命名'+('猫咪' if group['species']=='cat' else '刺猬'),group['species'],members[0],now))
        c.execute('UPDATE identity_clusters SET pet_id=? WHERE id=?',(pet_id,cluster_id))
    if pet_id:
        for photo_id in members:
            if c.execute('SELECT 1 FROM identity_exclusions WHERE photo_id=? AND pet_id=?',(photo_id,pet_id)).fetchone():continue
            c.execute("INSERT OR IGNORE INTO photo_pets VALUES(?,?,'suggested')",(photo_id,pet_id))


def store(c,photo_id,content_hash,detections,now):
    photo=c.execute('SELECT * FROM photos WHERE id=?',(photo_id,)).fetchone()
    if not photo or photo['content_hash']!=content_hash or photo['removed'] or not photo['visible']:return
    signature=MODEL_VERSION+':'+content_hash
    if photo['identity_hash']==signature:return
    if photo['manual'] and c.execute('SELECT 1 FROM identity_observations WHERE photo_id=? LIMIT 1',(photo_id,)).fetchone():
        c.execute('UPDATE photos SET identity_hash=? WHERE id=?',(signature,photo_id))
        return
    c.execute('DELETE FROM identity_observations WHERE photo_id=?',(photo_id,))
    c.execute('DELETE FROM video_hits WHERE photo_id=?',(photo_id,))
    used={}
    # Stable order plus one observation per group per frame avoids same-frame duplicates.
    for detection in detections:
        species=detection['species'];vector=normalized(detection['vector'])
        if species not in ('cat','hedgehog'):continue
        if photo['manual'] and species not in json.loads(photo['species']):continue
        seconds=detection.get('seconds')
        choices=candidates(c,species,photo_id,seconds)
        occupied=used.setdefault(seconds,set())
        choices=[g for g in choices if g['id'] not in occupied]
        cluster_id=choose_cluster(vector,choices)
        if cluster_id is None:
            cluster_id=next((g['id'] for g in choices if g.get('dismissed') and choose_cluster(vector,[g])),None)
        if cluster_id is None:
            cluster_id=uuid.uuid4().hex
            c.execute('INSERT INTO identity_clusters(id,species,anchor,pet_id) VALUES(?,?,?,NULL)',(cluster_id,species,vector.tobytes()))
        occupied.add(cluster_id)
        if seconds is not None:
            c.execute('INSERT OR IGNORE INTO video_hits VALUES(?,?,?,?)',(photo_id,seconds,species,cluster_id))
            # Keep a video from outweighing many independent photos in later grouping.
            if c.execute('SELECT count(*) FROM identity_observations WHERE photo_id=? AND cluster_id=?',(photo_id,cluster_id)).fetchone()[0]>=8:
                continue
        observation=uuid.uuid4().hex
        c.execute('INSERT INTO identity_observations VALUES(?,?,?,?,?,?,0)',
                  (observation,photo_id,species,json.dumps(detection['box']),vector.tobytes(),cluster_id))
        if seconds is not None:c.execute('INSERT INTO video_observation_times VALUES(?,?)',(observation,seconds))
        publish(c,cluster_id,now)
    c.execute('UPDATE photos SET identity_hash=? WHERE id=?',(signature,photo_id))


def exclude(c,photo_id,pet_id):
    c.execute('INSERT OR IGNORE INTO identity_exclusions VALUES(?,?)',(photo_id,pet_id))
    c.execute('''UPDATE identity_observations SET excluded=1 WHERE photo_id=? AND cluster_id IN
      (SELECT id FROM identity_clusters WHERE pet_id=?)''',(photo_id,pet_id))
    # A user correction must also remove a bad first sample's influence on future matching.
    for group in c.execute('SELECT id FROM identity_clusters WHERE pet_id=?',(pet_id,)).fetchall():
        rows=c.execute('''SELECT o.vector FROM identity_observations o JOIN available_photos p ON p.id=o.photo_id
          WHERE o.cluster_id=? AND o.excluded=0 AND p.visible=1 AND p.removed=0''',(group['id'],)).fetchall()
        if rows:
            samples=np.asarray([np.frombuffer(row['vector'],dtype=np.float32) for row in rows])
            center=normalized(samples.mean(axis=0))
            anchor=samples[int(np.argmax(samples@center))]
            c.execute('UPDATE identity_clusters SET anchor=? WHERE id=?',(anchor.tobytes(),group['id']))


class MergeConflict(ValueError):
    def __init__(self,photos):
        super().__init__('这些照片中检测到了两个不同区域，可能是不同宠物，也可能是重复检测。请查看后确认。')
        self.photos=photos


def merge_many(c,sources,target,confirm_conflicts=False):
    sources=list(dict.fromkeys(sources))
    if not sources or target in sources:raise ValueError('请选择至少两个不同的宠物档案')
    ids=[target,*sources];marks=','.join('?' for _ in ids)
    pets=c.execute('SELECT id,species FROM pets WHERE id IN ('+marks+')',ids).fetchall()
    if len(pets)!=len(ids):raise ValueError('部分宠物档案已不存在，请刷新后重新选择')
    if len({pet['species'] for pet in pets})!=1:raise ValueError('请选择同一种类的宠物，种类错误可先在编辑档案中更正')
    conflicts=c.execute('''SELECT DISTINCT p.id,p.name FROM identity_observations a
        JOIN identity_clusters ga ON ga.id=a.cluster_id JOIN identity_observations b ON b.photo_id=a.photo_id
        JOIN identity_clusters gb ON gb.id=b.cluster_id JOIN available_photos p ON p.id=a.photo_id
        LEFT JOIN video_observation_times ta ON ta.observation_id=a.id LEFT JOIN video_observation_times tb ON tb.observation_id=b.id
        WHERE ga.pet_id IN ('''+marks+') AND gb.pet_id IN ('+marks+''') AND ga.pet_id!=gb.pet_id
          AND coalesce(ta.seconds,0)=coalesce(tb.seconds,0) AND a.excluded=0 AND b.excluded=0 AND p.visible=1 AND p.removed=0 ORDER BY p.id''',ids+ids).fetchall()
    if conflicts and not confirm_conflicts:raise MergeConflict([dict(row) for row in conflicts])
    for source in sources:merge(c,source,target,confirm_conflicts=True)


def correct_species(c,pet_id,new_species):
    pet=c.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
    if not pet:raise ValueError('宠物档案不存在')
    old_species=pet['species']
    if old_species==new_species:return
    if new_species not in ('cat','hedgehog'):raise ValueError('请选择猫咪或刺猬')
    photos=c.execute('SELECT p.* FROM photos p JOIN photo_pets pp ON pp.photo_id=p.id WHERE pp.pet_id=?',(pet_id,)).fetchall()
    c.execute('UPDATE pets SET species=? WHERE id=?',(new_species,pet_id))
    c.execute('UPDATE identity_clusters SET species=? WHERE pet_id=?',(new_species,pet_id))
    c.execute('UPDATE identity_observations SET species=? WHERE cluster_id IN (SELECT id FROM identity_clusters WHERE pet_id=?)',(new_species,pet_id))
    for photo in photos:
        species=set(json.loads(photo['species']));species.add(new_species)
        other_pet=c.execute('''SELECT 1 FROM photo_pets pp JOIN pets pe ON pe.id=pp.pet_id
            WHERE pp.photo_id=? AND pp.pet_id!=? AND pe.species=? LIMIT 1''',(photo['id'],pet_id,old_species)).fetchone()
        other_region=c.execute('''SELECT 1 FROM identity_observations WHERE photo_id=? AND species=? AND excluded=0 LIMIT 1''',(photo['id'],old_species)).fetchone()
        if not other_pet and not other_region:species.discard(old_species)
        c.execute('UPDATE photos SET species=?,manual=1,recognized=1 WHERE id=?',(json.dumps(sorted(species)),photo['id']))


def merge(c,source,target,confirm_conflicts=False):
    source_pet=c.execute('SELECT * FROM pets WHERE id=?',(source,)).fetchone()
    target_pet=c.execute('SELECT * FROM pets WHERE id=?',(target,)).fetchone()
    if not source_pet or not target_pet or source==target:raise ValueError('请选择两个不同的宠物档案')
    if source_pet['species']!=target_pet['species']:raise ValueError('猫咪和刺猬不能合并')
    # Co-occurrence is evidence to review, not a veto over an explicit user correction.
    conflicts=c.execute('''SELECT DISTINCT p.id,p.name FROM identity_observations a JOIN identity_clusters ga ON ga.id=a.cluster_id
      JOIN identity_observations b ON b.photo_id=a.photo_id JOIN identity_clusters gb ON gb.id=b.cluster_id
      JOIN available_photos p ON p.id=a.photo_id
      LEFT JOIN video_observation_times ta ON ta.observation_id=a.id LEFT JOIN video_observation_times tb ON tb.observation_id=b.id
      WHERE ga.pet_id=? AND gb.pet_id=? AND a.excluded=0 AND b.excluded=0
        AND coalesce(ta.seconds,0)=coalesce(tb.seconds,0) AND p.visible=1 AND p.removed=0 ORDER BY p.id''',(source,target)).fetchall()
    if conflicts and not confirm_conflicts:raise MergeConflict([dict(row) for row in conflicts])
    for row in c.execute('SELECT photo_id,status FROM photo_pets WHERE pet_id=?',(source,)).fetchall():
        if c.execute('SELECT 1 FROM identity_exclusions WHERE photo_id=? AND pet_id=?',(row['photo_id'],target)).fetchone():continue
        c.execute('''INSERT INTO photo_pets VALUES(?,?,?) ON CONFLICT(photo_id,pet_id) DO UPDATE
          SET status=CASE WHEN photo_pets.status='confirmed' OR excluded.status='confirmed' THEN 'confirmed' ELSE 'suggested' END''',
          (row['photo_id'],target,row['status']))
    c.execute('UPDATE identity_clusters SET pet_id=? WHERE pet_id=?',(target,source))
    c.execute('UPDATE identity_clusters SET reference_seed=1 WHERE pet_id=?',(target,))
    c.execute('INSERT OR IGNORE INTO identity_exclusions SELECT photo_id,? FROM identity_exclusions WHERE pet_id=?',(target,source))
    c.execute('DELETE FROM photo_pets WHERE pet_id=?',(source,))
    c.execute('DELETE FROM pets WHERE id=?',(source,))


def delete_pet(c,pet_id):
    if not c.execute('SELECT 1 FROM pets WHERE id=?',(pet_id,)).fetchone():raise ValueError('宠物档案不存在')
    # Keep anonymous ignored groups, so reprocessing does not recreate a deleted profile.
    c.execute('UPDATE identity_clusters SET pet_id=NULL,dismissed=1 WHERE pet_id=?',(pet_id,))
    c.execute('DELETE FROM photo_pets WHERE pet_id=?',(pet_id,))
    c.execute('DELETE FROM pets WHERE id=?',(pet_id,))


def regroup(c,now):
    """Attach unpublished groups using frozen references, then publish multi-group families.

    Existing profiles and observation groups are preserved. Frozen anchors avoid
    cascading nearest-neighbour chains turning all members of a species into one pet.
    """
    groups={}
    for row in c.execute('''SELECT o.*,g.anchor,g.pet_id,g.reference_seed FROM identity_observations o
        JOIN identity_clusters g ON g.id=o.cluster_id JOIN available_photos p ON p.id=o.photo_id
        WHERE g.dismissed=0 AND o.excluded=0 AND p.visible=1 AND p.removed=0 ORDER BY o.id'''):
        group=groups.setdefault(row['cluster_id'],{'id':row['cluster_id'],'species':row['species'],
            'pet_id':row['pet_id'],'reference_seed':bool(row['reference_seed']),'anchor':np.frombuffer(row['anchor'],dtype=np.float32),
            'samples':[],'photos':set()})
        group['samples'].append(np.frombuffer(row['vector'],dtype=np.float32));group['photos'].add(row['photo_id'])
    for group in groups.values():
        group['samples']=np.asarray(group['samples']);group['center']=normalized(group['samples'].mean(axis=0))
    pets={row['id']:dict(row) for row in c.execute('SELECT * FROM pets')}
    references=[group for group in groups.values() if group['pet_id'] in pets and group['reference_seed']]
    # Explicitly added photographs also teach an existing/new profile without retraining.
    manual={}
    for row in c.execute('''SELECT pp.pet_id,o.vector,o.photo_id,pe.species FROM photo_pets pp JOIN pets pe ON pe.id=pp.pet_id
        JOIN identity_observations o ON o.photo_id=pp.photo_id AND o.species=pe.species
        JOIN available_photos p ON p.id=o.photo_id
        WHERE pp.status='confirmed' AND o.excluded=0 AND p.visible=1 AND p.removed=0'''):
        ref=manual.setdefault(row['pet_id'],{'id':'manual-'+row['pet_id'],'pet_id':row['pet_id'],
            'species':row['species'],'samples':[],'photos':set()})
        ref['samples'].append(np.frombuffer(row['vector'],dtype=np.float32));ref['photos'].add(row['photo_id'])
    for ref in manual.values():
        ref['samples']=np.asarray(ref['samples']);ref['center']=normalized(ref['samples'].mean(axis=0));ref['anchor']=ref['center']
        references.append(ref)
    exclusions={}
    for row in c.execute('SELECT * FROM identity_exclusions'):
        exclusions.setdefault(row['pet_id'],set()).add(row['photo_id'])
    occupied={}
    for ref in groups.values():
        if ref['pet_id']:occupied.setdefault(ref['pet_id'],set()).update(ref['photos'])
    for ref in references:occupied.setdefault(ref['pet_id'],set()).update(ref['photos'])

    def score(source,target):
        if source['species']!=target['species']:return None
        near=float(np.max(source['samples']@target['samples'].T))
        central=float(source['center']@target['center'])
        anchor=float(source['center']@target['anchor'])
        if near<BATCH_NEAREST or central<BATCH_CENTROID or anchor<BATCH_ANCHOR:return None
        return .65*near+.35*central

    orphan=[group for group in groups.values() if not group['pet_id']]
    proposals=[];unmatched=[]
    for source in orphan:
        pinned={row['pet_id'] for row in c.execute('''SELECT DISTINCT pp.pet_id FROM photo_pets pp JOIN pets p ON p.id=pp.pet_id
            WHERE pp.status='confirmed' AND p.species=? AND pp.photo_id IN ('''+','.join('?' for _ in source['photos'])+')',
            (source['species'],*sorted(source['photos'])))}
        if pinned:
            if len(pinned)==1:
                pet_id=next(iter(pinned))
                if not source['photos'] & exclusions.get(pet_id,set()):
                    c.execute('UPDATE identity_clusters SET pet_id=? WHERE id=?',(pet_id,source['id']))
                    occupied.setdefault(pet_id,set()).update(source['photos']);publish(c,source['id'],now)
            continue
        scores={}
        for target in references:
            pet_id=target['pet_id']
            if source['photos'] & occupied.get(pet_id,set()):continue
            if source['photos'] & exclusions.get(pet_id,set()):continue
            value=score(source,target)
            if value is not None:scores[pet_id]=max(scores.get(pet_id,-1),value + (.006 if not pets[pet_id]['unnamed'] else 0))
        ranked=sorted(scores.items(),key=lambda item:item[1],reverse=True)
        if ranked and (len(ranked)==1 or ranked[0][1]-ranked[1][1]>=MARGIN):proposals.append((ranked[0][1],source,ranked[0][0]))
        else:unmatched.append(source)
    attached=0
    for _,source,pet_id in sorted(proposals,key=lambda item:item[0],reverse=True):
        if source['photos'] & occupied.get(pet_id,set()):unmatched.append(source);continue
        c.execute('UPDATE identity_clusters SET pet_id=?,reference_seed=0 WHERE id=?',(pet_id,source['id']))
        occupied.setdefault(pet_id,set()).update(source['photos'])
        publish(c,source['id'],now);attached+=len(source['photos'])

    # Highest-support seeds first. Each family retains its first anchor even as
    # its sample bank expands, so transitive similarity alone cannot merge it.
    families=[]
    if unmatched:
        centers=np.asarray([source['center'] for source in unmatched])
        support=np.sum(centers@centers.T>=.74,axis=1)
        ordered=sorted(zip(unmatched,support),key=lambda item:(-int(item[1]),-len(item[0]['photos']),item[0]['id']))
        for source,_ in ordered:
            best=None;best_score=-1
            for family in families:
                if source['photos'] & family['photos']:continue
                value=score(source,family)
                if value is not None and value>best_score:best=family;best_score=value
            if best is None:
                families.append({**source,'samples':source['samples'].copy(),'photos':set(source['photos']),'members':[source]})
            else:
                best['members'].append(source);best['photos'].update(source['photos'])
                best['samples']=np.concatenate((best['samples'],source['samples']))
                best['center']=normalized(best['samples'].mean(axis=0))
    created=0
    for family in families:
        if len(family['photos'])<MIN_PHOTOS:continue
        pet_id=uuid.uuid4().hex
        # Prefer ordinary photos over screenshot/montage covers when available.
        covers=c.execute('SELECT id,name FROM photos WHERE id IN ('+','.join('?' for _ in family['photos'])+')',tuple(sorted(family['photos']))).fetchall()
        cover=next((row['id'] for row in covers if 'screenshot' not in row['name'].lower()),covers[0]['id'])
        c.execute('INSERT INTO pets(id,name,species,cover_id,created_at,unnamed) VALUES(?,?,?,?,?,1)',
            (pet_id,'未命名'+('猫咪' if family['species']=='cat' else '刺猬'),family['species'],cover,now))
        for member in family['members']:
            c.execute('UPDATE identity_clusters SET pet_id=?,reference_seed=? WHERE id=?',(pet_id,int(member is family['members'][0]),member['id']))
            publish(c,member['id'],now)
        created+=1;attached+=len(family['photos'])
    return {'attached':attached,'created':created,'version':GROUPING_VERSION}
