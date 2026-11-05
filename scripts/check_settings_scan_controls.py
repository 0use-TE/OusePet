"""Read-only deployed UI check; blocks all API writes, never clears user data."""
from pathlib import Path
import json
import argparse
import httpx
from playwright.sync_api import sync_playwright,expect

out=Path(__file__).resolve().parents[1]/'reports/nas/ui';out.mkdir(parents=True,exist_ok=True)
errors=[];writes=[]
parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://192.168.1.80:8766');parser.add_argument('--preview',action='store_true');args=parser.parse_args()
client=httpx.Client(base_url='http://192.168.1.80:8766',trust_env=False,timeout=30)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.on('pageerror',lambda error:errors.append(str(error)))
    def guard(route):
        if route.request.method!='GET':writes.append(route.request.url);route.abort()
        elif args.preview:
            response=client.get(route.request.url.split(':8770',1)[1]);route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/octet-stream'))
        else:route.continue_()
    page.route('**/api/**',guard)
    page.goto(args.base)
    page.get_by_role('button',name='设置',exact=True).click()
    expect(page.get_by_role('heading',name='文件夹管理')).to_be_visible()
    page.screenshot(path=str(out/'settings-folders-desktop.png'))
    page.get_by_role('button',name='添加文件夹',exact=True).click()
    page.keyboard.press('Escape')
    expect(page.get_by_role('heading',name='文件夹管理')).to_be_visible()
    page.get_by_role('button',name='AI 设置',exact=True).click()
    expect(page.get_by_role('switch',name='GPU 加速',exact=True)).to_be_visible()
    page.wait_for_timeout(200)
    page.screenshot(path=str(out/'settings-ai-desktop.png'))
    page.get_by_role('button',name='数据管理',exact=True).click()
    region=page.get_by_role('region',name='扫描与数据管理')
    region.scroll_into_view_if_needed()
    expect(page.get_by_role('button',name='重新扫描文件夹',exact=True)).to_be_enabled()
    page.screenshot(path=str(out/'settings-scan-desktop.png'))
    for width in (1440,390):
        page.set_viewport_size({'width':width,'height':900})
        page.get_by_role('button',name='清空数据并重新识别',exact=True).click()
        dialog=page.get_by_role('dialog',name='清空数据并重新识别')
        submit=dialog.get_by_role('button',name='清空并重新识别',exact=True)
        expect(submit).to_be_disabled()
        page.get_by_label('请输入“清空并重新识别”以确认',exact=True).fill('清空')
        expect(submit).to_be_disabled()
        page.get_by_label('请输入“清空并重新识别”以确认',exact=True).fill('清空并重新识别')
        expect(submit).to_be_enabled()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(out/f'reset-confirm-{width}.png'))
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog',name='设置')).to_be_visible()
    page.get_by_role('button',name='文件夹管理',exact=True).click()
    assert page.locator('.settings-content').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    page.wait_for_timeout(200)
    page.screenshot(path=str(out/'settings-folders-mobile.png'))
    browser.close()
assert not writes and not errors,(writes,errors)
client.close()
report={'checks':['rescan/reset settings entries','exact typed confirmation','Escape returns to settings','desktop/mobile fit'],'api_writes':writes,'page_errors':errors}
(out/'settings-scan-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report))
