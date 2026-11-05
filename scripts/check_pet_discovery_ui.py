"""Browser + real API flow: discover, name, incremental match, merge and correct."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import httpx
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright,expect
import uvicorn

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/identity/ui';OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='ousepet-identity-ui-') as temp:
    root=Path(temp);library=root/'photos';library.mkdir()
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(library),OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    sid=m.uid();storage={'id':sid,'path':str(library)}
    with m.db() as c:c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'UI fixtures',str(library),m.now()))
    def photo(index,group):
        path=library/f'pet-{group}-{index}.png';Image.new('RGB',(180,160),(group*70,index+10,30)).save(path)
        ident,_=m.index_file(storage,path)
        with m.db() as c:c.execute("UPDATE photos SET visible=1,recognized=1,species='[\"cat\"]' WHERE id=?",(ident,))
        return ident
    def extract(image):
        v=np.zeros(384,dtype=np.float32);v[image.getpixel((0,0))[0]//70]=1
        return ['cat'],[{'species':'cat','box':[0,0,180,160],'vector':v}]
    for group in (1,2):
        for index in range(5):photo(index,group)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(m.app,host='127.0.0.1',port=port,log_level='error'))
    with patch.object(m,'detect_identity',side_effect=extract):
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.05)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False) as client,sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1300,'height':900})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{port}/?view=pets')
                page.get_by_role('button',name='发现宠物',exact=True).click()
                unnamed=page.locator('.pet-card').filter(has_text='未命名猫咪')
                expect(unnamed).to_have_count(2,timeout=15000)
                page.screenshot(path=str(OUT/'unnamed-desktop.png'))
                unnamed.first.get_by_role('button',name='编辑未命名猫咪',exact=True).click()
                page.get_by_label('宠物名字',exact=True).fill('小橘')
                page.get_by_role('button',name='保存档案',exact=True).click()
                named=page.locator('.pet-card').filter(has_text='小橘')
                expect(named).to_have_count(1)
                named_id=next(pet['id'] for pet in client.get('/api/state').json()['pets'] if pet['name']=='小橘')
                # The first discovered group corresponds to the first five indexed files.
                extra=photo(6,1);m.infer_photo(extra)
                page.reload();expect(named).to_contain_text('6 张照片')
                # Simulate a second detection region in one existing photo, assigned to the other group.
                with m.db() as c:
                    source=c.execute('SELECT id FROM pets WHERE unnamed=1').fetchone()[0]
                    cluster=c.execute('SELECT id FROM identity_clusters WHERE pet_id=?',(source,)).fetchone()[0]
                    observation=c.execute('SELECT o.* FROM identity_observations o JOIN identity_clusters g ON g.id=o.cluster_id WHERE g.pet_id=? LIMIT 1',(named_id,)).fetchone()
                    c.execute('INSERT INTO identity_observations VALUES(?,?,?,?,?,?,0)',(m.uid(),observation['photo_id'],'cat','[50,0,100,50]',observation['vector'],cluster))
                unnamed.locator('.pet-select').click()
                named.locator('.pet-open').click()
                page.get_by_role('button',name='合并宠物',exact=True).click()
                page.get_by_role('button',name='保留宠物档案',exact=True).click()
                page.get_by_role('option',name='小橘 · 6 张',exact=True).click()
                page.get_by_role('button',name='确认合并',exact=True).click()
                conflict=page.get_by_role('region',name='合并冲突照片')
                expect(conflict).to_be_visible()
                assert len(client.get('/api/state').json()['pets'])==2,'review must not merge'
                expect(conflict.locator('img')).to_have_count(1)
                with page.expect_popup() as opened:
                    conflict.get_by_role('link').first.click()
                image_page=opened.value
                image_page.wait_for_load_state()
                assert image_page.locator('img').evaluate('(img)=>img.naturalWidth')>0
                image_page.close()
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUT/'merge-conflict-mobile.png'))
                page.get_by_role('button',name='确认是同一只，继续合并',exact=True).click()
                page.set_viewport_size({'width':1300,'height':900})
                expect(page.locator('h1')).to_have_text('宠物档案')
                assert page.locator('.photo-tile').count()==0
                assert not any(pet['unnamed'] for pet in client.get('/api/state').json()['pets'])
                expect(named).to_contain_text('11 张照片')
                named.locator('.pet-open').click()
                expect(page.locator('h1')).to_have_text('小橘')
                page.locator('.select-photo').first.click()
                page.get_by_role('button',name='移出此宠物',exact=True).click()
                expect(page.locator('.photo-tile')).to_have_count(10)
                assert client.get('/api/photos?view=all').json()['total']==11
                page.get_by_role('button',name='宠物档案',exact=True).click()
                page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(OUT/'named-mobile.png'))
                named.get_by_role('button',name='编辑小橘',exact=True).click()
                page.get_by_label('宠物名字',exact=True).fill('小橘的新名字')
                page.get_by_role('button',name='保存档案',exact=True).click()
                page.reload();expect(page.locator('.pet-card').filter(has_text='小橘的新名字')).to_contain_text('10 张照片')
                renamed=page.locator('.pet-card').filter(has_text='小橘的新名字')
                renamed.get_by_role('button',name='删除小橘的新名字',exact=True).click()
                expect(page.get_by_role('dialog',name='删除宠物档案')).to_be_visible()
                page.get_by_role('button',name='保留档案',exact=True).click()
                expect(renamed).to_have_count(1)
                renamed.get_by_role('button',name='删除小橘的新名字',exact=True).click()
                page.screenshot(path=str(OUT/'delete-pet-mobile.png'))
                page.get_by_role('button',name='确认删除',exact=True).click()
                expect(renamed).to_have_count(0)
                page.reload();expect(renamed).to_have_count(0)
                assert client.get('/api/photos?view=all').json()['total']==11
                assert not errors,errors
                expect(page.get_by_role('button',name='待确认',exact=True)).to_have_count(0)
                page.get_by_role('button',name='导航',exact=True).click()
                page.get_by_role('button',name='存储管理',exact=True).click()
                page.get_by_role('button',name='移除存储UI fixtures',exact=True).click()
                expect(page.get_by_role('dialog',name='移除存储位置')).to_be_visible()
                page.get_by_role('button',name='取消',exact=True).click()
                expect(page.locator('.storage-card')).to_have_count(1)
                page.get_by_role('button',name='移除存储UI fixtures',exact=True).click()
                page.screenshot(path=str(OUT/'remove-storage-mobile.png'))
                page.get_by_role('button',name='移除存储位置',exact=True).click()
                expect(page.locator('.storage-card')).to_have_count(0)
                assert client.get('/api/photos?view=all').json()['total']==0
                restored=client.post('/api/storages',json={'path':str(library),'name':'UI fixtures'});restored.raise_for_status()
                page.reload();expect(page.locator('.storage-card')).to_have_count(1)
                assert client.get('/api/photos?view=all').json()['total']==11
                page.goto(f'http://127.0.0.1:{port}/?view=review')
                expect(page.locator('h1')).to_have_text('宠物图库')
                page.locator('.photo-open').first.click()
                expect(page.get_by_role('button',name='确认宠物身份',exact=True)).to_have_count(0)
                page.keyboard.press('Escape')
                page.get_by_role('button',name='设置',exact=True).click()
                page.get_by_role('button',name='数据管理',exact=True).click()
                page.get_by_role('button',name='重新扫描文件夹',exact=True).click()
                expect(page.get_by_role('dialog',name='扫描任务')).to_be_visible()
                page.keyboard.press('Escape')
                page.get_by_role('button',name='设置',exact=True).click()
                page.get_by_role('button',name='数据管理',exact=True).click()
                page.get_by_role('button',name='清空数据并重新识别',exact=True).click()
                reset=page.get_by_role('dialog',name='清空数据并重新识别')
                expect(reset.get_by_role('button',name='清空并重新识别',exact=True)).to_be_disabled()
                page.get_by_label('请输入“清空并重新识别”以确认',exact=True).fill('清空')
                expect(reset.get_by_role('button',name='清空并重新识别',exact=True)).to_be_disabled()
                page.keyboard.press('Escape')
                expect(page.get_by_role('dialog',name='设置')).to_be_visible()
                assert client.get('/api/photos?view=all').json()['total']==11
                page.get_by_role('button',name='清空数据并重新识别',exact=True).click()
                page.get_by_label('请输入“清空并重新识别”以确认',exact=True).fill('清空并重新识别')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(OUT/'reset-library-mobile.png'))
                page.get_by_role('button',name='清空并重新识别',exact=True).click()
                expect(page.get_by_role('dialog',name='扫描任务')).to_be_visible()
                for _ in range(100):
                    state=client.get('/api/state').json()
                    if state['reset_task']['status']=='complete' and all(job['status']=='complete' for job in state['jobs']):break
                    time.sleep(.05)
                assert state['reset_task']['status']=='complete' and state['counts']['library']==11
                assert all(pet['unnamed'] for pet in state['pets'])
                assert not errors,errors
                browser.close()
        finally:server.should_exit=True;thread.join(timeout=10)
print('PASS: UI discovery threshold, naming, incremental match, merge, correction, mobile and persistence; no page errors')
