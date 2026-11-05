"""Measure actual cat + hedgehog inference on the NAS, including CUDA synchronization."""
import argparse,json,statistics,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from ousepet.vision import HedgehogDetector,open_image

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--root',default='/test-photos')
    parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--output')
    args=parser.parse_args()
    torch.set_num_threads(4)
    files=sorted(p for p in Path(args.root).rglob('*') if p.suffix.lower() in ('.jpg','.jpeg','.png'))
    if not files:raise RuntimeError('No benchmark photos found')
    chosen=[files[0],files[len(files)//2],files[-1]]
    # Pick one cat and two hedgehog views when the test fixture layout is available.
    cats=[p for p in files if '猫咪' in str(p)];hedges=[p for p in files if '刺猬' in str(p)]
    if cats and hedges:chosen=[cats[len(cats)//2],hedges[len(hedges)//2],hedges[-1]]
    images=[open_image(p) for p in chosen]
    started=time.perf_counter();model=HedgehogDetector(device=args.device)
    def run():
        results=[]
        for image in images:
            hedges=model.detect(image)
            cats=model.proposal_model.predict(image,device=args.device,imgsz=640,conf=.25,classes=[15],verbose=False)[0]
            results.append({'hedgehogs':len(hedges),'cat_boxes':len(cats.boxes)})
        if args.device!='cpu':torch.cuda.synchronize()
        return results
    run();initial=time.perf_counter()-started
    timings=[]
    for _ in range(args.repeat):
        started=time.perf_counter();detections=run();timings.append(time.perf_counter()-started)
    report={'torch':torch.__version__,'cuda':torch.version.cuda,'cuda_available':torch.cuda.is_available(),'device':args.device,'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,'arch_list':torch.cuda.get_arch_list() if torch.cuda.is_available() else [],'photos':[str(p) for p in chosen],'initialization_and_warmup_seconds':initial,'batch_seconds':timings,'median_seconds_per_photo':statistics.median(timings)/len(images),'detections':detections,'peak_gpu_memory_mb':torch.cuda.max_memory_allocated()/1048576 if args.device!='cpu' else 0}
    if args.output:Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))

if __name__=='__main__':main()
