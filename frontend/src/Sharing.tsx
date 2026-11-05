import { useEffect, useState } from "react";
import { Copy, Share2, Trash2, Link2, Images, ShieldCheck, Download, Ban, Check, ArrowUpRight } from "lucide-react";
import { api, type Album } from "./api";
import Dialog from "./Dialog";

type Config = { base_url: string; public_port: number };
type Share = { id: string; album_id: string; name: string; token: string; expires_at: number | null; enabled: boolean; expired: boolean; code_required: boolean; allow_download: boolean };
export function shareURL(config: Config, token: string) {
  const local = new URL(window.location.origin); local.port = String(config.public_port);
  return (config.base_url || local.origin).replace(/\/$/, "") + "/s/" + token;
}
async function copy(text: string) {
  try { if (navigator.clipboard) { await navigator.clipboard.writeText(text); return; } } catch { /* HTTP/IP fallback below. */ }
  const field = document.createElement("textarea"), active = document.activeElement as HTMLElement | null;
  field.value = text; field.style.position = "fixed"; field.style.opacity = "0";
  (document.querySelector("dialog[open]") || document.body).appendChild(field); field.select();
  const ok = document.execCommand("copy"); field.remove(); active?.focus(); if (!ok) throw new Error("请选中链接手动复制");
}
function LinkList({ items, config, revoke, remove, notify, albums, busy }: { items: Share[]; config: Config; revoke: (id: string) => void; remove: (id: string) => Promise<void>; notify: (text: string) => void; albums: Album[]; busy: boolean }) {
  const [confirm, setConfirm] = useState("");
  return <div className="share-link-list">{items.map((share) => {
    const album = albums.find((item) => item.id === share.album_id), active = share.enabled && !share.expired;
    const destination = active ? shareURL(config, share.token) : undefined;
    return <article key={share.id} className={"share-record" + (active ? "" : " inactive")}>
      <a className="share-record-cover" href={destination} target="_blank" rel="noopener noreferrer" aria-label={"打开分享" + share.name} aria-disabled={!active}>{album?.cover ? <img src={album.cover} alt="" loading="lazy" /> : <Images size={36} />}{active && <span className="share-cover-open"><ArrowUpRight size={19} /></span>}</a>
      <div className="share-record-content">
        <div className="share-record-title"><strong><a href={destination} target="_blank" rel="noopener noreferrer" aria-disabled={!active}>{share.name}</a></strong><span className={"share-status " + (active ? "active" : "")}>{!share.enabled ? "已关闭" : share.expired ? "已过期" : "分享中"}</span></div>
        <div className="share-record-details"><span>{share.expires_at ? new Date(share.expires_at * 1000).toLocaleDateString("zh-CN") + " 到期" : "永久有效"}</span>{share.code_required && <span><ShieldCheck size={13} />提取码</span>}{share.allow_download && <span><Download size={13} />可下载</span>}</div>
        <a className="share-record-url" aria-label={"分享链接" + share.name} href={destination} target="_blank" rel="noopener noreferrer" aria-disabled={!active} title={shareURL(config, share.token)}><Link2 size={14} /><span>{shareURL(config, share.token)}</span><ArrowUpRight size={13} /></a>
      </div>
      <div className="share-record-actions">
        <button className="button subtle" disabled={busy || !active} onClick={() => copy(shareURL(config, share.token)).then(() => notify("链接已复制")).catch((error) => notify(error.message))}><Copy size={14} />复制链接</button>
        {active && <button className="icon" title="关闭分享" aria-label={"关闭分享" + share.name} disabled={busy} onClick={() => revoke(share.id)}><Ban size={17} /></button>}
        <button className="icon share-delete" title="删除记录" aria-label={"删除记录" + share.name} disabled={busy} onClick={() => setConfirm(share.id)}><Trash2 size={17} /></button>
      </div>
      {confirm === share.id && <div className="share-delete-confirm" role="alert"><span>删除这条记录？对应链接将立即失效，回忆和原文件保留。</span><div><button className="button subtle" disabled={busy} onClick={() => setConfirm("")}>取消</button><button className="button share-danger" disabled={busy} onClick={() => { remove(share.id).then(() => setConfirm("")); }}>确认删除</button></div></div>}
    </article>;
  })}</div>;
}

