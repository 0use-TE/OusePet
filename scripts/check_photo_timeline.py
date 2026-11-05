"""Isolated API and browser checks for full-date indexing and direct timeline seeking."""
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
with tempfile.TemporaryDirectory(prefix='ousepet-timeline-') as temporary:
    root=Path(temporary);library=root/'photos';library.mkdir();image=library/'fixture.png';Image.new('RGB',(90,70),'#67547d').save(image)
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(library),OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    sid=m.uid()
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'Timeline fixtures',str(library),m.now()))
        for i in range(450):
            date='2026-11-02' if i<210 else '2025-10-01' if i<360 else '2021-06-28'
            c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,species,visible,recognized)
                VALUES(?,?,?,?,?,90,70,?,1,'["cat"]',1,1)''',(f'p{i:04}',sid,str(image),f'photo-{i}.png',f'hash-{i}',date+' 12:00:00'))
        c.execute("INSERT INTO pets(id,name,species,created_at) VALUES('timeline-pet','旧照片宠物','cat',?)",(m.now(),))
        c.execute("INSERT INTO photo_pets VALUES('p0400','timeline-pet','confirmed')")
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(m.app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        base=f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base,trust_env=False) as client,sync_playwright() as p:
            index=client.get('/api/photos/timeline').json()
            assert index['total']==450 and [(r['month'],r['offset']) for r in index['months']]==[('2026-11',0),('2025-10',210),('2021-06',360)]
            assert client.get('/api/photos/timeline?sort=asc').json()['months'][0]=={'month':'2021-06','count':90,'offset':0}
            assert client.get('/api/photos/timeline?pet_id=timeline-pet').json()['total']==1
            assert client.get('/api/photos/timeline?q=2021').json()['months']==[{'month':'2021-06','count':90,'offset':0}]
            assert client.get('/api/photos/timeline?view=hedgehogs').json()['total']==0
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1400,'height':950});errors=[];requests=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:requests.append(request.url) if '/api/photos?' in request.url else None)
            page.goto(base+'/?view=gallery')
            expect(page.locator('.photo-tile')).to_have_count(200)
            expect(page.get_by_role('navigation',name='照片时间线')).to_be_visible()
            expect(page.get_by_role('button',name='跳转到2021年',exact=True)).to_be_visible()
            page.screenshot(path=str(OUT/'timeline-desktop.png'))
            requests.clear()
            page.get_by_role('button',name='跳转到2021年',exact=True).click()
            expect(page.locator('.photo-tile')).to_have_count(90)
            assert all('offset=360' in url for url in requests),requests
            assert '2021年6月28日' in page.locator('.date-group h2').first.inner_text()
            expect(page.locator('.photo-pagination')).to_have_text('当前第 361–450 / 450 张照片')
            page.get_by_role('button',name='跳转到2026年',exact=True).click()
            expect(page.locator('.photo-tile')).to_have_count(200)
            page.get_by_role('button',name='跳转到2025年',exact=True).hover()
            page.get_by_role('button',name='跳转到2025年10月',exact=True).click()
            expect(page.locator('.date-group h2').first).to_contain_text('2025年10月1日')
            page.get_by_role('button',name='跳转到2026年',exact=True).click()
            expect(page.locator('.photo-tile')).to_have_count(200)
            slider=page.get_by_role('slider',name='快速定位照片日期')
            slider.focus();page.keyboard.press('End')
            expect(page.locator('.date-group h2').first).to_contain_text('2021年6月28日')
            page.get_by_role('button',name='跳转到2026年',exact=True).click()
            expect(page.locator('.photo-tile')).to_have_count(200)
            track=slider.bounding_box();x=track['x']+track['width']/2
            page.mouse.move(x,track['y']+10);page.mouse.down()
            page.mouse.move(x,track['y']+track['height']-10,steps=8)
            expect(page.locator('.timeline-date-preview')).to_be_visible()
            page.mouse.up()
            expect(page.locator('.date-group h2').first).to_contain_text('2021年6月28日')
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('button',name='跳转到2026年',exact=True).click()
            expect(page.locator('.photo-tile')).to_have_count(200)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert page.locator('.workspace').evaluate('(panel)=>panel.scrollLeft===0')
            page.screenshot(path=str(OUT/'timeline-mobile.png'))
            page.get_by_role('textbox',name='搜索照片').fill('2021')
            expect(page.locator('.photo-tile')).to_have_count(90)
            expect(page.get_by_role('button',name='跳转到2026年',exact=True)).to_have_count(0)
            expect(page.get_by_role('button',name='跳转到2021年',exact=True)).to_be_visible()
            page.get_by_role('button',name='设置',exact=True).click()
            expect(page.get_by_role('navigation',name='照片时间线')).to_have_count(0)
            assert not errors,errors
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10)
print('PASS: all dates indexed, month offsets, species/pet/search/sort filters, direct old-date seek, month picker, slider keyboard, mobile and dialog layering')
