"""Read-only NAS checks for library picker, multi-profile merge and editable kind."""
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect

out=Path(__file__).resolve().parents[1]/'reports/nas/ui';out.mkdir(parents=True,exist_ok=True)
errors=[];writes=[]
with httpx.Client(base_url='http://192.168.1.80:8766',trust_env=False) as client,sync_playwright() as p:
    state=client.get('/api/state').json();cats=[pet for pet in state['pets'] if pet['species']=='cat'][:2]
    assert len(cats)==2
    corrected=next(pet for pet in state['pets'] if pet['id']=='587cd776fa48428fad3d0c72d998a98a')
    assert corrected['species']=='hedgehog'
    album=state['albums'][0] if state['albums'] else None
    suffix='album='+album['id'] if album else 'pet='+cats[0]['id']
    browser=p.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':950})
    page.on('pageerror',lambda error:errors.append(str(error)))
    def guard(route):
        if route.request.method!='GET':writes.append(route.request.url);route.abort()
        else:route.continue_()
    page.route('**/api/**',guard)
    page.goto('http://192.168.1.80:8766/?view=gallery&'+suffix)
    page.get_by_role('button',name='添加照片',exact=True).first.click()
    dialog=page.get_by_role('dialog',name='从宠物图库添加照片');expect(dialog).to_be_visible()
    page.wait_for_selector('.picker-photo:not(:disabled)')
    photos=dialog.locator('.picker-photo:not(:disabled)');photos.nth(0).click();photos.nth(1).click()
    expect(dialog.locator('.picker-footer')).to_contain_text('已选 2 张')
    page.screenshot(path=str(out/'photo-picker-live.png'))
    page.keyboard.press('Escape');expect(dialog).to_have_count(0)
    page.goto('http://192.168.1.80:8766/?view=pets')
    for cat in cats:page.locator(f'.pet-card[data-pet-id="{cat["id"]}"] .pet-select').click()
    page.get_by_role('button',name='合并宠物',exact=True).click()
    merge=page.get_by_role('dialog',name='合并宠物档案');expect(merge.locator('.merge-pet-previews > div')).to_have_count(2)
    page.screenshot(path=str(out/'pet-bulk-merge-live.png'))
    page.keyboard.press('Escape');page.keyboard.press('Escape')
    card=page.locator(f'.pet-card[data-pet-id="{corrected["id"]}"]')
    card.get_by_role('button',name='编辑'+corrected['name'],exact=True).click()
    editor=page.get_by_role('dialog',name='编辑宠物档案')
    expect(editor.get_by_role('button',name='刺猬',exact=True)).to_have_attribute('aria-pressed','true')
    page.set_viewport_size({'width':390,'height':844})
    assert editor.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    page.screenshot(path=str(out/'pet-species-live-mobile.png'))
    page.keyboard.press('Escape');assert not errors and not writes,(errors,writes)
    browser.close()
print('PASS: deployed multi-picker, two-card merge confirmation and corrected species editor; no API writes/browser errors')
