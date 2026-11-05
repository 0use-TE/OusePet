"""Test the unmodified closed-vocabulary detector on all hedgehog originals."""
import json
from collections import Counter

import torch
from PIL import Image, ImageDraw, ImageOps
from ultralytics import YOLO

from evaluate_pets import ROOT, OUT, MANUAL_HEDGEHOG_BOXES, load_image


def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union>0 else 0


torch.set_num_threads(4)
model=YOLO(str(ROOT/'models/yolo11n.pt'))
inventory=[r for r in json.loads((OUT/'inventory.json').read_text(encoding='utf-8')) if r['id'].startswith('H')]
folder=OUT/'hedgehog-detection';folder.mkdir(exist_ok=True)
records=[]
for index,row in enumerate(inventory):
    image=load_image(ROOT/row['path'])
    manual=[round(v*image.size[j%2]) for j,v in enumerate(MANUAL_HEDGEHOG_BOXES[int(row['id'][1:])-1])]
    result=model.predict(image,device='cpu',imgsz=640,conf=.25,verbose=False)[0]
    detections=[]
    for box in result.boxes:
        bounds=box.xyxy[0].tolist()
        detections.append({'class':result.names[int(box.cls.item())],'confidence':float(box.conf.item()),'xyxy':bounds,'iou_with_manual_hedgehog':iou(bounds,manual)})
    records.append(dict(row,detections=detections))
    if index in (0,2,6,15,24,32) or any(d['iou_with_manual_hedgehog']>=.3 for d in detections):
        result.save(filename=str(folder/(row['id']+'.jpg')))
    if (index+1)%10==0:print('Tested',index+1,'/',len(inventory),flush=True)
overlaps=[dict(d,image=row['id']) for row in records for d in row['detections'] if d['iou_with_manual_hedgehog']>=.3]
summary={'model':'yolo11n.pt, original COCO checkpoint','device':'cpu','input_photos':len(records),'settings':{'imgsz':640,'conf':.25,'classes_filter':None},'available_classes':model.names,'has_hedgehog_class':any('hedgehog' in name.lower() for name in model.names.values()),'all_detected_object_counts':dict(Counter(d['class'] for r in records for d in r['detections'])),'photos_with_no_detections':[r['id'] for r in records if not r['detections']],'boxes_overlapping_manual_hedgehog_at_iou_0_3':overlaps,'interpretation':'A box overlapping a hedgehog but labelled another COCO class is not a correct hedgehog recognition. Manual boxes are used only to audit overlap, never provided as model input.','records':records}
(folder/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in ('available_classes','records')},ensure_ascii=False),flush=True)
