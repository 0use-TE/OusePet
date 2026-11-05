"""Exercise the local album with Edge; writes screenshots and a compact QA report."""
import json,time,hashlib
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/ui';OUT.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:8766'
client=httpx.Client(base_url=BASE,timeout=60)
errors=[];checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1519,'height':986},device_scale_factor=1)
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(BASE);page.wait_for_selector('h1')
    if not client.get('/api/state').json()['storages']:
        page.get_by_role('button',name='选择照片文件夹',exact=True).click()
        page.get_by_role('button',name='宠物照片',exact=True).click()
        page.get_by_role('button',name='添加此文件夹',exact=True).click()
        for _ in range(360):
            time.sleep(.5)
            state=client.get('/api/state').json()
            if state['jobs'] and state['jobs'][0]['status'] not in ('running','queued'):break
        assert state['jobs'][0]['status']=='complete',state['jobs'][0]
        checks.append('first-run directory picker and scan')
    for _ in range(360):
        state=client.get('/api/state').json()
        if not any(j['status'] in ('running','queued') for j in state['jobs']):break
        time.sleep(.5)
    page.reload();page.wait_for_selector('.photo-tile');page.wait_for_timeout(1600)
    state=client.get('/api/state').json()
    assert state['counts']['all']<state['storages'][0]['indexed']
    assert page.locator('h1').inner_text()=='图库'
    assert page.locator('.photo-tile').count()==state['counts']['library']
    checks.append('full library is the default and includes missed photos')
    page.get_by_role('button',name='宠物图库',exact=True).click();page.wait_for_timeout(400)
    assert page.locator('.photo-tile').count()==state['counts']['all']
    checks.append(f"pet-only gallery: {state['counts']['all']} / {state['storages'][0]['indexed']}")
    page.screenshot(path=str(OUT/'gallery-desktop.png'),full_page=False)
    tile=page.locator('.photo-tile').first;tile.hover()
    if tile.get_by_role('button',name='收藏',exact=True).count():tile.get_by_role('button',name='收藏',exact=True).click()
    page.wait_for_timeout(400)
    page.get_by_role('button',name='收藏',exact=True).first.click()
    page.wait_for_timeout(400);assert page.locator('.photo-tile').count()>0
    checks.append('favorite persists and filters')
    page.locator('.photo-open').first.click();page.get_by_role('dialog',name='照片查看器').wait_for()
    page.screenshot(path=str(OUT/'photo-viewer.png'))
    page.keyboard.press('Escape');assert page.locator('.lightbox').count()==0
    checks.append('photo viewer and Escape')
    page.get_by_role('button',name='宠物档案',exact=True).click();page.wait_for_timeout(300)
    assert page.locator('.pet-card').count()>=2
    page.screenshot(path=str(OUT/'pets-desktop.png'))
    page.get_by_role('button',name='存储管理',exact=True).click()
    page.get_by_role('button',name='浏览照片',exact=True).click()
    page.get_by_role('button',name='猫咪-基米',exact=True).click()
    page.wait_for_selector('.browse-photo');page.wait_for_timeout(500)
    missing=page.locator('.browse-photo').filter(has_not=page.locator('.already-added')).first
    assert missing.count()>0
    missing.click();page.screenshot(path=str(OUT/'storage-browser.png'))
    page.get_by_role('button',name='添加到图库',exact=True).click();page.wait_for_timeout(600)
    assert client.get('/api/state').json()['counts']['all']==state['counts']['all']+1
    checks.append('manual import of missed cat from real storage')
    page.get_by_role('button',name='相册',exact=True).click()
    if not any(a['name']=='日常小记' for a in client.get('/api/state').json()['albums']):
        page.get_by_role('button',name='创建相册',exact=True).first.click()
        page.get_by_label('相册名称',exact=True).fill('日常小记')
        page.get_by_role('button',name='创建',exact=True).click();page.wait_for_timeout(300)
    assert any(a['name']=='日常小记' for a in client.get('/api/state').json()['albums'])
    checks.append('create album')
    page.get_by_role('button',name='宠物图库',exact=True).click();page.wait_for_timeout(300)
    page.locator('.photo-tile').first.hover()
    page.locator('.select-photo').first.click()
    page.get_by_role('button',name='加入相册',exact=True).click()
    page.get_by_role('button',name='完成',exact=True).click();page.wait_for_timeout(400)
    album=next(a for a in client.get('/api/state').json()['albums'] if a['name']=='日常小记')
    assert album['count']>0
    checks.append('batch selection and add to album')
    page.get_by_role('textbox',name='搜索照片').fill('基米');page.wait_for_timeout(650)
    assert page.locator('.photo-tile').count()>0
    page.get_by_role('textbox',name='搜索照片').fill('');page.wait_for_timeout(500)
    checks.append('search pet names')
    page.reload();page.wait_for_selector('.photo-tile');page.wait_for_timeout(600)
    page.screenshot(path=str(OUT/'gallery-desktop.png'))
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(600)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    page.screenshot(path=str(OUT/'gallery-mobile.png'))
    page.get_by_role('button',name='导航',exact=True).click();page.get_by_role('button',name='宠物图库',exact=True).click();page.get_by_role('button',name='刺猬',exact=True).first.click();page.wait_for_timeout(500)
    assert page.locator('.photo-tile').count()>0
    checks.append('mobile layout and navigation')
    browser.close()
assert not errors,errors
(OUT/'browser-check.json').write_text(json.dumps({'checks':checks,'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':checks,'page_errors':errors},ensure_ascii=True,indent=2))
