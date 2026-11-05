"""Read-only layout regression for many pet groups and long names."""
import argparse
import copy
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

parser=argparse.ArgumentParser()
parser.add_argument('--base',default='http://192.168.1.80:8766')
parser.add_argument('--preview',action='store_true')
args=parser.parse_args()
out=Path(__file__).resolve().parents[1]/'reports/identity/ui';out.mkdir(parents=True,exist_ok=True)
errors=[];checks=[]
with httpx.Client(base_url='http://192.168.1.80:8766',trust_env=False,timeout=30) as client,sync_playwright() as p:
    fixture=copy.deepcopy(client.get('/api/state').json())
    fixture['jobs']=[{'id':'layout-scan','storage_id':'layout-storage','storage_name':'手机照片','status':'running','total':1000,'processed':200,'found':20,'error':None}]
    fixture['pets']=[{'id':f'layout-{index}','name':('未命名猫咪' if index%2==0 else '未命名刺猬')+('名字非常非常长的小伙伴' if index%7==0 else ''),
                     'species':'cat' if index%2==0 else 'hedgehog','cover':None,'count':5,'unnamed':True} for index in range(40)]
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    if args.preview:
        def proxy(route):
            response=client.get(route.request.url.split(':8770',1)[1])
            route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/octet-stream'))
        page.route('**/api/**',proxy)
    page.route('**/api/state',lambda route:route.fulfill(json=fixture))
    for width in (1519,800,390):
        page.set_viewport_size({'width':width,'height':900})
        page.goto(args.base+'/?view=review')
        page.wait_for_selector('.pet-shortcuts button')
        layout=page.evaluate('''()=>{
          const row=document.querySelector('.filter-row'),tabs=document.querySelector('.filter-tabs'),pets=document.querySelector('.pet-shortcuts'),work=document.querySelector('.workspace');
          return {rowHeight:row.clientHeight,tabsHeight:tabs.clientHeight,petHeight:pets.clientHeight,
            scrollable:pets.scrollWidth>pets.clientWidth,workOverflow:work.scrollWidth-work.clientWidth,
            wrapped:[...pets.querySelectorAll('button span')].some(s=>s.getBoundingClientRect().height>24),
            tabsWrap:[...tabs.querySelectorAll('button')].some(s=>getComputedStyle(s).whiteSpace!=='nowrap')};
        }''')
        assert layout['scrollable'] and not layout['wrapped'] and not layout['tabsWrap'],layout
        assert layout['workOverflow']<=1 and layout['tabsHeight']<40 and layout['petHeight']<=44,layout
        assert layout['rowHeight']<95,layout
        assert page.locator('.heading-actions .filter-tabs').count()==1
        assert page.locator('.filter-row .filter-tabs').count()==0
        tabs=page.locator('.filter-tabs').bounding_box();sort=page.locator('.sort-button').bounding_box()
        assert tabs['x']+tabs['width']<=sort['x']+1
        assert page.locator('.pet-shortcuts').bounding_box()['y']>=tabs['y']+tabs['height']
        page.locator('.pet-shortcuts button').last.focus()
        assert page.locator('.pet-shortcuts').evaluate('(element)=>element.scrollLeft')>0
        page.locator('.pet-shortcuts').evaluate('(element)=>element.scrollLeft=0')
        page.screenshot(path=str(out/f'pet-filters-{width}.png'))
        assert page.locator('.scan-strip').count()==0
        ball_before=page.locator('.scan-fab').bounding_box()
        assert page.locator('.scan-fab').inner_text()=='20%'
        page.locator('.select-photo').first.click()
        page.locator('.workspace').hover();page.mouse.wheel(0,900)
        page.wait_for_function('document.querySelector(".workspace").scrollTop>200')
        ball=page.locator('.scan-fab').bounding_box()
        workspace=page.locator('.workspace').bounding_box()
        selection=page.locator('.selection-bar').bounding_box()
        assert ball==ball_before,(ball,ball_before)
        assert ball['x']>=workspace['x'] and ball['x']+ball['width']<=workspace['x']+workspace['width']
        assert abs(selection['y']-(workspace['y']+24 if width>1100 else workspace['y']+22 if width>800 else workspace['y']+20 if width>540 else workspace['y']+19))<2
        page.screenshot(path=str(out/f'floating-progress-{width}.png'))
        page.locator('.scan-fab').click()
        assert page.get_by_role('dialog',name='扫描任务',exact=True).is_visible()
        assert page.evaluate('''()=>{const dialog=document.querySelector('dialog[open]'),r=dialog.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2).closest('dialog')===dialog}''')
        page.get_by_role('button',name='关闭',exact=True).click()
        page.get_by_role('button',name='取消选择',exact=True).click()
        page.locator('.workspace').evaluate('(element)=>element.scrollTop=0')
        checks.append({'viewport':width,**layout})
    page.locator('.pet-shortcuts button').last.click()
    assert 'pet=layout-39' in page.url
    # Pause, queued discovery and completion should have sensible compact states.
    fixture['jobs'][0]['status']='paused'
    fixture['discovery']={'status':'complete','total':0,'processed':0,'errors':0,'error':None}
    page.reload();page.wait_for_selector('.scan-fab')
    assert '已暂停' in page.locator('.scan-fab').get_attribute('aria-label')
    fixture['jobs']=[]
    fixture['discovery']['status']='queued'
    page.reload();page.wait_for_selector('.scan-fab')
    assert '等待处理' in page.locator('.scan-fab').get_attribute('aria-label')
    fixture['discovery']['status']='complete'
    page.reload();page.wait_for_selector('h1')
    assert page.locator('.scan-fab').count()==0
    assert not errors,errors
    browser.close()
    report={'base':args.base,'fixture_groups':40,'checks':checks,'page_errors':errors}
    (out.parent/'pet-filters-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))
