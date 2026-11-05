"""Read-only browser checks for whole-photo selection mode across date groups."""
import argparse
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect

parser=argparse.ArgumentParser()
parser.add_argument('--base',default='http://192.168.1.80:8766')
parser.add_argument('--preview',action='store_true')
args=parser.parse_args()
out=Path(__file__).resolve().parents[1]/'reports/ui';out.mkdir(exist_ok=True)
errors=[];writes=[]
with httpx.Client(base_url='http://192.168.1.80:8766',trust_env=False,timeout=30) as client,sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    def requests(route):
        if route.request.method!='GET':
            writes.append(route.request.url);route.abort();return
        if args.preview:
            response=client.get(route.request.url.split(':8770',1)[1])
            route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/octet-stream'))
        else:route.continue_()
    page.route('**/api/**',requests)
    for width in (1519,390):
        page.set_viewport_size({'width':width,'height':900})
        page.goto(args.base+'/?view=all');page.wait_for_selector('.photo-open')
        tiles=page.locator('.photo-open');first=tiles.nth(0);second=tiles.nth(1);third=tiles.nth(2)
        first.click();expect(page.locator('.lightbox')).to_have_count(1)
        page.keyboard.press('Escape');expect(page.locator('.lightbox')).to_have_count(0)
        page.locator('.select-photo').first.click()
        expect(page.locator('.photo-tile.selected')).to_have_count(1)
        assert page.locator('.photo-grid:not(.selecting)').count()==0
        assert page.locator('.favorite-photo:visible').count()==0
        # The former favorite icon area must now behave like the rest of the image.
        size=second.bounding_box();second.click(position={'x':size['width']-12,'y':12})
        expect(page.locator('.photo-tile.selected')).to_have_count(2)
        third.click();expect(page.locator('.photo-tile.selected')).to_have_count(3)
        expect(page.locator('.lightbox')).to_have_count(0)
        page.screenshot(path=str(out/f'whole-photo-selection-{width}.png'))
        third.focus();page.keyboard.press('Space')
        expect(page.locator('.photo-tile.selected')).to_have_count(2)
        second.click();first.click()
        expect(page.locator('.selection-bar')).to_have_count(0)
        assert page.locator('.photo-grid.selecting').count()==0
        first.click();expect(page.locator('.lightbox')).to_have_count(1)
        page.keyboard.press('Escape')
        page.locator('.select-photo').first.click()
        page.get_by_role('button',name='取消选择',exact=True).click()
        first.click();expect(page.locator('.lightbox')).to_have_count(1)
        page.keyboard.press('Escape')
    browser.close()
assert not errors and not writes,(errors,writes)
report={'base':args.base,'checks':['normal click previews','first selection enables whole-image selection across date groups',
        'former favorite area selects instead','click and Space toggle selection','last deselection restores preview',
        'cancel selection restores preview','desktop/mobile','no API writes'],'page_errors':errors}
(out/'photo-selection-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
