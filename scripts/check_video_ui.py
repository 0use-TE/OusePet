"""Real browser playback with an isolated library, poster editing and fallback."""
import os
from pathlib import Path
import shutil
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
with tempfile.TemporaryDirectory(prefix='ousepet-video-ui-') as temporary:
    root=Path(temporary);clip=root/'video.mp4';shutil.copyfile(ROOT/'.cache/video-browser-fixture.mp4',clip)
    os.environ.update(OUSEPET_DATA=str(root/'data'),OUSEPET_LIBRARY_ROOTS=str(root),OUSEPET_DISCOVERY='0')
    from ousepet import api as m,video
    video.probe=lambda path:{'width':320,'height':240,'duration':4,'date':None}
    video.frame=lambda *args:Image.new('RGB',(320,240),'#a489aa')
    video.compatible=lambda path,target,ready=None:shutil.copyfile(path,target)
    m.detect_identity=lambda image:(['cat'],[{'species':'cat','box':[0,0,200,200],'vector':np.eye(384,dtype=np.float32)[0]}])
    with m.db() as c:
        c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',('s','test',str(root),m.now()))
        storage=dict(c.execute("SELECT * FROM storages WHERE id='s'").fetchone())
    ident,_=m.index_file(storage,clip)
    still=root/'photo.jpg';Image.new('RGB',(320,240),'#a489aa').save(still)
    still_id,_=m.index_file(storage,still);m.apply_recognition(still_id,{'species':['cat'],'pets':[]})
    with m.db() as c:
        c.execute("UPDATE photos SET species='[\"cat\"]',visible=1,recognized=1 WHERE id=?",(ident,))
        c.execute("INSERT INTO pets(id,name,species,created_at) VALUES('cat','基米','cat',?)",(m.now(),))
        c.execute('INSERT INTO identity_clusters(id,species,anchor,pet_id) VALUES(?,?,?,?)',('cat','cat',np.eye(384,dtype=np.float32)[0].tobytes(),'cat'))
        c.execute("INSERT INTO photo_pets VALUES(?,'cat','suggested')",(ident,))
        c.execute("INSERT INTO video_hits VALUES(?,1,'cat','cat')",(ident,))
        c.execute("INSERT INTO albums VALUES('memory','旅行',?)",(m.now(),))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(m.app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        base=f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base,trust_env=False) as client,sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':980});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/?view=videos')
            expect(page.locator('h1')).to_have_text('图库');expect(page.locator('.photo-tile .video-duration')).to_have_text('▶ 0:04')
            expect(page.get_by_role('group',name='媒体类型筛选').get_by_role('button',name='视频',exact=True)).to_have_attribute('aria-pressed','true')
            expect(page.locator('.sidebar').get_by_role('button',name='视频',exact=True)).to_have_count(0)
            types=page.get_by_role('group',name='媒体类型筛选')
            types.get_by_role('button',name='照片',exact=True).click();expect(page.locator('.photo-tile')).to_have_count(1)
            expect(page.locator('.photo-tile .video-duration')).to_have_count(0)
            types.get_by_role('button',name='全部',exact=True).click();expect(page.locator('.photo-tile')).to_have_count(2)
            expect(page.locator('.photo-tile .video-duration')).to_have_count(1)
            types.get_by_role('button',name='视频',exact=True).click();expect(page.locator('.photo-tile')).to_have_count(1)
            page.reload();expect(page.get_by_role('group',name='媒体类型筛选').get_by_role('button',name='视频',exact=True)).to_have_attribute('aria-pressed','true')
            page.get_by_role('button',name='播放视频 video.mp4',exact=True).click()
            page.wait_for_function('()=>document.querySelector("video")?.readyState>=2')
            page.get_by_role('button',name='基米 · 0:01',exact=True).click()
            page.wait_for_function('()=>document.querySelector("video")?.currentTime>=1')
            page.locator('video').evaluate('(el)=>{el.pause();el.currentTime=2}')
            with page.expect_response(lambda response:response.url.endswith('/video-cover')) as saved:
                page.get_by_role('button',name='当前画面设为视频封面',exact=True).click()
            assert saved.value.status==200
            with m.db() as c:assert c.execute('SELECT video_cover_manual FROM photos WHERE id=?',(ident,)).fetchone()[0]==1
            page.screenshot(path=str(ROOT/'reports/ui/video-player-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('.video-player').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            assert page.locator('video').bounding_box()['width']>250
            page.screenshot(path=str(ROOT/'reports/ui/video-player-mobile.png'))
            page.keyboard.press('Escape');expect(page.locator('video')).to_have_count(0)
            # Unsupported originals automatically retry through a compatible cached stream.
            page.route('**/api/photos/'+ident+'/image',lambda route:route.abort())
            page.get_by_role('button',name='播放视频 video.mp4',exact=True).click()
            page.wait_for_function('()=>document.querySelector("video")?.src.endsWith("/play") && document.querySelector("video").readyState>=2')
            page.keyboard.press('Escape');page.unroute('**/api/photos/'+ident+'/image')
            # Videos can be selected into memories and used as a profile cover.
            page.goto(base+'/?view=gallery&album=memory');page.get_by_role('button',name='添加照片',exact=True).first.click()
            picker=page.get_by_role('dialog',name='从宠物图库添加照片');expect(picker.locator('.video-duration')).to_have_text('▶ 0:04')
            picker.get_by_role('button',name='选择照片 video.mp4',exact=True).click();picker.get_by_role('button',name='添加 1 项内容',exact=True).click()
            expect(picker).to_have_count(0);expect(page.locator('.photo-tile')).to_have_count(1)
            page.goto(base+'/?view=pets');page.get_by_role('button',name='编辑基米',exact=True).click()
            editor=page.get_by_role('dialog',name='编辑宠物档案');editor.get_by_role('button',name='更换封面',exact=True).click()
            cover=page.get_by_role('dialog',name='设置宠物封面');cover.get_by_role('button',name='选择照片 video.mp4',exact=True).click()
            cover.get_by_role('button',name='使用这张照片',exact=True).click();editor.get_by_role('button',name='保存档案',exact=True).click()
            expect(editor).to_have_count(0)
            assert next(pet for pet in client.get('/api/state').json()['pets'] if pet['id']=='cat')['cover_id']==ident
            assert not errors,errors
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10)
print('PASS video UI: duration, native playback, timestamp seek, frame poster, mobile, automatic compatible playback, memories and pet cover, no browser errors')
