"""Evaluate the final multi-model detector and rebuild its identity references."""
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image,ImageDraw,ImageOps
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ousepet.vision import HedgehogDetector,PetReferenceIndex,open_image
from evaluate_trained_hedgehog import iou,measure

OUT=ROOT/'reports/hedgehog-final'


def contact(rows,name):
    import math
    canvas=Image.new('RGB',(1250,math.ceil(len(rows)/5)*245),'#eeeeee');draw=ImageDraw.Draw(canvas)
    for i,r in enumerate(rows):
        thumb=ImageOps.contain(open_image(OUT/'annotated'/f"{r['id']}.jpg"),(240,200));x=i%5*250;y=i//5*245
        canvas.paste(thumb,(x+(250-thumb.width)//2,y+(200-thumb.height)//2))
        draw.text((x+4,y+204),f"{r['id']} boxes={len(r['detections'])} {r['split']}",fill='black')
    canvas.save(OUT/name)


def main():
    torch.set_num_threads(4)
    for name in ['cache','annotated']:(OUT/name).mkdir(parents=True,exist_ok=True)
    source=json.loads((ROOT/'reports/hedgehog-training/split-manifest.json').read_text(encoding='utf-8'))
    source=[r for r in source if r['id'].startswith(('H','C')) or r['split'] in ('val','test')]
    detector=HedgehogDetector()
    version=hashlib.sha256((ROOT/'ousepet/vision.py').read_bytes()+(ROOT/'models/hedgehog-detector-v1/settings.json').read_bytes()+(ROOT/'models/species-verifier-v1/prototypes.npy').read_bytes()).hexdigest()
    rows=[]
    for i,row in enumerate(source):
        cache=OUT/'cache'/f"{row['id']}.json"
        saved=json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
        if saved.get('version')==version:
            result=saved
        else:
            image=open_image(ROOT/row['path']);start=time.perf_counter();found=detector.detect(image);seconds=time.perf_counter()-start
            boxes=[{'box':d.box,'confidence':d.confidence,'source':d.source,'score_kind':d.score_kind,'species_margin':d.species_margin,'iou':iou(d.box,row['box_xyxy']) if row['hedgehog'] else 0.} for d in found]
            result=dict(row,detections=boxes,seconds=seconds,used_fallback=detector.last_used_fallback,version=version)
            cache.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        image=open_image(ROOT/row['path']);draw=ImageDraw.Draw(image)
        for d in result['detections']:
            draw.rectangle(d['box'],outline='#f07824',width=max(4,image.width//200))
            draw.text((d['box'][0],max(0,d['box'][1]-18)),'hedgehog',fill='#f07824')
        ImageOps.contain(image,(1100,1100)).save(OUT/'annotated'/f"{row['id']}.jpg",quality=90)
        rows.append(result)
        print(f"{i+1}/{len(source)} {row['id']} boxes={len(result['detections'])} fallback={result['used_fallback']} {result['seconds']:.2f}s",flush=True)
    test=[r for r in rows if r['split']=='test']
    positive=[r for r in test if r['hedgehog']];negative=[r for r in test if not r['hedgehog']]
    report={'pipeline':'specialized YOLO + COCO proposals + DINOv2 cat/hedgehog prototypes; Grounding DINO fallback; DINOv2 identity suggestions','test':measure(test,0),'test_hedgehogs':measure(positive,0),'test_cat_negatives':measure(negative,0),'validation':measure([r for r in rows if r['split']=='val'],0),'all_local_diagnostic_including_training':measure([r for r in rows if r['id'].startswith(('H','C'))],0),'median_cpu_seconds':float(np.median([r['seconds'] for r in test])),'fast_path_median_seconds':float(np.median([r['seconds'] for r in test if not r['used_fallback']])) if any(not r['used_fallback'] for r in test) else None,'test_fallback_photos':sum(r['used_fallback'] for r in test),'identity_accuracy':None,'limitations':['One hedgehog only; cannot validate discrimination between hedgehog individuals.','Bounding boxes are approximate manual annotations.','The date-separated holdout has been used for development comparisons, so this is not a fresh final acceptance test.','No empty-nest or toy-only negative photographs.','Nested-box suppression has not been validated on multiple overlapping hedgehogs.'],'test_records':test}
    refs=[];ref_images=[]
    for row in rows:
        if row['id'] not in {'H01','H07','H16','H23','H31'} or not row['detections']:continue
        box=max(row['detections'],key=lambda b:b['confidence'])
        refs.append({'id':row['id'],'identity':'扣嘚','species':'hedgehog','source':row['path'],'box':box['box']})
        ref_images.append(open_image(ROOT/row['path']).crop(tuple(box['box'])))
    index=PetReferenceIndex(refs,detector.features.embed(ref_images));index.save(ROOT/'models/references/hedgehog-v1')
    matches=[]
    for row in positive:
        image=open_image(ROOT/row['path']);boxes=row['detections'];vectors=detector.features.embed([image.crop(tuple(b['box'])) for b in boxes])
        matches.append({'id':row['id'],'animals':[{'detection':b,'identity':index.suggest(v,'hedgehog')} for b,v in zip(boxes,vectors)]})
    report['reference_count']=len(refs);report['identity_suggestions']=matches
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'all-records.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    contact([r for r in rows if r['id'].startswith('H')],'hedgehog-results.jpg')
    contact([r for r in rows if r['id'].startswith('C')],'cat-negatives.jpg')
    print('FINAL',json.dumps({k:v for k,v in report.items() if k not in ('test_records','identity_suggestions')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
