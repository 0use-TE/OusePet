"""Fetch a pinned official HF model through the local proxy, verifying weights."""
import concurrent.futures
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
META=json.loads((ROOT/'.cache/grounding-dino-metadata.json').read_text(encoding='utf-8'))
DEST=ROOT/'models/grounding-dino-tiny'
DEST.mkdir(parents=True,exist_ok=True)
os.environ['NO_PROXY']=''
opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'}))
BASE='https://huggingface.co/IDEA-Research/grounding-dino-tiny/resolve/'+META['sha']+'/'
manifest=[]
for item in META['siblings']:
    name=item['rfilename']
    if name.startswith('.') or name=='pytorch_model.bin':continue
    size=item['size'];target=DEST/name
    if size>10*1024*1024:
        partdir=DEST/(name+'.chunks');partdir.mkdir(exist_ok=True)
        step=4*1024*1024
        def fetch(start):
            end=min(start+step,size)-1;part=partdir/str(start)
            if part.exists() and part.stat().st_size==end-start+1:return
            for attempt in range(5):
                try:
                    req=urllib.request.Request(BASE+name+'?chunk='+str(start),headers={'Range':f'bytes={start}-{end}'})
                    with opener.open(req,timeout=45) as response:
                        assert response.status==206
                        assert response.headers.get('Content-Range','').startswith(f'bytes {start}-{end}/')
                        data=response.read(end-start+2)
                    assert len(data)==end-start+1
                    part.write_bytes(data);return
                except Exception:
                    if attempt==4:raise
                    time.sleep(1+attempt)
        starts=list(range(0,size,step))
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            futures=[pool.submit(fetch,start) for start in starts]
            for i,future in enumerate(concurrent.futures.as_completed(futures),1):
                future.result()
                if i%12==0 or i==len(starts):print(f'{name}: {i}/{len(starts)} chunks',flush=True)
        temporary=DEST/(name+'.part')
        with temporary.open('wb') as output:
            for start in starts:output.write((partdir/str(start)).read_bytes())
        digest=hashlib.file_digest(temporary.open('rb'),'sha256').hexdigest()
        assert digest==item['lfs']['sha256'],digest
        temporary.replace(target)
        for start in starts:(partdir/str(start)).unlink()
        partdir.rmdir()
    else:
        with opener.open(BASE+name,timeout=40) as response:data=response.read()
        assert len(data)==size,(name,len(data),size)
        target.write_bytes(data)
        digest=hashlib.sha256(data).hexdigest()
    manifest.append({'file':name,'bytes':size,'sha256':digest})
    print('Verified',name,size,flush=True)
(DEST/'download-manifest.json').write_text(json.dumps({'repo':META['id'],'revision':META['sha'],'files':manifest},indent=2)+'\n',encoding='utf-8')
print('Grounding DINO model download complete.',flush=True)
