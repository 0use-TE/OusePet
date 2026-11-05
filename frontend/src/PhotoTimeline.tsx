import { useEffect, useLayoutEffect, useRef, useState } from "react";

export type TimelineMonth = { month: string; count: number; offset: number };
const label = (month: string) => /^\d{4}-\d{2}$/.test(month) ? `${month.slice(0, 4)}年${Number(month.slice(5))}月` : "未知日期";

export default function PhotoTimeline({ months, activeMonth, onJump }: {
  months: TimelineMonth[]; activeMonth: string; onJump: (month: TimelineMonth) => void;
}) {
  const [expanded, setExpanded] = useState("");
  const [preview, setPreview] = useState(0);
  const [dragging, setDragging] = useState(false);
  const rail = useRef<HTMLElement>(null);
  const picker = useRef<HTMLDivElement>(null);
  const [pickerTop, setPickerTop] = useState(0);
  const active = Math.max(0, months.findIndex((month) => month.month === activeMonth));
  useEffect(() => { setPreview(active); }, [active]);
  const years = [...new Set(months.map((month) => month.month.slice(0, 4)))];
  useLayoutEffect(() => {
    if (!expanded || !rail.current || !picker.current) return;
    const update = () => {
      const root = rail.current;
      const popup = picker.current;
      const anchor = root?.querySelector<HTMLButtonElement>(`button[data-year="${expanded}"]`);
      if (!root || !popup || !anchor) return;
      const bounds = root.getBoundingClientRect();
      const target = anchor.getBoundingClientRect();
      const min = Math.max(0, 8 - bounds.top);
      const max = Math.min(bounds.height, window.innerHeight - 8 - bounds.top) - popup.offsetHeight;
      setPickerTop(Math.max(min, Math.min(target.top + target.height / 2 - bounds.top - popup.offsetHeight / 2, max)));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(rail.current);
    observer.observe(picker.current);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => { observer.disconnect(); window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); };
  }, [expanded, months]);
  const jump = (index: number) => { if (months[index]) onJump(months[index]); };
  return <nav ref={rail} className="photo-time-rail" aria-label="照片时间线" onMouseLeave={() => setExpanded("")}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setExpanded(""); }}>
    <div className="timeline-years">{years.map((year) => <button key={year} data-year={year} className={activeMonth.startsWith(year) ? "current" : ""}
      aria-label={`跳转到${year}年`} aria-current={activeMonth.startsWith(year) ? "date" : undefined}
      onMouseEnter={() => setExpanded(year)} onFocus={() => setExpanded(year)}
      onClick={() => { setExpanded(year); onJump(months.find((month) => month.month.startsWith(year))!); }}>{year === "unkn" ? "未知" : year}</button>)}</div>
    <input type="range" className="timeline-date-slider" aria-label="快速定位照片日期" aria-orientation="vertical"
      aria-valuetext={label(months[preview]?.month || "unknown")} min={0} max={Math.max(0, months.length - 1)} value={Math.min(preview, months.length - 1)}
      onPointerDown={() => { setDragging(true); setExpanded(""); }}
      onChange={(event) => setPreview(Number(event.target.value))}
      onPointerUp={(event) => { setDragging(false); jump(Number(event.currentTarget.value)); }}
      onPointerCancel={() => setDragging(false)}
      onKeyUp={(event) => { if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) jump(Number(event.currentTarget.value)); }} />
    {dragging && <div className="timeline-date-preview" style={{ top: `clamp(16px, ${months.length > 1 ? preview / (months.length - 1) * 100 : 0}%, calc(100% - 16px))` }}>{label(months[preview]?.month || "unknown")}</div>}
    {expanded && <div ref={picker} className="timeline-month-picker" style={{ top: pickerTop }}><strong>{expanded === "unkn" ? "未知日期" : `${expanded}年`}</strong>
      {months.filter((month) => month.month.startsWith(expanded)).map((month) => <button key={month.month} aria-label={`跳转到${label(month.month)}`} className={month.month === activeMonth ? "current" : ""}
        onClick={() => { onJump(month); setExpanded(""); }}><span>{month.month === "unknown" ? "未知日期" : `${Number(month.month.slice(5))}月`}</span><small>{month.count} 张</small></button>)}
    </div>}
  </nav>;
}
