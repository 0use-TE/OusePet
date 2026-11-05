import { useEffect, useRef, useState } from "react";
import { Check, Search, X } from "lucide-react";
import { api, type Pet, type Photo } from "./api";
import Select from "./Select";
import PhotoTimeline, { type TimelineMonth } from "./PhotoTimeline";
import { durationLabel } from "./VideoPlayer";

export type PhotoPickerTarget = { kind: "pet" | "album" | "cover" | "album-cover"; id: string; name: string; species?: string };

export default function PhotoPicker({ target, pets, onClose, onAdded, onSavingChange, onCoverSelected }: {
  target: PhotoPickerTarget; pets: Pet[]; onClose: () => void; onAdded: (count: number) => void; onSavingChange: (saving: boolean) => void;
  onCoverSelected?: (photo: Photo) => void;
}) {
  const choosingCover = target.kind === "cover" || target.kind === "album-cover";
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [species, setSpecies] = useState(choosingCover ? "all" : target.species || "all");
  const [sourcePet, setSourcePet] = useState(target.kind === "cover" ? target.id : "");
  const [limit, setLimit] = useState(200);
  const [offset, setOffset] = useState(0);
  const [months, setMonths] = useState<{ scope: string; items: TimelineMonth[] } | null>(null);
  const [activeMonth, setActiveMonth] = useState("");
  const [result, setResult] = useState<{ scope: string; items: Photo[]; total: number } | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [chosenCover, setChosenCover] = useState<Photo | null>(null);
  const [members, setMembers] = useState<Set<string>>(new Set());
  const [membersReady, setMembersReady] = useState(target.kind !== "album");
  const [membersError, setMembersError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [retry, setRetry] = useState(0);
  const scroll = useRef<HTMLDivElement>(null);
  const more = useRef<HTMLButtonElement>(null);
  const videoIds = useRef(new Set<string>());
  const hasSelectedVideo = selected.some((id) => videoIds.current.has(id));
  const scope = JSON.stringify([search, species, sourcePet]);
  const photos = result?.scope === scope + ":" + offset ? result.items : [];
  const total = result?.scope === scope + ":" + offset ? result.total : 0;
  const timelineMonths = months?.scope === scope ? months.items : [];
  const isMember = (photo: Photo) => members.has(photo.id) || (target.kind === "pet" && photo.pets.some((pet) => pet.id === target.id));
  const available = photos.filter((photo) => !isMember(photo));
  useEffect(() => { setSpecies(choosingCover ? "all" : target.species || "all"); setSourcePet(target.kind === "cover" ? target.id : ""); }, [target.id, target.species, target.kind, choosingCover]);
  useEffect(() => { const timer = setTimeout(() => setSearch(query), 250); return () => clearTimeout(timer); }, [query]);
  useEffect(() => { setLimit(200); setOffset(0); setActiveMonth(""); scroll.current?.scrollTo({ top: 0 }); }, [scope]);
  const view = species === "cat" ? "cats" : species === "hedgehog" ? "hedgehogs" : target.kind === "album-cover" ? "all" : "gallery";
  const filters = new URLSearchParams({ view, q: search, pet_id: sourcePet, album_id: target.kind === "album-cover" ? target.id : "", sort: "desc" }).toString();
  useEffect(() => {
    let active = true;
    api<{ months: TimelineMonth[] }>("/photos/timeline?" + filters).then((data) => { if (active) setMonths({ scope, items: data.months }); }).catch(() => { if (active) setMonths(null); });
    return () => { active = false; };
  }, [filters, scope, retry]);
  useEffect(() => {
    if (target.kind !== "album") return;
    let active = true; setMembersError("");
    const load = async () => {
      const first = await api<{ items: Photo[]; total: number }>(`/photos?view=all&album_id=${encodeURIComponent(target.id)}&limit=500`);
      const rest = await Promise.all(Array.from({ length: Math.max(0, Math.ceil(first.total / 500) - 1) }, (_, index) =>
        api<{ items: Photo[] }>(`/photos?view=all&album_id=${encodeURIComponent(target.id)}&limit=500&offset=${(index + 1) * 500}`)));
      if (active) { setMembers(new Set([...first.items, ...rest.flatMap((page) => page.items)].map((photo) => photo.id))); setMembersReady(true); }
    };
    load().catch((err) => { if (active) setMembersError(err instanceof Error ? err.message : "无法读取回忆，请重试"); });
    return () => { active = false; };
  }, [target.id, target.kind, retry]);
  useEffect(() => {
    let active = true; setLoading(true); setError("");
    Promise.all(Array.from({ length: Math.ceil(limit / 500) }, (_, index) => api<{ items: Photo[]; total: number }>(
      "/photos?" + filters + "&" + new URLSearchParams({ offset: String(offset + index * 500), limit: String(Math.min(500, limit - index * 500)) })
    ))).then((pages) => {
      pages.flatMap((page) => page.items).forEach((photo) => { if (photo.media_type === "video") videoIds.current.add(photo.id); });
      if (active) setResult({ scope: scope + ":" + offset, total: pages[0].total, items: [...new Map(pages.flatMap((page) => page.items).map((photo) => [photo.id, photo])).values()] });
    }).catch((err) => { if (active) setError(err instanceof Error ? err.message : "照片加载失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scope, filters, offset, limit, retry]);
  const jump = (month: TimelineMonth) => {
    setOffset(month.offset); setLimit(200); setActiveMonth(month.month); scroll.current?.scrollTo({ top: 0 });
  };
  useEffect(() => {
    if (!more.current || loading || error || membersError || saving) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setLimit((value) => value + 200);
    }, { root: scroll.current, rootMargin: "200px" });
    observer.observe(more.current); return () => observer.disconnect();
  }, [photos.length, total, loading, error, membersError, saving]);
  const toggle = (id: string) => setSelected((previous) => previous.includes(id) ? previous.filter((value) => value !== id) : choosingCover ? [id] : [...previous, id]);
  return <div className="photo-picker">
    <div className="picker-toolbar">
      <p>{choosingCover ? <>从<strong>{target.name}</strong>的照片中选择一张作为封面。</> : <>从宠物图库多选照片，添加到<strong>{target.name}</strong>。原有归属会保留。</>}</p>
      <div className="picker-search-row"><label className="picker-search"><Search size={16} /><input aria-label={choosingCover ? "搜索封面照片" : "搜索待添加照片"} placeholder="搜索宠物、文件名或日期" value={query} onChange={(event) => setQuery(event.target.value)} disabled={saving} /></label>
        {!choosingCover && <Select aria-label="按宠物筛选待添加照片" value={sourcePet} disabled={saving} onChange={(event) => setSourcePet(event.target.value)}>
          <option value="">全部宠物</option>{pets.filter((pet) => species === "all" || pet.species === species).map((pet) => <option key={pet.id} value={pet.id}>{pet.name}</option>)}
        </Select>}
      </div>
      {!choosingCover && <div className="picker-selection-row"><div className="species-tabs">{[["all", "全部"], ["cat", "猫咪"], ["hedgehog", "刺猬"]].map(([value, label]) => <button key={value} className={species === value ? "active" : ""} disabled={saving} onClick={() => { setSpecies(value); setSourcePet(""); }}>{label}</button>)}</div>
        <button className="text-button" disabled={saving || !membersReady || !available.length} onClick={() => setSelected((previous) => available.every((photo) => previous.includes(photo.id)) ? previous.filter((id) => !available.some((photo) => photo.id === id)) : [...new Set([...previous, ...available.map((photo) => photo.id)])])}>{available.length && available.every((photo) => selected.includes(photo.id)) ? "取消本页选择" : "选择已加载照片"}</button>
      </div>}
    </div>
    <div className="picker-content">
    <div className="picker-scroll" ref={scroll} aria-label={choosingCover ? "可用封面照片" : "待添加的宠物照片"} aria-busy={loading} onScroll={() => {
      const root = scroll.current; if (!root) return;
      const top = root.getBoundingClientRect().top;
      const visible = Array.from(root.querySelectorAll<HTMLElement>(".picker-photo")).find((tile) => tile.getBoundingClientRect().bottom > top + 16);
      if (visible?.dataset.month) setActiveMonth(visible.dataset.month);
    }}>
      {offset > 0 && <button className="button previous-photo-window" disabled={loading || saving} onClick={() => { setOffset(Math.max(0, offset - 200)); setLimit(200); scroll.current?.scrollTo({ top: 0 }); }}>查看更近的照片</button>}
      {(error || membersError) && <p className="picker-error" role="alert">{error || membersError}<button className="text-button" onClick={() => setRetry((value) => value + 1)}>重试</button></p>}
      {!photos.length && loading && <p className="picker-empty" role="status">正在加载宠物图库…</p>}
      {!photos.length && !loading && !error && <p className="picker-empty">{choosingCover && !search ? "这个档案暂无照片，请先添加照片再设置封面" : search || sourcePet ? "没有找到匹配的照片" : "宠物图库中暂无可添加照片"}</p>}
      <div className="picker-photo-grid">{photos.map((photo) => {
        const added = isMember(photo), checked = selected.includes(photo.id);
        return <button key={photo.id} data-month={photo.taken_at?.slice(0, 7) || "unknown"} className={"picker-photo" + (checked ? " selected" : "") + (added ? " already-added" : "")} aria-label={added ? `已添加 ${photo.name}` : `选择照片 ${photo.name}`} aria-pressed={checked} disabled={saving || added || !membersReady} title={`${photo.taken_at?.slice(0, 10) || "未知日期"} · ${photo.name}`} onClick={() => { if (choosingCover) setChosenCover(photo); toggle(photo.id); }}>
          <img src={photo.thumb} alt={photo.name} loading="lazy" /><span className="picker-check">{(checked || added) && <Check size={14} />}</span>{added && <span className="picker-member-label">已添加</span>}
          {photo.media_type === "video" && <span className="video-duration">▶ {durationLabel(photo.duration)}</span>}
        </button>;
      })}</div>
      {total > offset + photos.length && <button ref={more} className="button load-more" disabled={loading || saving} onClick={() => setLimit((value) => value + 200)}>{loading ? "正在加载…" : "加载更多照片"}</button>}
    </div>
    {timelineMonths.length > 0 && <div className="picker-timeline"><span className="picker-current-date">{(activeMonth || photos[0]?.taken_at?.slice(0, 7) || timelineMonths[0].month).replace("-", "/")}</span><PhotoTimeline months={timelineMonths} activeMonth={activeMonth || photos[0]?.taken_at?.slice(0, 7) || timelineMonths[0].month} onJump={(month) => { if (!saving) jump(month); }} /></div>}
    </div>
    <div className="dialog-footer picker-footer"><div><span aria-live="polite">已选 {selected.length} {hasSelectedVideo ? "项" : "张"}</span>{selected.length > 0 && <button className="icon" aria-label="清空待添加选择" disabled={saving} onClick={() => setSelected([])}><X size={14} /></button>}</div>
      <button className="button subtle" disabled={saving} onClick={onClose}>取消</button>
      <button className="button primary" disabled={!selected.length || saving || !membersReady} onClick={async () => {
        setSaving(true); onSavingChange(true); setError(""); let completed = 0;
        const ids = selected.filter((id) => !members.has(id));
        try {
          if (choosingCover) {
            if (onCoverSelected && chosenCover) { onCoverSelected(chosenCover); return; }
            await api("/photos/action", { ids: [selected[0]], action: "cover", pet_id: target.id });
            onAdded(1); return;
          }
          for (let offset = 0; offset < ids.length; offset += 500) {
            const batch = ids.slice(offset, offset + 500);
            await api("/photos/action", { ids: batch, action: target.kind === "pet" ? "assign" : "album", [target.kind === "pet" ? "pet_id" : "album_id"]: target.id });
            completed += batch.length; setMembers((previous) => new Set([...previous, ...batch]));
            setSelected((previous) => previous.filter((id) => !batch.includes(id)));
          }
          onAdded(completed);
        } catch (err) { setError(`${completed ? `已添加 ${completed} 张，剩余照片未添加。` : ""}${err instanceof Error ? err.message : "添加失败，请重试"}`); }
        finally { setSaving(false); onSavingChange(false); }
      }}>{saving ? "正在保存…" : choosingCover ? onCoverSelected ? "使用这张照片" : "设为封面" : `添加 ${selected.length} ${hasSelectedVideo ? "项内容" : "张照片"}`}</button>
    </div>
  </div>;
}
