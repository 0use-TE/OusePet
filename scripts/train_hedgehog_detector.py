"""Fine-tune a one-class hedgehog detector with date-separated holdout data."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ousepet.vision import open_image

import torch
from PIL import ImageOps
from ultralytics import YOLO
import yaml


def prepare():
    destination=ROOT/'.cache/hedgehog-dataset'
    rows=json.loads((ROOT/'reports/pets/prepared.json').read_text(encoding='utf-8'))
    selected=[]
    for row in rows:
        if not row['id'].startswith(('H','C')):continue
        hedge=row['id'].startswith('H')
        if row['role']=='query':split='test'
        elif hedge and row['date_group'] in ('2026-08-29','2026-10-02'):split='val'
        elif not hedge and row['date_group']=='2026-10-19':split='val'
        else:split='train'
        selected.append(dict(row,split=split,hedgehog=hedge))
    public=json.loads((ROOT/'samples/public-cats/manifest.json').read_text(encoding='utf-8'))['records']
    for i,row in enumerate(public):
        number=int(row['identity'].split('-')[1])
        if number<=4 and row['role']=='reference':split='train'
        elif number==5 and row['role']=='reference':split='val'
        elif number>=6:split='test'
        else:continue
        selected.append(dict(row,id=f'PUB{i+1:03d}',date_group='public-session-unknown',hedgehog=False,split=split))
    # Save EXIF-corrected copies. Originals remain untouched.
    for row in selected:
        image=open_image(ROOT/row['path'])
        width,height=image.size
        stem=row['id']
        image_dir=destination/'images'/row['split'];label_dir=destination/'labels'/row['split']
        image_dir.mkdir(parents=True,exist_ok=True);label_dir.mkdir(parents=True,exist_ok=True)
        ImageOps.contain(image,(1280,1280)).save(image_dir/(stem+'.jpg'),quality=95)
        if row['hedgehog']:
            x1,y1,x2,y2=row['box_xyxy']
            label=f'0 {(x1+x2)/2/width:.8f} {(y1+y2)/2/height:.8f} {(x2-x1)/width:.8f} {(y2-y1)/height:.8f}\n'
        else:label=''
        (label_dir/(stem+'.txt')).write_text(label)
    config={'path':str(destination),'train':'images/train','val':'images/val','test':'images/test','names':{0:'hedgehog'}}
    (destination/'dataset.yaml').write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
    report=ROOT/'reports/hedgehog-training';report.mkdir(parents=True,exist_ok=True)
    (report/'split-manifest.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for split in ('train','val','test'):
        subset=[r for r in selected if r['split']==split]
        print(split,'hedgehog',sum(r['hedgehog'] for r in subset),'negative',sum(not r['hedgehog'] for r in subset),flush=True)
    # Enforce date separation for local positives and negatives, and identity
    # separation for public negative cats. Never choose best weights using test.
    for prefix in ('H','C'):
        days={s:{r['date_group'] for r in selected if r['split']==s and r['id'].startswith(prefix)} for s in ('train','val','test')}
        assert not (days['train']&days['val'] or days['train']&days['test'] or days['val']&days['test']),days
    return destination/'dataset.yaml'


def main():
    os.environ['YOLO_OFFLINE']='true'
    torch.set_num_threads(8)
    path=prepare()
    model=YOLO(str(ROOT/'models/yolo11n.pt'))
    model.train(data=str(path),epochs=60,imgsz=416,batch=4,nbs=4,device='cpu',workers=0,
        project=str(ROOT/'reports/hedgehog-training'),name='run-v2',exist_ok=True,
        freeze=10,optimizer='AdamW',lr0=.001,lrf=.1,patience=20,
        seed=20261104,deterministic=True,amp=False,plots=False,
        mosaic=.5,close_mosaic=8,degrees=20,flipud=.25,fliplr=.5,
        hsv_h=.015,hsv_s=.4,hsv_v=.4,cache='ram',verbose=False)
    print('TRAINING_COMPLETE',flush=True)


if __name__=='__main__':main()
