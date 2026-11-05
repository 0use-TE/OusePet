"""Delayed/out-of-order response regression: never render another route's photos."""
import argparse
import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import httpx
from playwright.async_api import async_playwright,expect

parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://192.168.1.80:8766');parser.add_argument('--preview',action='store_true');args=parser.parse_args()

async def main():
  errors=[];calls=[]
  async with httpx.AsyncClient(base_url='http://192.168.1.80:8766',trust_env=False,timeout=30) as client,async_playwright() as p:
    fixture=(await client.get('/api/state')).json();source=(await client.get('/api/photos?view=all&limit=3')).json()['items']
    fixture['pets']=[{'id':key,'name':name,'species':'cat','cover':None,'count':1,'unnamed':False} for key,name in [('nav-a','测试宠物A'),('nav-b','测试宠物B')]]
    fixture['jobs']=[];fixture['discovery']={'status':'complete','total':0,'processed':0,'errors':0,'error':None}
    browser=await p.chromium.launch(channel='msedge',headless=True);page=await browser.new_page(viewport={'width':1519,'height':986})
    page.on('pageerror',lambda error:errors.append(str(error)))
    fail_once=True
    async def api(route):
      nonlocal fail_once
      path=urlsplit(route.request.url).path;params=parse_qs(urlsplit(route.request.url).query)
      assert route.request.method=='GET'
      if path=='/api/state':await route.fulfill(json=fixture);return
      if path=='/api/photos':
        pet=params.get('pet_id',[''])[0];query=params.get('q',[''])[0];calls.append(pet)
        await asyncio.sleep(.65 if pet=='nav-a' else .08)
        if query=='fail' and fail_once:
          fail_once=False;await route.fulfill(status=503,json={'detail':'测试加载失败'});return
        item=copy.deepcopy(source[0]);item.update(id=pet or 'other',name=pet or 'OTHER',pets=[])
        await route.fulfill(json={'items':[item],'total':1});return
      if args.preview:
        response=await client.get(path+('?' + urlsplit(route.request.url).query if urlsplit(route.request.url).query else ''))
        await route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/octet-stream'))
      else:await route.continue_()
    await page.route('**/api/**',api)
    await page.goto(args.base+'/?view=all');await page.wait_for_selector('.photo-open')
    await page.evaluate('''()=>{window.badPhotoFrames=[];function observe(){const title=document.querySelector('h1')?.textContent;const expected=title==='测试宠物A'?'nav-a':title==='测试宠物B'?'nav-b':null;if(expected){for(const img of document.querySelectorAll('.photo-open img'))if(img.alt!==expected)window.badPhotoFrames.push({title,alt:img.alt});}requestAnimationFrame(observe)}observe()}''')
    async def open_pet(name):
      await page.get_by_role('button',name='宠物档案',exact=True).click()
      await page.locator('.pet-card').filter(has_text=name).locator('.pet-open').click()
      await expect(page.locator('h1')).to_have_text(name)
    await open_pet('测试宠物A')
    await expect(page.locator('.photo-tile')).to_have_count(0)
    await expect(page.get_by_role('status').filter(has_text='正在加载照片')).to_be_visible()
    await expect(page.locator('.photo-open img')).to_have_attribute('alt','nav-a')
    # A pending A response arrives after B; it must not overwrite B.
    await page.get_by_role('button',name='有宠相簿',exact=True).click()
    await expect(page.locator('.photo-open img')).to_have_attribute('alt','OTHER')
    await open_pet('测试宠物A')
    await open_pet('测试宠物B')
    await expect(page.locator('.photo-open img')).to_have_attribute('alt','nav-b')
    await page.wait_for_timeout(900)
    await expect(page.locator('.photo-open img')).to_have_attribute('alt','nav-b')
    await page.go_back();await expect(page.locator('h1')).to_have_text('宠物档案')
    await page.go_back();await expect(page.locator('h1')).to_have_text('测试宠物A')
    await expect(page.locator('.photo-open img')).to_have_attribute('alt','nav-a')
    await page.get_by_role('textbox',name='搜索照片').fill('fail')
    await expect(page.get_by_role('button',name='重试加载',exact=True)).to_be_visible()
    await expect(page.locator('.photo-tile')).to_have_count(0)
    await page.get_by_role('button',name='重试加载',exact=True).click()
    await expect(page.locator('.photo-open img')).to_have_attribute('alt','nav-a')
    bad=await page.evaluate('window.badPhotoFrames');assert not bad,bad
    assert not errors,errors
    await browser.close()
    report={'base':args.base,'checks':['delayed pet load hides prior gallery','out-of-order responses cannot overwrite current pet','back navigation remains scoped','error retry retains scope','no incorrect photos in animation frames'],'incorrect_frames':bad,'page_errors':errors}
    out=Path(__file__).resolve().parents[1]/'reports/ui/photo-navigation-check.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=True,indent=2))
asyncio.run(main())
