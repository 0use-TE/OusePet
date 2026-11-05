"""History cleanup must preserve active work, photo data and restart decisions."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
with tempfile.TemporaryDirectory(prefix='ousepet-history-') as temp:
    os.environ.update(OUSEPET_DATA=temp,OUSEPET_LIBRARY_ROOTS=temp,OUSEPET_DISCOVERY='0')
    from ousepet import api as m
    with TestClient(m.app) as client:
        sid=m.uid()
        with m.db() as c:c.execute('INSERT INTO storages(id,name,path,created_at,auto_scan) VALUES(?,?,?,?,0)',(sid,'History',temp,m.now()))
        def job(status):
            ident=m.uid()
            with m.db() as c:c.execute('INSERT INTO jobs(id,storage_id,status,created_at) VALUES(?,?,?,?)',(ident,sid,status,m.now()))
            return ident
        active=[job(status) for status in ('running','queued','paused')]
        for ident in active:assert client.delete('/api/jobs/'+ident).status_code==409
        history=[job(status) for status in ('complete','cancelled','interrupted','error')]
        for ident in history:assert client.delete('/api/jobs/'+ident).status_code==200
        assert client.delete('/api/jobs/'+history[0]).status_code==404
        for index in range(35):job('complete')
        assert client.delete('/api/jobs/history').json()['count']==35
        assert client.delete('/api/jobs/history').json()['count']==0
        assert {j['id'] for j in client.get('/api/state').json()['jobs']}==set(active)
        # A hidden latest completed job must still prevent recovery of an older interrupted one.
        older=job('interrupted');latest=job('complete')
        client.delete('/api/jobs/'+latest).raise_for_status()
        with patch.object(m,'queue_scan') as queue,patch.object(m.POOL,'submit'):
            m.recover_scans();queue.assert_not_called()
        m.init()
        with patch.object(m,'queue_scan') as queue,patch.object(m.POOL,'submit'):
            m.recover_scans();queue.assert_not_called()
        visible={j['id'] for j in client.get('/api/state').json()['jobs']}
        assert latest not in visible and older in visible
        with m.db() as c:assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
print('PASS: delete terminal history, clear beyond visible 15, protect active states, persistence and no resurrection on restart')
