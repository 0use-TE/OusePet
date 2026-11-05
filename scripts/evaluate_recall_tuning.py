"""Evaluate grouping coverage on a copied NAS snapshot, never the live library."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ousepet import identity
root=ROOT/'reports/identity';root.mkdir(exist_ok=True)
with closing(sqlite3.connect(root/'tuning-before.sqlite3')) as source,closing(sqlite3.connect(root/'tuning-after.sqlite3')) as c:
    source.backup(c);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
    identity.init_schema(c)
    def summary():
        return {'pets':[dict(row) for row in c.execute('''SELECT pe.id,pe.name,pe.species,count(DISTINCT pp.photo_id) photos
            FROM pets pe LEFT JOIN photo_pets pp ON pp.pet_id=pe.id GROUP BY pe.id ORDER BY photos DESC''')],
            'coverage':[dict(row) for row in c.execute('''SELECT 'cat' species,count(*) total,sum(EXISTS(SELECT 1 FROM photo_pets pp JOIN pets pe ON pe.id=pp.pet_id WHERE pp.photo_id=p.id AND pe.species='cat')) assigned FROM available_photos p WHERE p.visible=1 AND p.species LIKE '%cat%'
            UNION ALL SELECT 'hedgehog',count(*),sum(EXISTS(SELECT 1 FROM photo_pets pp JOIN pets pe ON pe.id=pp.pet_id WHERE pp.photo_id=p.id AND pe.species='hedgehog')) FROM available_photos p WHERE p.visible=1 AND p.species LIKE '%hedgehog%' ''')]}
    before=summary();started=time.monotonic();result=identity.regroup(c,'2026-11-05T12:00:00');c.commit();after=summary()
    second=identity.regroup(c,'2026-11-05T12:00:01');c.commit()
    report={'scope':'Unlabelled real-library coverage, not identity accuracy. No live data changed.','seconds':time.monotonic()-started,'result':result,'second_run':second,'before':before,'after':after}
    (root/'recall-tuning-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
