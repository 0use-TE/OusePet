"""Photo library multi-picker integration on isolated API/database, never live user data."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright,expect
import uvicorn

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/ui';OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='ousepet-picker-') as temporary:
    root=Path(temporary);library=root/'photos';library.mkdir();image=library/'fixture.png';Image.new('RGB',(90,70),'#776188').save(image)
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(library),OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('picker-storage','照片',str(library),m.now()))
        for ident,name in (('source-pet','原来归属'),('target-pet','新宠物')):
            c.execute('INSERT INTO pets(id,name,species,created_at) VALUES(?,?,?,?)',(ident,name,'cat',m.now()))
        c.execute('INSERT INTO albums VALUES(?,?,?)',('target-album','基米翻垃圾桶',m.now()))
        for i in range(450):
            species='cat' if i<400 else 'hedgehog'
            c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized)
                VALUES(?,?,?,?,?,90,70,'2026-11-02 12:00:00',1,?,1,1)''',(f'p{i:03}','picker-storage',str(image),f'fixture-{i:03}.png',f'hash-{i}','["'+species+'"]'))
            if i<400:c.execute("INSERT INTO photo_pets VALUES(?,'source-pet','confirmed')",(f'p{i:03}',))
        c.execute("INSERT INTO photo_pets VALUES('p001','target-pet','confirmed')")
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(m.app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        base=f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base,trust_env=False) as client,sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1400,'height':950})
            errors=[];writes=[];fail_next=True
            page.on('pageerror',lambda error:errors.append(str(error)))
            def guard(route):
                global fail_next
                if route.request.method=='POST' and route.request.url.endswith('/api/photos/action'):
                    body=route.request.post_data_json;writes.append(body)
                    if fail_next:fail_next=False;route.fulfill(status=503,json={'detail':'临时失败，请重试'});return
                route.continue_()
            page.route('**/api/**',guard)
            page.goto(base+'/?view=gallery&album=target-album')
            expect(page.locator('h1')).to_have_text('基米翻垃圾桶')
            page.get_by_role('button',name='添加照片',exact=True).last.click()
            dialog=page.get_by_role('dialog',name='从宠物图库添加照片')
            expect(dialog).to_be_visible()
            expect(page.get_by_role('dialog',name='从存储添加照片')).to_have_count(0)
            search=page.get_by_role('textbox',name='搜索待添加照片')
            search.fill('fixture-00')
            for name in ('fixture-000.png','fixture-002.png'):
                button=dialog.get_by_role('button',name='选择照片 '+name,exact=True);expect(button).to_be_enabled();button.click()
            search.fill('fixture-210')
            dialog.get_by_role('button',name='选择照片 fixture-210.png',exact=True).click()
            expect(dialog.locator('.picker-footer')).to_contain_text('已选 3 张')
            dialog.get_by_role('button',name='添加 3 张照片',exact=True).click()
            expect(dialog.get_by_role('alert')).to_contain_text('临时失败')
            expect(dialog).to_be_visible()
            assert client.get('/api/photos?album_id=target-album').json()['total']==0
            dialog.get_by_role('button',name='添加 3 张照片',exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.locator('h1')).to_have_text('基米翻垃圾桶')
            expect(page.locator('.photo-tile')).to_have_count(3)
            assert client.get('/api/photos?pet_id=source-pet').json()['total']==400
            page.get_by_role('button',name='添加照片',exact=True).click()
            search.fill('fixture-210')
            expect(dialog.get_by_role('button',name='已添加 fixture-210.png',exact=True)).to_be_disabled()
            page.screenshot(path=str(OUT/'photo-picker-desktop.png'))
            page.keyboard.press('Escape');expect(dialog).to_have_count(0)
            page.set_viewport_size({'width':390,'height':844});page.goto(base+'/?view=gallery&pet=target-pet')
            page.get_by_role('button',name='添加照片',exact=True).click()
            search.fill('fixture-001')
            expect(dialog.get_by_role('button',name='已添加 fixture-001.png',exact=True)).to_be_disabled()
            search.fill('fixture-00')
            selected=dialog.get_by_role('button',name='选择照片 fixture-002.png',exact=True)
            selected.focus();page.keyboard.press('Space');expect(selected).to_have_attribute('aria-pressed','true')
            dialog.get_by_role('button',name='选择照片 fixture-003.png',exact=True).click()
            assert dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(OUT/'photo-picker-mobile.png'))
            dialog.get_by_role('button',name='添加 2 张照片',exact=True).click()
            expect(dialog).to_have_count(0);expect(page.locator('h1')).to_have_text('新宠物')
            expect(page.locator('.photo-tile')).to_have_count(3)
            assert client.get('/api/photos?pet_id=source-pet').json()['total']==400
            # More than 500 selections must be split into valid, non-duplicated API batches.
            with m.db() as c:
                c.execute('INSERT INTO albums VALUES(?,?,?)',('bulk-album','批量相册',m.now()))
                for i in range(450,750):
                    c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized)
                        VALUES(?,?,?,?,?,90,70,'2026-11-02 12:00:00',1,'["cat"]',1,1)''',(f'p{i:03}','picker-storage',str(image),f'fixture-{i:03}.png',f'hash-{i}'))
            page.set_viewport_size({'width':1400,'height':950});page.goto(base+'/?view=gallery&album=bulk-album')
            expect(page.locator('h1')).to_have_text('批量相册')
            page.get_by_role('button',name='添加照片',exact=True).first.click()
            page.wait_for_function('document.querySelectorAll(".picker-photo").length>=200')
            dialog.locator('.picker-scroll').evaluate('(el)=>el.scrollTop=el.scrollHeight')
            page.wait_for_function('document.querySelectorAll(".picker-photo").length>=400')
            dialog.locator('.picker-scroll').evaluate('(el)=>el.scrollTop=el.scrollHeight')
            page.wait_for_function('document.querySelectorAll(".picker-photo").length>=600')
            count=dialog.locator('.picker-photo').count()
            dialog.get_by_role('button',name='选择已加载照片',exact=True).click()
            start=len(writes);dialog.get_by_role('button',name=f'添加 {count} 张照片',exact=True).click()
            expect(dialog).to_have_count(0)
            assert client.get('/api/photos?album_id=bulk-album').json()['total']==count
            assert len(writes[start:])==2 and max(len(body['ids']) for body in writes[start:])<=500
            assert len({ident for body in writes[start:] for ident in body['ids']})==count
            assert all(body['action'] in ('album','assign') for body in writes)
            assert not errors,errors
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10)
print('PASS: empty/header picker entries, library source, cross-search multi-select, album/pet add, existing-members disabled, failed add/retry, original membership retained, keyboard/mobile and same route')
