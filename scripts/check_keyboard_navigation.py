"""Read-only keyboard/overlay hierarchy checks against the built album."""
import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import httpx
from playwright.sync_api import sync_playwright,expect

parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://192.168.1.80:8766');parser.add_argument('--preview',action='store_true');args=parser.parse_args()
out=Path(__file__).resolve().parents[1]/'reports/ui';out.mkdir(exist_ok=True)
errors=[];writes=[]
with httpx.Client(base_url='http://192.168.1.80:8766',trust_env=False,timeout=30) as client,sync_playwright() as p:
    fixture=copy.deepcopy(client.get('/api/state').json())
    fixture['albums']=[{'id':'keyboard-album','name':'快捷键测试相册','count':2,'cover':None}]
    sample=client.get('/api/photos?view=all&limit=2').json()['items']
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1519,'height':986})
    page.on('pageerror',lambda error:errors.append(str(error)))
    def requests(route):
        if route.request.method!='GET':writes.append(route.request.url);route.abort();return
        parsed=urlsplit(route.request.url)
        if parsed.path=='/api/state':route.fulfill(json=fixture);return
        if parsed.path=='/api/photos' and parse_qs(parsed.query).get('album_id')==['keyboard-album']:
            route.fulfill(json={'items':sample,'total':len(sample)});return
        if args.preview:
            response=client.get(parsed.path+('?' + parsed.query if parsed.query else ''))
            route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/octet-stream'))
        else:route.continue_()
    page.route('**/api/**',requests)
    page.goto(args.base+'/?view=pets');page.wait_for_selector('.pet-open')
    assert page.locator('.discovery-panel').count()==0
    assert page.get_by_text('相似宠物出现在至少 5 张不同照片中',exact=False).count()==0
    page.locator('.pet-open').first.click();page.wait_for_selector('.photo-open')
    title=page.locator('h1').inner_text()
    page.locator('.photo-open').first.click()
    image=page.locator('.lightbox-photo img');original=image.get_attribute('src')
    page.keyboard.press('ArrowRight');expect(image).not_to_have_attribute('src',original)
    page.keyboard.press('ArrowLeft');expect(image).to_have_attribute('src',original)
    page.get_by_role('button',name='选择宠物身份',exact=True).click()
    page.keyboard.press('Escape')
    expect(page.get_by_role('listbox',name='选择宠物身份')).not_to_be_visible()
    expect(page.locator('.lightbox')).to_have_count(1)
    page.keyboard.press('Escape');expect(page.locator('.lightbox')).to_have_count(0)
    expect(page.locator('h1')).to_have_text(title)
    page.locator('.photo-open').first.focus();page.keyboard.press('Control+a')
    expect(page.locator('.photo-tile.selected')).to_have_count(page.locator('.photo-tile').count())
    page.keyboard.press('Escape');expect(page.locator('.selection-bar')).to_have_count(0)
    expect(page.locator('h1')).to_have_text(title)
    page.get_by_role('button',name='设置',exact=True).click()
    page.get_by_role('button',name='使用帮助',exact=True).click()
    expect(page.get_by_role('heading',name='自动发现宠物与增量识别')).to_be_visible()
    expect(page.get_by_role('heading',name='键盘操作')).to_be_visible()
    page.get_by_role('heading',name='键盘操作').scroll_into_view_if_needed()
    page.screenshot(path=str(out/'settings-keyboard-desktop.png'))
    page.get_by_role('button',name='显示设置',exact=True).click()
    page.get_by_role('button',name='拍摄时间排序',exact=True).click()
    page.keyboard.press('Escape');expect(page.get_by_role('dialog',name='设置')).to_be_visible()
    page.keyboard.press('Escape');expect(page.get_by_role('dialog',name='设置')).to_have_count(0)
    expect(page.locator('h1')).to_have_text(title)
    page.keyboard.press('Escape');expect(page.locator('h1')).to_have_text('宠物档案')
    page.locator('h1').click();page.keyboard.press('/')
    search=page.get_by_role('textbox',name='搜索照片');expect(search).to_be_focused()
    search.fill('键盘测试');page.keyboard.press('Control+a')
    assert search.evaluate('(input)=>input.selectionStart===0&&input.selectionEnd===input.value.length')
    assert page.locator('.photo-tile.selected').count()==0
    page.keyboard.press('Escape');expect(search).to_have_value('')
    expect(page.locator('h1')).to_have_text('宠物档案')
    page.goto(args.base+'/?view=gallery&album=keyboard-album');page.wait_for_selector('.photo-open')
    page.keyboard.press('Escape');expect(page.locator('h1')).to_have_text('相册')
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
    page.get_by_role('button',name='导航',exact=True).click();expect(page.locator('.sidebar')).to_have_class('sidebar open')
    page.keyboard.press('Escape');expect(page.locator('.sidebar.open')).to_have_count(0)
    expect(page.locator('h1')).to_have_text('相册')
    page.get_by_role('button',name='设置',exact=True).click()
    page.get_by_role('button',name='使用帮助',exact=True).click()
    page.get_by_role('heading',name='键盘操作').scroll_into_view_if_needed()
    assert page.get_by_role('dialog',name='设置').evaluate('(dialog)=>dialog.scrollWidth<=dialog.clientWidth')
    page.screenshot(path=str(out/'settings-keyboard-mobile.png'))
    page.keyboard.press('Escape');expect(page.locator('h1')).to_have_text('相册')
    assert not errors and not writes,(errors,writes)
    browser.close()
report={'base':args.base,'checks':['Esc closes picker, viewer, selection, dialog, drawer and parent route one layer at a time',
       'pet/album details return to lists','arrow keys navigate viewer','Ctrl+A selects loaded photos but retains text editing','slash focuses search',
       'discovery explanation only in settings','desktop/mobile settings fit'],'page_errors':errors,'api_writes':writes}
(out/'keyboard-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=True,indent=2))
