"""Real browser/API: multi-card merge and species correction, isolated fixtures."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import httpx
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright,expect
import uvicorn

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/ui';OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='ousepet-pet-bulk-ui-') as temporary:
    root=Path(temporary);library=root/'photos';library.mkdir();image=library/'fixture.png';Image.new('RGB',(100,80),'#876f9c').save(image)
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(library),OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('storage','fixture',str(library),m.now()))
        for ident,name,species,n,unnamed in [('target','基米','cat',3,0),('a','来源甲','cat',2,0),('b','来源乙','cat',2,0),('wrong','未命名猫咪','cat',6,1),('hedge','扣嘚','hedgehog',2,0)]:
            c.execute('INSERT INTO pets(id,name,species,created_at,unnamed) VALUES(?,?,?,?,?)',(ident,name,species,m.now(),unnamed))
            gid=m.uid();vector=np.eye(384,dtype=np.float32)[0]
            c.execute('INSERT INTO identity_clusters(id,species,anchor,pet_id) VALUES(?,?,?,?)',(gid,species,vector.tobytes(),ident))
            for i in range(n):
                pid=ident+str(i)
                c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized)
                    VALUES(?,'storage',?,?,?,100,80,'2026-11-02',1,?,1,1)''',(pid,str(image),pid+'.png',pid,'["'+species+'"]'))
                c.execute("INSERT INTO photo_pets VALUES(?,?,'suggested')",(pid,ident))
                c.execute('INSERT INTO identity_observations VALUES(?,?,?,?,?,?,0)',(m.uid(),pid,species,'[0,0,100,80]',vector.tobytes(),gid))
        for i in range(7):c.execute('INSERT INTO pets(id,name,species,created_at) VALUES(?,?,?,?)',(f'filler{i}',f'其他猫{i}','cat',m.now()))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(m.app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        base=f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base,trust_env=False) as client,sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1420,'height':950});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/?view=cats&pet=wrong');page.wait_for_selector('.photo-tile')
            expect(page.locator('.photo-tile')).to_have_count(6)
            page.get_by_role('button',name='编辑档案',exact=True).click()
            editor=page.get_by_role('dialog',name='编辑宠物档案')
            expect(editor.get_by_role('button',name='猫咪',exact=True)).to_have_attribute('aria-pressed','true')
            editor.get_by_role('button',name='刺猬',exact=True).click()
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(OUT/'pet-species-edit-mobile.png'))
            editor.get_by_role('button',name='保存档案',exact=True).click()
            expect(editor).to_have_count(0);expect(page.locator('h1')).to_have_text('未命名刺猬')
            expect(page.locator('.photo-tile')).to_have_count(6);assert 'view=hedgehogs' in page.url and 'pet=wrong' in page.url
            page.get_by_role('button',name='返回',exact=True).click()
            expect(page.locator('h1')).to_have_text('宠物档案')
            page.get_by_role('button',name='排序',exact=True).click()
            ordering=page.get_by_role('dialog',name='宠物档案排序')
            rows=ordering.locator('li[data-order-id]')
            first=rows.nth(0).get_attribute('data-order-id');second=rows.nth(1).get_attribute('data-order-id')
            a=rows.nth(1).locator('strong').bounding_box();b=rows.nth(0).bounding_box()
            page.mouse.move(a['x']+5,a['y']+5);page.mouse.down();page.wait_for_timeout(460)
            expect(ordering.locator('li.dragging')).to_have_count(1)
            page.mouse.move(a['x']+5,b['y']+5,steps=6);page.wait_for_timeout(100);page.mouse.up()
            expect(rows.nth(0)).to_have_attribute('data-order-id',second)
            expect(ordering.locator('li.dragging')).to_have_count(0)
            # Native touch events: a long press drags, a short swipe still scrolls.
            cdp=page.context.new_cdp_session(page)
            cdp.send('Emulation.setTouchEmulationEnabled',{'enabled':True})
            a=rows.nth(0).locator('strong').bounding_box();b=rows.nth(1).bounding_box()
            point={'x':a['x']+5,'y':a['y']+5,'id':1}
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
            page.wait_for_timeout(460);expect(ordering.locator('li.dragging')).to_have_count(1)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{**point,'y':b['y']+b['height']-5}]})
            page.wait_for_timeout(100)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            expect(rows.nth(0)).to_have_attribute('data-order-id',first)
            expect(ordering.locator('li.dragging')).to_have_count(0)
            listing=ordering.locator('.pet-order-list');box=listing.bounding_box()
            point={'x':box['x']+65,'y':box['y']+box['height']-35,'id':2}
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
            for amount in (15,35,65,100):
                cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{**point,'y':point['y']-amount}]})
                page.wait_for_timeout(20)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            page.wait_for_timeout(150)
            assert listing.evaluate('(el)=>el.scrollTop')>0,'short swipe did not scroll'
            expect(ordering.locator('li.dragging')).to_have_count(0)
            listing.evaluate('(el)=>el.scrollTop=0');page.wait_for_timeout(100)
            a=rows.nth(0).locator('strong').bounding_box()
            point={'x':a['x']+5,'y':a['y']+5,'id':3}
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
            page.wait_for_timeout(460)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{**point,'y':box['y']+box['height']-8}]})
            page.wait_for_timeout(300)
            assert listing.evaluate('(el)=>el.scrollTop')>0,'drag at edge did not autoscroll'
            cdp.send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]})
            expect(ordering.locator('li.dragging')).to_have_count(0)
            # Desktop dragging can start immediately; all visible row surfaces work.
            for surface in ('img','.order-grip','strong'):
                for pet_name in ('基米','扣嘚'):
                    pin=ordering.get_by_role('button',name='置顶'+pet_name,exact=True)
                    if pin.is_enabled():pin.click()
                listing.evaluate('(el)=>el.scrollTop=0');page.wait_for_timeout(100)
                source=rows.nth(1);source_id=source.get_attribute('data-order-id')
                a=source.locator(surface).bounding_box();b=rows.nth(0).bounding_box()
                page.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);page.mouse.down()
                page.mouse.move(a['x']+a['width']/2,b['y']+8,steps=8);page.wait_for_timeout(100)
                expect(ordering.locator('.pet-order-drag-preview')).to_have_count(1)
                expect(rows.nth(0)).to_have_attribute('data-order-id',source_id)
                page.mouse.up();expect(ordering.locator('.pet-order-drag-preview')).to_have_count(0)
            listing.evaluate('(el)=>el.scrollTop=0')
            source=ordering.locator('li[data-order-id]:has(img)').nth(1);source_id=source.get_attribute('data-order-id');a=source.locator('img').bounding_box();b=rows.nth(0).bounding_box()
            point={'x':a['x']+10,'y':a['y']+10,'id':4}
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]});page.wait_for_timeout(460)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{**point,'y':b['y']+8}]});page.wait_for_timeout(100)
            expect(rows.nth(0)).to_have_attribute('data-order-id',source_id)
            expect(ordering.locator('.pet-order-drag-preview')).to_have_count(1)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            cdp.detach()
            for pet_name in ('扣嘚','基米'):
                pin=ordering.get_by_role('button',name='置顶'+pet_name,exact=True)
                if pin.is_enabled():pin.click()
            assert ordering.locator('li strong').all_text_contents()[:2]==['基米','扣嘚']
            ordering.get_by_role('button',name='下移基米',exact=True).click()
            ordering.get_by_role('button',name='上移基米',exact=True).click()
            assert ordering.locator('li strong').all_text_contents()[:2]==['基米','扣嘚']
            assert ordering.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(OUT/'pet-order-mobile.png'))
            ordering.get_by_role('button',name='保存顺序',exact=True).click()
            expect(ordering).to_have_count(0)
            assert page.locator('.pet-card').first.get_attribute('data-pet-id')=='target'
            assert page.locator('.pet-card').nth(1).get_attribute('data-pet-id')=='hedge'
            page.reload();expect(page.locator('.pet-card')).to_have_count(12)
            assert page.locator('.pet-card').nth(1).get_attribute('data-pet-id')=='hedge'
            page.get_by_role('button',name='排序',exact=True).click()
            page.get_by_role('dialog',name='宠物档案排序').get_by_role('button',name='置顶来源甲',exact=True).click()
            page.keyboard.press('Escape')
            expect(page.get_by_role('dialog',name='宠物档案排序')).to_have_count(0)
            assert [pet['id'] for pet in client.get('/api/state').json()['pets']][:2]==['target','hedge']
            expect(page.locator('[data-pet-id="target"] .pet-card-actions button')).to_have_count(2)
            expect(page.get_by_role('button',name='多选合并',exact=True)).to_have_count(0)
            original_cover=next(pet for pet in client.get('/api/state').json()['pets'] if pet['id']=='target')['cover_id']
            page.get_by_role('button',name='编辑基米',exact=True).click()
            editor=page.get_by_role('dialog',name='编辑宠物档案')
            expect(editor.locator('.pet-naming-note')).to_have_count(0)
            assert editor.locator('.pet-edit-cover').bounding_box()['width']>250
            editor.locator('#pet-rename').fill('基米草稿')
            editor.get_by_role('button',name='更换封面',exact=True).click()
            cover=page.get_by_role('dialog',name='设置宠物封面')
            expect(cover.locator('.picker-photo')).to_have_count(3)
            cover.get_by_role('button',name='选择照片 target0.png',exact=True).click()
            cover.get_by_role('button',name='选择照片 target2.png',exact=True).click()
            expect(cover.locator('.picker-photo.selected')).to_have_count(1)
            assert cover.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(OUT/'pet-cover-mobile.png'))
            cover.get_by_role('button',name='使用这张照片',exact=True).click()
            expect(editor.locator('#pet-rename')).to_have_value('基米草稿')
            expect(editor.locator('.pet-edit-cover img')).to_have_attribute('src','/api/photos/target2/thumbnail')
            assert next(pet for pet in client.get('/api/state').json()['pets'] if pet['id']=='target')['cover_id']==original_cover
            page.screenshot(path=str(OUT/'pet-editor-cover-mobile.png'))
            page.keyboard.press('Escape')
            page.get_by_role('button',name='编辑基米',exact=True).click()
            expect(editor.locator('#pet-rename')).to_have_value('基米')
            editor.get_by_role('button',name='更换封面',exact=True).click()
            cover.get_by_role('button',name='选择照片 target2.png',exact=True).click()
            cover.get_by_role('button',name='使用这张照片',exact=True).click()
            editor.get_by_role('button',name='保存档案',exact=True).click()
            expect(cover).to_have_count(0)
            expect(page.locator('[data-pet-id="target"] .collection-cover img')).to_have_attribute('src','/api/photos/target2/thumbnail')
            page.reload();expect(page.locator('[data-pet-id="target"] .collection-cover img')).to_have_attribute('src','/api/photos/target2/thumbnail')
            page.locator('[data-pet-id="target"] .pet-open').click()
            page.get_by_role('button',name='编辑档案',exact=True).click()
            editor.get_by_role('button',name='更换封面',exact=True).click()
            expect(page.get_by_role('dialog',name='设置宠物封面').locator('.picker-photo')).to_have_count(3)
            page.keyboard.press('Escape')
            expect(editor).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('h1')).to_have_text('基米')
            page.get_by_role('button',name='返回',exact=True).click()
            page.set_viewport_size({'width':1420,'height':950})
            page.get_by_role('button',name='选择档案未命名刺猬',exact=True).click()
            page.locator('.pet-card').filter(has_text='来源甲').locator('.pet-open').click()
            expect(page.get_by_role('button',name='合并宠物',exact=True)).to_be_disabled()
            expect(page.get_by_role('region',name='宠物多选操作')).to_contain_text('不同种类')
            page.keyboard.press('Escape');expect(page.get_by_role('region',name='宠物多选操作')).to_have_count(0)
            page.get_by_role('button',name='选择档案来源甲',exact=True).click()
            page.locator('.pet-card').filter(has_text='基米').locator('.pet-open').click()
            page.locator('.pet-card').filter(has_text='来源乙').locator('.pet-open').click()
            expect(page.get_by_role('region',name='宠物多选操作')).to_contain_text('已选 3 个宠物')
            page.screenshot(path=str(OUT/'pet-multi-selection-desktop.png'))
            page.get_by_role('button',name='合并宠物',exact=True).click()
            merge=page.get_by_role('dialog',name='合并宠物档案')
            expect(merge.locator('.merge-pet-previews > div')).to_have_count(3)
            expect(page.get_by_role('button',name='保留宠物档案',exact=True)).to_contain_text('基米')
            page.set_viewport_size({'width':390,'height':844})
            assert merge.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(OUT/'pet-bulk-merge-mobile.png'))
            page.get_by_role('button',name='确认合并',exact=True).click()
            expect(merge).to_have_count(0);expect(page.locator('h1')).to_have_text('宠物档案')
            expect(page.locator('.pet-card').filter(has_text='基米')).to_contain_text('7 张照片')
            assert not any(pet['id'] in ('a','b') for pet in client.get('/api/state').json()['pets'])
            assert 'view=pets' in page.url
            page.locator('h1').click();page.keyboard.press('Control+a')
            expect(page.get_by_role('region',name='宠物多选操作')).to_contain_text('已选 10 个宠物')
            page.keyboard.press('Escape')
            page.locator('.pet-card').filter(has_text='基米').locator('.pet-open').click()
            expect(page.locator('h1')).to_have_text('基米');expect(page.locator('.photo-tile')).to_have_count(7)
            page.reload();expect(page.locator('.photo-tile')).to_have_count(7)
            assert not errors,errors
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10)
print('PASS: persistent kind correction and detail route, unnamed preserved, mixed-kind disabled, whole-card multi-select, 3-way target merge, list retained, desktop/mobile, Ctrl+A and Escape')
