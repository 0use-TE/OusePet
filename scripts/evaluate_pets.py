"""Diagnostic local-pet retrieval with public identity-labelled distractors.

No weights are trained and no auto-archive threshold is fitted to these queries.
Hedgehog crops are explicitly manual annotations, not YOLO detections.
"""
import csv
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageOps
from torchvision import transforms
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/pets'
MANUAL_HEDGEHOG_BOXES = [
    [.10,.18,.87,.92],[.04,.10,.88,.67],[.00,.12,.98,.97],[.22,.30,.79,.95],[.14,.34,.99,.93],
    [.61,.55,.98,.87],[.32,.45,.85,.80],[.25,.31,.68,.70],[.03,.27,.76,.90],[.35,.09,.91,.83],
    [.30,.20,.84,.89],[.26,.10,.87,.97],[.48,.42,.92,.78],[.27,.34,.74,.75],[.31,.35,.78,.75],
    [.58,.40,.89,.81],[.56,.39,.87,.80],[.13,.12,.87,.88],[.15,.31,.99,.91],[.02,.10,.91,.87],
    [.20,.17,.83,.85],[.23,.16,.88,.87],[.17,.05,.97,.89],[.06,.00,.94,.90],[.10,.20,.97,.96],
    [.14,.23,.98,.98],[.26,.27,.98,.92],[.45,.48,.92,.90],[.16,.25,.96,.89],[.06,.35,.98,.92],
    [.00,.12,.99,.89],[.07,.16,.99,.91],[.24,.40,.77,.73],[.09,.22,.94,.99],[.28,.32,.80,.78],
    [.24,.33,.85,.83],[.12,.28,.82,.85],[.60,.22,.99,.82],[.02,.00,.94,.99],[.11,.01,.98,.97],
    [.07,.22,.94,.87],
]


def load_image(path):
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert('RGB')


def date_group(record):
    if record.get('exif_date'):
        return record['exif_date'][:10].replace(':', '-')
    name = Path(record['path']).stem
    match = re.search(r'(20\d{6})_', name)
    if match:
        return datetime.strptime(match.group(1), '%Y%m%d').date().isoformat()
    match = re.search(r'(1\d{12})', name)
    if match:
        return datetime.fromtimestamp(int(match.group(1))/1000, tz=timezone.utc).date().isoformat()
    return 'unknown-' + record['id']


