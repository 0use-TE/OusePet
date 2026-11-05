"""Build cat/hedgehog feature prototypes from the training split only."""
import json
from pathlib import Path
import sys
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ousepet.vision import DinoFeatures,open_image


def main():
    torch.set_num_threads(4)
    prepared=json.loads((ROOT/'reports/pets/prepared.json').read_text(encoding='utf-8'))
    usable=[r for r in prepared if 'crop_path' in r]
    vectors=np.load(ROOT/'reports/pets/dinov2_small.npy')
    assert len(vectors)==len(usable)
    cached={r['path']:v for r,v in zip(usable,vectors)}
    splits=json.loads((ROOT/'reports/hedgehog-training/split-manifest.json').read_text(encoding='utf-8'))
    features=DinoFeatures();groups={'cat':[],'hedgehog':[]};manifest=[]
    for r in splits:
        if r['split']!='train':continue
        vector=cached.get(r['path'])
        if vector is None:
            vector=features.embed([open_image(ROOT/r['path'])])[0]
        species='hedgehog' if r['hedgehog'] else 'cat'
        groups[species].append(vector);manifest.append({'id':r['id'],'source':r['path'],'species':species})
    species=['cat','hedgehog']
    prototypes=np.stack([np.mean(groups[s],axis=0) for s in species])
    prototypes/=np.linalg.norm(prototypes,axis=1,keepdims=True)
    directory=ROOT/'models/species-verifier-v1';directory.mkdir(parents=True,exist_ok=True)
    np.save(directory/'prototypes.npy',prototypes)
    settings={'feature_model':'DINOv2 Small','species':species,'minimum_hedgehog_similarity':.55,'minimum_species_margin':.05,'score_kind':'cosine_similarity_not_probability','training_samples':manifest,'note':'Species prototypes are trained only on training images. No identity classifier or colour rules are used.'}
    (directory/'settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({s:len(groups[s]) for s in species},flush=True)


if __name__=='__main__':main()
