"""Read-only regression checks for the default pet gallery and explicit all-media route."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

parser=argparse.ArgumentParser()
parser.add_argument('--base',default='http://192.168.1.80:8766')
parser.add_argument('--preview',action='store_true',help='Use local frontend/dist with the read-only live API')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':980})
    errors=[];requests=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:requests.append(request.url))
    def guard(route):
        request=route.request;path=urlsplit(request.url).path
        assert request.method=='GET','This check must remain read-only'
        if args.preview and request.is_navigation_request() and path=='/':
            return route.fulfill(path=str(root/'frontend/dist/index.html'))
        if args.preview and path.startswith('/assets/'):
            return route.fulfill(path=str(root/'frontend/dist/assets'/Path(path).name))
        route.continue_()
    page.route('**/*',guard)
    page.goto(args.base+'/')
    expect(page.locator('h1')).to_have_text('宠物图库')
    expect(page.get_by_role('button',name='宠物图库',exact=True)).to_have_class('nav-item active')
    page.wait_for_function("document.querySelector('.workspace')?.getAttribute('aria-busy') === 'false'")
    assert any('/api/photos?view=gallery&' in url for url in requests)
    assert not any('/api/photos?view=all&' in url for url in requests)
    page.get_by_role('button',name='图库',exact=True).click()
    expect(page.locator('h1')).to_have_text('图库')
    assert 'view=all' in page.url
    page.reload();expect(page.locator('h1')).to_have_text('图库')
    page.get_by_role('group',name='媒体类型筛选').get_by_role('button',name='照片',exact=True).click()
    assert 'view=all' in page.url and 'media=image' in page.url
    page.reload();expect(page.locator('h1')).to_have_text('图库')
    expect(page.get_by_role('group',name='媒体类型筛选').get_by_role('button',name='照片',exact=True)).to_have_attribute('aria-pressed','true')
    page.get_by_role('button',name='宠物图库',exact=True).click()
    expect(page.locator('h1')).to_have_text('宠物图库')
    assert not urlsplit(page.url).query
    page.reload();expect(page.locator('h1')).to_have_text('宠物图库')
    page.goto(args.base+'/?view=all');expect(page.locator('h1')).to_have_text('图库')
    page.goto(args.base+'/?view=videos');expect(page.locator('h1')).to_have_text('图库')
    expect(page.get_by_role('group',name='媒体类型筛选').get_by_role('button',name='视频',exact=True)).to_have_attribute('aria-pressed','true')
    assert not errors,errors
    browser.close()
print('PASS default pet gallery, explicit all-media route/reload, media filter, root return and legacy video link; read-only')
