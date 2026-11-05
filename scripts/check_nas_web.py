"""Verify the deployed NAS UI and set the requested inference preference from the web."""
import argparse,json,time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect

parser=argparse.ArgumentParser()
parser.add_argument('--mode',choices=['cpu','gpu'],required=True)
args=parser.parse_args()
base='http://192.168.1.80:8766'
out=Path(__file__).resolve().parents[1]/'reports/nas';(out/'ui').mkdir(parents=True,exist_ok=True)
client=httpx.Client(base_url=base,trust_env=False,timeout=30)
initial=client.get('/api/state').json();errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1519,'height':986})
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base);page.wait_for_selector('.photo-tile')
    assert page.locator('h1').inner_text()=='图库'
    assert page.locator('.gallery-end').count()==0
    page.get_by_role('button',name='宠物图库',exact=True).click()
    page.get_by_role('button',name='刺猬',exact=True).first.click()
    page.wait_for_selector('.photo-open');page.locator('.photo-open').first.click()
    page.wait_for_function("(()=>{const e=document.querySelector('.lightbox-photo img');return e&&e.complete&&e.naturalWidth>0})()")
    page.keyboard.press('Escape')
    page.get_by_role('button',name='设置',exact=True).first.click()
    switch=page.get_by_role('switch',name='GPU 加速',exact=True)
    expect(switch).to_be_enabled(timeout=15000)
    expected=args.mode=='gpu'
    if (switch.get_attribute('aria-checked')=='true')!=expected:switch.click()
    for _ in range(150):
        settings=client.get('/api/settings').json()
        if settings['gpu_enabled']==expected and not settings['switching'] and (settings['device'].startswith('cuda') if expected else settings['device']=='cpu'):break
        time.sleep(.2)
    assert settings['gpu_enabled']==expected and not settings['switching'],settings
    assert settings['device'].startswith('cuda') if expected else settings['device']=='cpu',settings
    expect(switch).to_have_attribute('aria-checked',str(expected).lower(),timeout=5000)
    page.wait_for_timeout(1300)
    page.screenshot(path=str(out/'ui'/f'settings-{args.mode}.png'))
    page.reload();page.wait_for_selector('h1')
    page.get_by_role('button',name='设置',exact=True).first.click()
    expect(page.get_by_role('switch',name='GPU 加速')).to_be_enabled(timeout=15000)
    expect(page.get_by_role('switch',name='GPU 加速')).to_have_attribute('aria-checked',str(expected).lower())
    page.get_by_role('button',name='关闭',exact=True).click()
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(out/'ui'/'mobile.png'))
    browser.close()
assert not errors,errors
report={'mode':args.mode,'settings':settings,'runtime':client.get('/api/runtime').json(),'initial_counts':initial['counts'],'current_state':client.get('/api/state').json(),'page_errors':errors}
(out/f'web-check-{args.mode}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'mode':args.mode,'settings':settings,'page_errors':errors},ensure_ascii=True))
