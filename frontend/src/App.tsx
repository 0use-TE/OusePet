import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type ReactNode,
} from "react";
import {
  Images,
  Cat,
  Heart,
  Folder,
  Plus,
  Search,
  Maximize,
  Minimize,
  Check,
  ChevronLeft,
  ChevronRight,
  X,
  Grid2X2,
  HardDrive,
  Users,
  Clock,
  ArrowUp,
  RefreshCw,
  Pause,
  Play,
  Album as AlbumIcon,
  Menu,
  Sparkles,
  Info,
  CheckCircle2,
  Settings as SettingsIcon,
  Trash2,
  Share2,
} from "lucide-react";
import Select from "./Select";
import PhotoTimeline, { type TimelineMonth } from "./PhotoTimeline";
import PhotoPicker from "./PhotoPicker";
import PetOrderList from "./PetOrderList";
import MemoryManager, { MemoryEditor } from "./MemoryManager";
import VideoPlayer, { durationLabel } from "./VideoPlayer";
import { ShareModal, ShareSettings, ShareLinks } from "./Sharing";
import {
  api,
  ApiError,
  type State,
  type Photo,
  type Browse,
  type Species,
  type Settings,
  type Pet,
  type Storage,
} from "./api";

const labels: Record<string, string> = {
  all: "图库",
  gallery: "宠物图库",
  cats: "猫咪",
  hedgehogs: "刺猬",
  favorites: "收藏",
  pets: "宠物档案",
  albums: "回忆",
  shares: "外链",
  storage: "存储管理",
};
function readRoute() {
  const params = new URLSearchParams(window.location.search);
  const requestedView = params.get("view") || (params.has("media") ? "all" : "gallery");
  const view = requestedView === "review" ? "gallery" : requestedView === "videos" ? "all" : requestedView;
  return {
    view: Object.hasOwn(labels, view) ? view : "gallery",
    pet: params.get("pet") || "",
    album: params.get("album") || "",
    media: requestedView === "videos" ? "video" : ["image", "video"].includes(params.get("media") || "") ? params.get("media")! : "all",
  };
}
const emptyState: State = {
  counts: {
    library: 0,
    all: 0,
    cats: 0,
    hedgehogs: 0,
    favorites: 0,
    review: 0,
  },
  pets: [],
  albums: [],
  storages: [],
  jobs: [],
};
function Hedgehog({ size = 20 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m3 15 1-5 3 1 1-5 3 2 3-4 2 4 4-1-1 4 3 3-3 4H6l-3-3Z" />
      <path d="m14 18 2-6 6 3M7 18v2m10-2v2" />
      <circle cx="18" cy="14" r=".6" fill="currentColor" />
    </svg>
  );
}
function Modal({
  title,
  children,
  onClose,
  wide = false,
  className = "",
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      className={`${wide ? "modal wide" : "modal"} ${className}`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(e) => {
        if (e.target === ref.current && className !== "settings-modal") onClose();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button className="icon" aria-label="关闭" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function App() {
  const [editingPet, setEditingPet] = useState<Pet | null>(null);
  const [draftCover, setDraftCover] = useState<Photo | null>(null);
  const workspace = useRef<HTMLElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const update = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);
  const photoWindow = useRef(200);
  const photoOffset = useRef(0);
  const [timelineResult, setTimelineResult] = useState<{ key: string; months: TimelineMonth[]; total: number } | null>(null);
  const [visibleMonth, setVisibleMonth] = useState("");
  const morePhotosButton = useRef<HTMLButtonElement>(null);
  const morePhotosScope = useRef("");
  const morePhotosRequest = useRef(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [morePhotosError, setMorePhotosError] = useState(false);
  const photoRequest = useRef(0);
  const [state, setState] = useState<State>(emptyState),
    [ready, setReady] = useState(false),
    [view, setView] = useState(() => readRoute().view),
    [petId, setPetId] = useState(() => readRoute().pet),
    [albumId, setAlbumId] = useState(() => readRoute().album),
    [media, setMedia] = useState(() => readRoute().media),
    [query, setQuery] = useState(""),
    [search, setSearch] = useState(""),
    [ascending, setAscending] = useState(false),
    [photoResult, setPhotoResult] = useState<{ key: string; items: Photo[]; total: number; start?: number } | null>(null),
    [photoError, setPhotoError] = useState<{ key: string; message: string } | null>(null),
    [selected, setSelected] = useState<string[]>([]),
    [selectedPets, setSelectedPets] = useState<string[]>([]),
    [petOrder, setPetOrder] = useState<string[]>([]),
    [mergePetIds, setMergePetIds] = useState<string[]>([]),
    [light, setLight] = useState<Photo | null>(null),
    [info, setInfo] = useState(true),
    [modal, setModal] = useState(""),
    [settings, setSettings] = useState<Settings | null>(null),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState(false),
    [navOpen, setNavOpen] = useState(false),
    [name, setName] = useState(""),
    [species, setSpecies] = useState<Species>("cat"),
    [choice, setChoice] = useState(""),
    [mergeConflict, setMergeConflict] = useState<{ target: string; photos: { id: string; name: string }[] } | null>(null),
    [removingStorage, setRemovingStorage] = useState<Storage | null>(null),
    [resetConfirmation, setResetConfirmation] = useState(""),
    [settingsTab, setSettingsTab] = useState("folders"),
    [storageFromSettings, setStorageFromSettings] = useState(false),
    [folderPath, setFolderPath] = useState(""),
    [dirs, setDirs] = useState<{ name: string; path: string }[]>([]),
    [parent, setParent] = useState<string | null>(null),
    [browse, setBrowse] = useState<Browse | null>(null),
    [browseId, setBrowseId] = useState(""),
    [browseSelected, setBrowseSelected] = useState<string[]>([]),
    [gridSize, setGridSize] = useState(() =>
      Number(localStorage.getItem("ousepet-grid") || 220),
    );
  const closeStorageModal = () => { setModal(storageFromSettings ? "settings" : ""); setStorageFromSettings(false); };
  const fail = useCallback(
    (error: unknown) =>
      setToast(error instanceof Error ? error.message : "操作未完成"),
    [],
  );
  useEffect(() => {
    workspace.current?.scrollTo({ top: 0, left: 0 });
  }, [view, petId, albumId, media, search, ascending]);
  useEffect(() => {
    const restore = () => {
      const route = readRoute();
      setView(route.view);
      setPetId(route.pet);
      setAlbumId(route.album);
      setMedia(route.media);
      setQuery("");
      setSelected([]);
      setLight(null);
      setNavOpen(false);
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  const refreshState = useCallback(async () => {
    const s = await api<State>("/state");
    setState(s);
    setReady(true);
    return s;
  }, []);
  useEffect(() => {
    if (modal !== "settings") return;
    let alive = true;
    const load = () =>
      api<Settings>("/settings")
        .then((value) => {
          if (alive) setSettings(value);
        })
        .catch(fail);
    load();
    const timer = setInterval(load, 1200);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [modal, fail]);
  const photoUrl = useCallback(
    (offset = 0, limit = 200) =>
      "/photos?" +
      new URLSearchParams({
        view: ["pets", "albums", "storage", "shares"].includes(view) ? "gallery" : view,
        q: search,
        pet_id: petId,
        album_id: albumId,
        media: view === "all" && !petId && !albumId ? media : "all",
        sort: ascending ? "asc" : "desc",
        offset: String(offset),
        limit: String(limit),
      }),
    [view, search, petId, albumId, ascending, media],
  );
  const photoView = !["pets", "albums", "storage", "shares"].includes(view);
  const photoScope = photoUrl();
  const currentPhotoScope = useRef("");
  currentPhotoScope.current = photoView ? photoScope : "";
  const photos = photoResult?.key === photoScope ? photoResult.items : [];
  const timelineMonths = timelineResult?.key === photoScope ? timelineResult.months : [];
  const total = photoResult?.key === photoScope ? photoResult.total : timelineResult?.key === photoScope ? timelineResult.total : 0;
  const loadedStart = photoResult?.key === photoScope ? photoResult.start || 0 : photoOffset.current;
  const loadingPhotos = photoView && photoResult?.key !== photoScope && photoError?.key !== photoScope;
  const failedPhotos = photoView && photoResult?.key !== photoScope && photoError?.key === photoScope;
  const refreshPhotos = useCallback(async () => {
    if (!photoView || currentPhotoScope.current !== photoScope) return;
    const request = ++photoRequest.current;
    const count = photoWindow.current;
    const start = photoOffset.current;
    setPhotoError(null);
    try {
    const pages = await Promise.all(
      Array.from({ length: Math.ceil(count / 500) }, (_, index) =>
        api<{ items: Photo[]; total: number }>(
          photoUrl(start + index * 500, Math.min(500, count - index * 500)),
        ),
      ),
    );
    if (request !== photoRequest.current || currentPhotoScope.current !== photoScope) return;
    setPhotoResult({ key: photoScope, items: [
      ...new Map(
        pages.flatMap((page) => page.items).map((photo) => [photo.id, photo]),
      ).values(),
    ], total: pages[0].total, start });
    } catch (error) {
      if (request !== photoRequest.current || currentPhotoScope.current !== photoScope) return;
      setPhotoError({ key: photoScope, message: error instanceof Error ? error.message : "照片加载失败" });
      throw error;
    }
  }, [photoUrl, photoScope, photoView]);
  useEffect(() => {
    refreshState().catch(fail);
  }, [refreshState, fail]);
  useEffect(() => {
    photoWindow.current = 200;
    photoOffset.current = 0;
    setVisibleMonth("");
    morePhotosScope.current = "";
    morePhotosRequest.current += 1;
    setLoadingMore(false); setMorePhotosError(false);
    refreshPhotos().catch(fail);
    setSelected([]);
  }, [refreshPhotos, fail]);
  useEffect(() => {
    if (!photoView) return;
    let cancelled = false;
    api<{ months: TimelineMonth[]; total: number }>(photoUrl().replace("/photos?", "/photos/timeline?")).then((result) => {
      if (!cancelled && currentPhotoScope.current === photoScope) setTimelineResult({ key: photoScope, ...result });
    }).catch(() => { if (!cancelled) setTimelineResult(null); });
    return () => { cancelled = true; };
  }, [photoScope, photoUrl, photoView, state.counts.all, state.counts.library]);
  const loadMorePhotos = useCallback(async () => {
    if (morePhotosScope.current === photoScope || currentPhotoScope.current !== photoScope || !photoView || total <= loadedStart + photos.length) return;
    morePhotosScope.current = photoScope;
    const request = ++morePhotosRequest.current;
    setLoadingMore(true); setMorePhotosError(false);
    const refreshVersion = photoRequest.current;
    try {
      const next = await api<{ items: Photo[]; total: number }>(photoUrl(loadedStart + photos.length, 200));
      if (request !== morePhotosRequest.current || currentPhotoScope.current !== photoScope) return;
      if (refreshVersion !== photoRequest.current) return;
      photoWindow.current = Math.max(photoWindow.current, photos.length + next.items.length);
      setPhotoResult((previous) => previous?.key === photoScope ? {
        ...previous, total: next.total, items: [...new Map([...previous.items, ...next.items].map((photo) => [photo.id, photo])).values()],
      } : previous);
    }
    catch {
      if (request === morePhotosRequest.current && currentPhotoScope.current === photoScope) setMorePhotosError(true);
    } finally {
      if (request === morePhotosRequest.current) { morePhotosScope.current = ""; setLoadingMore(false); }
    }
  }, [photoScope, photoView, total, photos.length, loadedStart, photoUrl]);
  const jumpToOffset = (offset: number) => {
    photoOffset.current = offset; photoWindow.current = 200;
    morePhotosRequest.current += 1; morePhotosScope.current = "";
    setLoadingMore(false); setMorePhotosError(false); setPhotoResult(null); setSelected([]);
    workspace.current?.scrollTo({ top: 0, left: 0 });
    refreshPhotos().catch(fail);
  };
  const jumpToMonth = (month: TimelineMonth) => {
    const existing = workspace.current?.querySelector<HTMLElement>(`[data-photo-month="${month.month}"]`);
    setVisibleMonth(month.month);
    if (existing && workspace.current) workspace.current.scrollTo({ top: existing.getBoundingClientRect().top - workspace.current.getBoundingClientRect().top + workspace.current.scrollTop - 16, left: 0 });
    else jumpToOffset(month.offset);
  };
  useEffect(() => {
    const panel = workspace.current;
    if (!panel || !photoView || !photos.length) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const top = panel.getBoundingClientRect().top + 90;
      let month = "";
      for (const section of panel.querySelectorAll<HTMLElement>("[data-photo-month]")) {
        if (month && section.getBoundingClientRect().top > top) break;
        month = section.dataset.photoMonth || "";
      }
      if (month) setVisibleMonth(month);
    };
    const scroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    panel.addEventListener("scroll", scroll, { passive: true }); update();
    return () => { panel.removeEventListener("scroll", scroll); cancelAnimationFrame(frame); };
  }, [photoView, photos]);
  useEffect(() => {
    const button = morePhotosButton.current;
    if (!button || loadingMore || morePhotosError || modal || light || total <= loadedStart + photos.length) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadMorePhotos();
    }, { root: workspace.current, rootMargin: "0px 0px 1200px 0px" });
    observer.observe(button);
    return () => observer.disconnect();
  }, [loadMorePhotos, loadingMore, morePhotosError, modal, light, total, photos.length, loadedStart]);
  useEffect(() => {
    const t = setTimeout(() => setSearch(query), 250);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(t);
  }, [toast]);
  const discovering = ["running", "queued"].includes(state.discovery?.status || "");
  const resetting = ["queued", "clearing"].includes(state.reset_task?.status || "");
  const active = resetting || discovering || state.jobs.some((j) =>
    ["running", "queued", "paused"].includes(j.status),
  );
  useEffect(() => {
    const t = setInterval(() => {
      refreshState()
        .then((next) => {
          if (active || next.counts.library !== state.counts.library || next.counts.all !== state.counts.all)
            return refreshPhotos();
        })
        .catch(fail);
    }, active ? 1600 : 10000);
    return () => clearInterval(t);
  }, [active, refreshState, refreshPhotos, fail, state.counts.library, state.counts.all]);
  const refresh = async () => {
    await Promise.all([refreshState(), refreshPhotos()]);
  };
  const removeJobHistory = async (id?: string) => {
    setBusy(true);
    try {
      await api(`/jobs/${id || "history"}`, {}, "DELETE");
      await refreshState();
      setToast(id ? "任务记录已删除" : "历史任务已清空，进行中的任务已保留");
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  };
  const go = useCallback((target: string, p = "", a = "") => {
    setSelectedPets([]);
    const url = new URL(window.location.href);
    url.searchParams.delete("media"); setMedia("all");
    for (const [key, value] of [["view", target === "gallery" ? "" : target], ["pet", p], ["album", a]]) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    if (url.href !== window.location.href) window.history.pushState(null, "", url);
    setView(target);
    setPetId(p);
    setAlbumId(a);
    setSelected([]);
    setNavOpen(false);
    setQuery("");
  }, []);
  const action = async (
    kind: string,
    ids = selected,
    extra: Record<string, string> = {},
  ) => {
    if (!ids.length) return;
    try {
      await api("/photos/action", { ids, action: kind, ...extra });
      await refresh();
      if (light && ids.includes(light.id)) {
        if (kind === "hide" || kind === "reject") setLight(null);
        else
          setLight({
            ...light,
            favorite:
              kind === "favorite"
                ? true
                : kind === "unfavorite"
                  ? false
                  : light.favorite,
            pets: light.pets,
          });
      }
      setSelected([]);
    } catch (e) {
      fail(e);
    }
  };
  const openDirectories = async (path = "") => {
    try {
      setBusy(true);
      const d = await api<{
        path: string;
        parent: string | null;
        directories: { name: string; path: string }[];
      }>("/directories?path=" + encodeURIComponent(path));
      setFolderPath(d.path);
      setDirs(d.directories);
      setParent(d.parent);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const addStorage = () => {
    setName("");
    setModal("directory");
    openDirectories();
  };
  const loadBrowse = async (id: string, path = "") => {
    try {
      setBusy(true);
      const d = await api<Browse>(
        `/storages/${id}/browse?path=${encodeURIComponent(path)}`,
      );
      setBrowse(d);
      setBrowseId(id);
      setBrowseSelected([]);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const openBrowse = () => {
    if (petId || albumId) { setSelected([]); setModal("photo-picker"); return; }
    if (!state.storages.length) {
      addStorage();
      return;
    }
    setChoice(state.pets[0]?.id || "cat");
    setModal("browse");
    setBrowse(null);
    loadBrowse(state.storages[0].id);
  };
  const toggle = (id: string) =>
    setSelected((s) =>
      s.includes(id) ? s.filter((v) => v !== id) : [...s, id],
    );
  const togglePet = (id: string) => setSelectedPets((previous) => previous.includes(id) ? previous.filter((value) => value !== id) : [...previous, id]);
  const editPet = (pet: Pet) => { setDraftCover(null); setEditingPet(pet); setName(pet.unnamed ? "" : pet.name); setSpecies(pet.species as Species); setModal("rename-pet"); };
  const selectedPetRecords = state.pets.filter((pet) => selectedPets.includes(pet.id));
  const selectedPetSpecies = new Set(selectedPetRecords.map((pet) => pet.species));
  const mergePetRecords = mergePetIds.map((id) => state.pets.find((pet) => pet.id === id)).filter((pet): pet is Pet => Boolean(pet));
  useEffect(() => {
    setSelectedPets((previous) => { const next = previous.filter((id) => state.pets.some((pet) => pet.id === id)); return next.length === previous.length ? previous : next; });
  }, [state.pets]);
  const title = petId
    ? state.pets.find((p) => p.id === petId)?.name
    : albumId
      ? state.albums.find((a) => a.id === albumId)?.name
      : labels[view];
  const currentJob = state.jobs.find((j) =>
    ["running", "queued", "paused"].includes(j.status),
  );
  const floatingTask = (resetting ? { status: "queued", storage_name: "正在清空整理数据，准备重新识别", total: 0, processed: 0 } : null)
    || state.jobs.find((job) => job.status === "running")
    || (state.discovery?.status === "running" ? { ...state.discovery, storage_name: "发现相似宠物" } : currentJob)
    || (discovering && state.discovery ? { ...state.discovery, storage_name: "发现相似宠物" } : null);
  const floatingPercent = floatingTask?.total
    ? Math.min(100, Math.max(0, Math.floor(floatingTask.processed / floatingTask.total * 100))) : 0;
  const floatingLabel = floatingTask
    ? `${floatingTask.storage_name}：${floatingTask.status === "paused" ? "已暂停" : floatingTask.status === "queued" ? "等待处理" : `${floatingTask.processed} / ${floatingTask.total} 张，${floatingPercent}%`}，点击查看任务`
    : "";
  const moveLight = useCallback(
    (delta: number) => {
      if (!light) return;
      const index = photos.findIndex((p) => p.id === light.id);
      const next = photos[index + delta];
      if (next) setLight(next);
    },
    [light, photos],
  );
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.repeat || modal || document.querySelector("dialog[open]")) return;
      const editing = (e.target as HTMLElement).closest("input,select,textarea,video,[contenteditable=true],[role=listbox]");
      if (e.key === "Escape") {
        if (document.fullscreenElement) return;
        if (light) setLight(null);
        else if (navOpen) setNavOpen(false);
        else if (selectedPets.length) setSelectedPets([]);
        else if (selected.length) setSelected([]);
        else if (query || search) { setQuery(""); setSearch(""); }
        else if (editing) return;
        else if (petId) go("pets");
        else if (albumId) go("albums");
        else if (["cats", "hedgehogs"].includes(view)) go("gallery");
        else return;
        e.preventDefault();
        return;
      }
      if (editing) return;
      if (light) {
        if (e.key === "ArrowRight") { e.preventDefault(); moveLight(1); }
        if (e.key === "ArrowLeft") { e.preventDefault(); moveLight(-1); }
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && view === "pets") {
        e.preventDefault(); setSelectedPets(state.pets.map((pet) => pet.id));
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && photoView && photos.length) {
        e.preventDefault(); setSelected(photos.map((photo) => photo.id));
      } else if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault(); document.querySelector<HTMLInputElement>(".search input")?.focus();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [light, moveLight, modal, navOpen, selected.length, selectedPets.length, state.pets, query, search, petId, albumId, view, photos, photoView, go]);
  const lightOpen = Boolean(light);
  useEffect(() => {
    if (!lightOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const root = document.querySelector<HTMLElement>(".lightbox");
    root?.querySelector<HTMLButtonElement>("button")?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !root) return;
      const controls = [
        ...root.querySelectorAll<HTMLElement>("button:not(:disabled)"),
      ];
      const first = controls[0],
        last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", trap);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", trap);
      previous?.focus();
    };
  }, [lightOpen]);
  const groups = photos.reduce<{ date: string; photos: Photo[] }[]>(
    (acc, p) => {
      const date = p.taken_at?.slice(0, 10) || "日期未知";
      if (acc.at(-1)?.date === date) acc.at(-1)!.photos.push(p);
      else acc.push({ date, photos: [p] });
      return acc;
    },
    [],
  );
  const petChoices = (
    <>
      <optgroup label="宠物档案">
        {state.pets.map((p) => (
          <option value={p.id} key={p.id}>
            {p.name} · {p.species === "cat" ? "猫咪" : "刺猬"}
          </option>
        ))}
      </optgroup>
      <optgroup label="按物种添加">
        <option value="cat">猫咪</option>
        <option value="hedgehog">刺猬</option>
      </optgroup>
    </>
  );
  const choiceExtra = (): Record<string, string> =>
    ["cat", "hedgehog"].includes(choice)
      ? { species: choice }
      : { pet_id: choice };
  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className="mobile-menu icon"
          aria-label="导航"
          onClick={() => setNavOpen(!navOpen)}
        >
          <Menu />
        </button>
        <button className="brand" onClick={() => go("all")}>
          <img src="/logo.png" alt="" />
          <strong>有宠相簿</strong>
        </button>
        <div className="search">
          <span className="search-orb">
            <Sparkles size={16} />
          </span>
          <Search size={17} className="search-mobile" />
          <input
            aria-label="搜索照片"
            placeholder="搜索宠物、文件名或拍摄日期"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query ? (
            <button
              className="icon small"
              aria-label="清除搜索"
              onClick={() => setQuery("")}
            >
              <X size={16} />
            </button>
          ) : null}
        </div>
        <div className="top-actions">
          <button
            className={"icon " + (currentJob || discovering ? "working" : "")}
            aria-label="扫描任务"
            onClick={() => setModal("tasks")}
          >
            <Clock size={20} />
            {(currentJob || discovering) && <i />}
          </button>
          <button
            className="icon fullscreen-button"
            aria-label={fullscreen ? "退出全屏" : "全屏显示"}
            title={fullscreen ? "退出全屏" : "全屏显示"}
            onClick={() => {
              const request = document.fullscreenElement
                ? document.exitFullscreen()
                : document.documentElement.requestFullscreen();
              request.catch(fail);
            }}
          >
            {fullscreen ? <Minimize size={20} /> : <Maximize size={20} />}
          </button>
          <button
            className="icon"
            aria-label="设置"
            onClick={() => setModal("settings")}
          >
            <SettingsIcon size={20} />
          </button>
        </div>
      </header>
      <aside className={"sidebar " + (navOpen ? "open" : "")}>
        <nav>
          {[
            ["all", Images],
            ["gallery", Sparkles],
            ["favorites", Heart],
            ["divider", null],
            ["pets", Users],
            ["albums", AlbumIcon],
            ["shares", Share2],
          ].map(([key, Icon]) =>
            key === "divider" ? (
              <div className="nav-divider" key="divider" />
            ) : (
              <button
                key={String(key)}
                className={
                  "nav-item " +
                  ((view === key || (key === "gallery" && ["cats", "hedgehogs"].includes(view))) && !petId && !albumId ? "active" : "")
                }
                title={labels[key as string]}
                aria-label={labels[key as string]}
                onClick={() => go(key as string)}
              >
                {Icon && <Icon size={19} />}
                <span>{labels[key as string]}</span>
              </button>
            ),
          )}
        </nav>
        <div className="sidebar-bottom">
          <button
            className={"nav-item " + (view === "storage" ? "active" : "")}
            onClick={() => go("storage")}
          >
            <HardDrive size={19} />
            <span>存储管理</span>
          </button>
        </div>
      </aside>
      {navOpen && (
        <div className="nav-backdrop" onClick={() => setNavOpen(false)} />
      )}
      <main ref={workspace} className={"workspace" + (floatingTask ? " has-floating-task" : "") + (photoView && timelineMonths.length ? " has-photo-timeline" : "")} tabIndex={-1} aria-label="图库内容" aria-busy={loadingPhotos}>
        <div className="page-heading">
          <div className="heading-title">
            {(petId || albumId) && (
              <button
                className="icon"
                aria-label="返回"
                onClick={() => go(petId ? "pets" : "albums")}
              >
                <ChevronLeft />
              </button>
            )}
            <div>
              <h1>{title}</h1>
              <span className="subtitle">
                {view === "storage"
                  ? `${state.storages.length} 个存储位置`
                  : view === "pets"
                    ? `${state.pets.length} 位小伙伴`
                    : view === "albums"
                      ? `${state.albums.length} 个回忆`
                      : view === "shares" ? "管理已分享的回忆" : loadingPhotos ? "正在加载…" : failedPhotos ? "内容加载失败" : state.counts.videos ? `${total} 项内容` : `${total} 张照片`}
              </span>
            </div>
          </div>
          <div className="heading-actions">
            {view === "shares" && <button className="button subtle" onClick={() => { setSettingsTab("sharing"); setModal("settings"); }}><SettingsIcon size={16} />分享设置</button>}
            {view === "all" && !petId && !albumId && <div className="filter-tabs" role="group" aria-label="媒体类型筛选">
              {[["all", "全部"], ["image", "照片"], ["video", "视频"]].map(([value, label]) => <button key={value} className={media === value ? "chosen" : ""} aria-pressed={media === value} onClick={() => {
                setMedia(value); const url = new URL(window.location.href); url.searchParams.set("view", "all");
                if (value === "all") url.searchParams.delete("media"); else url.searchParams.set("media", value);
                if (url.href !== window.location.href) window.history.pushState(null, "", url);
              }}>{label}</button>)}
            </div>}
            {view === "pets" && state.pets.length > 1 && <button className="button subtle" onClick={() => {
              setPetOrder(state.pets.map((pet) => pet.id)); setModal("pet-order");
            }}><ArrowUp size={16} />排序</button>}
            {!petId && !albumId && !["all", "pets", "albums", "storage", "videos", "shares"].includes(view) && (
              <div className="filter-tabs" role="group" aria-label="物种筛选">
                {[["gallery", "全部"], ["cats", "猫咪"], ["hedgehogs", "刺猬"]].map(([target, label]) => (
                  <button key={target} className={view === target ? "chosen" : ""} onClick={() => go(target)}>{label}</button>
                ))}
              </div>
            )}
            {view === "pets" && <button className="button subtle" disabled={discovering}
              onClick={() => api("/discovery/start", {}).then(refreshState).catch(fail)}>
              <Sparkles size={17} />{discovering ? "发现中" : "发现宠物"}
            </button>}
            {albumId && <button className="button subtle" onClick={() => setModal("memory-editor")}>编辑回忆</button>}
            {albumId && <button className="button subtle" onClick={() => setModal("memory-share")}><Share2 size={16} />分享</button>}
            {petId && <button className="button subtle" onClick={() => {
              const pet = state.pets.find((p) => p.id === petId);
              if (pet) editPet(pet);
            }}>编辑档案</button>}

            {!["storage", "pets", "albums", "shares"].includes(view) && (
              <button
                className="icon sort-button"
                title={ascending ? "最早拍摄在前" : "最新拍摄在前"}
                aria-label="切换照片排序"
                onClick={() => setAscending(!ascending)}
              >
                <ArrowUp
                  size={18}
                  style={{ transform: ascending ? "none" : "rotate(180deg)" }}
                />
              </button>
            )}
            {view !== "shares" && <button
              className="button primary"
              onClick={() => {
                if (petId || albumId) openBrowse();
                else if (view === "storage" || view === "all" || view === "videos") addStorage();
                else if (view === "pets") {
                  setName("");
                  setSpecies("cat");
                  setModal("pet");
                } else if (view === "albums") {
                  setName("");
                  setModal("album");
                } else openBrowse();
              }}
            >
              <Plus size={17} />
              <span>
                {petId || albumId ? "添加照片" : view === "storage" || view === "all" || view === "videos"
                  ? "添加存储"
                  : view === "pets"
                    ? "创建档案"
                    : view === "albums"
                      ? "创建回忆"
                      : "添加照片"}
              </span>
            </button>}
          </div>
        </div>
        {view === "shares" ? <ShareLinks albums={state.albums} /> : view === "storage" ? (
          <div className="storage-list">
            {state.storages.map((s) => (
              <article className="storage-card" key={s.id}>
                <div className="storage-symbol">
                  <HardDrive size={28} />
                </div>
                <div className="storage-details">
                  <h3>{s.name}</h3>
                  <p>{s.path}</p>
                  <span>
                    {s.count} 张宠物照片 · 已索引 {s.indexed} 张
                  </span>
                </div>
                <div className="storage-actions">
                  <button
                    className="button subtle auto-scan-toggle"
                    role="switch"
                    aria-label={s.name + "自动增量扫描"}
                    aria-checked={Boolean(s.auto_scan)}
                    title="每分钟检查新增或修改的照片，只处理变化的文件"
                    onClick={() => api(`/storages/${s.id}`, { auto_scan: !s.auto_scan }, "PATCH")
                      .then(refreshState).catch(fail)}
                  >
                    自动增量：{s.auto_scan ? "开" : "关"}
                  </button>
                  <button
                    className="button subtle"
                    onClick={() => {
                      setModal("browse");
                      setChoice(state.pets[0]?.id || "cat");
                      loadBrowse(s.id);
                    }}
                  >
                    浏览照片
                  </button>
                  <button
                    className="icon"
                    aria-label={"扫描" + s.name}
                    onClick={() =>
                      api(`/storages/${s.id}/scan`, {})
                        .then(refresh)
                        .catch(fail)
                    }
                  >
                    <RefreshCw size={19} />
                  </button>
                  <button className="button subtle" aria-label={"移除存储" + s.name} onClick={() => { setRemovingStorage(s); setModal("remove-storage"); }}>
                    <Trash2 size={15} />移除
                  </button>
                </div>
              </article>
            ))}
            {!state.storages.length && (
              <Empty
                icon={<HardDrive />}
                title="添加你的照片存储位置"
                text="选择猫咪和刺猬照片所在的文件夹。"
                action="选择文件夹"
                onClick={addStorage}
              />
            )}
          </div>
        ) : view === "pets" ? (
          <>
          {selectedPets.length > 0 && <div className="pet-selection-bar" role="region" aria-label="宠物多选操作">
            <button className="icon" aria-label="退出宠物多选" onClick={() => setSelectedPets([])}><X size={18} /></button>
            <strong>已选 {selectedPets.length} 个宠物</strong>
            <button onClick={() => setSelectedPets(state.pets.map((pet) => pet.id))}>全选</button>
            <button className="button primary" disabled={selectedPetRecords.length < 2 || selectedPetSpecies.size !== 1} title={selectedPetSpecies.size > 1 ? "请先在编辑档案中统一种类" : "将选中的档案合并为一个"} onClick={() => {
              const target = [...selectedPetRecords].sort((a,b) => Number(Boolean(a.unnamed)) - Number(Boolean(b.unnamed)) || b.count - a.count)[0];
              setMergePetIds([...selectedPets]); setChoice(target.id); setMergeConflict(null); setModal("merge-pet");
            }}>合并宠物</button>
            {selectedPetSpecies.size > 1 && <span>不同种类请先编辑更正</span>}
          </div>}
          <div className="collection-grid">
            {state.pets.map((p) => (
              <article className={"collection-card pet-card" + (selectedPets.includes(p.id) ? " pet-selected" : "")} data-pet-id={p.id} key={p.id}>
              <button className="pet-select" aria-label={"选择档案" + p.name} aria-pressed={selectedPets.includes(p.id)} onClick={() => togglePet(p.id)}>{selectedPets.includes(p.id) && <Check size={14} />}</button>
              <button
                className="pet-open"
                onClick={() =>
                  selectedPets.length ? togglePet(p.id) : go(p.species === "cat" ? "cats" : "hedgehogs", p.id)
                }
              >
                <div className="collection-cover">
                  {p.cover ? (
                    <img src={p.cover} alt={p.name} />
                  ) : (
                    <div className="cover-placeholder">
                      {p.species === "cat" ? (
                        <Cat size={60} />
                      ) : (
                        <Hedgehog size={64} />
                      )}
                    </div>
                  )}
                  <span className="species-badge">
                    {p.species === "cat" ? (
                      <Cat size={14} />
                    ) : (
                      <Hedgehog size={14} />
                    )}{" "}
                    {p.species === "cat" ? "猫咪" : "刺猬"}
                  </span>
                </div>
                <div className="collection-caption">
                  <h3>{p.name}</h3>
                  <span>{p.video_count ? `${p.count} 项 · ${p.video_count} 个视频` : `${p.count} 张照片`}{p.unnamed ? " · 待命名" : ""}</span>
                  <ChevronRight size={18} />
                </div>
              </button>
              {!selectedPets.length && <div className="pet-card-actions">
                <button className="button subtle" aria-label={"编辑" + p.name} onClick={() => editPet(p)}>编辑</button>
                <button className="button subtle delete-pet-button" aria-label={"删除" + p.name} onClick={() => {
                  setEditingPet(p); setModal("delete-pet");
                }}><Trash2 size={14} />删除</button>
              </div>}
              </article>
            ))}
          </div>
          </>
        ) : view === "albums" ? (
          <>
            {state.albums.length ? (
              <MemoryManager albums={state.albums} pets={state.pets} open={(id) => go("gallery", "", id)} changed={() => { refresh().catch(fail); }} />
            ) : (
              <Empty
                icon={<AlbumIcon />}
                title="把喜欢的时光放在一起"
                text="为日常、旅行或特别的一天创建回忆。"
                action="创建回忆"
                onClick={() => {
                  setName("");
                  setModal("album");
                }}
              />
            )}
          </>
        ) : (
          <>
            {!petId && !albumId && view !== "all" && view !== "videos" && (
              <div className="filter-row">
                <div className="pet-shortcuts" role="region" aria-label="按宠物筛选" tabIndex={0}>
                  {state.pets
                    .filter(
                      (p) =>
                        view === "gallery" ||
                        view === "favorites" ||
                        (view === "cats"
                          ? p.species === "cat"
                          : p.species === "hedgehog"),
                    )
                    .map((p) => (
                      <button
                        key={p.id}
                        title={p.name}
                        onClick={() =>
                          go(p.species === "cat" ? "cats" : "hedgehogs", p.id)
                        }
                      >
                        {p.cover ? (
                          <img src={p.cover} alt="" />
                        ) : p.species === "cat" ? (
                          <Cat size={16} />
                        ) : (
                          <Hedgehog size={16} />
                        )}
                        <span>{p.name}</span>
                      </button>
                    ))}
                </div>
              </div>
            )}
            {selected.length > 0 && (
              <div className="selection-bar">
                <button
                  className="icon"
                  aria-label="取消选择"
                  onClick={() => setSelected([])}
                >
                  <X size={18} />
                </button>
                <strong>已选 {selected.length} 张</strong>
                <button onClick={() => action("favorite")}>
                  <Heart size={17} />
                  收藏
                </button>
                <button
                  onClick={() => {
                    setChoice(state.pets[0]?.id || "cat");
                    setModal("assign");
                  }}
                >
                  <Users size={17} />
                  添加到宠物
                </button>
                <button
                  onClick={() => {
                    setChoice(state.albums[0]?.id || "");
                    setModal("add-album");
                  }}
                >
                  <AlbumIcon size={17} />
                  加入回忆
                </button>
                {petId && <button className="selection-remove" onClick={() => action("unassign", selected, { pet_id: petId })}>移出此宠物</button>}
                {albumId && <button className="selection-remove" onClick={() => action("remove_album", selected, { album_id: albumId })}>移出回忆</button>}
                {view !== "all" && view !== "videos" && !albumId && (
                  <button
                    onClick={() => action("reject")}
                    className="selection-remove"
                  >
                    不是宠物
                  </button>
                )}
              </div>
            )}
            {loadingPhotos ? (
              <div className="photo-loading" role="status"><RefreshCw size={22} className="spin" /><span>正在加载照片…</span></div>
            ) : failedPhotos ? (
              <div className="photo-loading" role="alert"><span>{photoError?.message}</span><button className="button subtle" onClick={() => refreshPhotos().catch(fail)}>重试加载</button></div>
            ) : !photos.length ? (
              ready && !state.storages.length && !petId && !albumId ? (
                <Empty
                  icon={<img src="/logo.png" alt="" />}
                  title="从一处照片开始"
                  text="添加照片所在的存储文件夹，开始浏览你的照片。"
                  action="选择照片文件夹"
                  onClick={addStorage}
                />
              ) : (
                <Empty
                  icon={
                    view === "favorites" ? (
                      <Heart />
                    ) : (
                      <Images />
                    )
                  }
                  title={
                    search
                      ? "没有找到相关照片"
                      : view === "favorites"
                        ? "收藏喜欢的瞬间"
                          : view === "videos" ? "这里还没有视频" : view === "all"
                            ? "这里还没有照片"
                            : "这里将收集宠物的日常"
                  }
                  text={
                    search
                      ? "换个名字或日期试试。"
                      : petId ? "从宠物图库中多选照片，添加到这个宠物档案。" : albumId ? "从宠物图库中多选照片，加入当前回忆。" : view === "all"
                          ? "添加照片所在的存储文件夹。"
                          : "也可以从存储中选择照片，添加到宠物图库。"
                  }
                  action={
                    search
                      ? undefined
                      : view === "all"
                        ? "添加存储"
                        : "添加照片"
                  }
                  onClick={petId || albumId ? openBrowse : ["all", "videos"].includes(view) ? addStorage : openBrowse}
                />
              )
            ) : (
              <div className="timeline">
                {loadedStart > 0 && <button className="button previous-photo-window" onClick={() => jumpToOffset(Math.max(0, loadedStart - 200))}>查看前一段照片</button>}
                {groups.map((g) => (
                  <section className="date-group" key={g.date} data-photo-month={g.date.slice(0, 7)}>
                    <div className="date-heading">
                      <h2>{formatDate(g.date)}</h2>
                      <button
                        className="date-select"
                        onClick={() =>
                          setSelected((s) =>
                            g.photos.every((p) => s.includes(p.id))
                              ? s.filter(
                                  (id) => !g.photos.some((p) => p.id === id),
                                )
                              : [
                                  ...new Set([
                                    ...s,
                                    ...g.photos.map((p) => p.id),
                                  ]),
                                ],
                          )
                        }
                      >
                        {g.photos.length} 张 <CheckCircle2 size={14} />
                      </button>
                    </div>
                    <PhotoGrid
                      photos={g.photos}
                      size={gridSize}
                      selected={selected}
                      onSelect={toggle}
                      onOpen={setLight}
                      onFavorite={(p) =>
                        action(p.favorite ? "unfavorite" : "favorite", [p.id])
                      }
                    />
                  </section>
                ))}
                <div className="photo-pagination" role="status">{loadedStart ? `当前第 ${loadedStart + 1}–${loadedStart + photos.length} / ${total} 张照片` : `已加载 ${photos.length} / ${total} 张照片`}</div>
                {total > loadedStart + photos.length && (
                  <button
                    ref={morePhotosButton}
                    className="button load-more"
                    disabled={loadingMore}
                    onClick={() => void loadMorePhotos()}
                  >
                    {loadingMore ? "正在加载照片…" : morePhotosError ? "加载失败，点击重试" : "继续加载照片"}
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </main>
      {photoView && timelineMonths.length > 0 && !modal && !light && <PhotoTimeline months={timelineMonths} activeMonth={visibleMonth || photos[0]?.taken_at.slice(0, 7) || timelineMonths[0].month} onJump={jumpToMonth} />}
      {floatingTask && <button className="scan-fab" aria-label={floatingLabel} title={floatingLabel} onClick={() => setModal("tasks")}>
        <svg className="scan-fab-ring" viewBox="0 0 56 56" aria-hidden="true">
          <circle className="scan-fab-track" cx="28" cy="28" r="24" />
          <circle className={"scan-fab-progress" + (!floatingTask.total && floatingTask.status === "running" ? " pending" : "")}
            cx="28" cy="28" r="24" strokeDasharray={!floatingTask.total && floatingTask.status === "running" ? "40 111" : "151"}
            strokeDashoffset={floatingTask.total ? 151 * (1 - floatingPercent / 100) : 0} />
        </svg>
        {floatingTask.status === "paused" ? <Pause size={19} />
          : floatingTask.status === "queued" || !floatingTask.total ? <Clock size={19} />
          : <span>{floatingPercent}%</span>}
      </button>}
      {modal === "memory-share" && state.albums.find((album) => album.id === albumId) && <ShareModal album={state.albums.find((album) => album.id === albumId)!} close={() => setModal("")} />}
      {modal === "memory-editor" && state.albums.find((album) => album.id === albumId) && <MemoryEditor
        album={state.albums.find((album) => album.id === albumId)!} pets={state.pets} close={() => setModal("")}
        saved={() => { setModal(""); refresh().catch(fail); setToast("已保存回忆"); }} />}
      {modal === "pet-cover" && editingPet && <Modal title="设置宠物封面" wide className="photo-picker-modal" onClose={() => { if (!busy) setModal("rename-pet"); }}>
        <PhotoPicker target={{ kind: "cover", id: editingPet.id, name: editingPet.name }} pets={state.pets} onSavingChange={setBusy}
          onClose={() => setModal("rename-pet")} onAdded={() => {}} onCoverSelected={(photo) => { setDraftCover(photo); setModal("rename-pet"); }} />
      </Modal>}
      {modal === "photo-picker" && (petId || albumId) && <Modal title="从宠物图库添加照片" wide className="photo-picker-modal" onClose={() => { if (!busy) { setModal(""); refresh().catch(fail); } }}>
        <PhotoPicker target={{ kind: petId ? "pet" : "album", id: petId || albumId, name: title || "当前档案", species: petId ? state.pets.find((pet) => pet.id === petId)?.species : undefined }} pets={state.pets}
          onSavingChange={setBusy} onClose={() => { setModal(""); refresh().catch(fail); }} onAdded={(count) => {
            setModal(""); setToast(`已添加 ${count} 张照片到“${title}”`); refresh().catch(fail);
          }} />
      </Modal>}
      {modal === "directory" && (
        <Modal title="添加存储位置" onClose={closeStorageModal}>
          <div className="dialog-body">
            <label className="field-label">文件夹位置</label>
            <form
              className="path-input"
              onSubmit={(e) => {
                e.preventDefault();
                openDirectories(folderPath);
              }}
            >
              <input
                aria-label="文件夹路径"
                placeholder="输入文件夹路径"
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
              />
              <button className="icon" type="submit" aria-label="打开路径">
                <ChevronRight size={18} />
              </button>
            </form>
            <div className="folder-toolbar">
              <span>{folderPath ? "选择此文件夹或继续浏览" : "常用位置"}</span>
              {parent && (
                <button
                  className="text-button"
                  onClick={() => openDirectories(parent)}
                >
                  <ArrowUp size={14} />
                  上一级
                </button>
              )}
            </div>
            <div className="directory-list">
              {dirs.map((d) => (
                <button key={d.path} onClick={() => openDirectories(d.path)}>
                  <Folder size={22} />
                  <span>{d.name}</span>
                  <ChevronRight size={16} />
                </button>
              ))}
              {!dirs.length && folderPath && (
                <p className="muted">此文件夹没有子文件夹</p>
              )}
            </div>
            <label className="field-label">存储名称</label>
            <input
              className="text-input"
              placeholder="使用文件夹名称"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="dialog-footer">
            <button className="button subtle" onClick={closeStorageModal}>
              取消
            </button>
            <button
              className="button primary"
              disabled={!folderPath || busy}
              onClick={async () => {
                try {
                  setBusy(true);
                  await api("/storages", { path: folderPath, name });
                  closeStorageModal();
                  if (!storageFromSettings) go("all");
                  await refresh();
                  setToast("存储已添加，正在整理照片");
                } catch (e) {
                  fail(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              添加此文件夹
            </button>
          </div>
        </Modal>
      )}
      {modal === "browse" && (
        <Modal title="从存储添加照片" wide onClose={() => setModal("")}>
          <div className="storage-browser">
            <aside>
              {state.storages.map((s) => (
                <button
                  key={s.id}
                  className={browseId === s.id ? "chosen" : ""}
                  onClick={() => loadBrowse(s.id)}
                >
                  <HardDrive size={17} />
                  <span>{s.name}</span>
                </button>
              ))}
              <button onClick={addStorage}>
                <Plus size={17} />
                添加存储
              </button>
            </aside>
            <div className="browse-main">
              <div className="browse-path">
                <button
                  className="icon"
                  disabled={!browse || browse.path === "." || !browse.path}
                  aria-label="上一级文件夹"
                  onClick={() =>
                    loadBrowse(
                      browseId,
                      browse!.path
                        .split(String.fromCharCode(92))
                        .join("/")
                        .split("/")
                        .slice(0, -1)
                        .join("/"),
                    )
                  }
                >
                  <ArrowUp size={17} />
                </button>
                <span>
                  {browse?.storage.name}
                  {browse && browse.path !== "."
                    ? " / " +
                      browse.path.replaceAll(String.fromCharCode(92), " / ")
                    : ""}
                </span>
                {busy && <RefreshCw className="spin" size={15} />}
              </div>
              <div className="browse-content">
                {browse?.directories.map((d) => (
                  <button
                    className="browse-folder"
                    key={d.path}
                    onClick={() => loadBrowse(browseId, d.path)}
                  >
                    <Folder size={26} />
                    <span>{d.name}</span>
                    <ChevronRight size={17} />
                  </button>
                ))}
                <div className="browse-photos">
                  {browse?.photos.map((p) => (
                    <button
                      className={
                        "browse-photo " +
                        (browseSelected.includes(p.id) ? "selected" : "")
                      }
                      key={p.id}
                      onClick={() =>
                        setBrowseSelected((s) =>
                          s.includes(p.id)
                            ? s.filter((id) => id !== p.id)
                            : [...s, p.id],
                        )
                      }
                    >
                      <img src={p.thumb} alt={p.name} loading="lazy" />
                      <span className="pick-check">
                        {browseSelected.includes(p.id) && <Check size={14} />}
                      </span>
                      {p.visible && (
                        <span className="already-added">已加入</span>
                      )}
                      <span className="browse-filename">{p.name}</span>
                    </button>
                  ))}
                </div>
                {browse &&
                  !browse.directories.length &&
                  !browse.photos.length && (
                    <p className="muted">这个文件夹还没有照片</p>
                  )}
              </div>
            </div>
          </div>
          <div className="dialog-footer browse-footer">
            <span>已选 {browseSelected.length} 张</span>
            <Select
              aria-label="添加到宠物"
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
            >
              {petChoices}
            </Select>
            <button
              className="button primary"
              disabled={!browseSelected.length || busy}
              onClick={async () => {
                try {
                  await api("/photos/action", {
                    ids: browseSelected,
                    action: "add",
                    ...choiceExtra(),
                  });
                  setModal("");
                  go("gallery");
                  await refresh();
                  setToast(`已添加 ${browseSelected.length} 张照片`);
                } catch (e) {
                  fail(e);
                }
              }}
            >
              添加到图库
            </button>
          </div>
        </Modal>
      )}
      {modal === "pet-order" && <Modal title="宠物档案排序" className="pet-order-modal" onClose={() => { if (!busy) setModal(""); }}>
        <div className="dialog-body">
        <PetOrderList pets={state.pets} order={petOrder} setOrder={setPetOrder} disabled={busy} />
        </div>
        <div className="dialog-footer"><button className="button" disabled={busy} onClick={() => setModal("")}>取消</button>
          <button className="button primary" disabled={busy} onClick={async () => {
            setBusy(true);
            try { await api("/pets/order", { ids: petOrder }); await refreshState(); setModal(""); setToast("已保存宠物档案顺序"); }
            catch (error) { fail(error); } finally { setBusy(false); }
          }}>保存顺序</button></div>
      </Modal>}
      {modal === "delete-pet" && editingPet && <Modal title="删除宠物档案" onClose={() => setModal("")}>
        <div className="dialog-body">
          <p>删除“{editingPet.name}”的档案？</p>
          <p className="pet-naming-note">照片原文件、图库和回忆中的照片都会保留，只移除此宠物的身份归档。已删除的相似分组不会自动重新生成。</p>
        </div>
        <div className="dialog-footer">
          <button className="button subtle" disabled={busy} onClick={() => setModal("")}>保留档案</button>
          <button className="button delete-pet-confirm" disabled={busy} onClick={async () => {
            setBusy(true);
            try {
              await api(`/pets/${editingPet.id}`, {}, "DELETE");
              setModal("");
              if (petId === editingPet.id) go("pets");
              setEditingPet(null); await refresh(); setToast("宠物档案已删除，照片已保留");
            } catch (error) { fail(error); }
            finally { setBusy(false); }
          }}>{busy ? "正在删除…" : "确认删除"}</button>
        </div>
      </Modal>}
      {modal === "rename-pet" && editingPet && <Modal title="编辑宠物档案" className="pet-editor-modal" onClose={() => { if (!busy) setModal(""); }}>
        <form onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          setBusy(true);
          try {
            const savedName = name.trim() || (editingPet.unnamed ? species === "cat" ? "未命名猫咪" : "未命名刺猬" : editingPet.name);
            await api(`/pets/${editingPet.id}`, { name: savedName, species, ...(draftCover ? { cover_id: draftCover.id } : {}) }, "PATCH");
            setModal("");
            if (petId === editingPet.id && species !== editingPet.species) go(species === "cat" ? "cats" : "hedgehogs", editingPet.id);
            await refresh(); setToast(species !== editingPet.species ? "已更正宠物种类及关联照片" : "已保存宠物档案");
          } catch (error) { fail(error); }
          finally { setBusy(false); }
        }}>
          <div className="dialog-body pet-editor-body">
            <button type="button" className="pet-edit-cover" aria-label="更换封面" disabled={busy || !editingPet.count} onClick={() => setModal("pet-cover")}>
              {draftCover?.thumb || editingPet.cover ? <img src={draftCover?.thumb || editingPet.cover!} alt="宠物封面" /> : <div className="pet-edit-cover-placeholder"><Images size={32} /></div>}
              <span className="pet-cover-change">更换封面</span>
            </button>
            <div className="pet-editor-fields">
            <label className="field-label" htmlFor="pet-rename">宠物名字</label>
            <input id="pet-rename" autoFocus required={!editingPet.unnamed} maxLength={40} className="text-input" value={name} onChange={(event) => setName(event.target.value)} placeholder={editingPet.unnamed ? "可暂不命名，先更正种类" : "给这位小伙伴起个名字"} />
            <label className="field-label pet-species-label">宠物种类</label>
            <div className="species-picker">
              <button type="button" aria-pressed={species === "cat"} className={species === "cat" ? "chosen" : ""} disabled={busy} onClick={() => setSpecies("cat")}><Cat size={28} />猫咪</button>
              <button type="button" aria-pressed={species === "hedgehog"} className={species === "hedgehog" ? "chosen" : ""} disabled={busy} onClick={() => setSpecies("hedgehog")}><Hedgehog size={28} />刺猬</button>
            </div>
            </div>
          </div>
          <div className="dialog-footer"><button className="button primary" disabled={busy || (!name.trim() && species === editingPet.species && !draftCover)}>{busy ? "正在保存…" : "保存档案"}</button></div>
        </form>
      </Modal>}
      {modal === "remove-storage" && removingStorage && <Modal title="移除存储位置" onClose={closeStorageModal}>
        <div className="dialog-body">
          <p>移除“{removingStorage.name}”后，会停止这个文件夹的扫描，并从图库中隐藏其中的照片。</p>
          <p className="muted">原图不会删除。宠物归属、手动移出记录、收藏和回忆关系会保留；重新添加同一文件夹时恢复已有记录，只处理新增、修改或未完成的照片。</p>
          <p className="muted">同时存在于其他已添加存储中的重复照片仍可查看。</p>
        </div>
        <div className="dialog-footer"><button className="button subtle" disabled={busy} onClick={closeStorageModal}>取消</button><button className="button primary" disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            await api(`/storages/${removingStorage.id}`, {}, "DELETE");
            closeStorageModal(); setRemovingStorage(null); setSelected([]); setLight(null);
            await refresh(); setToast("存储位置已移除，原图和整理记录已保留");
          } catch (error) { fail(error); }
          finally { setBusy(false); }
        }}>{busy ? "正在移除…" : "移除存储位置"}</button></div>
      </Modal>}
      {modal === "merge-pet" && mergePetRecords.length >= 2 && <Modal title="合并宠物档案" className="bulk-merge-modal" onClose={() => { if (!busy) setModal(""); }}>
        <div className="dialog-body">
          <p className="muted">将所选 {mergePetRecords.length} 个档案合并为一个，照片会去重保留。请选择要保留的档案，合并后沿用它的名字，并停留在档案列表。</p>
          <div className="merge-pet-previews">{mergePetRecords.map((pet) => <div key={pet.id} className={pet.id === choice ? "merge-target" : ""}>{pet.cover ? <img src={pet.cover} alt="" /> : <Users size={28} />}<span title={pet.name}>{pet.name}</span><small>{pet.id === choice ? "保留此档案" : `${pet.count} 张照片`}</small></div>)}</div>
          <label className="field-label">保留哪个档案</label>
          <Select aria-label="保留宠物档案" value={choice} disabled={busy} onChange={(event) => { setChoice(event.target.value); setMergeConflict(null); }}>
            {mergePetRecords.map((pet) => <option key={pet.id} value={pet.id}>{pet.name} · {pet.count} 张</option>)}
          </Select>
          {mergeConflict?.target === choice && <section className="merge-conflict" aria-label="合并冲突照片">
            <h3>请确认这些照片中的宠物</h3>
            <p className="muted">这 {mergeConflict.photos.length} 张照片中，系统将不同区域分到了两个档案。可能是不同宠物，也可能是重复检测或误分组。查看大图后，确认两个档案属于同一只宠物即可继续合并。</p>
            <div className="merge-conflict-photos">{mergeConflict.photos.map((photo) => <a key={photo.id} href={`/api/photos/${photo.id}/image`} target="_blank" rel="noreferrer" aria-label={`查看冲突照片 ${photo.name}（新标签页）`}>
              <img src={`/api/photos/${photo.id}/thumbnail`} alt={photo.name} loading="lazy" /><span>{photo.name}</span>
            </a>)}</div>
            <p className="muted">合并后保留“{state.pets.find((pet) => pet.id === choice)?.name}”的名字，照片不会删除。</p>
          </section>}
        </div>
        <div className="dialog-footer"><button className="button primary" disabled={!choice || busy} onClick={async () => {
          const target = state.pets.find((pet) => pet.id === choice);
          if (!target) return;
          setBusy(true);
          try {
            await api('/pets/merge', { source_ids: mergePetIds.filter((id) => id !== target.id), target_id: target.id, confirm_conflicts: mergeConflict?.target === target.id });
            await refreshState(); setModal(""); setSelectedPets([]); setMergePetIds([]);
            if (view !== "pets" || petId) go("pets");
            setToast(`已合并到“${target.name}”`);
          } catch (error) {
            if (error instanceof ApiError && error.status === 409 && (error.detail as { code?: string })?.code === "merge_conflict") {
              const detail = error.detail as { photos: { id: string; name: string }[] };
              setMergeConflict({ target: target.id, photos: detail.photos });
            } else fail(error);
          }
          finally { setBusy(false); }
        }}>{mergeConflict?.target === choice ? "确认是同一只，继续合并" : "确认合并"}</button></div>
      </Modal>}
      {(modal === "pet" || modal === "album") && (
        <Modal
          title={modal === "pet" ? "创建宠物档案" : "创建回忆"}
          onClose={() => setModal("")}
        >
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api(
                  modal === "pet" ? "/pets" : "/albums",
                  modal === "pet" ? { name, species } : { name },
                );
                setModal("");
                await refresh();
              } catch (err) {
                fail(err);
              }
            }}
          >
            <div className="dialog-body">
              {modal === "pet" && (
                <div className="species-picker">
                  <button
                    type="button"
                    className={species === "cat" ? "chosen" : ""}
                    onClick={() => setSpecies("cat")}
                  >
                    <Cat size={32} />
                    猫咪
                  </button>
                  <button
                    type="button"
                    className={species === "hedgehog" ? "chosen" : ""}
                    onClick={() => setSpecies("hedgehog")}
                  >
                    <Hedgehog size={34} />
                    刺猬
                  </button>
                </div>
              )}
              <label className="field-label" htmlFor="new-name">
                {modal === "pet" ? "宠物名字" : "回忆名称"}
              </label>
              <input
                id="new-name"
                className="text-input"
                autoFocus
                required
                maxLength={40}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={
                  modal === "pet" ? "给小伙伴起个名字" : "例如：周末晒太阳"
                }
              />
            </div>
            <div className="dialog-footer">
              <button
                type="button"
                className="button subtle"
                onClick={() => setModal("")}
              >
                取消
              </button>
              <button className="button primary" disabled={!name.trim()}>
                创建
              </button>
            </div>
          </form>
        </Modal>
      )}
      {(modal === "assign" || modal === "add-album") && (
        <Modal
          title={modal === "assign" ? "添加到宠物" : "加入回忆"}
          onClose={() => setModal("")}
        >
          <div className="dialog-body">
            <p className="muted">已选择 {selected.length} 张照片</p>
            <Select
              aria-label={modal === "assign" ? "选择宠物" : "选择回忆"}
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
            >
              {modal === "assign"
                ? petChoices
                : state.albums.map((a) => (
                    <option value={a.id} key={a.id}>
                      {a.name}
                    </option>
                  ))}
            </Select>
            {modal === "add-album" && !state.albums.length && (
              <button
                className="text-button"
                onClick={() => {
                  setName("");
                  setModal("album");
                }}
              >
                创建一个回忆
              </button>
            )}
          </div>
          <div className="dialog-footer">
            <button
              className="button primary"
              disabled={!choice}
              onClick={async () => {
                await action(
                  modal === "assign" ? "assign" : "album",
                  selected,
                  modal === "assign" ? choiceExtra() : { album_id: choice },
                );
                setModal("");
              }}
            >
              完成
            </button>
          </div>
        </Modal>
      )}
      {modal === "tasks" && (
        <Modal title="扫描任务" onClose={() => setModal("")}>
          <div className="dialog-body tasks">
            {resetting && <p className="muted" role="status">正在等待当前单张处理结束，清空整理数据后会自动开始全量识别。</p>}
            {state.reset_task?.status === "error" && <p className="task-error" role="alert">清空未完成：{state.reset_task.error}。可在设置中重试。</p>}
            {discovering && <div className="task">
              <div><strong>发现相似宠物</strong><span>{state.discovery?.status === "queued" ? "等待处理" : state.discovery?.phase === "grouping" ? "正在归并已有照片" : "正在整理"}</span></div>
              <div className="progress"><i style={{ width: `${state.discovery?.total ? state.discovery.processed / state.discovery.total * 100 : 0}%` }} /></div>
              <div><small>{state.discovery?.processed || 0} / {state.discovery?.total || 0} 张</small>
                <button className="button cancel-scan" onClick={() => api("/discovery/cancel", {}).then(refreshState).catch(fail)}>取消发现</button>
              </div>
            </div>}
            {!state.jobs.length && !discovering && !resetting && state.reset_task?.status !== "error" && (
              <p className="muted">暂无任务记录。</p>
            )}
            {state.jobs.map((j) => (
              <div className="task" key={j.id}>
                <div>
                  <strong>{j.storage_name}</strong>
                  <span>
                    {{
                      running: "正在整理",
                      queued: "等待扫描",
                      paused: "已暂停",
                      complete: "已完成",
                      error: "扫描中断",
                      interrupted: "扫描中断",
                      cancelled: "已取消",
                    }[j.status] || j.status}
                  </span>
                </div>
                <div className="progress">
                  <i
                    style={{
                      width: `${j.total ? (j.processed / j.total) * 100 : 0}%`,
                    }}
                  />
                </div>
                <div>
                  <small>
                    {j.processed} / {j.total} {state.counts.videos ? "项待处理" : "张待处理"} · 找到 {j.found} {state.counts.videos ? "项宠物内容" : "张宠物照片"}
                  </small>
                  {["running", "queued", "paused"].includes(j.status) ? (
                    <div className="task-actions">
                    <button
                      className="icon"
                      aria-label={
                        j.status === "paused" ? "继续扫描" : "暂停扫描"
                      }
                      onClick={() =>
                        api(
                          `/jobs/${j.id}/${j.status === "paused" ? "resume" : "pause"}`,
                          {},
                        )
                          .then(refreshState)
                          .catch(fail)
                      }
                    >
                      {j.status === "paused" ? (
                        <Play size={16} />
                      ) : (
                        <Pause size={16} />
                      )}
                    </button>
                    <button
                      className="button cancel-scan"
                      aria-label={"取消扫描" + j.storage_name}
                      onClick={() => api(`/jobs/${j.id}/cancel`, {})
                        .then(async () => {
                          await refresh();
                          setToast("已取消扫描并关闭该文件夹自动增量，已处理结果保留");
                        }).catch(fail)}
                    >
                      <X size={14} />取消
                    </button>
                    </div>
                  ) : (
                    <div className="task-actions">
                    <button
                      className="icon"
                      aria-label="重新扫描"
                      onClick={() =>
                        api(`/storages/${j.storage_id}/scan`, {})
                          .then(refreshState)
                          .catch(fail)
                      }
                    >
                      <RefreshCw size={16} />
                    </button>
                    <button className="icon delete-pet-button" aria-label={"删除任务记录" + j.storage_name} title="删除这条任务记录"
                      disabled={busy} onClick={() => removeJobHistory(j.id)}><Trash2 size={16} /></button>
                    </div>
                  )}
                </div>
                {j.current_file && ["running", "paused"].includes(j.status) && <p className="task-current-file">{j.current_file}</p>}
                {j.error && <p className="task-error">{j.error}</p>}
              </div>
            ))}
          </div>
          <div className="dialog-footer">
            <button className="button subtle" disabled={busy || !state.jobs.some((job) => ["complete", "cancelled", "interrupted", "error"].includes(job.status))}
              onClick={() => removeJobHistory()}><Trash2 size={15} />清空历史记录</button>
          </div>
        </Modal>
      )}
      {modal === "reset-library" && <Modal title="清空数据并重新识别" onClose={() => { if (!busy) setModal("settings"); }}>
        <form onSubmit={async (event) => {
          event.preventDefault(); if (busy || resetConfirmation !== "清空并重新识别") return;
          setBusy(true);
          try {
            await api("/library/reset", { confirmation: resetConfirmation });
            setSelected([]); setLight(null); setPhotoResult(null); go("all");
            await refreshState(); setModal("tasks"); setResetConfirmation("");
            setToast("已提交清空任务，完成后将自动重新识别");
          } catch (error) { fail(error); }
          finally { setBusy(false); }
        }}>
          <div className="dialog-body">
            <p>将清除所有照片索引、识别结果、宠物档案与命名、手动归属和移出记录、收藏、回忆、缩略图及任务历史。</p>
            <p className="muted">原始照片文件不会删除。保留当前已连接的文件夹和 GPU 设置；停止旧任务后，自动从这些文件夹重新识别全部照片。已移除文件夹的缓存也会清除。</p>
            <p className="muted">执行前会自动备份整理数据。重新识别后会生成新的未命名分组，需要重新命名和整理。</p>
            <label className="field-label" htmlFor="reset-confirmation">请输入“清空并重新识别”以确认</label>
            <input id="reset-confirmation" className="text-input" value={resetConfirmation} onChange={(event) => setResetConfirmation(event.target.value)} autoComplete="off" />
          </div>
          <div className="dialog-footer"><button type="button" className="button subtle" disabled={busy} onClick={() => setModal("settings")}>取消</button><button className="button primary" disabled={busy || resetConfirmation !== "清空并重新识别"}>{busy ? "正在提交…" : "清空并重新识别"}</button></div>
        </form>
      </Modal>}
      {modal === "settings" && (
        <Modal title="设置" className="settings-modal" onClose={() => setModal("")}>
          <div className="settings-layout">
            <nav className="settings-nav" aria-label="设置分类">
              <div className="settings-nav-caption">有宠相簿</div>
              {([["folders", "文件夹管理", Folder], ["ai", "AI 设置", Sparkles], ["display", "显示设置", Grid2X2], ["sharing", "分享设置", Share2], ["data", "数据管理", HardDrive], ["help", "使用帮助", Info]] as const).map(([id, label, Icon]) =>
                <button key={id} aria-current={settingsTab === id ? "page" : undefined} onClick={() => setSettingsTab(id)}><Icon size={18} /><span>{label}</span></button>
              )}
              <button className="settings-nav-back" onClick={() => setModal("")}><ChevronLeft size={17} /><span>返回图库</span></button>
            </nav>
            <section className="settings-content" key={settingsTab} aria-label="设置内容">
              {settingsTab === "folders" && <>
                <div className="settings-content-heading"><h3>文件夹管理</h3><div className="settings-header-actions">
                  <button className="button subtle" disabled={busy || resetting || !state.storages.length} onClick={async () => {
                    setBusy(true);
                    try { await api("/library/scan", {}); await refreshState(); setModal("tasks"); }
                    catch (error) { fail(error); } finally { setBusy(false); }
                  }}><RefreshCw size={14} />扫描全部</button>
                  <button className="button subtle" onClick={() => { addStorage(); setStorageFromSettings(true); }}><Plus size={15} />添加文件夹</button>
                </div></div>
                <p className="settings-intro">添加照片所在的文件夹，系统将自动扫描并整理其中的照片。</p>
                <div className="settings-folders">{state.storages.map((storage) => <article className="settings-folder" key={storage.id}>
                  <div className="settings-folder-icon"><Folder size={28} /></div>
                  <div className="settings-folder-details"><strong>{storage.name}</strong><p title={storage.path}>{storage.path}</p><div><span className="settings-folder-tag">{storage.auto_scan ? "自动增量" : "手动扫描"}</span><span>已索引 {storage.indexed} 张 · 宠物照片 {storage.count} 张</span></div></div>
                  <div className="settings-folder-actions">
                    <button className="icon" aria-label={"扫描" + storage.name} title="扫描新增或变化的照片" disabled={resetting} onClick={() => api(`/storages/${storage.id}/scan`, {}).then(refreshState).then(() => setToast("已安排扫描")).catch(fail)}><RefreshCw size={17} /></button>
                    <button className="icon" role="switch" aria-label={storage.name + "自动增量扫描"} aria-checked={Boolean(storage.auto_scan)} title={storage.auto_scan ? "关闭自动增量" : "开启自动增量"} disabled={resetting} onClick={() => api(`/storages/${storage.id}`, { auto_scan: !storage.auto_scan }, "PATCH").then(refreshState).catch(fail)}><Clock size={17} /></button>
                    <button className="icon" aria-label={"移除存储" + storage.name} title="移除存储位置" disabled={resetting} onClick={() => { setRemovingStorage(storage); setStorageFromSettings(true); setModal("remove-storage"); }}><Trash2 size={17} /></button>
                  </div>
                </article>)}</div>
                {!state.storages.length && <div className="settings-empty"><Folder size={32} /><strong>尚未添加文件夹</strong><p>添加一处照片存储位置，开始自动整理。</p></div>}
                <p className="settings-footnote">每分钟检查新增或变化的照片。移除文件夹不会删除原图，重新添加可恢复整理记录。</p>
              </>}
              {settingsTab === "ai" && <>
            <h3 className="settings-section-title">照片识别</h3>
            <div className="gpu-setting-row">
              <div>
                <label id="gpu-setting-label">GPU 加速</label>
                <p>优先使用独显，不可用时自动使用 CPU</p>
              </div>
              <button
                className="toggle"
                role="switch"
                aria-labelledby="gpu-setting-label"
                aria-checked={Boolean(settings?.gpu_enabled)}
                disabled={!settings || settings.switching}
                onClick={async () => {
                  if (!settings) return;
                  setSettings({ ...settings, switching: true });
                  try {
                    setSettings(
                      await api<Settings>(
                        "/settings",
                        { gpu_enabled: !settings.gpu_enabled },
                        "PATCH",
                      ),
                    );
                  } catch (e) {
                    setSettings(settings);
                    fail(e);
                  }
                }}
              >
                <span />
              </button>
            </div>
            <div className="device-status">
              <i
                className={
                  settings?.device.startsWith("cuda") ? "gpu-active" : ""
                }
              />
              <span>
                {settings?.switching
                  ? "正在切换…"
                  : settings?.device.startsWith("cuda")
                    ? `当前使用 GPU · ${settings.gpu_name || "独立显卡"}`
                    : settings?.device === "cpu"
                      ? "当前使用 CPU"
                      : "扫描时启用识别"}
              </span>
            </div>
                <div className="settings-note"><Sparkles size={18} /><div><strong>宽松匹配 · 优先归档</strong><p>自动合并相近的小组，至少 5 张照片时生成未命名档案。命名、合并或手动添加参考照片后，会重新匹配已有图库，无需逐张添加。相似宠物可能误归档，可整组选中或移出，手动移出的记录会保留。</p></div></div>
              </>}
              {settingsTab === "sharing" && <ShareSettings />}
              {settingsTab === "display" && <>
            <h3 className="settings-section-title display-section">显示</h3>
            <label className="field-label">照片大小</label>
            <div className="size-control">
              <Grid2X2 size={17} />
              <input
                aria-label="照片大小"
                type="range"
                min="150"
                max="330"
                step="10"
                value={gridSize}
                onChange={(e) => {
                  setGridSize(Number(e.target.value));
                  localStorage.setItem("ousepet-grid", e.target.value);
                }}
              />
              <Images size={25} />
            </div>
            <div className="setting-row">
              <span>拍摄时间排序</span>
              <Select
                aria-label="拍摄时间排序"
                value={ascending ? "asc" : "desc"}
                onChange={(e) => setAscending(e.target.value === "asc")}
              >
                <option value="desc">最新在前</option>
                <option value="asc">最早在前</option>
              </Select>
            </div>
              </>}
              {settingsTab === "data" && <>
            <section className="settings-help scan-settings" aria-label="扫描与数据管理">
              <h3 className="settings-section-title">扫描与数据管理</h3>
              <p>重新检查所有已连接的文件夹，只识别新增、修改或未完成的照片，保留已整理的数据。</p>
              <button className="button subtle" disabled={busy || resetting || !state.storages.length} onClick={async () => {
                setBusy(true);
                try { await api("/library/scan", {}); await refreshState(); setModal("tasks"); setToast("已安排重新扫描，可在任务列表查看进度"); }
                catch (error) { fail(error); }
                finally { setBusy(false); }
              }}><RefreshCw size={15} />重新扫描文件夹</button>
              <p>如需从头识别全部照片，可清空所有整理数据后重新开始。此操作会清除宠物命名、手动归属、收藏和回忆，原图保留。</p>
              <button className="button subtle reset-library-button" disabled={busy || resetting} onClick={() => { setResetConfirmation(""); setModal("reset-library"); }}><Trash2 size={15} />清空数据并重新识别</button>
              {resetting && <p role="status">正在停止旧任务并清空数据，完成后自动开始重新识别。</p>}
              {state.reset_task?.status === "error" && <p role="alert">清空未完成：{state.reset_task.error}。可以重试，原始照片保留。</p>}
            </section>
              </>}
              {settingsTab === "help" && <>
                <h3 className="settings-section-title">使用帮助</h3>
            <section className="settings-help">
              <h3 className="settings-section-title">自动发现宠物与增量识别</h3>
              <p>视频会完整索引到图库，采样识别到宠物后归入宠物图库和对应档案；每个视频只算一条内容。同框或先后出现的多只宠物可以共同归属，播放窗口可定位出现时间，并将当前画面设为视频封面。</p>
              <p>默认 20 秒内每 2 秒、5 分钟内每 5 秒、更长每 10 秒初采样；超长视频均匀取样覆盖全片，初采样最多 120 帧，发现宠物后附近按秒加密最多 60 帧。“精细识别”优先每秒采样，同样受单次 180 帧上限限制。短暂出现仍可能漏识别，人工归属和封面会保留。</p>
              <p>常见 MP4/MOV/MKV/WebM 等视频可入库。浏览器不支持原编码时自动生成兼容播放副本，首次准备较慢，原视频不改动；兼容副本会占用应用存储，清空数据时一并清理。部分特殊编码仍可能无法播放，可下载原视频。</p>
              <p>添加照片文件夹后即可自动识别，无需先给宠物添加参考照片。开启自动增量的文件夹每分钟检查一次，只处理新增、修改或未完成识别的照片，未变化照片不重复识别。</p>
              <p>相似宠物出现在至少 5 张不同照片中，就会生成未命名分组。检查后可命名；同一宠物分成多组可以合并，误分的照片可以移出。合并保留目标档案的名字，并留在宠物档案列表。</p>
              <p>身份匹配采用宽松策略，优先把不同姿势和场景归入已有档案。点击“发现宠物”也会复用已有特征重新归并小组；命名或合并后会继续匹配存量照片。宽松匹配会增加误分，手动移出的照片不会自动加回。</p>
              <p>取消扫描会关闭该文件夹的自动增量，可在“存储管理”重新开启。发现任务的进度与取消操作可通过右下角悬浮球查看。</p>
              <p>自动识别后直接归档，无需逐张确认。你可以在宠物档案中移出误分照片，或从图库、存储中添加漏掉的照片。</p>
              <p>同一张照片可以同时属于多只宠物。将同框照片分别添加到基米和扣嘚的档案即可，移出其中一个档案不会影响另一个。宠物档案页面的“排序”可以置顶或调整显示顺序，并自动保存。</p>
              <p>移除存储只断开文件夹并隐藏照片，不删除原图或整理记录。再次添加同一文件夹会复用识别结果，并保留宠物归属、手动移出记录、收藏和回忆关系。</p>
            </section>
            <section className="settings-help">
              <h3 className="settings-section-title">键盘操作</h3>
              <dl className="keyboard-shortcuts">
                <div><dt><kbd>Esc</kbd></dt><dd>关闭当前弹窗或预览、退出多选，再返回上一级；每次只退出一层</dd></div>
                <div><dt><kbd>←</kbd> / <kbd>→</kbd></dt><dd>预览上一张 / 下一张照片</dd></div>
                <div><dt><kbd>Ctrl / ⌘</kbd> + <kbd>A</kbd></dt><dd>选择当前已加载的照片</dd></div>
                <div><dt><kbd>/</kbd></dt><dd>聚焦搜索框；输入时保留原有键盘操作</dd></div>
                <div><dt><kbd>Tab</kbd>、<kbd>Enter</kbd> / <kbd>空格</kbd></dt><dd>切换焦点、触发按钮；多选时切换照片选中状态</dd></div>
              </dl>
            </section>
              </>}
            </section>
          </div>
        </Modal>
      )}
      {light && (
        <div
          className="lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="照片查看器"
        >
          <div className="lightbox-toolbar">
            <button
              className="icon"
              aria-label="关闭照片"
              onClick={() => setLight(null)}
            >
              <X />
            </button>
            <span>{light.name}</span>
            <div />
            <button
              className={"icon " + (light.favorite ? "is-favorite" : "")}
              aria-label={light.favorite ? "取消收藏" : "收藏照片"}
              onClick={() =>
                action(light.favorite ? "unfavorite" : "favorite", [light.id])
              }
            >
              <Heart
                size={21}
                fill={light.favorite ? "currentColor" : "none"}
              />
            </button>
            <button
              className={"icon " + (info ? "active" : "")}
              aria-label="照片信息"
              onClick={() => setInfo(!info)}
            >
              <Info size={21} />
            </button>
          </div>
          <div className="lightbox-content">
            <div className="lightbox-photo">
              <button
                className="photo-arrow previous icon"
                aria-label="上一张"
                disabled={photos[0]?.id === light.id}
                onClick={() => moveLight(-1)}
              >
                <ChevronLeft size={30} />
              </button>
              {light.media_type === "video" ? <VideoPlayer key={light.id} photo={light} changed={() => { refresh().catch(fail); }} notify={setToast} /> : <img src={light.url} alt={light.name} />}
              <button
                className="photo-arrow next icon"
                aria-label="下一张"
                disabled={photos.at(-1)?.id === light.id}
                onClick={() => moveLight(1)}
              >
                <ChevronRight size={30} />
              </button>
            </div>
            {info && (
              <aside className="photo-info">
                <h3>{light.media_type === "video" ? "视频详情" : "照片详情"}</h3>
                <p className="photo-date">
                  {formatDate(light.taken_at.slice(0, 10))}
                </p>
                <h4>{light.media_type === "video" ? "视频里的小伙伴" : "照片里的小伙伴"}</h4>
                {light.pets.map((p) => (
                  <div className="identity-row" key={p.id}>
                    <span>
                      {p.species === "cat" ? (
                        <Cat size={18} />
                      ) : (
                        <Hedgehog size={18} />
                      )}
                    </span>
                    <strong>{p.name}</strong>
                    <button
                      className="icon"
                      title="移除身份"
                      aria-label={"移除" + p.name + "身份"}
                      onClick={async () => {
                        await action("unassign", [light.id], { pet_id: p.id });
                        setLight({
                          ...light,
                          pets: light.pets.filter((v) => v.id !== p.id),
                        });
                      }}
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
                <Select
                  aria-label="选择宠物身份"
                  defaultValue=""
                  onChange={async (e) => {
                    const id = e.target.value;
                    if (!id) return;
                    await action("assign", [light.id], { pet_id: id });
                    const pet = state.pets.find((p) => p.id === id)!;
                    setLight({
                      ...light,
                      pets: [
                        ...light.pets.filter((p) => p.id !== id),
                        { ...pet, status: "confirmed" },
                      ],
                    });
                    e.target.value = "";
                  }}
                >
                  <option value="">＋ 添加宠物身份</option>
                  {state.pets.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                {light.pets.map((pet) => (
                  <button
                    key={pet.id}
                    className="text-button set-cover"
                    onClick={() =>
                      action("cover", [light.id], {
                        pet_id: pet.id,
                      }).then(() => setToast("已设为宠物封面"))
                    }
                  >
                    设为 {pet.name} 的封面
                  </button>
                ))}
                <div className="file-info">
                  <h4>文件信息</h4>
                  <p>{light.name}</p>
                  <span>
                    {light.width} × {light.height}
                  </span>
                  <p className="file-path">{light.path}</p>
                </div>
                <button
                  className="text-button"
                  onClick={() => action("hide", [light.id])}
                >
                  移出宠物图库
                </button>
              </aside>
            )}
          </div>
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      )}
    </div>
  );
}
function Empty({
  icon,
  title,
  text,
  action,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  action?: string;
  onClick?: () => void;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h2>{title}</h2>
      <p>{text}</p>
      {action && (
        <button className="button primary" onClick={onClick}>
          <Plus size={17} />
          {action}
        </button>
      )}
    </div>
  );
}
function formatDate(date: string) {
  const d = new Date(date + "T12:00:00");
  if (Number.isNaN(d.getTime())) return date;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${["周日", "周一", "周二", "周三", "周四", "周五", "周六"][d.getDay()]}`;
}
function PhotoGrid({
  photos,
  size,
  selected,
  onSelect,
  onOpen,
  onFavorite,
}: {
  photos: Photo[];
  size: number;
  selected: string[];
  onSelect: (id: string) => void;
  onOpen: (p: Photo) => void;
  onFavorite: (p: Photo) => void;
}) {
  const selecting = selected.length > 0;
  const ref = useRef<HTMLDivElement>(null),
    [width, setWidth] = useState(1000);
  useEffect(() => {
    const r = new ResizeObserver((entries) =>
      setWidth(entries[0].contentRect.width),
    );
    if (ref.current) r.observe(ref.current);
    return () => r.disconnect();
  }, []);
  const rows: { items: Photo[]; height: number; full: boolean }[] = [];
  let items: Photo[] = [],
    ratio = 0;
  photos.forEach((p, i) => {
    items.push(p);
    ratio += Math.min(2.1, Math.max(0.55, p.width / p.height));
    const target = width < 600 ? Math.min(180, size) : size;
    if (ratio * target + 4 * (items.length - 1) >= width) {
      rows.push({
        items,
        height: (width - 4 * (items.length - 1)) / ratio,
        full: true,
      });
      items = [];
      ratio = 0;
    }
    if (i === photos.length - 1 && items.length)
      rows.push({
        items,
        height: Math.min(target, (width - 4 * (items.length - 1)) / ratio),
        full: false,
      });
  });
  return (
    <div ref={ref} className={"photo-grid" + (selecting ? " selecting" : "")}>
      {rows.map((r, i) => (
        <div className="photo-row" key={i} style={{ height: r.height }}>
          {r.items.map((p) => (
            <div
              className={
                "photo-tile " + (selected.includes(p.id) ? "selected" : "")
              }
              key={p.id}
              style={{
                width:
                  r.height * Math.min(2.1, Math.max(0.55, p.width / p.height)),
                flexGrow: r.full ? 1 : 0,
              }}
            >
              <button
                className="photo-open"
                aria-label={(selecting ? selected.includes(p.id) ? "取消选择照片 " : "选择照片 " : p.media_type === "video" ? "播放视频 " : "查看照片 ") + p.name}
                aria-pressed={selecting ? selected.includes(p.id) : undefined}
                onClick={() => selecting ? onSelect(p.id) : onOpen(p)}
              >
                <img
                  src={p.thumb}
                  loading="lazy"
                  alt={p.pets.map((p) => p.name).join("、") || p.name}
                />
              </button>
              {p.media_type === "video" && <span className="video-duration">▶ {durationLabel(p.duration)}</span>}
              <button
                className="select-photo"
                aria-label={(selected.includes(p.id) ? "取消选择照片 " : "选择照片 ") + p.name}
                aria-pressed={selected.includes(p.id)}
                onClick={() => onSelect(p.id)}
              >
                {selected.includes(p.id) && <Check size={15} />}
              </button>
              <button
                className={
                  "favorite-photo " + (p.favorite ? "is-favorite" : "")
                }
                aria-label={p.favorite ? "取消收藏" : "收藏"}
                onClick={() => onFavorite(p)}
              >
                <Heart size={17} fill={p.favorite ? "currentColor" : "none"} />
              </button>
              {p.pets.length > 0 && (
                <div className="photo-label">
                  {p.pets.map((p) => p.name).join(" · ")}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
export default App;
