"""Calibrate on validation only, then evaluate the untouched test split once."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from PIL import ImageDraw, ImageOps
import torch
from ultralytics import YOLO

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ousepet.vision import DinoFeatures, PetReferenceIndex, open_image

OUT=ROOT/'reports/hedgehog-trained'


def iou(a,b):
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    total=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
    return overlap/total if total else 0.


def predict(model,row):
    image=open_image(ROOT/row['path'])
    start=time.perf_counter()
    result=model.predict(image,conf=.01,imgsz=416,device='cpu',verbose=False)[0]
    boxes=[]
    for box in result.boxes:
        bounds=box.xyxy[0].tolist()
        boxes.append({'box':bounds,'confidence':box.conf.item(),'iou':iou(bounds,row['box_xyxy']) if row['hedgehog'] else 0.})
    return dict(row,detections=boxes,seconds=time.perf_counter()-start)


def measure(rows,threshold):
    tp=fp=fn=any_positive=negative_fp=0
    for row in rows:
        boxes=[b for b in row['detections'] if b['confidence']>=threshold]
        if row['hedgehog']:
            any_positive+=bool(boxes)
            match=any(b['iou']>=.5 for b in boxes)
            tp+=match;fn+=not match;fp+=len(boxes)-int(match)
        else:
            fp+=len(boxes);negative_fp+=bool(boxes)
    return {'threshold':threshold,'positive_photos':sum(r['hedgehog'] for r in rows),'negative_photos':sum(not r['hedgehog'] for r in rows),'positive_photos_with_any_box':any_positive,'true_positive_boxes_iou_0_5':tp,'false_positive_boxes':fp,'false_negative_photos':fn,'negative_photos_with_false_hedgehog':negative_fp,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None}


def main():
    torch.set_num_threads(4)
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'annotated').mkdir(exist_ok=True)
    source=json.loads((ROOT/'reports/hedgehog-training/split-manifest.json').read_text(encoding='utf-8'))
    checkpoint=ROOT/'reports/hedgehog-training/run-v2/weights/best.pt'
    model=YOLO(str(checkpoint))
    validation=[predict(model,r) for r in source if r['split']=='val']
    sweep=[measure(validation,float(t)) for t in np.arange(.1,.91,.05)]
    safe=[s for s in sweep if s['negative_photos_with_false_hedgehog']==0 and s['true_positive_boxes_iou_0_5']>0]
    if not safe:raise RuntimeError('Validation cannot find a usable threshold without false cat detections; model not promoted')
    chosen=max(safe,key=lambda s:(s['true_positive_boxes_iou_0_5'],-s['false_positive_boxes'],s['threshold']))
    threshold=round(chosen['threshold'],2)
    calibration={'selection':'Validation only: zero negative-photo false detections, maximise matched positives, minimise extra boxes, then prefer a higher threshold.','selected_threshold':threshold,'sweep':sweep}
    (OUT/'calibration.json').write_text(json.dumps(calibration,indent=2)+'\n',encoding='utf-8')
    print('Validation threshold locked:',threshold,chosen,flush=True)
    # The held-out split is first touched only after threshold is locked to disk.
    test=[predict(model,r) for r in source if r['split']=='test']
    test_metrics=measure(test,threshold)
    local_h=[r for r in test if r['id'].startswith('H')]
    local_cat=[r for r in test if r['id'].startswith('C')]
    public_cat=[r for r in test if r['id'].startswith('PUB')]
    asset=ROOT/'models/hedgehog-detector-v1';asset.mkdir(parents=True,exist_ok=True)
    shutil.copy2(checkpoint,asset/'detector.pt')
    settings={'model':'YOLO11n fine-tuned one-class hedgehog detector','imgsz':416,'threshold':threshold,'base_model':'yolo11n.pt','model_sha256':hashlib.sha256((asset/'detector.pt').read_bytes()).hexdigest(),'calibration':'validation only; see reports/hedgehog-trained/calibration.json','automatic_identity_assignment':False,'training_data_limitation':'17 training hedgehog photos of one individual; not a general hedgehog-population benchmark'}
    (asset/'settings.json').write_text(json.dumps(settings,indent=2)+'\n',encoding='utf-8')
    # Produce full local diagnostics too, clearly separate from held-out metrics.
    local_source=[r for r in source if r['id'].startswith(('H','C'))]
    available={r['id']:r for r in validation+test}
    local=[available[r['id']] if r['id'] in available else predict(model,r) for r in local_source]
    for row in local:
        image=open_image(ROOT/row['path']);draw=ImageDraw.Draw(image)
        for box in row['detections']:
            if box['confidence']<threshold:continue
            draw.rectangle(box['box'],outline='#ef7c24',width=max(4,image.width//180))
            draw.text((box['box'][0],max(0,box['box'][1]-20)),f"hedgehog {box['confidence']:.2f}",fill='#ef7c24')
        ImageOps.contain(image,(1100,1100)).save(OUT/'annotated'/f"{row['id']}.jpg",quality=90)
    refs={'H01','H07','H16','H23','H31'};ref_records=[];ref_images=[]
    for row in local:
        if row['id'] not in refs:continue
        boxes=[b for b in row['detections'] if b['confidence']>=threshold]
        if not boxes:continue
        box=max(boxes,key=lambda b:b['confidence'])
        ref_records.append({'id':row['id'],'identity':'扣嘚','species':'hedgehog','source':row['path'],'box':box['box']})
        ref_images.append(open_image(ROOT/row['path']).crop(tuple(box['box'])))
    if not ref_records:raise RuntimeError('No reference images automatically detected')
    features=DinoFeatures();bank=PetReferenceIndex(ref_records,features.embed(ref_images));bank.save(ROOT/'models/references/hedgehog-v1')
    suggestions=[]
    for row in local_h:
        boxes=[b for b in row['detections'] if b['confidence']>=threshold]
        image=open_image(ROOT/row['path'])
        vectors=features.embed([image.crop(tuple(b['box'])) for b in boxes])
        suggestions.append({'id':row['id'],'animals':[{'detection':b,**bank.suggest(v,'hedgehog')} for b,v in zip(boxes,vectors)]})
    report={'test':test_metrics,'test_hedgehogs':measure(local_h,threshold),'test_local_cat_negatives':measure(local_cat,threshold),'test_public_cat_negatives':measure(public_cat,threshold),'validation':measure(validation,threshold),'local_all_including_training_diagnostic_only':measure(local,threshold),'median_cpu_seconds_per_photo':float(np.median([r['seconds'] for r in test])),'reference_count':len(ref_records),'reference_ids':[r['id'] for r in ref_records],'individual_accuracy':None,'identity_suggestions':suggestions,'limitations':['Only one hedgehog identity. Detection is not individual identification.','Bounding boxes are approximate manual annotations.','No empty-nest/toy-only negatives yet.','All test photos were excluded from training and calibration by local capture date or public cat identity.'],'test_records':test}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'local-diagnostics.json').write_text(json.dumps(local,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('FINAL',json.dumps({k:v for k,v in report.items() if k not in ('test_records','identity_suggestions')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
