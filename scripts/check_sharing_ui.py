"""Two separate listeners: private sharing controls and a real visitor session."""
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from PIL import Image
import httpx
from playwright.sync_api import sync_playwright,expect
import uvicorn

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
with tempfile.TemporaryDirectory(prefix='ousepet-share-ui-') as temporary:
    root=Path(temporary);os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m,sharing,video
    manage_port=port();share_port=port();sharing.PUBLIC_PORT=share_port
    fixture=ROOT/'.cache/video-browser-fixture.mp4'
    video.frame=lambda *args:Image.new('RGB',(320,240),'#9a86aa')
    video.compatible=lambda path,target,ready=None,strip_metadata=False:shutil.copyfile(path,target)
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('s','test',str(root),m.now()))
        storage=dict(c.execute("SELECT * FROM storages WHERE id='s'").fetchone())
    ids=[]
    for i in range(3):
        path=root/f'photo{i}.jpg';Image.new('RGB',(500,400),('#9a86aa','#75658a','#b9a4b3')[i]).save(path)
        ident,_=m.index_file(storage,path);ids.append(ident)
    clip=root/'clip.mp4';shutil.copyfile(fixture,clip)
    with m.db() as c:
        c.execute("INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,media_type,duration) VALUES('v','s',?,'video.mp4','v',320,240,'2026-01-01',1,'video',4)",(str(clip),))
        c.execute("INSERT INTO albums VALUES('memory','基米的旅行',?)",(m.now(),))
        for ident in ids[:2]+['v']:c.execute("INSERT INTO album_photos VALUES('memory',?)",(ident,))
    servers=[uvicorn.Server(uvicorn.Config(m.app,host='127.0.0.1',port=manage_port,log_level='error')),
        uvicorn.Server(uvicorn.Config(sharing.public_app,host='127.0.0.1',port=share_port,log_level='error'))]
    threads=[threading.Thread(target=server.run,daemon=True) for server in servers]
    for thread in threads:thread.start()
    try:
        for _ in range(100):
            if all(server.started for server in servers):break
            time.sleep(.03)
        admin_url=f'http://127.0.0.1:{manage_port}';public_url=f'http://127.0.0.1:{share_port}'
        with httpx.Client(base_url=admin_url,trust_env=False) as client,sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':980});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(admin_url+'/?view=albums');page.get_by_role('button',name='分享回忆基米的旅行',exact=True).click()
            dialog=page.get_by_role('dialog',name='分享回忆',exact=True)
            dialog.locator('#share-pin').fill('123456')
            dialog.get_by_role('button',name='创建分享链接',exact=True).click()
            link=dialog.get_by_role('link',name='分享链接基米的旅行',exact=True)
            expect(link).to_be_visible();url=link.get_attribute('href');assert url.startswith(public_url+'/s/')
            with page.expect_popup() as opened:link.click()
            preview=opened.value;expect(preview.locator('h1')).to_have_text('查看回忆');assert preview.url==url;preview.close()
            # HTTP/IP copy fallback stays inside the modal's focus scope.
            page.evaluate("Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true}); document.execCommand=()=>true")
            dialog.get_by_role('button',name='复制链接',exact=True).click();expect(dialog.get_by_role('status')).to_have_text('链接已复制')
            page.screenshot(path=str(ROOT/'reports/ui/memory-share-private.png'))
            visitor=browser.new_context(viewport={'width':1440,'height':980});guest=visitor.new_page()
            guest.on('pageerror',lambda error:errors.append(str(error)))
            def boundary(route):
                assert urlsplit(route.request.url).path.startswith('/api/public/'),'Visitor used a management API'
                route.continue_()
            guest.route('**/api/**',boundary)
            guest.goto(url);expect(guest.locator('h1')).to_have_text('查看回忆')
            guest.locator('#guest-pin').fill('bad');guest.get_by_role('button',name='打开回忆',exact=True).click()
            expect(guest.get_by_role('alert')).to_contain_text('提取码不正确')
            guest.locator('#guest-pin').fill('123456');guest.get_by_role('button',name='打开回忆',exact=True).click()
            expect(guest.locator('h1')).to_have_text('基米的旅行');expect(guest.locator('.shared-tile')).to_have_count(3)
            expect(guest.locator('.shared-title img')).to_have_count(0)
            expect(guest.locator('.shared-hero')).to_have_count(0)
            guest.get_by_role('button',name='查看照片 1',exact=True).click()
            expect(guest.get_by_role('dialog',name='回忆预览')).to_be_visible();expect(guest.get_by_role('link',name='下载',exact=True)).to_have_count(0)
            guest.keyboard.press('Escape');expect(guest.get_by_role('dialog',name='回忆预览')).to_have_count(0)
            guest.get_by_role('button',name='播放视频 3',exact=True).click();guest.wait_for_function('()=>document.querySelector("video")?.readyState>=2')
            guest.locator('video').evaluate('(el)=>el.play()');guest.wait_for_function('()=>document.querySelector("video").currentTime>.2')
            guest.keyboard.press('Escape')
            guest.set_viewport_size({'width':390,'height':844});assert guest.locator('.shared-page').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            guest.screenshot(path=str(ROOT/'reports/ui/memory-share-visitor-mobile.png'))
            dialog.get_by_role('button',name='关闭分享基米的旅行',exact=True).click();expect(dialog.locator('.share-status')).to_contain_text('已关闭')
            guest.reload();expect(guest.get_by_role('alert')).to_contain_text('分享已失效')
            page.keyboard.press('Escape');page.get_by_role('button',name='设置',exact=True).click();page.get_by_role('button',name='分享设置',exact=True).click()
            page.locator('#share-domain').fill('https://photos.example.com');page.get_by_role('button',name='保存域名',exact=True).click()
            expect(page.get_by_role('status')).to_have_text('分享域名已保存')
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(ROOT/'reports/ui/memory-share-settings-mobile.png'))
            page.keyboard.press('Escape');page.set_viewport_size({'width':1440,'height':980})
            page.get_by_role('button',name='外链',exact=True).click()
            expect(page.locator('.share-record-url')).to_have_attribute('title','https://photos.example.com'+urlsplit(url).path)
            expect(page.locator('.share-record-url')).not_to_have_attribute('href')
            page.get_by_role('button',name='删除记录基米的旅行',exact=True).click()
            page.get_by_role('button',name='取消',exact=True).click();expect(page.locator('.share-record')).to_have_count(1)
            page.get_by_role('button',name='删除记录基米的旅行',exact=True).click();page.get_by_role('button',name='确认删除',exact=True).click()
            expect(page.locator('.share-record')).to_have_count(0)
            assert client.get('/api/shares').json()['items']==[]
            active_link=client.post('/api/albums/memory/shares',json={}).json()
            page.reload();expect(page.locator('.share-record')).to_have_count(1)
            page.screenshot(path=str(ROOT/'reports/ui/share-list-redesign.png'))
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(350)
            assert page.locator('.share-record').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(ROOT/'reports/ui/share-list-redesign-mobile.png'))
            page.get_by_role('button',name='删除记录基米的旅行',exact=True).click();page.get_by_role('button',name='确认删除',exact=True).click()
            expect(page.locator('.share-record')).to_have_count(0)
            assert client.get('/api/shares').json()['items']==[]
            assert client.get('/api/state').json()['albums'][0]['id']=='memory'
            assert client.get(public_url+'/api/public/shares/'+active_link['token']).status_code==404
            # Long shared memories scroll inside the visitor page and load the next batch.
            extra=[]
            with m.db() as c:
                for index in range(105):
                    ident='long'+str(index);extra.append(ident)
                    c.execute('''INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime)
                        VALUES(?,'s',?,'long.jpg',?,500,400,'2026-11-01',1)''',(ident,str(root/'photo0.jpg'),ident))
            long_album=client.post('/api/albums',json={'name':'长回忆','photo_ids':extra}).json()['id']
            long_share=client.post('/api/albums/'+long_album+'/shares',json={}).json()
            guest.goto(public_url+'/s/'+long_share['token']);expect(guest.locator('.shared-tile')).to_have_count(100)
            assert guest.locator('.shared-page').evaluate('(el)=>el.scrollHeight>el.clientHeight')
            guest.get_by_role('button',name='加载更多',exact=True).click();expect(guest.locator('.shared-tile')).to_have_count(105)
            assert guest.locator('.shared-page').evaluate('(el)=>el.scrollTop>0')
            assert not errors,errors
            browser.close()
    finally:
        for server in servers:server.should_exit=True
        for thread in threads:thread.join(timeout=10)
print('PASS sharing UI: default IP/public port, PIN, copy fallback, visitor-only APIs, photos/video, no download, mobile, revoke and custom domain')
