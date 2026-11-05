import { useEffect, useRef, useState, type ReactNode } from "react";
import { Album as AlbumIcon, Check, ChevronRight, Trash2, X } from "lucide-react";
import { api, type Album, type Pet, type Photo } from "./api";
import PhotoPicker from "./PhotoPicker";
import Select from "./Select";
import { ShareModal } from "./Sharing";

function Dialog({ title, children, close, wide = false }: { title: string; children: ReactNode; close: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className={wide ? "modal wide photo-picker-modal" : "modal"} aria-label={title}
    onCancel={(event) => { event.preventDefault(); close(); }}>
    <div className="modal-heading"><h2>{title}</h2><button className="icon" aria-label="关闭" onClick={close}><X size={20} /></button></div>{children}
  </dialog>;
}

export function MemoryEditor({ album, pets, close, saved }: { album: Album; pets: Pet[]; close: () => void; saved: () => void }) {
  const [name, setName] = useState(album.name), [cover, setCover] = useState<Photo | null>(null);
  const [picking, setPicking] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  if (picking) return <Dialog title="设置回忆封面" wide close={() => { if (!busy) setPicking(false); }}>
    <PhotoPicker target={{ kind: "album-cover", id: album.id, name: album.name }} pets={pets} onSavingChange={setBusy}
      onClose={() => setPicking(false)} onAdded={() => {}} onCoverSelected={(photo) => { setCover(photo); setPicking(false); }} />
  </Dialog>;
  return <Dialog title="编辑回忆" close={() => { if (!busy) close(); }}>
    <form onSubmit={async (event) => {
      event.preventDefault(); if (busy) return; setBusy(true); setError("");
      try { await api(`/albums/${album.id}`, { name: name.trim(), ...(cover ? { cover_id: cover.id } : {}) }, "PATCH"); saved(); }
      catch (err) { setError(err instanceof Error ? err.message : "保存失败"); } finally { setBusy(false); }
    }}>
      <div className="dialog-body">
        <button type="button" className="pet-edit-cover memory-edit-cover" aria-label="更换回忆封面" disabled={busy || !album.count} onClick={() => setPicking(true)}>
          {cover?.thumb || album.cover ? <img src={cover?.thumb || album.cover!} alt="回忆封面" /> : <div className="pet-edit-cover-placeholder"><AlbumIcon size={44} /></div>}
          <span className="pet-cover-change">更换封面</span>
        </button>
        <label className="field-label" htmlFor="memory-name">回忆名称</label>
        <input id="memory-name" className="text-input" value={name} maxLength={60} required onChange={(event) => setName(event.target.value)} disabled={busy} />
        {error && <p className="picker-error" role="alert">{error}</p>}
      </div>
      <div className="dialog-footer"><button type="button" className="button" disabled={busy} onClick={close}>取消</button><button className="button primary" disabled={busy || !name.trim()}>保存回忆</button></div>
    </form>
  </Dialog>;
}

export default function MemoryManager({ albums, pets, open, changed }: { albums: Album[]; pets: Pet[]; open: (id: string) => void; changed: () => void }) {
  const [selected, setSelected] = useState<string[]>([]), [editing, setEditing] = useState<Album | null>(null);
  const [deleting, setDeleting] = useState<Album | null>(null), [merging, setMerging] = useState(false), [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [sharing, setSharing] = useState<Album | null>(null);
  const records = albums.filter((album) => selected.includes(album.id));
  const toggle = (id: string) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (document.querySelector('dialog[open]') || (event.target as Element).closest('input,textarea,[contenteditable=true]')) return;
      if (event.key === "Escape" && selected.length) { event.preventDefault(); setSelected([]); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") { event.preventDefault(); setSelected(albums.map((album) => album.id)); }
    };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  }, [albums, selected.length]);
  return <>
    {!!records.length && <div className="pet-selection-bar" role="region" aria-label="回忆多选操作">
      <button className="icon" aria-label="退出回忆多选" onClick={() => setSelected([])}><X size={18} /></button><strong>已选 {records.length} 个回忆</strong>
      <button onClick={() => setSelected(albums.map((album) => album.id))}>全选</button>
      <button className="button primary" disabled={records.length < 2} onClick={() => { setTarget(records[0].id); setError(""); setMerging(true); }}>合并回忆</button>
    </div>}
    <div className="collection-grid">{albums.map((album) => <article className={"collection-card pet-card" + (selected.includes(album.id) ? " pet-selected" : "")} data-memory-id={album.id} key={album.id}>
      <button className="pet-select" aria-label={"选择回忆" + album.name} aria-pressed={selected.includes(album.id)} onClick={() => toggle(album.id)}>{selected.includes(album.id) && <Check size={14} />}</button>
      <button className="pet-open" onClick={() => selected.length ? toggle(album.id) : open(album.id)}>
        <div className="collection-cover">{album.cover ? <img src={album.cover} alt={album.name} /> : <div className="cover-placeholder"><AlbumIcon size={56} /></div>}</div>
        <div className="collection-caption"><h3>{album.name}</h3><span>{album.video_count ? `${album.count} 项 · ${album.video_count} 个视频` : `${album.count} 张照片`}</span><ChevronRight size={18} /></div>
      </button>
      {!selected.length && <div className="pet-card-actions">
        <button className="button subtle" aria-label={"编辑回忆" + album.name} onClick={() => setEditing(album)}>编辑</button>
        <button className="button subtle" aria-label={"分享回忆" + album.name} onClick={() => setSharing(album)}>分享</button>
        <button className="button subtle" aria-label={"删除回忆" + album.name} onClick={() => { setDeleting(album); setError(""); }}><Trash2 size={14} />删除</button>
      </div>}
    </article>)}</div>
    {editing && <MemoryEditor album={editing} pets={pets} close={() => setEditing(null)} saved={() => { setEditing(null); changed(); }} />}
    {sharing && <ShareModal album={sharing} close={() => setSharing(null)} />}
    {deleting && <Dialog title="删除回忆" close={() => { if (!busy) setDeleting(null); }}>
      <div className="dialog-body"><p>删除“{deleting.name}”？照片会保留在图库中。</p>{error && <p role="alert" className="picker-error">{error}</p>}</div>
      <div className="dialog-footer"><button className="button" disabled={busy} onClick={() => setDeleting(null)}>取消</button><button className="button primary" disabled={busy} onClick={async () => {
        setBusy(true); try { await api(`/albums/${deleting.id}`, {}, "DELETE"); setDeleting(null); changed(); }
        catch (err) { setError(err instanceof Error ? err.message : "删除失败"); } finally { setBusy(false); }
      }}>删除回忆</button></div>
    </Dialog>}
    {merging && <Dialog title="合并回忆" close={() => { if (!busy) setMerging(false); }}>
      <div className="dialog-body"><label className="field-label">保留哪个回忆</label>
        <Select aria-label="保留回忆" value={target} disabled={busy} onChange={(event) => setTarget(event.target.value)}>{records.map((album) => <option value={album.id} key={album.id}>{album.name} · {album.count} 张</option>)}</Select>
        {error && <p className="picker-error" role="alert">{error}</p>}
      </div><div className="dialog-footer"><button className="button" disabled={busy} onClick={() => setMerging(false)}>取消</button><button className="button primary" disabled={busy || records.length < 2} onClick={async () => {
        setBusy(true); try { await api('/albums/merge', { target_id: target, source_ids: records.filter((album) => album.id !== target).map((album) => album.id) }); setMerging(false); setSelected([]); changed(); }
        catch (err) { setError(err instanceof Error ? err.message : "合并失败"); } finally { setBusy(false); }
      }}>确认合并</button></div>
    </Dialog>}
  </>;
}
