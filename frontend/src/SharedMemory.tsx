import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Play, X } from "lucide-react";
import { durationLabel } from "./VideoPlayer";

type Item = { id: string; media_type: string; duration: number; date: string; thumb: string; preview: string; download: string | null };
type Shared = { name: string; total: number; cover: string | null; items: Item[]; allow_download: boolean };
export default function SharedMemory() {
  const token = window.location.pathname.split("/s/")[1] || "";
  const [data, setData] = useState<Shared | null>(null), [locked, setLocked] = useState(false), [pin, setPin] = useState("");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [light, setLight] = useState<number | null>(null);
  const viewer = useRef<HTMLDialogElement>(null);
  const load = async (offset = 0) => {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/public/shares/${encodeURIComponent(token)}?offset=${offset}&limit=100`, { credentials: "same-origin" });
      if (response.status === 401) { setLocked(true); return; }
      if (!response.ok) throw new Error("分享已失效或已关闭");
      const result: Shared = await response.json(); setLocked(false);
      setData((previous) => offset && previous ? { ...result, items: [...previous.items, ...result.items] } : result);
    } catch (err) { setError(err instanceof Error ? err.message : "暂时无法加载分享"); }
    finally { setBusy(false); }
  };
  useEffect(() => { load(); }, [token]);
  const item = light === null ? null : data?.items[light];
  useEffect(() => { if (item && !viewer.current?.open) viewer.current?.showModal(); }, [item]);
  useEffect(() => {
    if (!item) return;
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") setLight(null);
      if ((event.target as Element).closest('video')) return;
      if (event.key === "ArrowLeft") setLight((index) => Math.max(0, (index || 0) - 1));
      if (event.key === "ArrowRight") setLight((index) => Math.min((data?.items.length || 1) - 1, (index || 0) + 1));
    };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  }, [item, data?.items.length]);
  return <main className="shared-page">
    <header className="shared-brand"><img src="/logo.png" alt="" /><span>有宠相簿</span></header>
    {locked ? <form className="shared-unlock" onSubmit={async (event) => {
      event.preventDefault(); setBusy(true); setError("");
      try {
        const response = await fetch(`/api/public/shares/${encodeURIComponent(token)}/unlock`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin }) });
        if (!response.ok) { const result = await response.json(); throw new Error(result.detail || "提取码不正确"); }
        await load();
      } catch (err) { setError(err instanceof Error ? err.message : "无法打开分享"); } finally { setBusy(false); }
    }}><h1>查看回忆</h1><label htmlFor="guest-pin">提取码</label><input id="guest-pin" className="text-input" value={pin} maxLength={32} autoComplete="off" required onChange={(event) => setPin(event.target.value)} /><button className="button primary" disabled={busy}>打开回忆</button>{error && <p role="alert">{error}</p>}</form>
    : <>{data && <><div className="shared-title">
      <h1>{data.name}</h1><span>{data.total} 项回忆</span>
    </div><div className="shared-grid">{data.items.map((photo, index) => <button key={photo.id} className="shared-tile" aria-label={photo.media_type === "video" ? `播放视频 ${index + 1}` : `查看照片 ${index + 1}`} onClick={() => setLight(index)}>
      <img src={photo.thumb} alt={photo.date || "回忆"} loading="lazy" />{photo.media_type === "video" && <span className="video-duration"><Play size={12} />{durationLabel(photo.duration)}</span>}<span className="shared-tile-date">{photo.date}</span>
    </button>)}</div>{!data.total && <p className="shared-empty">这份回忆暂时没有可展示的内容</p>}
    {data.items.length < data.total && <button className="button shared-load" disabled={busy} onClick={() => load(data.items.length)}>{busy ? "正在加载…" : "加载更多"}</button>}</>}
    {error && <div className="shared-empty" role="alert">{error}</div>}{!data && busy && <p className="shared-empty">正在打开回忆…</p>}</>}
    {item && data && <dialog ref={viewer} className="shared-viewer" aria-label="回忆预览" onCancel={(event) => { event.preventDefault(); setLight(null); }}>
      <div className="shared-viewer-bar"><button className="icon" aria-label="关闭预览" onClick={() => setLight(null)}><X /></button><span>{light! + 1} / {data.items.length}</span>{item.download && <a className="button subtle" href={item.download} download><Download size={16} />下载</a>}</div>
      <div className="shared-viewer-content"><button className="icon" aria-label="上一项" disabled={light === 0} onClick={() => setLight(light! - 1)}><ChevronLeft /></button>
      {item.media_type === "video" ? <GuestVideo key={item.id} item={item} /> : <img src={item.preview} alt={item.date} />}
      <button className="icon" aria-label="下一项" disabled={light === data.items.length - 1} onClick={() => setLight(light! + 1)}><ChevronRight /></button></div>
    </dialog>}
  </main>;
}
function GuestVideo({ item }: { item: Item }) {
  const [waiting, setWaiting] = useState(true), [failed, setFailed] = useState(false);
  return <div className="guest-video"><video src={item.preview} poster={item.thumb} controls playsInline preload="metadata" onCanPlay={() => setWaiting(false)} onError={() => { setFailed(true); setWaiting(false); }} />
    {waiting && <p role="status">正在准备视频…</p>}{failed && <p role="alert">视频暂时无法播放</p>}</div>;
}
