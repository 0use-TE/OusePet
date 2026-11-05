"""Actual browser + isolated API checks for cancellation and automatic scan controls."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/ui';OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='ousepet-scan-ui-') as temp:
    root=Path(temp);photos=root/'photos';photos.mkdir()
    Image.new('RGB',(100,80),'orange').save(photos/'test.png')
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(photos),OUSEPET_WATCH_INTERVAL='1')
    from ousepet import api as module
    started=threading.Event();release=threading.Event()
    def slow_infer(ident):
        started.set();assert release.wait(30)
        module.apply_recognition(ident,{'species':['cat'],'pets':[]})
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(module.app,host='127.0.0.1',port=port,log_level='error'))
    with patch.object(module,'infer_photo',side_effect=slow_infer):
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        base=f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.05)
            with httpx.Client(base_url=base,trust_env=False) as client, sync_playwright() as p:
                storage=client.post('/api/storages',json={'path':str(photos),'name':'测试照片'}).json()
                assert started.wait(5)
                browser=p.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1100,'height':820})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base);page.get_by_role('button',name='扫描任务',exact=True).click()
                expect(page.get_by_role('button',name='取消扫描测试照片')).to_be_visible()
                page.screenshot(path=str(OUT/'scan-cancel-desktop.png'))
                page.get_by_role('button',name='取消扫描测试照片').click()
                expect(page.locator('.task').first).to_contain_text('已取消')
                assert client.get('/api/state').json()['storages'][0]['auto_scan']==0
                release.set();module.POOL.submit(lambda:None).result(timeout=5)
                assert client.get('/api/state').json()['jobs'][0]['status']=='cancelled'
                page.get_by_role('button',name='关闭',exact=True).click()
                page.get_by_role('button',name='存储管理',exact=True).click()
                toggle=page.get_by_role('switch',name='测试照片自动增量扫描')
                expect(toggle).to_have_attribute('aria-checked','false')
                toggle.click();expect(toggle).to_have_attribute('aria-checked','true')
                page.reload();expect(toggle).to_have_attribute('aria-checked','true')
                page.set_viewport_size({'width':390,'height':844})
                page.wait_for_timeout(250)
                expect(toggle).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(OUT/'scan-incremental-mobile.png'))
                # A paused job provides a stable mobile cancellation target.
                paused=module.uid()
                with module.db() as c:c.execute('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',(paused,storage['id'],'paused',module.now()))
                page.reload();page.get_by_role('button',name='扫描任务',exact=True).click()
                page.screenshot(path=str(OUT/'scan-cancel-mobile.png'))
                page.get_by_role('button',name='取消扫描测试照片').click()
                expect(page.locator('.task').first).to_contain_text('已取消')
                # Remove one terminal record, then clear remaining history while active work stays.
                page.get_by_role('button',name='删除任务记录测试照片',exact=True).first.click()
                expect(page.get_by_role('button',name='删除任务记录测试照片',exact=True)).to_have_count(1)
                active=module.uid()
                with module.db() as c:c.execute('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',(active,storage['id'],'running',module.now()))
                assert client.delete('/api/jobs/'+active).status_code==409
                page.reload();page.get_by_role('button',name='扫描任务',exact=True).click()
                page.get_by_role('button',name='清空历史记录',exact=True).click()
                expect(page.locator('.task')).to_have_count(1)
                expect(page.locator('.task')).to_contain_text('正在整理')
                expect(page.get_by_role('button',name='清空历史记录',exact=True)).to_be_disabled()
                with module.db() as c:
                    c.executemany('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',[(module.uid(),storage['id'],'complete',module.now()) for _ in range(20)])
                page.reload();page.get_by_role('button',name='扫描任务',exact=True).click()
                expect(page.locator('.task').first).to_contain_text('正在整理')
                footer=page.get_by_role('button',name='清空历史记录',exact=True).bounding_box()
                assert footer and footer['y']+footer['height']<=844
                page.get_by_role('button',name='清空历史记录',exact=True).click()
                expect(page.locator('.task')).to_have_count(1)
                page.screenshot(path=str(OUT/'scan-history-mobile.png'))
                assert not errors,errors
                browser.close()
        finally:
            release.set();server.should_exit=True;thread.join(timeout=10)
print('PASS: desktop/mobile cancellation, no completion overwrite, automatic switch persistence, no overflow or page errors')
