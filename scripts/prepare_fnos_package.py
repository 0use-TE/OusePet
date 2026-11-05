"""Assemble the NAS desktop integration package, using the approved application icon."""
from pathlib import Path
import tarfile,shutil
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'deploy/fnos/ousepet'
stage=ROOT/'.cache/fnos-package/ousepet'
shutil.copytree(source,stage,dirs_exist_ok=True)
with Image.open(ROOT/'assets/branding/logo-rounded-v2.png') as original:
    for size,target in [(64,'ICON.PNG'),(256,'ICON_256.PNG'),(64,'app/ui/images/icon_64.png'),(256,'app/ui/images/icon_256.png')]:
        path=stage/target;path.parent.mkdir(parents=True,exist_ok=True)
        original.resize((size,size),Image.Resampling.LANCZOS).save(path)
for name in ['install_init','install_callback','uninstall_init','uninstall_callback','upgrade_init','upgrade_callback','config_init','config_callback']:
    (stage/'cmd'/name).write_text('#!/bin/bash\nexit 0\n',encoding='utf-8')
(stage/'wizard').mkdir(exist_ok=True)
with tarfile.open(ROOT/'.cache/fnos-package.tar','w') as archive:
    def modes(info):
        if '/cmd/' in info.name:info.mode=0o755
        return info
    archive.add(stage,arcname='ousepet',filter=modes)
print('Prepared .cache/fnos-package.tar')