export function ShareModal({ album, close }: { album: Album; close: () => void }) {
  const [config, setConfig] = useState<Config | null>(null), [items, setItems] = useState<Share[]>([]);
  const [days, setDays] = useState("7"), [pin, setPin] = useState(""), [download, setDownload] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const load = () => api<{ items: Share[] }>(`/shares?album_id=${encodeURIComponent(album.id)}`).then((data) => setItems(data.items));
  useEffect(() => { Promise.all([api<Config>("/share-settings").then(setConfig), load()]).catch((err) => setError(err.message)); }, [album.id]);
  const revoke = async (id: string) => {
    if (busy) return; setBusy(true);
    try { await api(`/shares/${id}`, {}, "DELETE"); await load(); setMessage("分享已关闭"); } catch (err) { setError(err instanceof Error ? err.message : "关闭失败"); } finally { setBusy(false); }
  };
  const remove = async (id: string) => {
    if (busy) return; setBusy(true);
    try { await api(`/shares/${id}?permanent=true`, {}, "DELETE"); await load(); setMessage("记录已删除"); } catch (err) { setError(err instanceof Error ? err.message : "删除失败"); } finally { setBusy(false); }
  };
  return <Dialog title="分享回忆" className="memory-share-modal" close={() => { if (!busy) close(); }}>
    <div className="share-memory-summary"><div>{album.cover ? <img src={album.cover} alt="" /> : <Images size={32} />}</div><section><h3>{album.name}</h3><span>{album.count} 项内容</span></section><Share2 size={24} /></div>
    <form onSubmit={async (event) => {
      event.preventDefault(); if (busy) return; setBusy(true); setError(""); setMessage("");
      try { await api(`/albums/${album.id}/shares`, { days: Number(days), pin, allow_download: download }); await load(); setMessage("分享链接已创建"); }
      catch (err) { setError(err instanceof Error ? err.message : "创建失败"); } finally { setBusy(false); }
    }}>
      <div className="dialog-body share-create-fields">
        <label className="field-label">有效期</label>
        <div className="share-duration-options" role="group" aria-label="分享有效期">{[["7", "7 天"], ["30", "30 天"], ["0", "永久"]].map(([value, label]) => <button key={value} type="button" disabled={busy} aria-pressed={days === value} onClick={() => setDays(value)}>{label}{days === value && <Check size={14} />}</button>)}</div>
        <label className="field-label" htmlFor="share-pin">提取码（可选）</label><input id="share-pin" className="text-input" placeholder="不填则无需提取码" value={pin} minLength={4} maxLength={32} disabled={busy} onChange={(event) => setPin(event.target.value)} />
        <label className="share-checkbox"><Download size={17} /><span>允许下载原文件</span><input type="checkbox" role="switch" checked={download} disabled={busy} onChange={(event) => setDownload(event.target.checked)} /></label>
        {error && <p className="picker-error" role="alert">{error}</p>}{message && <p className="share-message" role="status">{message}</p>}
      </div><div className="dialog-footer"><button className="button primary" disabled={busy || !config}><Share2 size={15} />创建分享链接</button></div>
    </form>
    {config && items.length > 0 && <div className="dialog-body share-existing"><h3>已有链接 <span>{items.length}</span></h3><LinkList items={items} config={config} revoke={revoke} remove={remove} albums={[album]} busy={busy} notify={setMessage} /></div>}
  </Dialog>;
}

