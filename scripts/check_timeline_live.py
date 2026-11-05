"""Read-only NAS timeline smoke test: seek directly to oldest indexed year."""
from pathlib import Path
import json
import httpx
from playwright.sync_api import sync_playwright,expect

base='http://192.168.1.80:8766';out=Path(__file__).resolve().parents[1]/'reports/nas/ui';out.mkdir(parents=True,exist_ok=True)
errors=[];writes=[];requests=[]
with httpx.Client(base_url=base,trust_env=False) as client,sync_playwright() as p:
    index=client.get('/api/photos/timeline?view=gallery').json();assert index['months']
    year=index['months'][-1]['month'][:4];target=next(month for month in index['months'] if month['month'].startswith(year))
    month_title=f"{year}年{int(target['month'][5:])}月"
    browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1519,'height':986})
    page.on('pageerror',lambda error:errors.append(str(error)))
    def guard(route):
        if route.request.method!='GET':writes.append(route.request.url);route.abort()
        else:route.continue_()
    page.route('**/api/**',guard)
    page.on('request',lambda request:requests.append(request.url) if '/api/photos?' in request.url else None)
    page.goto(base+'/?view=gallery');page.wait_for_selector('.photo-tile')
    expect(page.get_by_role('button',name=f'跳转到{year}年',exact=True)).to_be_visible()
    page.screenshot(path=str(out/'timeline-live-desktop.png'))
    requests.clear();page.get_by_role('button',name=f'跳转到{year}年',exact=True).click()
    expect(page.locator('.date-group h2').first).to_contain_text(month_title)
    assert any(f"offset={target['offset']}&" in url for url in requests),requests
    page.screenshot(path=str(out/'timeline-live-oldest.png'))
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert page.locator('.workspace').evaluate('(el)=>el.scrollLeft===0')
    page.screenshot(path=str(out/'timeline-live-mobile.png'))
    assert not errors and not writes,(errors,writes)
    browser.close()
print(json.dumps({'total':index['total'],'oldest_year':year,'target':target,'page_errors':errors,'writes':writes}))
