"""Isolated real API and browser: memories management and picker date seeking."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect
import uvicorn

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
with tempfile.TemporaryDirectory(prefix='ousepet-memories-') as temporary:
    root=Path(temporary);image=root/'sample.jpg';Image.new('RGB',(180,120),'#9586aa').save(image)
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('storage','test',str(root),m.now()))
        for i in range(260):
            taken='2026-11-01' if i<220 else '2021-02-01'
            c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized)
                VALUES(?,'storage',?,?,?,180,120,?,1,'["cat"]',1,1)''',(f'p{i}',str(image),f'photo{i}.jpg',str(i),taken))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(m.app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        base=f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base,trust_env=False) as client:
            def create(name,ids):
                response=client.post('/api/albums',json={'name':name,'photo_ids':ids});response.raise_for_status();return response.json()['id']
            a=create('保留回忆',['p1','p2']);b=create('来源回忆',['p2','p3']);other=create('独立回忆',['p4'])
            client.patch('/api/albums/'+a,json={'name':'保留回忆','cover_id':'p1'}).raise_for_status()
            assert client.patch('/api/albums/'+a,json={'name':'不应保存','cover_id':'p4'}).status_code==400
            record=next(x for x in client.get('/api/state').json()['albums'] if x['id']==a)
            assert record['name']=='保留回忆' and record['cover_id']=='p1'
            assert client.post('/api/albums/merge',json={'target_id':a,'source_ids':[b,'missing']}).status_code==400
            assert any(x['id']==b for x in client.get('/api/state').json()['albums'])
            for ids in ([a],[b,b]):assert client.post('/api/albums/merge',json={'target_id':a,'source_ids':ids}).status_code==400
            client.post('/api/albums/merge',json={'target_id':a,'source_ids':[b]}).raise_for_status()
            record=next(x for x in client.get('/api/state').json()['albums'] if x['id']==a)
            assert record['name']=='保留回忆' and record['cover_id']=='p1' and record['count']==3
            m.init();assert next(x for x in client.get('/api/state').json()['albums'] if x['id']==a)['cover_id']=='p1'
            client.delete('/api/albums/'+other).raise_for_status()
            assert client.get('/api/photos?view=all').json()['total']==260
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':980});errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/?view=albums');expect(page.locator('h1')).to_have_text('回忆')
                page.get_by_role('button',name='编辑回忆保留回忆',exact=True).click()
                editor=page.get_by_role('dialog',name='编辑回忆')
                editor.locator('#memory-name').fill('旅行回忆')
                editor.get_by_role('button',name='更换回忆封面',exact=True).click()
                cover=page.get_by_role('dialog',name='设置回忆封面')
                expect(cover.locator('.picker-photo')).to_have_count(3)
                cover.get_by_role('button',name='选择照片 photo3.jpg',exact=True).click()
                cover.get_by_role('button',name='使用这张照片',exact=True).click()
                expect(editor.locator('#memory-name')).to_have_value('旅行回忆')
                editor.get_by_role('button',name='保存回忆',exact=True).click();expect(editor).to_have_count(0)
                expect(page.locator('[data-memory-id="'+a+'"] .collection-cover img')).to_have_attribute('src','/api/photos/p3/thumbnail')
                page.locator('[data-memory-id="'+a+'"] .pet-open').click()
                page.get_by_role('button',name='添加照片',exact=True).first.click()
                picker=page.get_by_role('dialog',name='从宠物图库添加照片')
                expect(picker.get_by_role('navigation',name='照片时间线')).to_be_visible()
                picker.get_by_role('button',name='选择照片 photo99.jpg',exact=True).click()
                picker.get_by_role('button',name='跳转到2021年',exact=True).click()
                expect(picker.locator('.picker-photo')).to_have_count(40)
                expect(picker.locator('.picker-current-date')).to_have_text('2021/02')
                picker.get_by_role('button',name='选择照片 photo250.jpg',exact=True).click()
                expect(picker.locator('.picker-footer')).to_contain_text('已选 2 张')
                page.set_viewport_size({'width':390,'height':844})
                assert picker.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                page.screenshot(path=str(ROOT/'reports/ui/memory-picker-timeline-mobile.png'))
                picker.get_by_role('button',name='添加 2 张照片',exact=True).click();expect(picker).to_have_count(0)
                expect(page.locator('h1')).to_have_text('旅行回忆')
                page.get_by_role('button',name='返回',exact=True).click()
                c=create('另一段回忆',['p250','p251'])
                page.reload();page.get_by_role('button',name='选择回忆旅行回忆',exact=True).click()
                page.locator('[data-memory-id="'+c+'"] .pet-open').click()
                page.get_by_role('button',name='合并回忆',exact=True).click()
                page.get_by_role('button',name='保留回忆',exact=True).click()
                page.get_by_role('option',name='旅行回忆 · 5 张',exact=True).click()
                page.get_by_role('button',name='确认合并',exact=True).click()
                expect(page.locator('[data-memory-id="'+c+'"]')).to_have_count(0)
                expect(page.locator('[data-memory-id="'+a+'"]')).to_contain_text('6 张照片')
                page.locator('[data-memory-id="'+a+'"] .pet-open').click()
                page.get_by_role('button',name='选择照片 photo251.jpg',exact=True).click()
                page.get_by_role('button',name='移出回忆',exact=True).click()
                expect(page.locator('.photo-tile')).to_have_count(5)
                assert client.get('/api/photos?view=all').json()['total']==260
                page.get_by_role('button',name='返回',exact=True).click()
                page.get_by_role('button',name='删除回忆旅行回忆',exact=True).click()
                page.get_by_role('dialog',name='删除回忆').get_by_role('button',name='删除回忆',exact=True).click()
                expect(page.locator('[data-memory-id="'+a+'"]')).to_have_count(0)
                assert client.get('/api/photos?view=all').json()['total']==260
                assert not errors,errors
                browser.close()
    finally:server.should_exit=True;thread.join(timeout=10)
print('PASS: atomic memory editing/cover/merge/delete, persistent cover, photo retention, mobile, date seeking to unloaded year, cross-date selection and list retained')
