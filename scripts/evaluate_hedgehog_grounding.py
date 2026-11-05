"""Evaluate hedgehog detection and reference retrieval on local positives/negatives."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ousepet.vision import AnimalDetector, DinoFeatures, PetReferenceIndex, open_image

OUT=ROOT/'reports/hedgehog-grounding'
REF_IDS={'H01','H07','H16','H23','H31'}


def overlap(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
    return area/union if union>0 else 0.


def annotate(image,detections,path):
    image=image.copy();draw=ImageDraw.Draw(image)
    for d in detections:
        color='#ef6b29' if d['species']=='hedgehog' else '#12b8c4'
        draw.rectangle(d['box'],outline=color,width=max(3,image.width//250))
        draw.text((d['box'][0],max(0,d['box'][1]-20)),f"{d['species']} {d['confidence']:.2f}",fill=color,stroke_width=1)
    ImageOps.contain(image,(1200,1200)).save(path,quality=90)


def contact(rows,name):
    import math
    canvas=Image.new('RGB',(1250,math.ceil(len(rows)/5)*250),'#eeeeee');draw=ImageDraw.Draw(canvas)
    for i,r in enumerate(rows):
        image=open_image(OUT/'annotated'/f"{r['id']}.jpg")
        thumb=ImageOps.contain(image,(240,205));x=i%5*250;y=i//5*250
        canvas.paste(thumb,(x+(250-thumb.width)//2,y+(205-thumb.height)//2))
        best=max([d.get('iou',0) for d in r['detections'] if d['species']=='hedgehog'],default=0)
        draw.text((x+4,y+208),f"{r['id']} hedge={r['hedgehog_count']} IoU={best:.2f}",fill='black')
    canvas.save(OUT/name)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pilot',action='store_true');args=parser.parse_args()
    torch.set_num_threads(4)
    for name in ['cache','annotated','crops']:(OUT/name).mkdir(parents=True,exist_ok=True)
    source=json.loads((ROOT/'reports/pets/prepared.json').read_text(encoding='utf-8'))
    source=[r for r in source if r['id'].startswith(('H','C'))]
    if args.pilot:source=[r for r in source if r['id'] in REF_IDS]
    detector=AnimalDetector(shortest_edge=480,longest_edge=800)
    manifest=json.loads((ROOT/'models/grounding-dino-tiny/download-manifest.json').read_text(encoding='utf-8'))
    settings={'checkpoint_revision':manifest['revision'],'prompt':detector.PROMPT,'postprocess':detector.POSTPROCESS_VERSION,'threshold':detector.threshold,'text_threshold':detector.text_threshold,'image_size':detector.image_size,'transformers':'4.57.1','device':'cpu'}
    config_hash=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()
    rows=[]
    for i,row in enumerate(source):
        image=open_image(ROOT/row['path'])
        digest=hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()
        cache=OUT/'cache'/f"{row['id']}.json"
        saved=json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
        if saved.get('config_hash')==config_hash and saved.get('source_sha256')==digest:
            record=saved
        else:
            start=time.perf_counter();detections=[d.to_dict() for d in detector.detect(image)];seconds=time.perf_counter()-start
            expected='hedgehog' if row['id'].startswith('H') else 'cat'
            if expected=='hedgehog':
                for d in detections:d['iou']=overlap(d['box'],row['box_xyxy'])
            record={'id':row['id'],'path':row['path'],'role':row['role'],'expected_species':expected,'config_hash':config_hash,'source_sha256':digest,'seconds':seconds,'detections':detections,'hedgehog_count':sum(d['species']=='hedgehog' for d in detections),'matched_hedgehog_iou_0_5':expected=='hedgehog' and any(d['species']=='hedgehog' and d['iou']>=.5 for d in detections)}
            cache.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        annotate(image,record['detections'],OUT/'annotated'/f"{row['id']}.jpg")
        rows.append(record)
        print(f"{i+1}/{len(source)} {record['id']} hedgehogs={record['hedgehog_count']} matched={record['matched_hedgehog_iou_0_5']} seconds={record['seconds']:.2f}",flush=True)
    if args.pilot:
        (OUT/'pilot.json').write_text(json.dumps({'settings':settings,'records':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        contact(rows,'pilot.jpg');return
    positives=[r for r in rows if r['expected_species']=='hedgehog'];negatives=[r for r in rows if r['expected_species']=='cat']
    heldout=[r for r in positives if r['role']=='query']
    summary={'settings':settings,'positive_photos':len(positives),'positive_any_hedgehog_box':sum(r['hedgehog_count']>0 for r in positives),'positive_matched_iou_0_5':sum(r['matched_hedgehog_iou_0_5'] for r in positives),'heldout_date_query_photos':len(heldout),'heldout_date_matched_iou_0_5':sum(r['matched_hedgehog_iou_0_5'] for r in heldout),'cat_negative_photos':len(negatives),'cat_negative_photos_with_false_hedgehog':sum(r['hedgehog_count']>0 for r in negatives),'missed_or_poor_boxes':[r['id'] for r in positives if not r['matched_hedgehog_iou_0_5']],'false_positives':[r['id'] for r in negatives if r['hedgehog_count']>0],'median_seconds_per_photo':float(np.median([r['seconds'] for r in rows])),'limitations':['Manual bounding boxes are approximate and have not been independently reviewed.','One known hedgehog only; detection success cannot establish individual discrimination.','No empty-room/toy-only negative photos in this evaluation.'],'records':rows}
    # Reference images must be automatically detected too; no hand-selected crop fallback.
    features=DinoFeatures()
    ref_records=[];ref_crops=[]
    for row in positives:
        if row['id'] not in REF_IDS:continue
        choices=[d for d in row['detections'] if d['species']=='hedgehog']
        if not choices:continue
        best=max(choices,key=lambda d:d['confidence'])
        ref_records.append({'id':row['id'],'identity':'扣嘚','species':'hedgehog','source':row['path'],'box':best['box']})
        ref_crops.append(open_image(ROOT/row['path']).crop(tuple(best['box'])))
    if ref_crops:
        index=PetReferenceIndex(ref_records,features.embed(ref_crops));index.save(ROOT/'models/references/hedgehog')
        matches=[]
        for row in heldout:
            choices=[d for d in row['detections'] if d['species']=='hedgehog']
            if not choices:
                matches.append({'id':row['id'],'status':'no_hedgehog_detected'});continue
            # Every animal box is processed separately; no forced image-level identity.
            image=open_image(ROOT/row['path'])
            crops=[image.crop(tuple(d['box'])) for d in choices]
            vectors=features.embed(crops)
            matches.append({'id':row['id'],'animals':[{'detection':d,**index.suggest(v,'hedgehog')} for d,v in zip(choices,vectors)]})
        summary['reference_matching']={'automatic_reference_count':len(ref_records),'reference_ids':[r['id'] for r in ref_records],'results':matches,'individual_accuracy':None}
    (OUT/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    contact(positives,'hedgehogs.jpg');contact(negatives,'cat-negatives.jpg')
    print('DONE',json.dumps({k:v for k,v in summary.items() if k not in ('records','reference_matching')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
