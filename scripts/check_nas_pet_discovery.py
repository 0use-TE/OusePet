"""Read-only checks of automatically discovered groups on the deployed NAS."""
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect

BASE='http://192.168.1.80:8766'
OUT=Path(__file__).resolve().parents[1]/'reports/identity';(OUT/'ui').mkdir(parents=True,exist_ok=True)
with httpx.Client(base_url=BASE,trust_env=False,timeout=30) as client,sync_playwright() as p:
    initial=client.get('/api/state').json()
    groups=[pet for pet in initial['pets'] if pet['unnamed'] and pet['count']>=5]
    assert groups,'no five-photo group has been discovered yet'
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1519,'height':986})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(BASE+'/?view=pets')
    cards=page.locator('.pet-card').filter(has_text='未命名')
    expect(cards.first).to_be_visible()
    page.wait_for_function('Array.from(document.querySelectorAll(".pet-card img")).every(i=>i.complete&&i.naturalWidth>0)')
    page.screenshot(path=str(OUT/'ui'/'nas-unnamed-pets.png'))
    cards.first.locator('.pet-card-actions button').first.click()
    expect(page.get_by_role('dialog',name='编辑宠物档案')).to_be_visible()
    expect(page.get_by_label('宠物名字',exact=True)).to_have_value('')
    page.screenshot(path=str(OUT/'ui'/'nas-name-pet.png'))
    page.get_by_role('button',name='关闭',exact=True).click()
    cards.first.locator('.pet-open').click()
    page.wait_for_function('document.querySelectorAll(".photo-tile").length>=5')
    page.wait_for_function('Array.from(document.querySelectorAll(".photo-open img")).filter(i=>i.getBoundingClientRect().top<innerHeight).every(i=>i.complete&&i.naturalWidth>0)')
    page.screenshot(path=str(OUT/'ui'/'nas-unnamed-photos.png'))
    page.get_by_role('button',name='宠物档案',exact=True).click()
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'ui'/'nas-pets-mobile.png'))
    browser.close();assert not errors,errors
    current=client.get('/api/state').json()
    report={'discovery':current['discovery'],'groups':current['pets'],'runtime':client.get('/api/runtime').json(),
            'checks':['actual five-photo groups published','naming dialog opens without changing user names','real grouped photos load',
                      'desktop/mobile layout','no page errors'], 'page_errors':errors}
    (OUT/'nas-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'discovery':report['discovery'],'unnamed_groups':sum(pet['unnamed'] for pet in report['groups']),
                      'checks':report['checks']},ensure_ascii=True,indent=2))
