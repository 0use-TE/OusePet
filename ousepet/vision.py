"""Offline animal detection and reference-image retrieval.

Detection confidence and reference cosine similarity are distinct quantities.
No identity score is treated as an automatically calibrated probability.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sys

import numpy as np
from PIL import Image, ImageOps
import torch
import torch.nn.functional as F
from torchvision import transforms
from torchvision.ops import nms

ROOT = Path(__file__).resolve().parents[1]


def open_image(path):
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert('RGB')


@dataclass
class Detection:
    species: str
    confidence: float
    box: list[float]
    text_label: str
    source: str | None = None
    score_kind: str = 'detector_score'
    species_margin: float | None = None

    def to_dict(self):
        return asdict(self)


class AnimalDetector:
    """Grounding DINO Tiny with explicit competition between species terms."""
    PROMPT = 'a hedgehog. a cat.'
    POSTPROCESS_VERSION = 'species-token-mean-v1'

    def __init__(self, model_dir=None, threshold=.35, text_threshold=.25, device='cpu', shortest_edge=800, longest_edge=1333):
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
        directory = Path(model_dir or ROOT/'models/grounding-dino-tiny')
        self.processor = AutoProcessor.from_pretrained(directory, local_files_only=True)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(directory, local_files_only=True).to(device).eval()
        # Use the supported pure-PyTorch attention path on CPU and older GPUs.
        self.model.config.disable_custom_kernels = True
        self.threshold, self.text_threshold, self.device = threshold, text_threshold, device
        self.image_size={'shortest_edge':shortest_edge,'longest_edge':longest_edge}
        offsets=self.processor.tokenizer(self.PROMPT,return_offsets_mapping=True)['offset_mapping']
        self.term_positions={}
        for species in ('hedgehog','cat'):
            span=re.search(r'\b'+species+r'\b',self.PROMPT).span()
            self.term_positions[species]=[i for i,(start,end) in enumerate(offsets) if end>span[0] and start<span[1]]
            if not self.term_positions[species]:
                raise ValueError('Cannot locate species tokens in the detector prompt')

    @torch.inference_mode()
    def detect(self, image):
        image = ImageOps.exif_transpose(image).convert('RGB')
        inputs = self.processor(images=image, text=self.PROMPT, return_tensors='pt', size=self.image_size).to(self.device)
        outputs = self.model(**inputs)
        # Standard phrase decoding can concatenate both names when both cross a
        # token threshold. Compare the actual species tokens instead of assigning
        # a mixed string to an arbitrary species, or prompting only "hedgehog"
        # and accidentally accepting a cat that resembles one.
        probabilities=outputs.logits[0].sigmoid().cpu()
        species_scores=torch.stack([probabilities[:,self.term_positions[s]].mean(dim=1) for s in ('hedgehog','cat')],dim=1)
        scores,indices=species_scores.max(dim=1)
        cx,cy,w,h=outputs.pred_boxes[0].cpu().unbind(-1)
        boxes=torch.stack([(cx-w/2)*image.width,(cy-h/2)*image.height,(cx+w/2)*image.width,(cy+h/2)*image.height],dim=1)
        detections = []
        for query in (scores>=self.threshold).nonzero().flatten().tolist():
            box=boxes[query].tolist();score=scores[query].item()
            species=('hedgehog','cat')[indices[query].item()]
            if probabilities[query,self.term_positions[species]].min().item()<self.text_threshold:
                continue
            if abs(species_scores[query,0].item()-species_scores[query,1].item())<.05:
                species='ambiguous'
            label='a '+species
            bounds = [max(0., min(float(v), float(image.width if i%2==0 else image.height))) for i,v in enumerate(box)]
            if bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:
                continue
            detections.append(Detection(species, float(score), bounds, label))
        kept = []
        for species in ('hedgehog', 'cat', 'ambiguous'):
            group = [d for d in detections if d.species==species]
            if group:
                indices=nms(torch.tensor([d.box for d in group]), torch.tensor([d.confidence for d in group]), .5)
                kept.extend(group[i] for i in indices.tolist())
        return sorted(kept, key=lambda d:d.confidence, reverse=True)


class DinoFeatures:
    def __init__(self, weights=None, device='cpu'):
        source = ROOT/'.cache/dinov2'
        if not source.exists():
            raise FileNotFoundError('Missing official DINOv2 source checkout: '+str(source))
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from dinov2.hub.backbones import dinov2_vits14
        self.device=device
        self.model=dinov2_vits14(pretrained=False)
        self.model.load_state_dict(torch.load(weights or ROOT/'models/dinov2_vits14_pretrain.pth', map_location='cpu', weights_only=True))
        self.model=self.model.to(device).eval()
        self.process=transforms.Compose([
            transforms.Resize((224,224),interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.ToTensor(),transforms.Normalize([.485,.456,.406],[.229,.224,.225]),
        ])

    @torch.inference_mode()
    def embed(self, images):
        if not images:
            return np.empty((0,384),dtype=np.float32)
        batch=torch.stack([self.process(image.convert('RGB')) for image in images]).to(self.device)
        result=F.normalize(self.model(batch),dim=1).cpu().numpy()
        if not np.isfinite(result).all():
            raise ValueError('Non-finite image embeddings')
        return result


class YoloHedgehogDetector:
    """A small dedicated detector; cats remain a separate model/task."""
    def __init__(self, model_dir=None, threshold=None, device='cpu'):
        import json
        from ultralytics import YOLO
        directory=Path(model_dir or ROOT/'models/hedgehog-detector-v1')
        settings=json.loads((directory/'settings.json').read_text(encoding='utf-8'))
        self.threshold=settings['threshold'] if threshold is None else threshold
        self.imgsz=settings['imgsz']
        self.device=device
        self.model=YOLO(str(directory/'detector.pt'))
        if self.model.names!={0:'hedgehog'}:
            raise ValueError('This checkpoint is not the dedicated hedgehog detector')

    @torch.inference_mode()
    def detect(self,image):
        image=ImageOps.exif_transpose(image).convert('RGB')
        result=self.model.predict(image,conf=self.threshold,imgsz=self.imgsz,device=self.device,verbose=False)[0]
        return [Detection('hedgehog',float(box.conf.item()),box.xyxy[0].tolist(),'hedgehog') for box in result.boxes]


class HedgehogDetector:
    """Multi-model proposals, DINO species verification, and optional fallback.

