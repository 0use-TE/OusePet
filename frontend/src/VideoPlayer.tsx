import { useRef, useState } from "react";
import { api, type Photo } from "./api";

export function durationLabel(seconds = 0) {
  const value = Math.max(0, Math.floor(seconds));
  return value >= 3600 ? `${Math.floor(value / 3600)}:${String(Math.floor(value / 60) % 60).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}` : `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

export default function VideoPlayer({ photo, changed, notify }: { photo: Photo; changed: () => void; notify: (message: string) => void }) {
  const player = useRef<HTMLVideoElement>(null);
  const [compatible, setCompatible] = useState(false), [loading, setLoading] = useState(false), [failed, setFailed] = useState(false), [busy, setBusy] = useState(false);
  const [poster, setPoster] = useState(photo.thumb);
  return <div className="video-player">
    <video ref={player} key={compatible ? "compatible" : "original"} controls playsInline preload="metadata" poster={poster}
      src={compatible ? `/api/photos/${photo.id}/play` : photo.url} onCanPlay={() => setLoading(false)}
      onError={() => { if (!compatible) { setCompatible(true); setLoading(true); } else { setFailed(true); setLoading(false); } }} />
    {loading && <p role="status">正在准备兼容播放，长视频需要一些时间…</p>}
    {failed && <p role="alert">暂时无法播放，可<a href={photo.url} download={photo.name}>下载原视频</a>。</p>}
    <div className="video-actions">
      <button className="button subtle" disabled={busy || failed} onClick={async () => {
        if (!player.current || player.current.readyState < 1) return;
        setBusy(true);
        try {
          await api(`/photos/${photo.id}/video-cover`, { seconds: player.current.currentTime }, "PATCH");
          setPoster(photo.thumb.split("?")[0] + `?v=${Date.now()}`); changed(); notify("已将当前画面设为视频封面");
        } catch (error) { notify(error instanceof Error ? error.message : "封面设置失败"); } finally { setBusy(false); }
      }}>当前画面设为视频封面</button>
      <button className="button subtle" disabled={busy || photo.manual} title={photo.manual ? "保留人工整理结果" : "加密采样，单次最多 180 帧"} onClick={async () => {
        setBusy(true); try { await api(`/photos/${photo.id}/video-rescan`, {}); changed(); notify("已安排视频精细识别"); }
        catch (error) { notify(error instanceof Error ? error.message : "无法开始识别"); } finally { setBusy(false); }
      }}>精细识别</button>
    </div>
    {!!photo.video_hits?.length && <div className="video-hit-times" aria-label="宠物出现时间">{photo.video_hits.map((hit) => <button key={hit.pet_id} className="button subtle" onClick={() => {
      if (player.current) { player.current.currentTime = hit.seconds; player.current.play().catch(() => {}); }
    }}>{hit.name} · {durationLabel(hit.seconds)}</button>)}</div>}
    {photo.video_error && <p className="picker-error" role="alert">{photo.video_error}</p>}
  </div>;
}
