"""Read-only visitor service, intentionally independent from the management API."""
from contextlib import contextmanager
import base64
import binascii
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from ousepet import video

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('OUSEPET_DATA',str(ROOT/'.cache/album')))
DB=DATA/'album.sqlite3'
DIST=ROOT/'frontend/dist'
PUBLIC_PORT=int(os.environ.get('OUSEPET_SHARE_PORT','8767'))
MEDIA_LOCK=threading.Lock()


@contextmanager
def db():
    c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
    try:yield c;c.commit()
    finally:c.close()


def init_schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS memory_shares(
      id TEXT PRIMARY KEY,album_id TEXT NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
      token TEXT UNIQUE NOT NULL,pin_hash TEXT,expires_at REAL,allow_download INTEGER NOT NULL DEFAULT 0,
      enabled INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS share_attempts(key TEXT PRIMARY KEY,started REAL NOT NULL,count INTEGER NOT NULL);''')
    c.execute("INSERT OR IGNORE INTO settings VALUES('share_secret',?)",(secrets.token_hex(32),))


def normalise_origin(value):
    value=value.strip().rstrip('/')
    if not value:return ''
    if '://' not in value:value='https://'+value
    try:
        url=urlsplit(value);port=url.port
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError()
        if any(char.isspace() for char in value) or any(char in value for char in ('?','#','\\')):raise ValueError()
    except ValueError:raise HTTPException(400,'请输入完整的 HTTP/HTTPS 域名或 IP 地址，不包含路径')
    return value


def pin_hash(pin):
    if not pin:return None
    if len(pin)<4:raise HTTPException(400,'提取码至少 4 位')
    salt=secrets.token_hex(16)
    return salt+'$'+hashlib.pbkdf2_hmac('sha256',pin.encode(),salt.encode(),120000).hex()


class ShareInput(BaseModel):
    days:int=Field(default=7,ge=0,le=365)
    pin:str=Field(default='',max_length=32)
    allow_download:bool=False


class DomainInput(BaseModel):
    base_url:str=Field(default='',max_length=250)


def serialize_share(row):
    return {'id':row['id'],'album_id':row['album_id'],'name':row['name'],'token':row['token'],
        'expires_at':row['expires_at'],'allow_download':bool(row['allow_download']),'enabled':bool(row['enabled']),
        'code_required':bool(row['pin_hash']),'created_at':row['created_at'],'expired':bool(row['expires_at'] and row['expires_at']<=time.time())}


def install_admin(app):
    @app.get('/api/share-settings')
    def settings():
        with db() as c:row=c.execute("SELECT value FROM settings WHERE key='share_base_url'").fetchone()
        return {'base_url':row[0] if row else '', 'public_port':PUBLIC_PORT}

    @app.patch('/api/share-settings')
    def save_settings(body:DomainInput):
        origin=normalise_origin(body.base_url)
        with db() as c:c.execute("INSERT OR REPLACE INTO settings VALUES('share_base_url',?)",(origin,))
        return settings()

    @app.get('/api/shares')
    def shares(album_id:str=''):
        with db() as c:
            rows=c.execute('''SELECT s.*,a.name FROM memory_shares s JOIN albums a ON a.id=s.album_id
                WHERE (?='' OR s.album_id=?) ORDER BY s.created_at DESC''',(album_id,album_id)).fetchall()
        return {'items':[serialize_share(row) for row in rows]}

    @app.post('/api/albums/{ident}/shares')
    def create_share(ident:str,body:ShareInput):
        secret=pin_hash(body.pin);created=time.time();token=secrets.token_urlsafe(32);ident_share=secrets.token_hex(16)
        with db() as c:
            if not c.execute('SELECT 1 FROM albums WHERE id=?',(ident,)).fetchone():raise HTTPException(404,'回忆不存在')
            c.execute('INSERT INTO memory_shares VALUES(?,?,?,?,?,?,1,?)',
                (ident_share,ident,token,secret,created+body.days*86400 if body.days else None,int(body.allow_download),created))
            row=c.execute('SELECT s.*,a.name FROM memory_shares s JOIN albums a ON a.id=s.album_id WHERE s.id=?',(ident_share,)).fetchone()
        return serialize_share(row)

    @app.delete('/api/shares/{ident}')
    def revoke(ident:str,permanent:bool=False):
        with db() as c:
            sql='DELETE FROM memory_shares WHERE id=?' if permanent else 'UPDATE memory_shares SET enabled=0 WHERE id=?'
            if not c.execute(sql,(ident,)).rowcount:raise HTTPException(404,'分享不存在')
        return {'ok':True}


public_app=FastAPI(title='回忆分享',docs_url=None,redoc_url=None,openapi_url=None)


@public_app.middleware('http')
async def visitor_headers(request,call_next):
    response=await call_next(request)
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    response.headers['X-Robots-Tag']='noindex, nofollow'
    return response


def share_row(c,token):
    row=c.execute('SELECT s.*,a.name FROM memory_shares s JOIN albums a ON a.id=s.album_id WHERE s.token=?',(token,)).fetchone()
    if not row or not row['enabled'] or (row['expires_at'] and row['expires_at']<=time.time()):
        raise HTTPException(404,'分享已失效或已关闭')
    return row


def secret(c):return bytes.fromhex(c.execute("SELECT value FROM settings WHERE key='share_secret'").fetchone()[0])


def cookie_name(token):return 'memory_'+hashlib.sha256(token.encode()).hexdigest()[:12]


def access(c,row,request):
    if not row['pin_hash']:return
    cookie=request.cookies.get(cookie_name(row['token']),'')
    try:
        payload,signature=cookie.split('.')
        expected=hmac.new(secret(c),payload.encode(),hashlib.sha256).hexdigest()
        data=json.loads(base64.urlsafe_b64decode(payload+'='*((-len(payload))%4)))
        # PIN hash binds a session to the current protection settings.
        if not hmac.compare_digest(signature,expected) or data['token']!=row['token'] or data['until']<=time.time() or data['pin']!=hashlib.sha256(row['pin_hash'].encode()).hexdigest():
            raise ValueError()
    except (ValueError,KeyError,TypeError,binascii.Error,UnicodeDecodeError):raise HTTPException(401,'请输入提取码')


class Unlock(BaseModel):
    pin:str=Field(max_length=32)


@public_app.post('/api/public/shares/{token}/unlock')
def unlock(token:str,body:Unlock,request:Request):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=share_row(c,token)
        key=hashlib.sha256((token+':'+(request.client.host if request.client else '')).encode()).hexdigest()
        attempt=c.execute('SELECT * FROM share_attempts WHERE key=?',(key,)).fetchone();stamp=time.time()
        if attempt and stamp-attempt['started']<60 and attempt['count']>=10:raise HTTPException(429,'尝试次数过多，请一分钟后再试')
        correct=not row['pin_hash']
        if row['pin_hash']:
            salt,digest=row['pin_hash'].split('$')
            correct=hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',body.pin.encode(),salt.encode(),120000).hex(),digest)
        if not correct:
            if not attempt or stamp-attempt['started']>=60:c.execute('INSERT OR REPLACE INTO share_attempts VALUES(?,?,1)',(key,stamp))
            else:c.execute('UPDATE share_attempts SET count=count+1 WHERE key=?',(key,))
        else:
            c.execute('DELETE FROM share_attempts WHERE key=? OR started<?',(key,stamp-3600))
            payload=base64.urlsafe_b64encode(json.dumps({'token':token,'until':stamp+86400,'pin':hashlib.sha256((row['pin_hash'] or '').encode()).hexdigest()}).encode()).decode().rstrip('=')
            signed=payload+'.'+hmac.new(secret(c),payload.encode(),hashlib.sha256).hexdigest()
    if not correct:raise HTTPException(403,'提取码不正确')
    response=JSONResponse({'ok':True})
    response.set_cookie(cookie_name(token),signed,max_age=86400,httponly=True,samesite='lax',
        secure=request.url.scheme=='https' or request.headers.get('x-forwarded-proto')=='https',path='/api/public/shares/'+token)
    return response


@public_app.get('/api/public/shares/{token}')
def shared_memory(token:str,request:Request,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200)):
    with db() as c:
        row=share_row(c,token);access(c,row,request)
        where='FROM album_photos a JOIN available_photos p ON p.id=a.photo_id WHERE a.album_id=?'
        total=c.execute('SELECT count(*) '+where,(row['album_id'],)).fetchone()[0]
        photos=c.execute('SELECT p.* '+where+' ORDER BY p.taken_at DESC,p.id DESC LIMIT ? OFFSET ?',(row['album_id'],limit,offset)).fetchall()
        cover=c.execute('SELECT photo_id FROM album_covers WHERE album_id=?',(row['album_id'],)).fetchone()
        visible_cover=c.execute('SELECT 1 '+where+' AND p.id=?',(row['album_id'],cover[0])).fetchone() if cover else None
        prefix='/api/public/shares/'+token+'/media/'
        def item(p):return {'id':p['id'],'media_type':p['media_type'],'duration':p['duration'],'date':(p['taken_at'] or '')[:10],
            'thumb':prefix+p['id']+'/thumbnail','preview':prefix+p['id']+'/preview',
            'download':prefix+p['id']+'/download' if row['allow_download'] else None}
        result={'name':row['name'],'total':total,'items':[item(p) for p in photos],
            'cover':prefix+cover[0]+'/thumbnail' if visible_cover else None,'allow_download':bool(row['allow_download'])}
    return result


def media_path(c,row):
    candidates=[row['path']]+[r[0] for r in c.execute('SELECT f.path FROM scan_files f JOIN storages s ON s.id=f.storage_id WHERE f.photo_id=? AND s.detached=0',(row['id'],))]
    roots=[Path(p).resolve() for p in os.environ.get('OUSEPET_LIBRARY_ROOTS',str(ROOT)).split(os.pathsep) if p]
    for value in candidates:
        path=Path(value).resolve()
        if path.is_file() and any(path.is_relative_to(root) for root in roots):return path
    raise HTTPException(404,'内容暂时不可用')


@public_app.get('/api/public/shares/{token}/media/{ident}/{kind}')
def shared_media(token:str,ident:str,kind:str,request:Request):
    with db() as c:
        row=share_row(c,token);access(c,row,request)
        photo=c.execute('''SELECT p.* FROM album_photos a JOIN available_photos p ON p.id=a.photo_id
            WHERE a.album_id=? AND p.id=?''',(row['album_id'],ident)).fetchone()
        if not photo:raise HTTPException(404,'内容未分享到此回忆')
        if kind not in ('thumbnail','preview','download'):raise HTTPException(404)
        if kind=='download' and not row['allow_download']:raise HTTPException(403,'此分享未开启下载')
        path=media_path(c,photo)
    def recheck():
        with db() as c:
            current=share_row(c,token);access(c,current,request)
            if not c.execute('''SELECT 1 FROM album_photos a JOIN available_photos p ON p.id=a.photo_id
                WHERE a.album_id=? AND p.id=? AND p.content_hash=?''',(current['album_id'],ident,photo['content_hash'])).fetchone():
                raise HTTPException(404,'内容未分享到此回忆')
    def ready():
        try:recheck();return True
        except HTTPException:return False
    if kind=='download':return FileResponse(path,filename=photo['name'])
    folder=DATA/'share-cache';folder.mkdir(exist_ok=True)
    key=photo['id']+'-'+photo['content_hash'][:16]
    if photo['media_type']=='video' and kind=='preview':
        target=folder/(key+'-web.mp4')
        with MEDIA_LOCK:
            if not target.exists():
                try:video.compatible(path,target,ready=ready,strip_metadata=True)
                except OSError:
                    recheck();raise HTTPException(422,'视频暂时无法播放')
        recheck()
        return FileResponse(target,media_type='video/mp4')
    target=folder/(key+f"-{photo['video_cover']}-{kind}.jpg")
    with MEDIA_LOCK:
        if not target.exists():
            try:
                if photo['media_type']=='video':image=video.frame(path,photo['video_cover'])
                else:
                    with Image.open(path) as raw:image=ImageOps.exif_transpose(raw).convert('RGB')
                size=720 if kind=='thumbnail' else 1920;image.thumbnail((size,size))
                temporary=target.with_name(target.stem+'-'+secrets.token_hex(6)+'.tmp')
                image.save(temporary,format='JPEG',quality=88);temporary.replace(target)
            except OSError:raise HTTPException(404,'内容暂时无法读取')
    recheck()
    return FileResponse(target,media_type='image/jpeg')


@public_app.get('/s/{token}')
def share_page(token:str):
    return FileResponse(DIST/'index.html')


@public_app.get('/assets/{path:path}')
def assets(path:str):
    target=(DIST/'assets'/path).resolve()
    if not target.is_relative_to((DIST/'assets').resolve()) or not target.is_file():raise HTTPException(404)
    return FileResponse(target)


@public_app.get('/logo.png')
def logo():return FileResponse(ROOT/'assets/branding/logo-rounded-v2.png',media_type='image/png')
