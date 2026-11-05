import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { ArrowDown, ArrowUp, GripVertical, Users } from "lucide-react";
import type { Pet } from "./api";

export default function PetOrderList({ pets, order, setOrder, disabled }: {
  pets: Pet[]; order: string[]; setOrder: Dispatch<SetStateAction<string[]>>; disabled: boolean;
}) {
  const list = useRef<HTMLOListElement>(null);
  const [dragging, setDragging] = useState("");
  const [preview, setPreview] = useState<{ id: string; left: number; top: number; width: number } | null>(null);
  useEffect(() => {
    const element = list.current;
    if (!element || disabled) return;
    let pending: ReturnType<typeof setTimeout> | undefined;
    let frame = 0, id = "", active = false, startX = 0, startY = 0, x = 0, y = 0;
    let pointer: number | null = null, touch: number | null = null;
    let left = 0, width = 0, grabOffset = 0;
    const clear = () => {
      clearTimeout(pending); cancelAnimationFrame(frame);
      if (pointer !== null && element.hasPointerCapture(pointer)) element.releasePointerCapture(pointer);
      pointer = null; touch = null; id = ""; active = false; setDragging(""); setPreview(null);
    };
    const reposition = () => {
      if (!active) return;
      setPreview((previous) => previous?.top === y - grabOffset ? previous : { id, left, top: y - grabOffset, width });
      const rect = element.getBoundingClientRect();
      if (y < rect.top + 48) element.scrollTop -= Math.min(14, (rect.top + 48 - y) / 3);
      else if (y > rect.bottom - 48) element.scrollTop += Math.min(14, (y - rect.bottom + 48) / 3);
      const rows = Array.from(element.querySelectorAll<HTMLElement>("li[data-order-id]"));
      const others = rows.filter((row) => row.dataset.orderId !== id);
      const before = others.find((row) => { const box = row.getBoundingClientRect(); return y < box.top + box.height / 2; });
      setOrder((current) => {
        const next = current.filter((value) => value !== id);
        const position = before ? next.indexOf(before.dataset.orderId!) : next.length;
        next.splice(position < 0 ? next.length : position, 0, id);
        return next.every((value, index) => value === current[index]) ? current : next;
      });
      frame = requestAnimationFrame(reposition);
    };
    const activate = () => {
      if (active || !id) return;
      clearTimeout(pending);
      active = true; setDragging(id);
      setPreview({ id, left, top: y - grabOffset, width });
      frame = requestAnimationFrame(reposition);
    };
    const begin = (target: EventTarget | null, px: number, py: number) => {
      if (!(target instanceof Element) || target.closest("button")) return false;
      const row = target.closest<HTMLElement>("li[data-order-id]");
      if (!row) return false;
      clear(); id = row.dataset.orderId!; startX = x = px; startY = y = py;
      const box = row.getBoundingClientRect(); left = box.left; width = box.width; grabOffset = py - box.top;
      pending = setTimeout(activate, 350);
      return true;
    };
    const move = (px: number, py: number) => {
      x = px; y = py;
      if (!active && Math.hypot(x - startX, y - startY) > 8) {
        if (pointer !== null) activate(); else clear();
      }
    };
    const down = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.button !== 0) return;
      if (begin(event.target, event.clientX, event.clientY)) {
        event.preventDefault(); pointer = event.pointerId;
        element.setPointerCapture(pointer);
      }
    };
    const pointerMove = (event: PointerEvent) => { if (event.pointerId === pointer) move(event.clientX, event.clientY); };
    const pointerEnd = (event: PointerEvent) => { if (event.pointerId === pointer) clear(); };
    const touchStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) { clear(); return; }
      const point = event.touches[0];
      if (begin(event.target, point.clientX, point.clientY)) touch = point.identifier;
    };
    const touchMove = (event: TouchEvent) => {
      const point = Array.from(event.touches).find((item) => item.identifier === touch);
      if (!point) return;
      if (active) event.preventDefault();
      move(point.clientX, point.clientY);
    };
    const touchEnd = (event: TouchEvent) => {
      if (!Array.from(event.touches).some((point) => point.identifier === touch)) clear();
    };
    const context = (event: Event) => { if (id) event.preventDefault(); };
    element.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", pointerMove);
    window.addEventListener("pointerup", pointerEnd);
    window.addEventListener("pointercancel", pointerEnd);
    window.addEventListener("blur", clear);
    element.addEventListener("touchstart", touchStart, { passive: true });
    element.addEventListener("touchmove", touchMove, { passive: false });
    element.addEventListener("touchend", touchEnd);
    element.addEventListener("touchcancel", touchEnd);
    element.addEventListener("contextmenu", context);
    return () => {
      clear();
      element.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", pointerMove);
      window.removeEventListener("pointerup", pointerEnd);
      window.removeEventListener("pointercancel", pointerEnd);
      window.removeEventListener("blur", clear);
      element.removeEventListener("touchstart", touchStart);
      element.removeEventListener("touchmove", touchMove);
      element.removeEventListener("touchend", touchEnd);
      element.removeEventListener("touchcancel", touchEnd);
      element.removeEventListener("contextmenu", context);
    };
  }, [disabled, setOrder]);
  const draggedPet = preview ? pets.find((pet) => pet.id === preview.id) : null;
  return <><ol ref={list} className={"pet-order-list" + (dragging ? " is-dragging" : "")} aria-label="宠物档案顺序">
    {order.map((id, index) => {
      const pet = pets.find((value) => value.id === id);
      if (!pet) return null;
      const move = (target: number) => setOrder((current) => {
        const next = [...current], from = next.indexOf(id);
        if (from < 0) return current;
        next.splice(from, 1); next.splice(target, 0, id); return next;
      });
      return <li key={id} data-order-id={id} className={dragging === id ? "dragging" : ""}>
        <GripVertical size={15} className="order-grip" aria-hidden="true" />
        <span className="muted">{index + 1}</span>
        {pet.cover ? <img src={pet.cover} alt="" draggable={false} /> : <span className="pet-order-avatar"><Users size={20} /></span>}
        <strong>{pet.name}</strong>
        <button className="button subtle" disabled={disabled || index === 0} aria-label={"置顶" + pet.name} onClick={() => move(0)}>置顶</button>
        <button className="icon" disabled={disabled || index === 0} aria-label={"上移" + pet.name} onClick={() => move(index - 1)}><ArrowUp size={17} /></button>
        <button className="icon" disabled={disabled || index === order.length - 1} aria-label={"下移" + pet.name} onClick={() => move(index + 1)}><ArrowDown size={17} /></button>
      </li>;
    })}
  </ol>
    {preview && draggedPet && <div className="pet-order-drag-preview" aria-hidden="true" style={{ left: preview.left, top: preview.top, width: preview.width }}>
      <GripVertical size={20} />
      {draggedPet.cover ? <img src={draggedPet.cover} alt="" /> : <Users size={40} />}
      <strong>{draggedPet.name}</strong>
    </div>}
  </>;
}