export function ShareSettings() {
  const [config, setConfig] = useState<Config | null>(null), [domain, setDomain] = useState("");
  const [port, setPort] = useState(""), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const setAddress = (value: string) => {
    setDomain(value);
    try { setPort(value ? new URL(value.includes("://") ? value : "https://" + value).port : ""); } catch { setPort(""); }
  };
  useEffect(() => { api<Config>("/share-settings").then((data) => { setConfig(data); setAddress(data.base_url); }).catch((err) => setMessage(err.message)); }, []);
  const address = config ? shareURL(config, "").replace(/\/s\/$/, "") : "";
  const externalPort = address ? new URL(address).port || (address.startsWith("https:") ? "443" : "80") : "";
  return <>
    <h3 className="settings-section-title">分享链接地址</h3>
    <form className="share-domain-form" onSubmit={async (event) => {
      event.preventDefault(); setBusy(true);
      try {
        let value = domain.trim();
        if (port) {
          if (!value) throw new Error("请先填写分享域名；留空时自动使用本机分享端口");
          const url = new URL(value.includes("://") ? value : "https://" + value);
          url.port = port; value = url.href;
        }
        const data = await api<Config>("/share-settings", { base_url: value }, "PATCH"); setConfig(data); setAddress(data.base_url); window.dispatchEvent(new Event("share-settings-changed")); setMessage("分享域名已保存"); }
      catch (err) { setMessage(err instanceof Error ? err.message : "保存失败"); } finally { setBusy(false); }
    }}>
      <label className="field-label" htmlFor="share-domain">分享域名</label><input id="share-domain" className="text-input" placeholder="https://photos.example.com" value={domain} maxLength={250} disabled={!config || busy} onChange={(event) => setAddress(event.target.value)} />
      <label className="field-label share-port-label" htmlFor="share-port">外部访问端口（可选）</label><input id="share-port" className="text-input share-port-input" type="number" min="1" max="65535" placeholder="HTTPS 默认 443，HTTP 默认 80" value={port} disabled={!config || busy} onChange={(event) => setPort(event.target.value)} />
      <button className="button primary" disabled={busy || !config}>保存域名</button>
    </form>
    {config && <div className="share-address-info"><div><span>当前分享地址</span><strong>{address}</strong><span>外部访问端口：{externalPort}</span></div><div><span>反向代理目标</span><strong>{window.location.hostname.includes(":") ? `[${window.location.hostname.replace(/^\[|\]$/g, "")}]` : window.location.hostname}:{config.public_port}</strong><span>分享服务端口：{config.public_port}</span></div></div>}
    <div className="settings-help"><p>留空时使用当前 IP 和分享端口 {config?.public_port || 8767}。配置域名后，新复制的链接使用该域名。</p><p>反向代理请指向分享端口 {config?.public_port || 8767}；管理端口 8766 用于你自己的操作。分享内容跟随回忆更新，关闭分享或删除回忆后链接失效。</p><p>关闭下载会隐藏原文件下载入口，观看时仍可保存已加载的画面。分享中的照片预览不包含原图 EXIF，视频预览会移除来源元数据。</p></div>
    {message && <p className="share-message" role="status">{message}</p>}
  </>;
}

export function ShareLinks({ albums = [] }: { albums?: Album[] }) {
  const [config, setConfig] = useState<Config | null>(null), [items, setItems] = useState<Share[]>([]);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const load = () => api<{ items: Share[] }>("/shares").then((data) => setItems(data.items));
  useEffect(() => { Promise.all([api<Config>("/share-settings").then(setConfig), load()]).catch((err) => setError(err.message)).finally(() => setLoading(false)); }, []);
  useEffect(() => {
    const update = () => { api<Config>("/share-settings").then(setConfig).catch((err) => setError(err.message)); };
    window.addEventListener("share-settings-changed", update);
    return () => window.removeEventListener("share-settings-changed", update);
  }, []);
  return <section className="share-management" aria-label="外链列表">
    <div className="share-list-toolbar"><div className="filter-tabs" role="group" aria-label="外链状态">{[["all", "全部"], ["active", "分享中"], ["inactive", "已失效"]].map(([key, label]) => <button key={key} className={filter === key ? "chosen" : ""} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div><span>{items.length} 条外链</span></div>
    {message && <p className="share-message" role="status">{message}</p>}
    {error && <p className="picker-error" role="alert">{error}</p>}
    {loading && <p className="muted">正在加载外链…</p>}
    {config && <LinkList items={items.filter((item) => filter === "all" || (item.enabled && !item.expired ? filter === "active" : filter === "inactive"))} albums={albums} busy={busy} config={config} notify={setMessage} remove={async (id) => {
      if (busy) return; setBusy(true); setError("");
      try { await api(`/shares/${id}?permanent=true`, {}, "DELETE"); await load(); setMessage("记录已删除"); }
      catch (err) { setError(err instanceof Error ? err.message : "删除失败"); } finally { setBusy(false); }
    }} revoke={async (id) => {
      if (busy) return; setBusy(true); try { await api(`/shares/${id}`, {}, "DELETE"); await load(); setMessage("分享已关闭"); }
      catch (err) { setMessage(err instanceof Error ? err.message : "关闭失败"); } finally { setBusy(false); }
    }} />}
    {!loading && !error && !items.length && <p className="muted">还没有外链，可以在回忆中创建分享。</p>}
  </section>;
}
