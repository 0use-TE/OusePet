"""Read-only UI checks for standalone navigation, routing and custom pickers."""
import argparse
import json
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://192.168.1.80:8766')
parser.add_argument('--preview', action='store_true', help='Proxy preview API/media to NAS')
args = parser.parse_args()
out = Path(__file__).resolve().parents[1] / 'reports/nas/ui'
out.mkdir(parents=True, exist_ok=True)
errors = []
checks = []
with httpx.Client(base_url='http://192.168.1.80:8766', trust_env=False, timeout=30) as client, sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1519, 'height': 986})
    page.on('pageerror', lambda error: errors.append(str(error)))
    if args.preview:
        def proxy(route):
            response = client.get(route.request.url.split(':8770', 1)[1])
            route.fulfill(status=response.status_code, body=response.content,
                          content_type=response.headers.get('content-type', 'application/octet-stream'))
        page.route('**/api/**', proxy)
    page.goto(args.base+'/?view=all')
    page.wait_for_selector('.photo-tile')
    expect(page.locator('h1')).to_have_text('图库')
    workspace=page.locator('.workspace')
    assert page.evaluate('document.documentElement.scrollHeight <= innerHeight')
    assert page.locator('.search').bounding_box()['width'] > 800
    before=page.locator('.search').bounding_box()
    workspace.hover();page.mouse.wheel(0,900)
    page.wait_for_function('document.querySelector(".workspace").scrollTop > 200')
    assert page.evaluate('scrollY')==0
    assert page.locator('.search').bounding_box()==before
    page.screenshot(path=str(out/'gallery-inner-scroll.png'))
    workspace.evaluate('(element) => element.scrollTop = 0')
    checks.append('gallery owns vertical scroll; page and wide search stay fixed')
    assert page.locator('.sidebar .nav-item').count() == 7
    assert page.locator('.sidebar-note').count() == 0
    assert page.get_by_role('button', name='图库显示设置', exact=True).count() == 0
    assert page.locator('.topbar').get_by_role('button', name='添加存储', exact=True).count() == 0
    page.get_by_role('button', name='宠物图库', exact=True).click()
    page.get_by_role('button', name='猫咪', exact=True).click()
    expect(page.locator('h1')).to_have_text('猫咪')
    assert workspace.evaluate('(element) => element.scrollTop')==0
    assert 'view=cats' in page.url
    expect(page.locator('.sidebar .active')).to_have_text('宠物图库')
    page.reload()
    expect(page.locator('h1')).to_have_text('猫咪')
    page.go_back()
    expect(page.locator('h1')).to_have_text('宠物图库')
    checks.append('seven sidebar items including external links; no review/duplicate species/settings/add entry; route reload and back')
    page.get_by_role('button', name='设置', exact=True).click()
    page.get_by_role('button', name='显示设置', exact=True).click()
    picker = page.get_by_role('button', name='拍摄时间排序', exact=True)
    picker.click()
    expect(page.get_by_role('listbox', name='拍摄时间排序')).to_be_visible()
    page.screenshot(path=str(out / 'navigation-dropdown.png'))
    page.keyboard.press('End')
    page.keyboard.press('Enter')
    expect(picker).to_contain_text('最早在前')
    picker.click()
    page.keyboard.press('Home')
    page.keyboard.press('Enter')
    expect(picker).to_contain_text('最新在前')
    picker.click()
    page.keyboard.press('Escape')
    expect(picker).to_be_focused()
    expect(page.get_by_role('dialog', name='设置', exact=True)).to_be_visible()
    page.get_by_role('button', name='关闭', exact=True).click()
    checks.append('dropdown in modal: dark menu, keyboard selection, Escape and focus restoration')
    page.get_by_role('button', name='全屏显示', exact=True).click()
    page.wait_for_function('Boolean(document.fullscreenElement)')
    page.get_by_role('button', name='退出全屏', exact=True).click()
    page.wait_for_function('!document.fullscreenElement')
    checks.append('browser fullscreen enter and exit')
    page.get_by_role('button', name='图库', exact=True).click()
    page.wait_for_selector('.photo-tile')
    page.screenshot(path=str(out / 'navigation-desktop.png'))
    page.locator('.photo-open').first.click()
    page.get_by_role('button', name='选择宠物身份', exact=True).click()
    expect(page.get_by_role('listbox', name='选择宠物身份')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('.lightbox')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('.lightbox')).to_have_count(0)
    checks.append('photo identity picker Escape leaves viewer open')
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.get_by_role('button', name='设置', exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.get_by_role('button', name='导航', exact=True).click()
    page.get_by_role('button', name='宠物图库', exact=True).click()
    page.get_by_role('button', name='刺猬', exact=True).click()
    expect(page.locator('h1')).to_have_text('刺猬')
    page.get_by_role('button', name='设置', exact=True).click()
    page.get_by_role('button', name='显示设置', exact=True).click()
    page.get_by_role('button', name='拍摄时间排序', exact=True).click()
    bounds = page.get_by_role('listbox', name='拍摄时间排序').bounding_box()
    assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
    page.screenshot(path=str(out / 'navigation-mobile-dropdown.png'))
    page.keyboard.press('Escape')
    page.get_by_role('button', name='关闭', exact=True).click()
    page.screenshot(path=str(out / 'navigation-mobile.png'))
    checks.append('mobile navigation and dropdown fit viewport; settings remains visible')
    browser.close()
assert not errors, errors
report = {'base': args.base, 'preview': args.preview, 'checks': checks, 'page_errors': errors}
(out.parent / 'navigation-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
