"""Verify deployed cancellation/discovery with a temporary, isolated NAS storage."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

HOST='192.168.1.80'
BASE=f'http://{HOST}:8766'
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/nas';(OUT/'ui').mkdir(parents=True,exist_ok=True)
token='scan-qa-'+uuid.uuid4().hex
directory='/vol1/1000/OusePet/test-photos/'+token
name='临时扫描验证'
sid=None;errors=[]
def remote_python(code):
    return subprocess.run(['ssh',HOST,'python3 -'],input=code,text=True,encoding='utf-8',check=True,capture_output=True)
def state():return client.get('/api/state').json()
def job(ident):return next(j for j in state()['jobs'] if j['id']==ident)

with httpx.Client(base_url=BASE,trust_env=False,timeout=30) as client:
    remote_python(f'from pathlib import Path\nPath({directory!r}).mkdir()\n')
    try:
        response=client.post('/api/storages',json={'path':'/test-photos/'+token,'name':name})
        response.raise_for_status();storage=response.json();sid=storage['id']
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1300,'height':900})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(BASE+'/?view=storage')
            page.get_by_role('button',name='扫描任务',exact=True).click()
            cancel=page.get_by_role('button',name='取消扫描'+name,exact=True)
            if cancel.count():cancel.click()
            else:
                # On an idle NAS the empty initial job may already have completed.
                client.patch(f'/api/storages/{sid}',json={'auto_scan':False}).raise_for_status()
            page.get_by_role('button',name='关闭',exact=True).click()
            with tempfile.TemporaryDirectory() as temporary:
                image=Path(temporary)/'automatic.png'
                Image.new('RGB',(65,49),(27,134,201)).save(image)
                subprocess.run(['scp','-q',str(image),HOST+':'+directory+'/automatic.png'],check=True)
            remote_python(f'import os,time\np={directory+"/automatic.png"!r}\nos.utime(p,(time.time()-30,time.time()-30))\n')
            page.reload()
            switch=page.get_by_role('switch',name=name+'自动增量扫描',exact=True)
            expect(switch).to_have_attribute('aria-checked','false')
            switch.click();expect(switch).to_have_attribute('aria-checked','true')
            # No manual scan or second add-storage call: the production watcher must discover it.
            deadline=time.monotonic()+75
            detected=None
            while time.monotonic()<deadline:
                detected=next((j for j in state()['jobs'] if j['storage_id']==sid and j['id']!=storage['job_id'] and j['total']==1),None)
                if detected:break
                time.sleep(1)
            assert detected,'production watcher did not discover the new photo'
            page.reload();page.get_by_role('button',name='扫描任务',exact=True).click()
            cancel=page.get_by_role('button',name='取消扫描'+name,exact=True)
            cancelled=False
            if cancel.count():
                page.screenshot(path=str(OUT/'ui'/'scan-cancel-nas.png'))
                cancel.click()
                expect(page.locator('.task').filter(has_text=name).first).to_contain_text('已取消')
                assert job(detected['id'])['status']=='cancelled'
                cancelled=True
            page.get_by_role('button',name='关闭',exact=True).click()
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(OUT/'ui'/'scan-storage-nas-mobile.png'))
            assert not errors,errors
            browser.close()
        report={'base':BASE,'temporary_storage':sid,'automatic_job':detected,'cancelled_automatic_job':cancelled,
                'initial_job':job(storage['job_id']),'page_errors':errors}
        (OUT/'incremental-live-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True,indent=2))
    finally:
        if sid:
            client.patch(f'/api/storages/{sid}',json={'auto_scan':False})
            for item in state()['jobs']:
                if item['storage_id']==sid and item['status'] in ('running','queued','paused'):
                    client.post(f'/api/jobs/{item["id"]}/cancel')
            # Remove only rows belonging to the temporary storage, never user photos.
            code=f'''import sqlite3
c=sqlite3.connect('/data/album.sqlite3',timeout=30)
c.execute('PRAGMA foreign_keys=ON')
sid={sid!r}
assert c.execute('SELECT path FROM storages WHERE id=?',(sid,)).fetchone()[0]=={'/test-photos/'+token!r}
c.execute('DELETE FROM scan_files WHERE storage_id=?',(sid,))
c.execute('DELETE FROM photos WHERE storage_id=?',(sid,))
c.execute('DELETE FROM storages WHERE id=?',(sid,))
c.commit()
'''
            subprocess.run(['ssh',HOST,'sudo -n docker exec -i ousepet-album python -'],input=code,text=True,check=True)
        remote_python(f'from pathlib import Path\nimport shutil\np=Path({directory!r})\nassert p.parent==Path("/vol1/1000/OusePet/test-photos") and p.name=={token!r}\nshutil.rmtree(p)\n')
