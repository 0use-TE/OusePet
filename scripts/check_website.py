"""Check the buildless Pages website without third-party dependencies."""
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'website'


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids, f'Duplicate ID: {attrs["id"]}'
            self.ids.add(attrs['id'])
        for key in ('src', 'href'):
            if key in attrs:
                self.links.append(attrs[key])
        if tag == 'img':
            assert 'alt' in attrs, 'Image needs alternative text'


def main():
    page = Page()
    page.feed((SITE / 'index.html').read_text(encoding='utf-8'))
    assert 'image-viewer' in page.ids and 'preview-panel' in page.ids
    for value in page.links:
        url = urlsplit(value)
        if url.scheme or url.netloc:
            assert url.scheme == 'https', f'Unexpected external scheme: {value}'
            continue
        assert not url.path.startswith('/'), f'Use project-relative asset paths: {value}'
        if url.path:
            target = (SITE / unquote(url.path)).resolve()
            assert target.is_relative_to(SITE.resolve()) and target.is_file(), f'Missing asset: {value}'
        if not url.path and url.fragment:
            assert url.fragment in page.ids, f'Missing section: {value}'
    for value in re.findall(r"assets/[\w.-]+", (SITE / 'app.js').read_text(encoding='utf-8')):
        assert (SITE / value).is_file(), f'Missing preview: {value}'
    assert not (SITE / 'CNAME').exists(), 'Project website must preserve the account Pages domain'
    print(f'PASS: website assets, {len(page.ids)} unique IDs, navigation, preview resources and project-relative paths')


if __name__ == '__main__':
    main()
