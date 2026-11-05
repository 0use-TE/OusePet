"""A second, explicit experiment: higher resolution and rotation on missed cats."""
import json
import time

import numpy as np
import torch
from ultralytics import YOLO

import evaluate_pets as evaluation

ROOT, OUT = evaluation.ROOT, evaluation.OUT
torch.set_num_threads(4)
records = json.loads((OUT/'prepared.json').read_text(encoding='utf-8'))
usable = [r for r in records if 'crop_path' in r]
model = YOLO(str(ROOT/'models/yolo11n.pt'))
recovered, failed = [], []
for row in records:
    if not row['id'].startswith('C') or 'crop_path' in row:
        continue
    image = evaluation.load_image(ROOT/row['path'])
    attempts=[]
    for angle in (0,90,180,270):
        rotated=image.rotate(angle,expand=True)
        start=time.perf_counter()
        result=model.predict(rotated,device='cpu',imgsz=960,conf=.15,classes=[15],verbose=False)[0]
        attempts.append({'rotation':angle,'seconds':time.perf_counter()-start,'boxes':len(result.boxes)})
        if len(result.boxes)!=1:
            continue
        box=[round(x) for x in result.boxes[0].xyxy[0].tolist()]
        crop=rotated.crop(tuple(box))
        path=OUT/'crops'/f"{row['id']}-fallback.jpg"
        crop.save(path,quality=92)
        updated=dict(row,crop_path=str(path.relative_to(ROOT)),crop_method='yolo11n_960_conf_0.15_rotation_retry',rotation_degrees=angle,box_xyxy_in_rotated_image=box,detection_status='detected_fallback',fallback_confidence=result.boxes[0].conf.item(),attempts=attempts)
        updated.pop('excluded_reason',None)
        recovered.append(updated)
        print('Recovered',row['id'],'rotation',angle,'confidence',round(updated['fallback_confidence'],3),flush=True)
        break
    else:
        failed.append({'id':row['id'],'attempts':attempts})
        print('Still missed',row['id'],flush=True)
if recovered:
    evaluation.contact(recovered,'jimi-fallback-crops.jpg')
    new,extra_vectors,timings=evaluation.embeddings(recovered, save_prefix='fallback-')
    combined={k:np.concatenate([np.load(OUT/(k+'.npy')),extra_vectors[k]],axis=0) for k in extra_vectors}
    summary,predictions=evaluation.compare(usable+new,combined)
else:
    summary={};predictions=[]
result={'experiment':'Higher-resolution and rotation retry only on baseline missed Jimi photos. Crop correctness requires visual review. No model training or threshold calibration.','recovered':[r['id'] for r in recovered],'still_missed':[r['id'] for r in failed],'baseline_detected':sum(r['id'].startswith('C') for r in usable),'after_fallback_detected':sum(r['id'].startswith('C') for r in usable)+len(recovered),'total_jimi_photos':31,'recovered_records':recovered,'failed_records':failed,'models':summary}
(OUT/'fallback-evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'fallback-predictions.json').write_text(json.dumps(predictions,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Fallback done',json.dumps({'recovered':result['recovered'],'still_missed':result['still_missed'],'models':{k:{'jimi_queries':v['jimi_queries'],'jimi_correct':v['jimi_correct'],'errors':v['errors']} for k,v in summary.items()}}),flush=True)
