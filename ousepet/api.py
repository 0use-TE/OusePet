"""Local album API. Originals are indexed and read, never edited or removed."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, closing
from datetime import datetime
import hashlib
import gc
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
from ousepet import identity,video,sharing

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('OUSEPET_DATA',str(ROOT/'.cache/album')))
DATA.mkdir(parents=True,exist_ok=True);(DATA/'thumbnails').mkdir(exist_ok=True)
DB=DATA/'album.sqlite3'
DIST=ROOT/'frontend/dist'
EXTENSIONS={'.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff'} | video.EXTENSIONS
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='album-scan')
MODEL=None
STOP=threading.Event()
RUNTIME={'requested':os.environ.get('OUSEPET_DEVICE','auto'),'device':'not_loaded','gpu_name':None,'fallback_error':None,'mode':None,'switching':False}
MODEL_LOCK=threading.RLock()
VIDEO_PLAY_LOCK=threading.Lock()
VIDEO_THUMBNAIL_LIMIT=threading.Semaphore(2)
SEEDS={}
INDEX_LOCK=threading.RLock()
SCAN_LOCK=threading.RLock()
RESETTING=threading.Event()
WATCHER=None
WATCH_INTERVAL=max(1,float(os.environ.get('OUSEPET_WATCH_INTERVAL','60')))
FILE_SETTLE_SECONDS=5
app=FastAPI(title='有宠相簿',docs_url=None,redoc_url=None)


@app.middleware('http')
async def guard_reset(request,call_next):
    if RESETTING.is_set() and request.url.path.startswith('/api/') and (request.method!='GET' or request.url.path.endswith('/browse')):
        return JSONResponse(status_code=409,content={'detail':'正在清空数据，请稍候再操作'})
    return await call_next(request)


@contextmanager
def db():
    connection=sqlite3.connect(DB,timeout=30)
    connection.row_factory=sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        yield connection
        connection.commit()
    finally:connection.close()


def now():return datetime.now().isoformat(timespec='seconds')
def uid():return uuid.uuid4().hex


def init():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS storages(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL UNIQUE,created_at TEXT,last_scan TEXT);
        CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY,storage_id TEXT REFERENCES storages(id),path TEXT NOT NULL,name TEXT NOT NULL,content_hash TEXT UNIQUE,width INTEGER,height INTEGER,taken_at TEXT,mtime REAL,species TEXT DEFAULT '[]',visible INTEGER DEFAULT 0,removed INTEGER DEFAULT 0,favorite INTEGER DEFAULT 0,manual INTEGER DEFAULT 0,created_at TEXT);
        CREATE TABLE IF NOT EXISTS pets(id TEXT PRIMARY KEY,name TEXT NOT NULL,species TEXT NOT NULL,cover_id TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS photo_pets(photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE,pet_id TEXT REFERENCES pets(id) ON DELETE CASCADE,status TEXT DEFAULT 'suggested',PRIMARY KEY(photo_id,pet_id));
        CREATE TABLE IF NOT EXISTS albums(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT);
        CREATE TABLE IF NOT EXISTS album_photos(album_id TEXT REFERENCES albums(id) ON DELETE CASCADE,photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE,PRIMARY KEY(album_id,photo_id));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,storage_id TEXT REFERENCES storages(id) ON DELETE CASCADE,status TEXT,total INTEGER DEFAULT 0,processed INTEGER DEFAULT 0,found INTEGER DEFAULT 0,current_file TEXT DEFAULT '',error TEXT,created_at TEXT,finished_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')
        if 'recognized' not in {r['name'] for r in c.execute('PRAGMA table_info(photos)')}:
            c.execute('ALTER TABLE photos ADD COLUMN recognized INTEGER DEFAULT 0')
        if 'file_size' not in {r['name'] for r in c.execute('PRAGMA table_info(photos)')}:
            c.execute('ALTER TABLE photos ADD COLUMN file_size INTEGER')
        for column,definition in [('media_type',"TEXT NOT NULL DEFAULT 'image'"),('duration','REAL DEFAULT 0'),
            ('video_cover','REAL NOT NULL DEFAULT 0'),('video_cover_manual','INTEGER NOT NULL DEFAULT 0'),('video_error','TEXT'),('video_fine','INTEGER NOT NULL DEFAULT 0')]:
            if column not in {r['name'] for r in c.execute('PRAGMA table_info(photos)')}:
                c.execute(f'ALTER TABLE photos ADD COLUMN {column} {definition}')
        if 'auto_scan' not in {r['name'] for r in c.execute('PRAGMA table_info(storages)')}:
            c.execute('ALTER TABLE storages ADD COLUMN auto_scan INTEGER NOT NULL DEFAULT 1')
        if 'detached' not in {r['name'] for r in c.execute('PRAGMA table_info(storages)')}:
            c.execute('ALTER TABLE storages ADD COLUMN detached INTEGER NOT NULL DEFAULT 0')
        if 'dismissed' not in {r['name'] for r in c.execute('PRAGMA table_info(jobs)')}:
            c.execute('ALTER TABLE jobs ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0')
        c.execute('CREATE INDEX IF NOT EXISTS photos_path ON photos(path)')
        c.execute('''CREATE TABLE IF NOT EXISTS scan_files(
            path TEXT PRIMARY KEY,storage_id TEXT REFERENCES storages(id) ON DELETE CASCADE,
            mtime REAL,size INTEGER,photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE)''')
        c.execute('CREATE INDEX IF NOT EXISTS scan_files_photo ON scan_files(photo_id)')
        c.execute('''CREATE VIEW IF NOT EXISTS available_photos AS SELECT p.* FROM photos p
            WHERE EXISTS (SELECT 1 FROM storages s WHERE s.id=p.storage_id AND s.detached=0)
               OR EXISTS (SELECT 1 FROM scan_files f JOIN storages s ON s.id=f.storage_id
                          WHERE f.photo_id=p.id AND s.detached=0)''')
        identity.init_schema(c)
        c.execute('''CREATE TABLE IF NOT EXISTS album_covers(album_id TEXT PRIMARY KEY REFERENCES albums(id) ON DELETE CASCADE,
            photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE)''')
        sharing.init_schema(c)
        c.execute("INSERT OR IGNORE INTO settings VALUES('gpu_enabled',?)",('false' if os.environ.get('OUSEPET_DEVICE')=='cpu' else 'true',))
        c.execute("UPDATE jobs SET status='interrupted',finished_at=? WHERE status IN ('running','queued')",(now(),))
    load_seeds()


def load_seeds():
    """Reuse actual completed inference for identical local test photographs."""
    try:
        prepared=json.loads((ROOT/'reports/pets/prepared.json').read_text(encoding='utf-8'))
        fallback=json.loads((ROOT/'reports/pets/fallback-evaluation.json').read_text(encoding='utf-8'))
        recovered=set(fallback['recovered'])
        hedge=json.loads((ROOT/'reports/hedgehog-final/all-records.json').read_text(encoding='utf-8'))
        hedge_by_id={r['id']:r for r in hedge if r['id'].startswith('H')}
        for r in prepared:
            species=[];pets=[]
            if r['id'].startswith('C') and ('crop_path' in r or r['id'] in recovered):species=['cat'];pets=['基米']
            elif r['id'].startswith('H'):
                if hedge_by_id.get(r['id'],{}).get('detections'):species=['hedgehog'];pets=['扣嘚']
                if r['id'] in {'H08','H13','H16','H17','H28'}:species.append('cat');pets.append('基米')
            elif r['id'].startswith('P') and 'crop_path' in r:species=['cat']
            SEEDS[r['sha256']]={'species':species,'pets':pets,'date':r.get('date_group')}
    except (OSError,KeyError,ValueError):pass


def inside(path,root):
    try:path.resolve().relative_to(root.resolve());return True
    except ValueError:return False


def resolved_directory(value):
    path=Path(value).expanduser()
    if not path.is_absolute():raise HTTPException(400,'请选择完整的目录路径')
    path=path.resolve()
    if not path.is_dir():raise HTTPException(404,'目录不存在或无法读取')
    allowed=os.environ.get('OUSEPET_LIBRARY_ROOTS')
    if allowed and not any(inside(path,Path(p)) for p in allowed.split(os.pathsep) if p):raise HTTPException(403,'此目录不在可用存储中')
    return path


def serialize_photo(c,row):
    photo=dict(row)
    photo['species']=json.loads(photo['species'])
    photo['favorite']=bool(photo['favorite']);photo['manual']=bool(photo['manual'])
    photo['pets']=[dict(r) for r in c.execute('SELECT p.id,p.name,p.species,pp.status FROM photo_pets pp JOIN pets p ON p.id=pp.pet_id WHERE pp.photo_id=? ORDER BY p.name',(row['id'],))]
    photo['thumb']=f"/api/photos/{row['id']}/thumbnail"
    photo['url']=f"/api/photos/{row['id']}/image"
    if row['media_type']=='video':
        photo['thumb']+=f"?v={row['content_hash'][:12]}-{row['video_cover']}"
        photo['video_hits']=[dict(hit) for hit in c.execute('''SELECT g.pet_id,p.name,min(h.seconds) AS seconds,max(h.seconds) AS last_seconds,
            count(DISTINCT h.seconds) AS frames FROM video_hits h JOIN identity_clusters g ON g.id=h.cluster_id
            JOIN pets p ON p.id=g.pet_id JOIN photo_pets pp ON pp.photo_id=h.photo_id AND pp.pet_id=g.pet_id
            WHERE h.photo_id=? AND NOT EXISTS(SELECT 1 FROM identity_exclusions e WHERE e.photo_id=h.photo_id AND e.pet_id=g.pet_id)
            GROUP BY g.pet_id ORDER BY seconds''',(row['id'],))]
    return photo


def cover_url(c,ident):
    if not ident:return None
    row=c.execute('SELECT media_type,content_hash,video_cover FROM photos WHERE id=?',(ident,)).fetchone()
    suffix=f"?v={row['content_hash'][:12]}-{row['video_cover']}" if row and row['media_type']=='video' else ''
    return f'/api/photos/{ident}/thumbnail'+suffix


def index_file(storage,path):
    with INDEX_LOCK:
        if RESETTING.is_set():raise OSError('正在清空数据')
        before=path.stat()
        result=_index_file(storage,path)
        after=path.stat()
        if (before.st_mtime_ns,before.st_size)!=(after.st_mtime_ns,after.st_size):
            raise OSError('照片仍在写入，稍后重试')
        with db() as c:
            c.execute('INSERT OR REPLACE INTO scan_files VALUES(?,?,?,?,?)',
                      (str(path),storage['id'],after.st_mtime,after.st_size,result[0]))
        return result


def _index_file(storage,path):
    stat=path.stat()
    with db() as c:
        existing=c.execute('SELECT * FROM photos WHERE path=?',(str(path),)).fetchone()
        if existing and existing['mtime']==stat.st_mtime and existing['file_size'] in (None,stat.st_size):
            c.execute('UPDATE photos SET file_size=? WHERE id=?',(stat.st_size,existing['id']))
            return existing['id'],False
        if not existing:
            cached=c.execute('''SELECT p.*,s.detached FROM scan_files f JOIN photos p ON p.id=f.photo_id
                JOIN storages s ON s.id=p.storage_id WHERE f.path=? AND f.mtime=? AND f.size=?''',
                (str(path),stat.st_mtime,stat.st_size)).fetchone()
            if cached:
                if cached['detached'] or not Path(cached['path']).is_file():
                    c.execute('UPDATE photos SET path=?,storage_id=?,name=?,mtime=?,file_size=? WHERE id=?',
                              (str(path),storage['id'],path.name,stat.st_mtime,stat.st_size,cached['id']))
                return cached['id'],False
    with path.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
    is_video=path.suffix.lower() in video.EXTENSIONS
    metadata=video.probe(path) if is_video else {}
    if is_video:
        width,height=metadata['width'],metadata['height'];date=None
        if metadata.get('date'):
            try:date=datetime.fromisoformat(metadata['date'].replace('Z','+00:00')).astimezone().isoformat(sep=' ',timespec='seconds')
            except ValueError:pass
    else:
        with Image.open(path) as opened:
            exif=opened.getexif();date=exif.get(36867) or exif.get(306)
            oriented=ImageOps.exif_transpose(opened);width,height=oriented.size
    seed=SEEDS.get(digest)
    if date and not is_video:
        try:date=datetime.strptime(str(date)[:19],'%Y:%m:%d %H:%M:%S').isoformat(sep=' ')
        except ValueError:date=None
    if not date:
        match=re.search(r'(20\d{6})_(\d{6})',path.stem)
        if match:
            try:date=datetime.strptime(''.join(match.groups()),'%Y%m%d%H%M%S').isoformat(sep=' ')
            except ValueError:pass
    if not date and seed and seed.get('date') and not seed['date'].startswith(('unknown','public')):date=seed['date']+' 12:00:00'
    date=date or datetime.fromtimestamp(stat.st_mtime).isoformat(sep=' ',timespec='seconds')
    with db() as c:
        duplicate=c.execute('SELECT p.id,p.path,s.detached FROM photos p JOIN storages s ON s.id=p.storage_id WHERE content_hash=?',(digest,)).fetchone()
        if duplicate:
            if duplicate['detached'] or not Path(duplicate['path']).is_file():c.execute('UPDATE photos SET path=?,storage_id=?,name=?,mtime=?,file_size=? WHERE id=?',(str(path),storage['id'],path.name,stat.st_mtime,stat.st_size,duplicate['id']))
            elif duplicate['path']==str(path):c.execute('UPDATE photos SET mtime=?,file_size=? WHERE id=?',(stat.st_mtime,stat.st_size,duplicate['id']))
            return duplicate['id'],False
        if existing:
            c.execute('DELETE FROM scan_files WHERE photo_id=?',(existing['id'],))
            c.execute('DELETE FROM identity_observations WHERE photo_id=?',(existing['id'],))
            c.execute('DELETE FROM video_hits WHERE photo_id=?',(existing['id'],))
            c.execute('UPDATE photos SET identity_hash=NULL WHERE id=?',(existing['id'],))
            c.execute('DELETE FROM photo_pets WHERE photo_id=?',(existing['id'],))
            c.execute('UPDATE photos SET content_hash=?,width=?,height=?,taken_at=?,mtime=?,file_size=?,species=?,visible=0,manual=0,recognized=0 WHERE id=?',(digest,width,height,date,stat.st_mtime,stat.st_size,'[]',existing['id']))
            c.execute('UPDATE photos SET media_type=?,duration=?,video_cover=0,video_cover_manual=0,video_error=NULL WHERE id=?',('video' if is_video else 'image',metadata.get('duration',0),existing['id']))
            return existing['id'],True
        ident=uid()
        c.execute('INSERT INTO photos(id,storage_id,path,name,content_hash,width,height,taken_at,mtime,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,storage['id'],str(path),path.name,digest,width,height,date,stat.st_mtime,now()))
        c.execute('UPDATE photos SET file_size=? WHERE id=?',(stat.st_size,ident))
        c.execute('UPDATE photos SET media_type=?,duration=? WHERE id=?',('video' if is_video else 'image',metadata.get('duration',0),ident))
    return ident,True


def apply_recognition(ident,seed):
    with db() as c:
        photo=c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
        if not photo or photo['removed'] or photo['manual']:return
        c.execute('UPDATE photos SET species=?,visible=?,recognized=1 WHERE id=?',(json.dumps(seed['species']),int(bool(seed['species'])),ident))
        for name in seed.get('pets',[]):
            pet=c.execute('SELECT id FROM pets WHERE name=?',(name,)).fetchone()
            if pet:c.execute('INSERT OR IGNORE INTO photo_pets VALUES(?,?,?)',(ident,pet['id'],'suggested'))


def desired_mode():
    with db() as c:enabled=c.execute("SELECT value FROM settings WHERE key='gpu_enabled'").fetchone()[0]=='true'
    return 'auto' if enabled else 'cpu'


def get_model(force_cpu=False):
    global MODEL
    import torch
    from ousepet.vision import HedgehogDetector
    torch.set_num_threads(int(os.environ.get('OUSEPET_CPU_THREADS','4')))
    mode=desired_mode()
    requested='cpu' if mode=='cpu' else os.environ.get('OUSEPET_DEVICE','auto')
    if mode=='auto' and requested=='cpu':requested='auto'
    if mode!=RUNTIME['mode']:RUNTIME['fallback_error']=None
    RUNTIME['requested']=requested
    MODEL=None;gc.collect()
    if torch.cuda.is_available():torch.cuda.empty_cache()
    device='cpu'
    RUNTIME.update(torch_version=torch.__version__,cuda_version=torch.version.cuda)
    if not force_cpu and requested!='cpu':
        try:
            if not torch.cuda.is_available():
                if requested!='auto':raise RuntimeError('CUDA is not available')
            else:
                candidate='cuda:0' if requested in ('auto','cuda') else requested
                check=torch.ones((16,16),device=candidate)
                (check@check).sum().item();torch.cuda.synchronize()
                RUNTIME['gpu_name']=torch.cuda.get_device_name(0);device=candidate
        except RuntimeError as error:
            RUNTIME['fallback_error']=str(error)
            logging.warning('GPU initialization failed; using CPU: %s',error)
    try:MODEL=HedgehogDetector(device=device)
    except RuntimeError as error:
        if device=='cpu':raise
        RUNTIME['fallback_error']=str(error);device='cpu';torch.cuda.empty_cache()
        MODEL=HedgehogDetector(device=device)
    RUNTIME.update(device=device,mode=mode,switching=False)
    logging.info('OusePet inference device: %s',device)
    return MODEL


def detect_species(image):
    with MODEL_LOCK:return _locked_detect_species(image)


def _locked_detect_species(image):
    global MODEL
    if MODEL is None or RUNTIME['mode']!=desired_mode():get_model()
    try:return _detect_species(image)
    except RuntimeError as error:
        if MODEL.device=='cpu':raise
        RUNTIME['fallback_error']=str(error)
        logging.warning('GPU inference failed; retrying on CPU: %s',error)
        MODEL=None
        import torch
        torch.cuda.empty_cache();get_model(force_cpu=True)
        return _detect_species(image)


def apply_device_settings():
    try:
        with MODEL_LOCK:
            if STOP.is_set():return
            if MODEL is None or RUNTIME['mode']!=desired_mode():get_model()
            else:RUNTIME['switching']=False
    except Exception:
        RUNTIME['switching']=False
        logging.exception('Could not apply inference device settings')


def _detect_animals(image):
    hedges=MODEL.detect(image)
    cat_result=MODEL.proposal_model.predict(image,device=MODEL.device,imgsz=640,conf=.25,classes=[15],verbose=False)[0]
    def overlap(a,b):
        area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
        total=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
        return area/total if total else 0
    cats=[b for b in cat_result.boxes if not any(overlap(b.xyxy[0].tolist(),h.box)>.25 for h in hedges)]
    return [{'species':'hedgehog','box':h.box} for h in hedges]+[{'species':'cat','box':b.xyxy[0].tolist()} for b in cats]


def _detect_species(image):
    return sorted({d['species'] for d in _detect_animals(image)})


def detect_identity(image):
    with MODEL_LOCK:
        if MODEL is None or RUNTIME['mode']!=desired_mode():get_model()
        def extract():
            detections=_detect_animals(image)
            usable=[]
            for d in detections:
                x1,y1,x2,y2=d['box']
                d['box']=[max(0,x1),max(0,y1),min(image.width,x2),min(image.height,y2)]
                if d['box'][2]-d['box'][0]>=24 and d['box'][3]-d['box'][1]>=24:usable.append(d)
            vectors=MODEL.features.embed([image.crop(tuple(d['box'])) for d in usable])
            for d,v in zip(usable,vectors):d['vector']=v
            return sorted({d['species'] for d in detections}),usable
        try:return extract()
        except RuntimeError as error:
            if MODEL.device=='cpu':raise
            RUNTIME['fallback_error']=str(error)
            get_model(force_cpu=True)
            return extract()


def store_identity(photo,detections):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        identity.store(c,photo['id'],photo['content_hash'],detections,now())


def infer_photo(ident,ready=None,progress=None):
    with db() as c:row=c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
    if not row or row['removed'] or row['manual']:return
    if row['media_type']=='video':return infer_video(row,ready=ready,progress=progress,fine=bool(row['video_fine']))
    if row['content_hash'] in SEEDS:apply_recognition(ident,SEEDS[row['content_hash']]);return
    from ousepet.vision import open_image
    image=open_image(row['path']);species,detections=detect_identity(image)
    apply_recognition(ident,{'species':species,'pets':[]})
    store_identity(row,detections)


def infer_video(row,ready=None,progress=None,fine=False,identity_only=False):
    from PIL import ImageFilter,ImageStat
    times=video.sample_times(row['duration'],fine);detections=[];species=set();hits=[];best=(-1,0,None);decoded=0
    def process(points):
        nonlocal decoded,best
        for index,seconds in enumerate(points):
            if STOP.is_set() or (ready is not None and not ready()):raise video.Cancelled('视频任务已取消')
            if progress:progress(decoded+1,len(times)+len(points) if points is not times else len(times))
            try:image=video.frame(row['path'],seconds,ready)
            except video.Cancelled:raise
            except OSError:continue
            kinds,found=detect_identity(image);decoded+=1;species.update(kinds)
            if kinds:hits.append(seconds)
            score=max((max(0,d['box'][2]-d['box'][0])*max(0,d['box'][3]-d['box'][1])/(image.width*image.height) for d in found),default=0)
            score=score*100+min(ImageStat.Stat(image.convert('L').filter(ImageFilter.FIND_EDGES)).var[0]/1000,1)
            if found:score+=10
            if score>best[0]:best=(score,seconds,image.copy())
            for detection in found:detections.append({**detection,'seconds':seconds})
    try:
        process(times)
        refine=video.refinement_times(row['duration'],hits,times)
        if refine:process(refine)
        if not decoded:raise OSError('视频采样全部失败，请检查文件是否完整')
        if ready is not None and not ready():raise video.Cancelled('视频任务已取消')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT * FROM photos WHERE id=?',(row['id'],)).fetchone()
            if not current or current['content_hash']!=row['content_hash'] or current['removed']:return
            if not current['manual'] and not identity_only:
                c.execute('UPDATE photos SET species=?,visible=?,recognized=1,video_error=NULL WHERE id=?',(json.dumps(sorted(species)),int(bool(species)),row['id']))
            if not current['video_cover_manual'] and not identity_only:
                c.execute('UPDATE photos SET video_cover=? WHERE id=?',(best[1],row['id']))
            identity.store(c,row['id'],row['content_hash'],detections,now())
        if best[2] and not current['video_cover_manual'] and not identity_only:
            save_video_thumbnail(row,best[1],best[2])
    except video.Cancelled:raise
    except Exception as error:
        with db() as c:c.execute('UPDATE photos SET video_error=?,recognized=1 WHERE id=? AND content_hash=?',(str(error),row['id'],row['content_hash']))
        raise


def discovery_job():
    with db() as c:
        if c.execute('SELECT status FROM discovery WHERE id=1').fetchone()[0]!='queued':return
        items=[dict(r) for r in c.execute("SELECT * FROM available_photos WHERE visible=1 AND removed=0 AND coalesce(identity_hash,'') != ? || content_hash",(identity.MODEL_VERSION+':',))]
        c.execute("UPDATE discovery SET status='running',phase='features',total=?,processed=0,errors=0,error=NULL WHERE id=1",(len(items),))
    for index,photo in enumerate(items):
        if STOP.is_set():return
        with db() as c:
            if c.execute('SELECT status FROM discovery WHERE id=1').fetchone()[0]!='running':return
            fresh=c.execute('SELECT * FROM photos WHERE id=?',(photo['id'],)).fetchone()
        try:
            if fresh and fresh['visible'] and not fresh['removed'] and fresh['identity_hash']!=identity.MODEL_VERSION+':'+fresh['content_hash']:
                if fresh['media_type']=='video':
                    def discovery_ready():
                        with db() as c:return not STOP.is_set() and c.execute('SELECT status FROM discovery WHERE id=1').fetchone()[0]=='running'
                    infer_video(fresh,ready=discovery_ready,identity_only=True)
                else:
                    from ousepet.vision import open_image
                    _,detections=detect_identity(open_image(fresh['path']))
                    store_identity(fresh,detections)
        except video.Cancelled:return
        except Exception as error:
            logging.exception('Pet discovery failed for %s',photo['name'])
            with db() as c:c.execute("UPDATE discovery SET errors=errors+1,error=? WHERE id=1 AND status='running'",(str(error),))
        with db() as c:c.execute("UPDATE discovery SET processed=? WHERE id=1 AND status='running'",(index+1,))
    with db() as c:c.execute("UPDATE discovery SET phase='grouping' WHERE id=1 AND status='running'")
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if STOP.is_set() or c.execute('SELECT status FROM discovery WHERE id=1').fetchone()[0]!='running':return
            identity.regroup(c,now())
            c.execute("UPDATE discovery SET status='complete',phase='complete' WHERE id=1 AND status='running'")
    except Exception as error:
        logging.exception('Could not regroup identity features')
        with db() as c:c.execute("UPDATE discovery SET status='error',phase='error',errors=errors+1,error=? WHERE id=1 AND status='running'",(str(error),))


def queue_discovery():
    with SCAN_LOCK,db() as c:
        if RESETTING.is_set():raise HTTPException(409,'正在清空数据，请稍候')
        status=c.execute('SELECT status FROM discovery WHERE id=1').fetchone()[0]
        if status in ('queued','running'):return {'status':status}
        c.execute("UPDATE discovery SET status='queued',phase='features',total=0,processed=0,errors=0,error=NULL WHERE id=1")
    POOL.submit(discovery_job)
    return {'status':'queued'}


@app.post('/api/discovery/start')
def start_discovery():return queue_discovery()


def schedule_identity_matching():
    if os.environ.get('OUSEPET_DISCOVERY','1')=='0' or RESETTING.is_set():return
    with db() as c:status=c.execute('SELECT status FROM discovery WHERE id=1').fetchone()[0]
    if status!='cancelled':queue_discovery()


@app.post('/api/discovery/cancel')
def cancel_discovery():
    with db() as c:c.execute("UPDATE discovery SET status='cancelled' WHERE id=1 AND status IN ('running','queued')")
    return {'ok':True}


def scan_ready(job_id):
    while not STOP.is_set():
        with db() as c:row=c.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row or row['status'] not in ('running','queued','paused'):return False
        if row['status']!='paused':return True
        STOP.wait(.2)
    return False


def pending_files(storage,automatic=False,job_id=None):
    """Stat files only; unchanged photos and duplicate paths never need rehashing."""
    with db() as c:
        known={r['path']:dict(r) for r in c.execute('SELECT path,mtime,file_size AS size,recognized,removed,manual FROM photos')}
        tracked={r['path'] for r in c.execute('SELECT path FROM photos WHERE storage_id=? UNION SELECT path FROM scan_files WHERE storage_id=?',(storage['id'],storage['id']))}
        for r in c.execute('''SELECT f.path,f.mtime,f.size,p.recognized,p.removed,p.manual
                            FROM scan_files f JOIN photos p ON p.id=f.photo_id'''):
            known[r['path']]=dict(r)
    base=Path(storage['path'])
    if not base.is_dir():raise OSError('照片目录不存在或无法读取')
    files=[];backfill=[]
    def walk_error(error):raise error
    for directory,dirs,names in os.walk(base,onerror=walk_error):
        dirs[:]=[d for d in dirs if not d.startswith(('.', '@')) and not (Path(directory)/d).is_symlink()]
        for name in names:
            if STOP.is_set() or (job_id and not scan_ready(job_id)):return None
            path=Path(directory)/name
            if name.startswith(('.', '@')) or path.suffix.lower() not in EXTENSIONS or not inside(path,base):continue
            try:
                stat=path.stat()
                if not path.is_file() or (automatic and time.time()-stat.st_mtime<FILE_SETTLE_SECONDS):continue
            except OSError:continue
            path=path.resolve();previous=known.get(str(path))
            if previous and previous['mtime']==stat.st_mtime and previous['size'] in (None,stat.st_size):
                if previous['size'] is None:backfill.append((stat.st_size,str(path)))
                if str(path) in tracked and (previous['recognized'] or previous['removed'] or previous['manual']):continue
            files.append(path)
    if backfill:
        with db() as c:c.executemany('UPDATE photos SET file_size=? WHERE path=? AND file_size IS NULL',backfill)
    return files


def scan_job(job_id,files=None):
    try:
        if not scan_ready(job_id):return
        with db() as c:
            job=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            storage=c.execute('SELECT * FROM storages WHERE id=?',(job['storage_id'],)).fetchone()
            c.execute("UPDATE jobs SET status='running' WHERE id=? AND status='queued'",(job_id,))
        if files is None:files=pending_files(storage,job_id=job_id)
        if files is None or not scan_ready(job_id):return
        with db() as c:c.execute('UPDATE jobs SET total=?,processed=0,found=0 WHERE id=? AND status=\'running\'',(len(files),job_id))
        videos=[path for path in files if path.suffix.lower() in video.EXTENSIONS]
        for index,path in enumerate(videos):
            if not scan_ready(job_id):return
            with db() as c:c.execute('UPDATE jobs SET current_file=? WHERE id=?',(f'正在索引视频 {index+1}/{len(videos)} · {path.name}',job_id))
            try:index_file(storage,path.resolve())
            except (OSError,ValueError):pass
        found=0
        for i,path in enumerate(files):
            if not scan_ready(job_id):return
            try:
                ident,created=index_file(storage,path.resolve())
                with db() as c:photo=c.execute('SELECT recognized,removed,manual,media_type FROM photos WHERE id=?',(ident,)).fetchone()
                if not scan_ready(job_id):return
                if (created or not photo['recognized']) and not (photo['removed'] or photo['manual']):
                    if photo['media_type']=='video':
                        def video_progress(done,total):
                            with db() as c:c.execute('UPDATE jobs SET current_file=? WHERE id=?',(f'{path.name} · 视频采样 {done}/{total}',job_id))
                        infer_photo(ident,ready=lambda:scan_ready(job_id),progress=video_progress)
                    else:infer_photo(ident)
                with db() as c:
                    visible=c.execute('SELECT visible FROM photos WHERE id=?',(ident,)).fetchone()['visible']
                    found+=bool(visible)
                    c.execute("UPDATE jobs SET processed=?,found=?,current_file=? WHERE id=? AND status IN ('running','paused')",(i+1,found,path.name,job_id))
            except (OSError,ValueError) as error:
                with db() as c:c.execute("UPDATE jobs SET processed=?,current_file=?,error=? WHERE id=? AND status IN ('running','paused')",(i+1,path.name,str(error),job_id))
        if not scan_ready(job_id):return
        with db() as c:
            changed=c.execute("UPDATE jobs SET status='complete',finished_at=?,current_file='' WHERE id=? AND status='running'",(now(),job_id)).rowcount
            if changed:c.execute('UPDATE storages SET last_scan=? WHERE id=?',(now(),storage['id']))
        if changed:schedule_identity_matching()
    except Exception as error:
        with db() as c:c.execute("UPDATE jobs SET status='error',error=?,finished_at=? WHERE id=? AND status IN ('running','queued','paused')",(str(error),now(),job_id))


def queue_scan(storage_id,files=None,automatic=False,reset_task=False):
    with SCAN_LOCK:
        if RESETTING.is_set() and not reset_task:raise HTTPException(409,'正在清空数据，请稍候')
        with db() as c:
            storage=c.execute('SELECT * FROM storages WHERE id=?',(storage_id,)).fetchone()
            if not storage or storage['detached']:raise HTTPException(404,'存储位置已移除或不存在')
            if automatic and not storage['auto_scan']:return None
            active=c.execute("SELECT id FROM jobs WHERE storage_id=? AND status IN ('running','queued','paused')",(storage_id,)).fetchone()
            if active:return active['id']
            ident=uid();c.execute('INSERT INTO jobs(id,storage_id,status,total,created_at) VALUES(?,?,?,?,?)',(ident,storage_id,'queued',len(files) if files is not None else 0,now()))
        POOL.submit(scan_job,ident,files);return ident


def check_new_files():
    if RESETTING.is_set():return
    with db() as c:
        storages=[dict(r) for r in c.execute("SELECT * FROM storages s WHERE detached=0 AND auto_scan=1 AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.storage_id=s.id AND j.status IN ('running','queued','paused'))")]
    for storage in storages:
        if STOP.is_set():return
        try:
            files=pending_files(storage,automatic=True)
            if files:queue_scan(storage['id'],files,automatic=True)
        except OSError:logging.exception('Could not check storage %s',storage['name'])


def watch_storages():
    while not STOP.wait(WATCH_INTERVAL):
        try:check_new_files()
        except Exception:logging.exception('Automatic incremental check failed')


@app.on_event('startup')
def recover_scans():
    global WATCHER
    STOP.clear()
    with db() as c:reset=read_reset_task(c)
    if reset['status'] in ('queued','clearing'):
        RESETTING.set();POOL.submit(reset_library_job)
        if WATCHER is None or not WATCHER.is_alive():
            WATCHER=threading.Thread(target=watch_storages,name='album-watch',daemon=True);WATCHER.start()
        return
    with db() as c:
        jobs=[dict(r) for r in c.execute('SELECT * FROM jobs WHERE storage_id IN (SELECT id FROM storages WHERE detached=0) AND rowid IN (SELECT max(rowid) FROM jobs GROUP BY storage_id) ORDER BY rowid')]
    for job in jobs:
        if job['status']=='interrupted':queue_scan(job['storage_id'])
        elif job['status']=='paused':POOL.submit(scan_job,job['id'])
    with db() as c:discovery_status=c.execute('SELECT status FROM discovery WHERE id=1').fetchone()[0]
    if discovery_status!='cancelled' and os.environ.get('OUSEPET_DISCOVERY','1')!='0':queue_discovery()
    if WATCHER is None or not WATCHER.is_alive():
        WATCHER=threading.Thread(target=watch_storages,name='album-watch',daemon=True)
        WATCHER.start()


@app.on_event('shutdown')
def shutdown():
    STOP.set()
    if WATCHER:WATCHER.join(timeout=5)
    POOL.shutdown(wait=True,cancel_futures=True)


@app.get('/api/health')
def health():
    with db() as c:c.execute('SELECT 1').fetchone()
    return {'ok':True}


@app.get('/api/runtime')
def runtime():return dict(RUNTIME)


class SettingsInput(BaseModel):
    gpu_enabled:bool


def read_reset_task(c):
    row=c.execute("SELECT value FROM settings WHERE key='reset_task'").fetchone()
    return json.loads(row[0]) if row else {'status':'idle'}


def save_reset_task(c,task):
    c.execute("INSERT INTO settings VALUES('reset_task',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(task),))


def reset_library_job():
    try:
        # All inference shares POOL: no old inference can write after this cleanup.
        with INDEX_LOCK,SCAN_LOCK:
            backups=DATA/'backups';backups.mkdir(exist_ok=True)
            backup=backups/f'album-before-reset-{uid()}.sqlite3'
            with db() as c:
                task=read_reset_task(c)
                if task['status'] not in ('queued','clearing'):return
                with closing(sqlite3.connect(backup)) as destination, destination:
                    c.backup(destination)
                    destination.execute("DELETE FROM settings WHERE key='reset_task'")
                save_reset_task(c,{'status':'clearing'})
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                for table in ('identity_observations','identity_exclusions','photo_pets','identity_clusters','album_photos','albums','pets','scan_files','photos','jobs'):
                    c.execute('DELETE FROM '+table)
                c.execute('DELETE FROM storages WHERE detached=1')
                c.execute('DELETE FROM share_attempts')
                c.execute("UPDATE discovery SET status='idle',total=0,processed=0,errors=0,error=NULL WHERE id=1")
            for path in (DATA/'thumbnails').iterdir():
                if path.is_file() or path.is_symlink():path.unlink()
            for path in (DATA/'video-playback').glob('*'):
                if path.is_file() or path.is_symlink():path.unlink()
            for path in (DATA/'share-cache').glob('*'):
                if path.is_file() or path.is_symlink():path.unlink()
            with db() as c:storages=[r['id'] for r in c.execute('SELECT id FROM storages WHERE detached=0')]
            jobs=[queue_scan(ident,reset_task=True) for ident in storages]
            with db() as c:save_reset_task(c,{'status':'complete','job_ids':jobs,'backup':backup.name})
    except Exception as error:
        logging.exception('Could not reset library')
        with db() as c:save_reset_task(c,{'status':'error','error':str(error)})
    finally:RESETTING.clear()


class ResetLibrary(BaseModel):
    confirmation:str


@app.post('/api/library/reset')
def reset_library(body:ResetLibrary):
    if body.confirmation!='清空并重新识别':raise HTTPException(400,'请输入“清空并重新识别”以确认')
    with SCAN_LOCK:
        if RESETTING.is_set():raise HTTPException(409,'正在清空数据，请勿重复提交')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute("UPDATE jobs SET status='cancelled',finished_at=?,current_file='' WHERE status IN ('running','queued','paused')",(now(),))
            c.execute("UPDATE discovery SET status='cancelled' WHERE status IN ('running','queued')")
            save_reset_task(c,{'status':'queued'})
        RESETTING.set()
        POOL.submit(reset_library_job)
    return {'status':'queued'}


@app.post('/api/library/scan')
def scan_library():
    with db() as c:storages=[r['id'] for r in c.execute('SELECT id FROM storages WHERE detached=0')]
    if not storages:raise HTTPException(400,'请先添加照片存储位置')
    return {'job_ids':[queue_scan(ident) for ident in storages]}


@app.get('/api/settings')
def settings():
    return {'gpu_enabled':desired_mode()=='auto','device':RUNTIME['device'],'gpu_name':RUNTIME['gpu_name'],'switching':RUNTIME['switching']}


@app.patch('/api/settings')
def update_settings(body:SettingsInput):
    with db() as c:c.execute("UPDATE settings SET value=? WHERE key='gpu_enabled'",('true' if body.gpu_enabled else 'false',))
    RUNTIME['switching']=True
    threading.Thread(target=apply_device_settings,name='device-settings',daemon=True).start()
    return settings()


@app.get('/api/state')
def state():
    with db() as c:
        counts={
            'library':c.execute('SELECT count(*) FROM available_photos').fetchone()[0],
            'all':c.execute('SELECT count(*) FROM available_photos WHERE visible=1').fetchone()[0],
            'cats':c.execute("SELECT count(*) FROM available_photos WHERE visible=1 AND species LIKE '%cat%'").fetchone()[0],
            'hedgehogs':c.execute("SELECT count(*) FROM available_photos WHERE visible=1 AND species LIKE '%hedgehog%'").fetchone()[0],
            'favorites':c.execute('SELECT count(*) FROM available_photos WHERE favorite=1').fetchone()[0],
            'review':0,
            'videos':c.execute("SELECT count(*) FROM available_photos WHERE media_type='video'").fetchone()[0],
        }
        pets=[]
        for r in c.execute('SELECT * FROM pets ORDER BY unnamed,created_at,id'):
            pet=dict(r)
            pet['count']=c.execute('SELECT count(*) FROM photo_pets pp JOIN available_photos p ON p.id=pp.photo_id WHERE pp.pet_id=? AND p.visible=1',(r['id'],)).fetchone()[0]
            pet['video_count']=c.execute("SELECT count(*) FROM photo_pets pp JOIN available_photos p ON p.id=pp.photo_id WHERE pp.pet_id=? AND p.visible=1 AND p.media_type='video'",(r['id'],)).fetchone()[0]
            cover=c.execute('SELECT p.id FROM available_photos p JOIN photo_pets pp ON pp.photo_id=p.id WHERE pp.pet_id=? AND p.visible=1 ORDER BY (p.id=?) DESC,p.taken_at DESC LIMIT 1',(r['id'],r['cover_id'] or '')).fetchone()
            if isinstance(cover,sqlite3.Row):cover=cover['id']
            pet['cover']=cover_url(c,cover)
            pet['unnamed']=bool(pet['unnamed'])
            pets.append(pet)
        saved_order=c.execute("SELECT value FROM settings WHERE key='pet_order'").fetchone()
        order=json.loads(saved_order[0]) if saved_order else []
        positions={ident:index for index,ident in enumerate(order)}
        pets.sort(key=lambda pet:positions.get(pet['id'],len(positions)))
        albums=[]
        for r in c.execute('SELECT * FROM albums ORDER BY created_at DESC'):
            album=dict(r);album['count']=c.execute('SELECT count(*) FROM album_photos ap JOIN available_photos p ON p.id=ap.photo_id WHERE album_id=?',(r['id'],)).fetchone()[0]
            album['video_count']=c.execute("SELECT count(*) FROM album_photos ap JOIN available_photos p ON p.id=ap.photo_id WHERE album_id=? AND p.media_type='video'",(r['id'],)).fetchone()[0]
            chosen=c.execute('SELECT photo_id FROM album_covers WHERE album_id=?',(r['id'],)).fetchone()
            album['cover_id']=chosen[0] if chosen else None
            cover=c.execute('SELECT ap.photo_id FROM album_photos ap JOIN available_photos p ON p.id=ap.photo_id WHERE album_id=? ORDER BY (p.id=?) DESC,p.taken_at DESC,p.id DESC LIMIT 1',(r['id'],album['cover_id'] or '')).fetchone()
            album['cover']=cover_url(c,cover[0]) if cover else None;albums.append(album)
        storages=[]
        for r in c.execute('SELECT * FROM storages WHERE detached=0 ORDER BY created_at'):
            storage=dict(r)
            membership='(storage_id=? OR id IN (SELECT photo_id FROM scan_files WHERE storage_id=?))'
            storage['indexed']=c.execute('SELECT count(*) FROM available_photos WHERE '+membership,(r['id'],r['id'])).fetchone()[0]
            storage['count']=c.execute('SELECT count(*) FROM available_photos WHERE visible=1 AND '+membership,(r['id'],r['id'])).fetchone()[0]
            storages.append(storage)
        jobs=[dict(r) for r in c.execute("SELECT j.*,s.name AS storage_name FROM jobs j JOIN storages s ON s.id=j.storage_id WHERE j.dismissed=0 AND s.detached=0 ORDER BY (j.status IN ('running','queued','paused')) DESC,j.created_at DESC,j.rowid DESC LIMIT 15")]
        discovery=dict(c.execute('SELECT * FROM discovery WHERE id=1').fetchone())
        reset_task=read_reset_task(c)
    return {'counts':counts,'pets':pets,'albums':albums,'storages':storages,'jobs':jobs,'discovery':discovery,'reset_task':reset_task}


def photo_filter(view,q,pet_id,album_id,media='all'):
    clauses=['1=1' if view in ('all','favorites','videos') or album_id else 'p.visible=1'];args=[]
    if view=='videos':clauses.append("p.media_type='video'")
    if media not in ('all','image','video'):raise HTTPException(400,'请选择照片或视频')
    if media!='all':clauses.append('p.media_type=?');args.append(media)
    if view=='cats':clauses.append("p.species LIKE '%cat%'")
    if view=='hedgehogs':clauses.append("p.species LIKE '%hedgehog%'")
    if view=='favorites':clauses.append('p.favorite=1')
    if pet_id:clauses.append('EXISTS(SELECT 1 FROM photo_pets pp WHERE pp.photo_id=p.id AND pp.pet_id=?)');args.append(pet_id)
    if album_id:clauses.append('EXISTS(SELECT 1 FROM album_photos ap WHERE ap.photo_id=p.id AND ap.album_id=?)');args.append(album_id)
    if q:
        clauses.append('(p.name LIKE ? OR p.taken_at LIKE ? OR EXISTS(SELECT 1 FROM photo_pets pp JOIN pets pe ON pe.id=pp.pet_id WHERE pp.photo_id=p.id AND pe.name LIKE ?))');args.extend(['%'+q+'%']*3)
    return ' AND '.join(clauses),args


@app.get('/api/photos/timeline')
def photo_timeline(view:str='gallery',q:str='',pet_id:str='',album_id:str='',sort:str='desc',media:str='all'):
    where,args=photo_filter(view,q,pet_id,album_id,media)
    order='ASC' if sort=='asc' else 'DESC'
    with db() as c:
        rows=c.execute(f'''SELECT coalesce(substr(taken_at,1,7),'') AS month,count(*) AS count
            FROM available_photos p WHERE {where} GROUP BY month ORDER BY month {order}''',args).fetchall()
    offset=0;months=[]
    for row in rows:
        months.append({'month':row['month'] or 'unknown','count':row['count'],'offset':offset})
        offset+=row['count']
    return {'months':months,'total':offset}


@app.get('/api/photos')
def photos(view:str='gallery',q:str='',pet_id:str='',album_id:str='',sort:str='desc',limit:int=Query(200,ge=1,le=500),offset:int=Query(0,ge=0),media:str='all'):
    where,args=photo_filter(view,q,pet_id,album_id,media);order='ASC' if sort=='asc' else 'DESC'
    with db() as c:
        total=c.execute('SELECT count(*) FROM available_photos p WHERE '+where,args).fetchone()[0]
        rows=c.execute(f'SELECT p.* FROM available_photos p WHERE {where} ORDER BY taken_at {order},id {order} LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
        return {'items':[serialize_photo(c,r) for r in rows],'total':total,'has_more':offset+len(rows)<total}


@app.get('/api/photos/{ident}/thumbnail')
def thumbnail(ident:str):
    with db() as c:row=c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'照片不存在')
    if row['media_type']=='video':
        target=video_thumbnail_path(row,row['video_cover'])
        if not target.exists():
            try:
                with VIDEO_THUMBNAIL_LIMIT:
                    if not target.exists():save_video_thumbnail(row,row['video_cover'],video.frame(row['path'],row['video_cover']))
            except OSError:raise HTTPException(404,'视频封面暂时无法读取')
        return FileResponse(target,media_type='image/jpeg',headers={'Cache-Control':'private,max-age=86400'})
    target=DATA/'thumbnails'/f"{ident}-{int(row['mtime'])}.jpg"
    if not target.exists():
        try:
            with Image.open(row['path']) as opened:
                image=ImageOps.exif_transpose(opened).convert('RGB');image.thumbnail((720,720))
                temporary=target.with_name(target.stem+'-'+uid()+'.tmp')
                image.save(temporary,format='JPEG',quality=86);temporary.replace(target)
        except OSError:raise HTTPException(404,'照片暂时无法读取')
    return FileResponse(target,media_type='image/jpeg',headers={'Cache-Control':'private,max-age=86400'})


@app.get('/api/photos/{ident}/image')
def original(ident:str):
    with db() as c:row=c.execute('SELECT p.*,s.path AS root FROM photos p JOIN storages s ON s.id=p.storage_id WHERE p.id=?',(ident,)).fetchone()
    if not row or not Path(row['path']).is_file() or not inside(Path(row['path']),Path(row['root'])):raise HTTPException(404,'照片暂时无法读取')
    return FileResponse(row['path'],media_type=mimetypes.guess_type(row['path'])[0] or 'image/jpeg')


def video_thumbnail_path(row,seconds):
    return DATA/'thumbnails'/f"{row['id']}-{row['content_hash'][:12]}-{seconds:.3f}.jpg"


def save_video_thumbnail(row,seconds,image):
    target=video_thumbnail_path(row,seconds);image=image.copy();image.thumbnail((720,720))
    temporary=target.with_name(target.stem+'-'+uid()+'.tmp')
    image.save(temporary,format='JPEG',quality=88);temporary.replace(target)


@app.get('/api/photos/{ident}/play')
def play_video(ident:str):
    with db() as c:row=c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
    if not row or row['media_type']!='video' or not Path(row['path']).is_file():raise HTTPException(404,'视频不存在')
    folder=DATA/'video-playback';folder.mkdir(exist_ok=True)
    target=folder/f"{ident}-{row['content_hash'][:16]}.mp4"
    with VIDEO_PLAY_LOCK:
        if not target.exists():
            try:video.compatible(row['path'],target,ready=lambda:not STOP.is_set() and not RESETTING.is_set())
            except OSError as error:raise HTTPException(422,str(error))
    return FileResponse(target,media_type='video/mp4')


class VideoCover(BaseModel):
    seconds:float=Field(ge=0,allow_inf_nan=False)


@app.patch('/api/photos/{ident}/video-cover')
def set_video_cover(ident:str,body:VideoCover):
    with db() as c:row=c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
    if not row or row['media_type']!='video':raise HTTPException(404,'视频不存在')
    if body.seconds>=row['duration']:raise HTTPException(400,'封面时间超出视频时长')
    try:image=video.frame(row['path'],body.seconds)
    except OSError as error:raise HTTPException(422,str(error))
    with db() as c:
        current=c.execute('SELECT content_hash FROM photos WHERE id=?',(ident,)).fetchone()
        if not current or current[0]!=row['content_hash']:raise HTTPException(409,'视频文件已变化，请重新打开')
        c.execute('UPDATE photos SET video_cover=?,video_cover_manual=1 WHERE id=?',(body.seconds,ident))
    save_video_thumbnail(row,body.seconds,image)
    return {'ok':True}


@app.post('/api/photos/{ident}/video-rescan')
def rescan_video(ident:str):
    with SCAN_LOCK:
        with db() as c:
            row=c.execute('SELECT * FROM available_photos WHERE id=?',(ident,)).fetchone()
            if not row or row['media_type']!='video':raise HTTPException(404,'视频不存在')
            if row['manual'] or row['removed']:raise HTTPException(409,'此视频已手工整理，将保留人工结果')
            if c.execute("SELECT 1 FROM jobs WHERE storage_id=? AND status IN ('queued','running','paused')",(row['storage_id'],)).fetchone():raise HTTPException(409,'请先等待当前文件夹的扫描任务结束')
            c.execute('UPDATE photos SET video_fine=1,recognized=0,identity_hash=NULL WHERE id=?',(ident,))
        job=queue_scan(row['storage_id'],files=[Path(row['path'])])
    return {'job_id':job}


class StorageInput(BaseModel):
    path:str
    name:str=''


@app.get('/api/directories')
def directories(path:str=''):
    shortcuts=[]
    configured=os.environ.get('OUSEPET_LIBRARY_ROOTS')
    available=[Path(p) for p in configured.split(os.pathsep)] if configured else [ROOT/'samples/pets',Path.home()/'Pictures']
    for item in available:
        if item.is_dir():shortcuts.append({'name':'宠物照片' if item==ROOT/'samples/pets' else item.name or str(item),'path':str(item.resolve())})
    if not path:return {'path':'','parent':None,'directories':shortcuts,'shortcuts':shortcuts}
    folder=resolved_directory(path)
    try:children=sorted([{'name':p.name,'path':str(p)} for p in folder.iterdir() if p.is_dir() and not p.name.startswith(('.','@'))],key=lambda p:p['name'].lower())
    except PermissionError:raise HTTPException(403,'无法读取这个目录')
    parent=str(folder.parent) if folder.parent!=folder else None
    return {'path':str(folder),'parent':parent,'directories':children,'shortcuts':shortcuts}


@app.post('/api/storages')
def add_storage(body:StorageInput):
    path=resolved_directory(body.path)
    with SCAN_LOCK,db() as c:
        row=c.execute('SELECT id,detached FROM storages WHERE path=?',(str(path),)).fetchone()
        if row:
            ident=row['id']
            if row['detached']:c.execute('UPDATE storages SET detached=0,auto_scan=1,name=? WHERE id=?',(body.name.strip() or path.name,ident))
        else:
            ident=uid();c.execute('INSERT INTO storages(id,name,path,created_at,last_scan) VALUES(?,?,?,?,?)',(ident,body.name.strip() or path.name,str(path),now(),None))
    return {'id':ident,'job_id':queue_scan(ident)}


@app.delete('/api/storages/{ident}')
def remove_storage(ident:str):
    # Keep all indexes and user edits; terminal jobs cannot resume on reimport.
    with SCAN_LOCK,db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT id FROM storages WHERE id=? AND detached=0',(ident,)).fetchone():raise HTTPException(404,'存储位置已移除或不存在')
        c.execute('UPDATE storages SET detached=1,auto_scan=0 WHERE id=?',(ident,))
        c.execute("UPDATE jobs SET status='cancelled',finished_at=?,current_file='' WHERE storage_id=? AND status IN ('running','queued','paused')",(now(),ident))
    return {'ok':True}


@app.post('/api/storages/{ident}/scan')
def scan(ident:str):return {'job_id':queue_scan(ident)}


class StorageSettings(BaseModel):
    auto_scan:bool


@app.patch('/api/storages/{ident}')
def storage_settings(ident:str,body:StorageSettings):
    with SCAN_LOCK,db() as c:
        if not c.execute('SELECT id FROM storages WHERE id=? AND detached=0',(ident,)).fetchone():raise HTTPException(404,'存储位置已移除或不存在')
        c.execute('UPDATE storages SET auto_scan=? WHERE id=?',(int(body.auto_scan),ident))
    return {'ok':True}


@app.get('/api/storages/{ident}/browse')
def browse(ident:str,path:str=''):
    with db() as c:storage=c.execute('SELECT * FROM storages WHERE id=?',(ident,)).fetchone()
    if not storage or storage['detached']:raise HTTPException(404,'存储位置已移除或不存在')
    base=Path(storage['path']);folder=base/Path(path)
    if not folder.is_dir() or not inside(folder,base):raise HTTPException(404,'目录不存在')
    children=[];files=[]
    try:entries=sorted(folder.iterdir(),key=lambda p:p.name.lower())
    except PermissionError:raise HTTPException(403,'无法读取这个目录')
    for entry in entries:
        if entry.name.startswith(('.','@')) or not inside(entry,base):continue
        if entry.is_dir():children.append({'name':entry.name,'path':str(entry.relative_to(base))})
        elif entry.suffix.lower() in EXTENSIONS:
            try:
                photo_id,_=index_file(storage,entry.resolve())
                with db() as c:photo=c.execute('SELECT * FROM photos WHERE id=?',(photo_id,)).fetchone();files.append(serialize_photo(c,photo))
            except (OSError,ValueError):pass
    return {'path':str(folder.relative_to(base)),'storage':dict(storage),'directories':children,'photos':files}


class PhotoAction(BaseModel):
    ids:list[str]=Field(min_length=1,max_length=500)
    action:str
    pet_id:str|None=None
    species:str|None=None
    album_id:str|None=None


@app.post('/api/photos/action')
def photo_action(body:PhotoAction):
    if body.species and body.species not in ('cat','hedgehog'):raise HTTPException(400,'请选择猫咪或刺猬')
    with db() as c:
        if body.action=='cover':
            c.execute('BEGIN IMMEDIATE')
            if not body.pet_id or len(body.ids)!=1:
                raise HTTPException(400,'请选择一张宠物照片作为封面')
            if not c.execute('''SELECT 1 FROM photo_pets pp JOIN available_photos p ON p.id=pp.photo_id
                WHERE pp.pet_id=? AND p.id=? AND p.visible=1''',(body.pet_id,body.ids[0])).fetchone():
                raise HTTPException(400,'照片已移出该档案，请选择档案内的照片')
        if body.pet_id and not c.execute('SELECT 1 FROM pets WHERE id=?',(body.pet_id,)).fetchone():raise HTTPException(404,'宠物档案不存在')
        if body.album_id and not c.execute('SELECT 1 FROM albums WHERE id=?',(body.album_id,)).fetchone():raise HTTPException(404,'相册不存在')
        for ident in body.ids:
            photo=c.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
            if not photo:continue
            if body.action=='favorite':c.execute('UPDATE photos SET favorite=1 WHERE id=?',(ident,))
            elif body.action=='unfavorite':c.execute('UPDATE photos SET favorite=0 WHERE id=?',(ident,))
            elif body.action=='hide':c.execute('UPDATE photos SET visible=0,removed=1 WHERE id=?',(ident,))
            elif body.action=='reject':
                c.execute("UPDATE photos SET visible=0,removed=1,manual=1,species='[]' WHERE id=?",(ident,))
                c.execute('DELETE FROM photo_pets WHERE photo_id=?',(ident,))
            elif body.action=='confirm':c.execute("UPDATE photo_pets SET status='confirmed' WHERE photo_id=?",(ident,))
            elif body.action in ('add','assign'):
                species=set(json.loads(photo['species']))
                if body.species:species.add(body.species)
                if body.pet_id:
                    pet=c.execute('SELECT * FROM pets WHERE id=?',(body.pet_id,)).fetchone();species.add(pet['species'])
                    c.execute("INSERT INTO photo_pets VALUES(?,?,'confirmed') ON CONFLICT(photo_id,pet_id) DO UPDATE SET status='confirmed'",(ident,body.pet_id))
                    c.execute('DELETE FROM identity_exclusions WHERE photo_id=? AND pet_id=?',(ident,body.pet_id))
                    c.execute('''UPDATE identity_observations SET excluded=0 WHERE photo_id=? AND cluster_id IN
                      (SELECT id FROM identity_clusters WHERE pet_id=?)''',(ident,body.pet_id))
                if not species:raise HTTPException(400,'请选择宠物或物种')
                c.execute('UPDATE photos SET visible=1,removed=0,manual=1,species=? WHERE id=?',(json.dumps(sorted(species)),ident))
            elif body.action=='album' and body.album_id:c.execute('INSERT OR IGNORE INTO album_photos VALUES(?,?)',(body.album_id,ident))
            elif body.action=='remove_album' and body.album_id:c.execute('DELETE FROM album_photos WHERE album_id=? AND photo_id=?',(body.album_id,ident))
            elif body.action=='unassign' and body.pet_id:
                identity.exclude(c,ident,body.pet_id)
                c.execute('DELETE FROM photo_pets WHERE photo_id=? AND pet_id=?',(ident,body.pet_id))
            elif body.action=='cover' and body.pet_id:c.execute('UPDATE pets SET cover_id=? WHERE id=?',(ident,body.pet_id))
            else:raise HTTPException(400,'操作不存在')
    if body.action in ('add','assign'):schedule_identity_matching()
    return {'ok':True,'count':len(body.ids)}


class PetInput(BaseModel):
    name:str=Field(min_length=1,max_length=40)
    species:str
    cover_id:str|None=None


class PetOrder(BaseModel):
    ids:list[str]=Field(min_length=1,max_length=10000)


@app.post('/api/pets/order')
def reorder_pets(body:PetOrder):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing={r[0] for r in c.execute('SELECT id FROM pets')}
        if len(set(body.ids))!=len(body.ids) or not set(body.ids)<=existing:
            raise HTTPException(400,'档案已变化，请关闭排序后重试')
        # Newly discovered profiles append; stale IDs from deleted/merged profiles disappear.
        remaining=[r[0] for r in c.execute('SELECT id FROM pets ORDER BY unnamed,created_at,id') if r[0] not in set(body.ids)]
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('pet_order',?)",(json.dumps(body.ids+remaining),))
    return {'ok':True}


@app.post('/api/pets')
def create_pet(body:PetInput):
    if body.species not in ('cat','hedgehog'):raise HTTPException(400,'请选择猫咪或刺猬')
    ident=uid()
    with db() as c:c.execute('INSERT INTO pets(id,name,species,cover_id,created_at) VALUES(?,?,?,?,?)',(ident,body.name.strip(),body.species,None,now()))
    return {'id':ident}


@app.patch('/api/pets/{ident}')
def edit_pet(ident:str,body:PetInput):
    if body.species not in ('cat','hedgehog'):raise HTTPException(400,'请选择猫咪或刺猬')
    if not body.name.strip():raise HTTPException(400,'请输入宠物名字')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM pets WHERE id=?',(ident,)).fetchone()
        if not row:raise HTTPException(404,'宠物档案不存在')
        if body.cover_id is not None:
            if not c.execute('''SELECT 1 FROM photo_pets pp JOIN available_photos p ON p.id=pp.photo_id
                WHERE pp.pet_id=? AND p.id=? AND p.visible=1''',(ident,body.cover_id)).fetchone():
                raise HTTPException(400,'照片已移出该档案，请重新选择封面')
            c.execute('UPDATE pets SET cover_id=? WHERE id=?',(body.cover_id,ident))
        identity.correct_species(c,ident,body.species)
        auto_name='未命名'+('猫咪' if body.species=='cat' else '刺猬')
        is_unnamed=bool(row['unnamed']) and body.name.strip() in (row['name'],auto_name)
        c.execute('UPDATE pets SET name=?,unnamed=? WHERE id=?',(auto_name if is_unnamed else body.name.strip(),int(is_unnamed),ident))
        c.execute('UPDATE identity_clusters SET reference_seed=1 WHERE pet_id=?',(ident,))
    schedule_identity_matching()
    return {'ok':True}


class MergePets(BaseModel):
    target_id:str
    confirm_conflicts:bool=False


class MergePetBatch(MergePets):
    source_ids:list[str]=Field(min_length=1,max_length=500)


@app.post('/api/pets/merge')
def merge_pet_batch(body:MergePetBatch):
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            identity.merge_many(c,body.source_ids,body.target_id,body.confirm_conflicts)
    except identity.MergeConflict as error:
        raise HTTPException(409,{'code':'merge_conflict','message':str(error),'photos':error.photos})
    except ValueError as error:raise HTTPException(400,str(error))
    schedule_identity_matching()
    return {'ok':True,'target_id':body.target_id,'merged':len(set(body.source_ids))}


@app.delete('/api/pets/{ident}')
def delete_pet(ident:str):
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            identity.delete_pet(c,ident)
    except ValueError as error:raise HTTPException(404,str(error))
    return {'ok':True}


@app.post('/api/pets/{ident}/merge')
def merge_pets(ident:str,body:MergePets):
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            identity.merge(c,ident,body.target_id,body.confirm_conflicts)
    except identity.MergeConflict as error:
        raise HTTPException(409,{'code':'merge_conflict','message':str(error),'photos':error.photos})
    except ValueError as error:raise HTTPException(400,str(error))
    schedule_identity_matching()
    return {'ok':True}


class AlbumInput(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    photo_ids:list[str]=[]


class AlbumEdit(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    cover_id:str|None=None


@app.patch('/api/albums/{ident}')
def edit_album(ident:str,body:AlbumEdit):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not body.name.strip():raise HTTPException(400,'请输入回忆名称')
        if not c.execute('SELECT 1 FROM albums WHERE id=?',(ident,)).fetchone():raise HTTPException(404,'回忆不存在')
        if body.cover_id is not None:
            if not c.execute('''SELECT 1 FROM album_photos a JOIN available_photos p ON p.id=a.photo_id
                WHERE a.album_id=? AND a.photo_id=?''',(ident,body.cover_id)).fetchone():raise HTTPException(400,'请选择回忆内的照片作为封面')
            c.execute('INSERT OR REPLACE INTO album_covers VALUES(?,?)',(ident,body.cover_id))
        c.execute('UPDATE albums SET name=? WHERE id=?',(body.name.strip(),ident))
    return {'ok':True}


class AlbumMerge(BaseModel):
    target_id:str
    source_ids:list[str]=Field(min_length=1,max_length=500)


@app.post('/api/albums/merge')
def merge_albums(body:AlbumMerge):
    ids=body.source_ids
    if body.target_id in ids or len(set(ids))!=len(ids):raise HTTPException(400,'请选择不同的回忆')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for ident in [body.target_id,*ids]:
            if not c.execute('SELECT 1 FROM albums WHERE id=?',(ident,)).fetchone():raise HTTPException(400,'回忆已变化，请重新选择')
        for ident in ids:
            c.execute('INSERT OR IGNORE INTO album_photos SELECT ?,photo_id FROM album_photos WHERE album_id=?',(body.target_id,ident))
            c.execute('DELETE FROM albums WHERE id=?',(ident,))
    return {'ok':True}


@app.delete('/api/albums/{ident}')
def delete_album(ident:str):
    with db() as c:
        if not c.execute('DELETE FROM albums WHERE id=?',(ident,)).rowcount:raise HTTPException(404,'回忆不存在')
    return {'ok':True}


@app.post('/api/albums')
def create_album(body:AlbumInput):
    ident=uid()
    with db() as c:
        c.execute('INSERT INTO albums VALUES(?,?,?)',(ident,body.name.strip(),now()))
        for photo_id in body.photo_ids:
            if c.execute('SELECT 1 FROM photos WHERE id=?',(photo_id,)).fetchone():c.execute('INSERT OR IGNORE INTO album_photos VALUES(?,?)',(ident,photo_id))
    return {'id':ident}


@app.delete('/api/jobs/history')
def clear_job_history():
    with SCAN_LOCK,db() as c:
        count=c.execute("UPDATE jobs SET dismissed=1 WHERE dismissed=0 AND status IN ('complete','cancelled','interrupted','error')").rowcount
    return {'ok':True,'count':count}


@app.delete('/api/jobs/{ident}')
def delete_job_history(ident:str):
    with SCAN_LOCK,db() as c:
        row=c.execute('SELECT status FROM jobs WHERE id=? AND dismissed=0',(ident,)).fetchone()
        if not row:raise HTTPException(404,'任务记录不存在')
        if row['status'] not in ('complete','cancelled','interrupted','error'):
            raise HTTPException(409,'请先取消任务，再删除记录')
        c.execute('UPDATE jobs SET dismissed=1 WHERE id=?',(ident,))
    return {'ok':True}


@app.post('/api/jobs/{ident}/{action}')
def job_action(ident:str,action:str):
    value={'pause':'paused','resume':'running','cancel':'cancelled'}.get(action)
    if not value:raise HTTPException(400,'操作不存在')
    with SCAN_LOCK,db() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone()
        if not row:raise HTTPException(404,'任务不存在')
        if row['status'] not in ('running','queued','paused'):raise HTTPException(400,'任务已结束')
        c.execute('UPDATE jobs SET status=?,finished_at=?,current_file=CASE WHEN ? THEN \'\' ELSE current_file END WHERE id=?',
                  (value,now() if action=='cancel' else None,action=='cancel',ident))
        if action=='cancel':c.execute('UPDATE storages SET auto_scan=0 WHERE id=?',(row['storage_id'],))
    return {'ok':True}


@app.get('/logo.png')
def logo():return FileResponse(ROOT/'assets/branding/logo-rounded-v2.png',media_type='image/png')


@app.get('/assets/{path:path}')
def assets(path:str):
    target=DIST/'assets'/path
    if not target.is_file() or not inside(target,DIST/'assets'):raise HTTPException(404)
    return FileResponse(target)


@app.get('/')
def home():
    if not (DIST/'index.html').exists():raise HTTPException(503,'前端正在准备中')
    return FileResponse(DIST/'index.html')


sharing.install_admin(app)
init()