def contact(records, filename, columns=5):
    canvas = Image.new('RGB', (columns*250, math.ceil(len(records)/columns)*235), '#eeeeee')
    draw = ImageDraw.Draw(canvas)
    for i, row in enumerate(records):
        im = load_image(ROOT / row['crop_path'])
        thumb = ImageOps.contain(im, (240, 195))
        x, y = i % columns*250, i//columns*235
        canvas.paste(thumb, (x+(250-thumb.width)//2, y+(195-thumb.height)//2))
        draw.text((x+4,y+198), row['id']+' '+row['role'], fill='black')
    canvas.save(OUT / filename)


def prepare():
    (OUT / 'crops').mkdir(parents=True, exist_ok=True)
    inventory = json.loads((OUT / 'inventory.json').read_text(encoding='utf-8'))
    public = json.loads((ROOT / 'samples/public-cats/manifest.json').read_text(encoding='utf-8'))
    detector = YOLO(str(ROOT / 'models/yolo11n.pt'))
    reference_ids = {'C04','C07','C09','C12','C17'}
    reference_dates = {date_group(r) for r in inventory if r['id'] in reference_ids}
    hedge_refs = {'H01','H07','H16','H23','H31'}
    hedge_dates = {date_group(r) for r in inventory if r['id'] in hedge_refs}
    sources = []
    for row in inventory:
        row = dict(row)
        row['date_group'] = date_group(row)
        row['identity'] = 'Jimi' if row['id'].startswith('C') else 'Koude'
        refs, dates = (reference_ids, reference_dates) if row['identity']=='Jimi' else (hedge_refs, hedge_dates)
        row['role'] = 'reference' if row['id'] in refs else ('excluded_same_day' if row['date_group'] in dates else 'query')
        sources.append(row)
    for i, row in enumerate(public['records']):
        sources.append(dict(row, id='P'+f'{i+1:03d}', label=row['identity'], date_group='public-session-unknown'))
    records=[]
    for i, source in enumerate(sources):
        image = load_image(ROOT / source['path'])
        row = dict(source)
        row['sha256'] = hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest()
        if row['id'].startswith('H'):
            bbox = MANUAL_HEDGEHOG_BOXES[int(row['id'][1:])-1]
            box = [round(v*image.size[j%2]) for j,v in enumerate(bbox)]
            row['crop_method'] = 'manual_box_from_visual_inspection'
            row['detection_status'] = 'not_evaluated_no_hedgehog_detector'
        else:
            result = detector.predict(image, device='cpu', imgsz=640, conf=.25, classes=[15], verbose=False)[0]
            row['cat_detections'] = [{'xyxy':b.xyxy[0].tolist(),'confidence':b.conf.item()} for b in result.boxes]
            row['crop_method'] = 'yolo11n_conf_0.25'
            row['detection_status'] = 'detected' if len(result.boxes) else 'missed'
            if len(result.boxes) != 1:
                row['excluded_reason'] = 'no cat detection' if len(result.boxes)==0 else 'multiple cats; target identity requires manual annotation'
                records.append(row)
                continue
            box = [round(x) for x in result.boxes[0].xyxy[0].tolist()]
        row['box_xyxy'] = box
        crop = image.crop(tuple(box))
        row['crop_path'] = str((OUT/'crops'/f"{row['id']}.jpg").relative_to(ROOT))
        crop.save(ROOT / row['crop_path'], quality=92)
        row['average_hash'] = ''.join('1' if x else '0' for x in (np.asarray(crop.convert('L').resize((8,8))) > np.asarray(crop.convert('L').resize((8,8))).mean()).ravel())
        records.append(row)
        if (i+1)%20==0:print('Prepared',i+1,'/',len(sources),flush=True)
    (OUT/'prepared.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for prefix,name in [('C','jimi-crops.jpg'),('H','hedgehog-manual-crops.jpg'),('P','public-cat-crops.jpg')]:
        subset=[r for r in records if r['id'].startswith(prefix) and 'crop_path' in r]
        if subset:contact(subset,name)
    return records


def embeddings(records, save_prefix=''):
    process=transforms.Compose([transforms.Resize((224,224),interpolation=transforms.InterpolationMode.BICUBIC),transforms.ToTensor(),transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
    sys.path.insert(0,str(ROOT/'.cache/dinov2'))
    from dinov2.hub.backbones import dinov2_vits14
    model=dinov2_vits14(pretrained=False).eval()
    model.load_state_dict(torch.load(ROOT/'models/dinov2_vits14_pretrain.pth',map_location='cpu',weights_only=True))
    options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(ROOT/'models/pet-recognition-base/model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    vectors={'dinov2_small':[],'pet_recognition_base':[]};timings={k:[] for k in vectors}
    usable=[r for r in records if 'crop_path' in r]
    for i in range(0,len(usable),8):
        chunk=usable[i:i+8];batch=torch.stack([process(load_image(ROOT/r['crop_path'])) for r in chunk])
        with torch.inference_mode():
            start=time.perf_counter();dino=F.normalize(model(batch),dim=1).numpy();timings['dinov2_small'].append((time.perf_counter()-start)/len(chunk))
        start=time.perf_counter();pet=session.run(None,{session.get_inputs()[0].name:batch.numpy()})[0];timings['pet_recognition_base'].append((time.perf_counter()-start)/len(chunk))
        pet=pet/np.linalg.norm(pet,axis=1,keepdims=True)
        assert np.isfinite(dino).all() and np.isfinite(pet).all()
        vectors['dinov2_small'].extend(dino);vectors['pet_recognition_base'].extend(pet)
        print('Embedded',min(i+8,len(usable)),'/',len(usable),flush=True)
    for k,v in vectors.items():np.save(OUT/(save_prefix+k+'.npy'),np.asarray(v))
    return usable,{k:np.asarray(v) for k,v in vectors.items()},timings


def compare(usable,vectors):
    refs=[i for i,r in enumerate(usable) if r['role']=='reference' and r['identity']!='Koude']
    query=[i for i,r in enumerate(usable) if r['role'] in ('query','unknown') and r['identity']!='Koude']
    identities=sorted({usable[i]['identity'] for i in refs})
    all_predictions=[];summary={}
    for model,features in vectors.items():
        assert len(features) == len(usable), f'{model}: feature rows must match the photo manifest'
        predictions=[]
        for i in query:
            row=usable[i];candidates=[]
            for identity in identities:
                indices=[j for j in refs if usable[j]['identity']==identity]
                scores=features[indices]@features[i]
                # Fixed rule declared before looking at query results: average top 2 references.
                top=np.argsort(scores)[::-1][:2]
                candidates.append({'identity':identity,'score':float(scores[top].mean()),'nearest_reference':usable[indices[int(top[0])]]['id']})
            candidates.sort(key=lambda c:c['score'],reverse=True)
            prediction={'model':model,'id':row['id'],'true_identity':row['identity'],'role':row['role'],'predicted':candidates[0]['identity'],'score':candidates[0]['score'],'margin':candidates[0]['score']-candidates[1]['score'],'correct':row['identity']==candidates[0]['identity'],'nearest_reference':candidates[0]['nearest_reference'],'candidates':candidates}
            predictions.append(prediction)
        known=[p for p in predictions if p['role']=='query']
        jimi=[p for p in known if p['true_identity']=='Jimi']
        unknown=[p for p in predictions if p['role']=='unknown']
        summary[model]={'known_queries':len(known),'known_correct':sum(p['correct'] for p in known),'jimi_queries':len(jimi),'jimi_correct':sum(p['correct'] for p in jimi),'unknown_queries':len(unknown),'unknown_top_score_range':[min(p['score'] for p in unknown),max(p['score'] for p in unknown)] if unknown else None,'false_jimi_matches_on_non_jimi':sum(p['predicted']=='Jimi' for p in predictions if p['true_identity']!='Jimi'),'errors':[p['id'] for p in known if not p['correct']]}
        # Diagnostic sweeps only, not independently calibrated deployment thresholds.
        summary[model]['uncalibrated_threshold_sweep']=[]
        for threshold in (.5,.6,.7,.8,.9):
            accepted=[p for p in predictions if p['score']>=threshold and p['margin']>=.05]
            summary[model]['uncalibrated_threshold_sweep'].append({'score_threshold':threshold,'margin_threshold':.05,'accepted':len(accepted),'correct':sum(p['correct'] for p in accepted),'unknown_accepted':sum(p['role']=='unknown' for p in accepted)})
        h_refs=[i for i,r in enumerate(usable) if r['identity']=='Koude' and r['role']=='reference']
        h_queries=[i for i,r in enumerate(usable) if r['identity']=='Koude' and r['role']=='query']
        scores=[]
        for i in h_queries:
            sims=features[h_refs]@features[i]
            scores.append({'id':usable[i]['id'],'nearest_reference':usable[h_refs[int(np.argmax(sims))]]['id'],'similarity':float(max(sims))})
        summary[model]['hedgehog_same_individual_similarity_only']={'manual_reference_count':len(h_refs),'query_count':len(scores),'scores':scores,'limitation':'Only one known hedgehog, no other hedgehog negatives. No identity accuracy can be measured. Pet model is cat/dog-specific; its hedgehog results are out-of-domain exploratory only.'}
        all_predictions.extend(predictions)
    return summary,all_predictions


def main():
    torch.set_num_threads(4)
    records=prepare()
    usable,vectors,timings=embeddings(records)
    summary,predictions=compare(usable,vectors)
    detection={}
    for prefix in ['C','P']:
        rows=[r for r in records if r['id'].startswith(prefix)]
        detection[prefix]={'input_photos':len(rows),'photos_with_cat_detection':sum(r['detection_status']=='detected' for r in rows),'single_cat_usable':sum('crop_path' in r for r in rows),'missed':[r['id'] for r in rows if r['detection_status']=='missed'],'multiple_cat_ambiguous':[r['id'] for r in rows if r.get('excluded_reason','').startswith('multiple')]}
    ref_hashes={r['sha256'] for r in usable if r['role']=='reference'}
    duplicate_queries=[r['id'] for r in usable if r['role'] in ('query','unknown') and r['sha256'] in ref_hashes]
    assert not duplicate_queries,duplicate_queries
    # Identify potential near-duplicate leakage for review, without silently calling
    # an arbitrary image-hash cutoff a reliable duplicate detector.
    near=[]
    for q in usable:
        if q['role'] not in ('query','unknown'):continue
        for ref in usable:
            if ref['role']!='reference' or ref['identity']!=q['identity']:continue
            distance=sum(a!=b for a,b in zip(q['average_hash'],ref['average_hash']))
            if distance<=5:near.append({'query':q['id'],'reference':ref['id'],'average_hash_hamming':distance})
    report={'scope':'Diagnostic retrieval experiment, not independent product acceptance. No model training. Local folder names are user-provided identity labels.','public_source':'https://www.kaggle.com/datasets/timost1234/cat-individuals','limitations':['Public subset may overlap pet-recognition-base training identities.','Public reference/query session dates are unknown; public split is not session-independent.','Local query photos from every reference calendar date are excluded.','Hedgehog boxes were manually drawn, not automatically detected.','Threshold sweep is exploratory; no auto-archive threshold is validated.'],'detection':detection,'split':{'local_references':[r['id'] for r in records if r['role']=='reference' and not r['id'].startswith('P')],'excluded_same_day':[r['id'] for r in records if r['role']=='excluded_same_day']},'potential_near_duplicate_pairs':near,'models':summary,'mean_seconds_per_crop_in_batches_including_first_batch':{k:float(np.mean(v)) for k,v in timings.items()}}
    (OUT/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'predictions.json').write_text(json.dumps(predictions,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (OUT/'predictions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['model','id','true_identity','role','predicted','score','margin','correct','nearest_reference'])
        writer.writeheader();writer.writerows({k:p[k] for k in writer.fieldnames} for p in predictions)
    byid={r['id']:r for r in usable}
    for model in vectors:
        ranked=sorted([p for p in predictions if p['model']==model and p['true_identity']=='Jimi'],key=lambda p:p['score'])
        pairs=[]
        for p in ranked[:5]:
            pairs.extend([dict(byid[p['id']],role=f"query score={p['score']:.3f}"),dict(byid[p['nearest_reference']],role=f"reference {p['predicted']}")])
        if pairs:contact(pairs,model+'-jimi-hardest.jpg',columns=2)
    print('DONE',json.dumps({'detection':detection,'models':{k:{kk:vv for kk,vv in v.items() if kk not in ('hedgehog_same_individual_similarity_only','uncalibrated_threshold_sweep')} for k,v in summary.items()}},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
