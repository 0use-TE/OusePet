"""Bounded video decoding; originals are never modified."""
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import time
from PIL import Image

EXTENSIONS={'.mp4','.mov','.m4v','.mkv','.avi','.webm','.mts','.m2ts','.3gp'}
MAX_COARSE=120
MAX_REFINE=60


class Cancelled(OSError):pass


def run(args,ready=None,timeout=45):
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    try:process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**options)
    except OSError as error:raise OSError('视频解码器不可用，请检查 FFmpeg 安装') from error
    start=time.monotonic()
    try:
        while True:
            if ready is not None and not ready():raise Cancelled('视频任务已取消')
            if time.monotonic()-start>timeout:raise OSError('视频解码超时')
            try:
                out,error=process.communicate(timeout=.2)
                if process.returncode:raise OSError('视频解码失败：'+error.decode(errors='replace')[-300:])
                return out
            except subprocess.TimeoutExpired:continue
    finally:
        if process.poll() is None:process.kill();process.communicate()


def probe(path):
    data=json.loads(run([os.environ.get('OUSEPET_FFPROBE','ffprobe'),'-v','error','-select_streams','v:0',
        '-show_streams','-show_format','-of','json',str(path)]))
    streams=data.get('streams',[])
    if not streams:raise OSError('视频中没有可读取的画面')
    stream=streams[0];info=data.get('format',{})
    try:duration=float(info.get('duration') or stream.get('duration') or 0)
    except (ValueError,TypeError):duration=0
    if not math.isfinite(duration) or duration<=0:raise OSError('无法读取视频时长')
    width=int(stream.get('width') or 0);height=int(stream.get('height') or 0)
    rotation=next((item.get('rotation',0) for item in stream.get('side_data_list',[]) if 'rotation' in item),stream.get('tags',{}).get('rotate',0))
    if abs(float(rotation))%180==90:width,height=height,width
    if not width or not height:raise OSError('无法读取视频尺寸')
    return {'duration':duration,'width':width,'height':height,
        'date':stream.get('tags',{}).get('creation_time') or info.get('tags',{}).get('creation_time'),
        'codec':stream.get('codec_name','')}


def frame(path,seconds,ready=None):
    raw=run([os.environ.get('OUSEPET_FFMPEG','ffmpeg'),'-v','error','-nostdin','-threads','2',
        '-ss',f'{max(0,seconds):.3f}','-i',str(path),'-map','0:v:0','-frames:v','1',
        '-vf','scale=1280:1280:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','mjpeg','-threads','2','pipe:1'],ready)
    try:
        with Image.open(BytesIO(raw)) as image:return image.convert('RGB')
    except OSError as error:raise OSError('此时间点无法解码画面') from error


def sample_times(duration,fine=False):
    step=1 if fine else 2 if duration<=20 else 5 if duration<=300 else 10
    end=max(0,duration-min(.25,duration/2))
    count=min(MAX_COARSE,math.ceil(end/step)+1)
    if end/step+1>MAX_COARSE:return [round(end*i/(count-1),3) for i in range(count)]
    return sorted({*[float(i*step) for i in range(count) if i*step<=end],round(end,3)})[:MAX_COARSE]


def refinement_times(duration,hits,existing):
    points=sorted({float(max(0,t+d)) for t in hits for d in (-2,-1,0,1,2)
        if 0<=t+d<duration-.1 and all(abs(t+d-x)>.15 for x in existing)})
    if len(points)>MAX_REFINE:points=[points[round(i*(len(points)-1)/(MAX_REFINE-1))] for i in range(MAX_REFINE)]
    return points


def compatible(path,target,ready=None,strip_metadata=False):
    temporary=target.with_name(target.stem+'-'+str(time.time_ns())+'.mp4')
    try:
        run([os.environ.get('OUSEPET_FFMPEG','ffmpeg'),'-v','error','-nostdin','-y','-threads','2','-i',str(path),
            '-map','0:v:0','-map','0:a:0?','-vf',"scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2",
            '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-threads','2',
            '-c:a','aac','-b:a','128k','-ac','2',*(['-map_metadata','-1','-map_chapters','-1'] if strip_metadata else []),'-movflags','+faststart',str(temporary)],ready,timeout=900)
        temporary.replace(target)
    finally:
        if temporary.exists():temporary.unlink()
