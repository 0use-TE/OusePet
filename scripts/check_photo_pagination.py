"""Browser pagination regression with isolated API fixtures, no user data writes."""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import httpx
from playwright.sync_api import sync_playwright,expect

parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:8770');args=parser.parse_args()
out=Path(__file__).resolve().parents[1]/'reports/ui';out.mkdir(parents=True,exist_ok=True)
errors=[];writes=[];requests=[];failed=False
with httpx.Client(base_url='http://192.168.1.80:8766',trust_env=False) as client,sync_playwright() as p:
    sample=client.get('/api/photos?limit=1').json()['items'][0]
    fixtures=[{**sample,'id':f'fixture-{i}','name':f'fixture-{i}.jpg','taken_at':'2026-08-11 12:00:00' if i<200 else '2021-06-28 12:00:00'} for i in range(450)]
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1380,'height':900})
    page.on('pageerror',lambda error:errors.append(str(error)))
    def route_api(route):
        global failed
        request=route.request;url=urlsplit(request.url)
        if request.method!='GET':writes.append(request.url);route.abort();return
        if url.path=='/api/photos':
            query=parse_qs(url.query);limit=int(query.get('limit',['200'])[0]);offset=int(query.get('offset',['0'])[0])
            requests.append((offset,limit))
            if offset==200 and not failed:
                failed=True;route.fulfill(status=503,json={'detail':'fixture temporary failure'});return
            photos=fixtures[:1] if query.get('q') else fixtures
            route.fulfill(json={'items':photos[offset:offset+limit],'total':len(photos),'has_more':offset+limit<len(photos)});return
        response=client.get(url.path+('?' +url.query if url.query else ''))
        route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/octet-stream'))
    page.route('**/api/**',route_api)
    page.goto(args.base+'/?view=gallery')
    expect(page.locator('.photo-tile')).to_have_count(200)
    expect(page.locator('.photo-pagination')).to_have_text('已加载 200 / 450 张照片')
    workspace=page.locator('.workspace')
    workspace.evaluate('(el)=>el.scrollTop=el.scrollHeight')
    retry=page.get_by_role('button',name='加载失败，点击重试',exact=True)
    expect(retry).to_be_visible()
    count=len(requests);page.wait_for_timeout(300);assert len(requests)==count,'failure auto-retried repeatedly'
    retry.click();expect(page.locator('.photo-tile')).to_have_count(400)
    assert any('2021年6月28日' in text for text in page.locator('.date-group').all_text_contents())
    workspace.evaluate('(el)=>el.scrollTop=el.scrollHeight')
    expect(page.locator('.photo-tile')).to_have_count(450)
    expect(page.locator('.photo-pagination')).to_have_text('已加载 450 / 450 张照片')
    expect(page.get_by_role('button',name='继续加载照片',exact=True)).to_have_count(0)
    page.screenshot(path=str(out/'pagination-older-photos.png'))
    page.get_by_role('textbox',name='搜索照片').fill('fixture')
    expect(page.locator('.photo-tile')).to_have_count(1)
    expect(page.locator('.photo-pagination')).to_have_text('已加载 1 / 1 张照片')
    assert not errors and not writes,(errors,writes)
    browser.close()
print(json.dumps({'checks':['initial count','automatic scroll pagination reaches older dates','failure pauses and supports retry','all photos loaded','scope resets count'],'requests':requests,'page_errors':errors,'writes':writes}))
