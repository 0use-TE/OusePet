"""Run offline hedgehog detection and reference suggestions on a file/directory."""
import argparse
import json
from pathlib import Path
import sys

import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ousepet.vision import AnimalDetector, HedgehogDetector, DinoFeatures, PetReferenceIndex, open_image


def main():
    parser=argparse.ArgumentParser(description='有宠相簿：本地刺猬检测与身份建议')
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/hedgehog-inference')
    parser.add_argument('--references',type=Path,default=ROOT/'models/references/hedgehog-v1')
    parser.add_argument('--backend',choices=['specialized','grounding'],default='specialized')
    parser.add_argument('--grounding-fallback',action='store_true',help='启用较慢的开放词汇备用检测，默认关闭')
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--shortest-edge',type=int,default=480)
    parser.add_argument('--threshold',type=float)
    args=parser.parse_args()
    if not args.input.exists():parser.error('输入文件或目录不存在')
    if args.threshold is not None and not 0<args.threshold<1:parser.error('threshold 必须在 0 和 1 之间')
    torch.set_num_threads(args.threads)
    extensions={'.jpg','.jpeg','.png','.webp','.bmp'}
    files=sorted(p for p in args.input.rglob('*') if p.suffix.lower() in extensions) if args.input.is_dir() else [args.input]
    if not files:parser.error('没有找到支持的图片')
    detector=HedgehogDetector(threshold=args.threshold,allow_fallback=args.grounding_fallback) if args.backend=='specialized' else AnimalDetector(threshold=args.threshold or .35,shortest_edge=args.shortest_edge,longest_edge=800 if args.shortest_edge<=480 else 1333)
    features=detector.features if hasattr(detector,'features') else DinoFeatures()
    index=PetReferenceIndex.load(args.references) if (args.references/'references.json').exists() else None
    args.output.mkdir(parents=True,exist_ok=True)
    records=[]
    for path in files:
        try:
            image=open_image(path)
            detections=detector.detect(image)
            hedgehogs=[d for d in detections if d.species=='hedgehog']
            vectors=features.embed([image.crop(tuple(d.box)) for d in hedgehogs])
            animals=[]
            for detection,vector in zip(hedgehogs,vectors):
                suggestion=index.suggest(vector,'hedgehog') if index else {'status':'unknown_pet','candidates':[],'reason':'no_reference_profile'}
                animals.append({'detection':detection.to_dict(),'identity_suggestion':suggestion})
            record={'path':str(path.resolve()),'status':'needs_confirmation' if animals else 'no_hedgehog_detected','hedgehogs':animals,'other_detections':[d.to_dict() for d in detections if d.species!='hedgehog']}
            print(path.name,record['status'],'hedgehogs='+str(len(animals)),flush=True)
        except (OSError,ValueError) as error:
            record={'path':str(path.resolve()),'status':'error','error':str(error)}
            print(path.name,'ERROR',str(error),flush=True)
        records.append(record)
    output={'model':('YOLO hedgehog proposals + DINO species verifier' if args.backend=='specialized' else 'Grounding DINO Tiny')+' + DINOv2 identity references','device':'cpu','prompt':getattr(detector,'PROMPT',None),'proposal_threshold':detector.threshold,'grounding_fallback':args.grounding_fallback,'image_size':getattr(detector,'image_size',{'imgsz':getattr(detector,'imgsz',None)}),'automatic_identity_assignment':False,'records':records}
    target=args.output/'results.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved:',target,flush=True)
    if all(row['status']=='error' for row in records):raise SystemExit(1)


if __name__=='__main__':main()