The returned score is a species-prototype cosine similarity, not a probability.
"""
    def __init__(self, model_dir=None, threshold=None, device='cpu', allow_fallback=False):
        import json
        from ultralytics import YOLO
        self.device=device;self.threshold=.2 if threshold is None else threshold
        self.primary=YoloHedgehogDetector(model_dir=model_dir,threshold=self.threshold,device=device)
        self.proposal_model=YOLO(str(ROOT/'models/yolo11n.pt'))
        self.imgsz=416
        self.features=DinoFeatures(device=device)
        directory=ROOT/'models/species-verifier-v1'
        settings=json.loads((directory/'settings.json').read_text(encoding='utf-8'))
        self.prototypes=np.load(directory/'prototypes.npy')
        self.minimum_similarity=settings['minimum_hedgehog_similarity']
        self.minimum_margin=settings['minimum_species_margin']
        self.allow_fallback=allow_fallback;self.fallback=None
        self.last_used_fallback=False

    def verify(self,image,candidates):
        if not candidates:return []
        candidates=sorted(candidates,key=lambda d:d.confidence,reverse=True)[:20]
        vectors=self.features.embed([image.crop(tuple(d.box)) for d in candidates])
        scores=vectors@self.prototypes.T
        verified=[]
        for d,pair in zip(candidates,scores):
            cat,hedgehog=map(float,pair);margin=hedgehog-cat
            if hedgehog>=self.minimum_similarity and margin>=self.minimum_margin:
                verified.append(Detection('hedgehog',hedgehog,d.box,'hedgehog',d.source,'species_reference_cosine',margin))
        if not verified:return []
        # A face/part box almost contained in a verified body box should not
        # become a second animal. Preserve boxes that overlap only partially.
        whole=[]
        for i,d in enumerate(verified):
            area=(d.box[2]-d.box[0])*(d.box[3]-d.box[1])
            contained=False
            for j,other in enumerate(verified):
                other_area=(other.box[2]-other.box[0])*(other.box[3]-other.box[1])
                if i==j or other_area<=area*1.3:continue
                intersection=max(0,min(d.box[2],other.box[2])-max(d.box[0],other.box[0]))*max(0,min(d.box[3],other.box[3])-max(d.box[1],other.box[1]))
                if intersection/area>=.9:
                    contained=True;break
            if not contained:whole.append(d)
        verified=whole
        kept=nms(torch.tensor([d.box for d in verified]),torch.tensor([d.confidence for d in verified]),.45)
        return [verified[i] for i in kept.tolist()]

    @torch.inference_mode()
    def detect(self,image):
        image=ImageOps.exif_transpose(image).convert('RGB')
        candidates=self.primary.detect(image)
        for d in candidates:d.source='specialized_yolo'
        result=self.proposal_model.predict(image,conf=.2,imgsz=640,device=self.device,classes=[14,15,16,21],verbose=False)[0]
        for b in result.boxes:
            candidates.append(Detection('proposal',float(b.conf.item()),b.xyxy[0].tolist(),result.names[int(b.cls.item())],'coco_yolo_proposal'))
        verified=self.verify(image,candidates)
        self.last_used_fallback=False
        if not verified and self.allow_fallback:
            self.last_used_fallback=True
            if self.fallback is None:
                self.fallback=AnimalDetector(threshold=.2,device=self.device,shortest_edge=480,longest_edge=800)
            candidates=self.fallback.detect(image)
            for d in candidates:d.source='grounding_proposal'
            verified=self.verify(image,candidates)
        return verified


class PetReferenceIndex:
    """Explicit reference bank, with species filtering and no automatic confirmation."""
    def __init__(self, records, vectors):
        self.records=list(records)
        self.vectors=np.asarray(vectors,dtype=np.float32)
        if len(self.records)!=len(self.vectors):
            raise ValueError('Reference manifest and feature counts do not match')

    def suggest(self, vector, species):
        candidates=[]
        identities=sorted({r['identity'] for r in self.records if r['species']==species})
        for identity in identities:
            indices=[i for i,r in enumerate(self.records) if r['identity']==identity and r['species']==species]
            scores=self.vectors[indices]@vector
            order=np.argsort(scores)[::-1]
            candidates.append({'identity':identity,'similarity':float(scores[order[:2]].mean()),'nearest_reference':self.records[indices[int(order[0])]]['id']})
        candidates.sort(key=lambda c:c['similarity'],reverse=True)
        margin=candidates[0]['similarity']-candidates[1]['similarity'] if len(candidates)>1 else None
        return {'status':'needs_confirmation' if candidates else 'unknown_pet', 'candidates':candidates, 'top_two_margin':margin, 'reason':'uncalibrated_reference_matching' if len(candidates)>1 else 'only_one_known_individual_no_identity_discrimination_test'}

    def save(self, directory):
        import json
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        (directory/'references.json').write_text(json.dumps(self.records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        np.save(directory/'features.npy',self.vectors)

    @classmethod
    def load(cls, directory):
        import json
        directory=Path(directory)
        return cls(json.loads((directory/'references.json').read_text(encoding='utf-8')),np.load(directory/'features.npy'))
