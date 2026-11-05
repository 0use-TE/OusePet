"""Diagnostic grouping of cached labelled crop features; not independent calibration."""
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ousepet import identity

records=[r for r in json.loads((ROOT/'reports/pets/prepared.json').read_text(encoding='utf-8')) if 'crop_path' in r]
features=np.load(ROOT/'reports/pets/dinov2_small.npy')
groups=[]
for record,vector in zip(records,features):
    species='hedgehog' if record['id'].startswith('H') else 'cat'
    candidates=[{**g,'samples':np.asarray(g['samples'])} for g in groups if g['species']==species]
    match=identity.choose_cluster(vector,candidates)
    if match is None:
        group={'id':str(len(groups)),'species':species,'anchor':vector,'samples':[],'records':[]}
        groups.append(group)
    else:group=next(g for g in groups if g['id']==match)
    group['samples'].append(vector);group['records'].append(record)
visible=[g for g in groups if len(g['records'])>=identity.MIN_PHOTOS]
report={'scope':'Diagnostic only; cached crops include manual hedgehog boxes and unknown public-session overlap. Thresholds are conservative heuristics, not validated identity probabilities.',
        'photos':len(records),'min_photos':identity.MIN_PHOTOS,
        'thresholds':{'nearest':identity.NEAREST,'centroid':identity.CENTROID,'anchor':identity.ANCHOR,'margin':identity.MARGIN},
        'visible_groups':[{'species':g['species'],'photos':[r['id'] for r in g['records']],
                           'identities':sorted({r['identity'] for r in g['records']})} for g in visible],
        'subthreshold_groups':len(groups)-len(visible),
        'mixed_visible_groups':sum(len({r['identity'] for r in g['records']})>1 for g in visible)}
out=ROOT/'reports/identity';out.mkdir(exist_ok=True)
(out/'cached-crop-diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
