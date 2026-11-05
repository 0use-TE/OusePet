import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
export default function Dialog({ title, children, close, wide = false, className = "" }: { title: string; children: ReactNode; close: () => void; wide?: boolean; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className={(wide ? "modal wide photo-picker-modal" : "modal") + " " + className} aria-label={title}
    onCancel={(event) => { event.preventDefault(); close(); }}>
    <div className="modal-heading"><h2>{title}</h2><button className="icon" aria-label="关闭" onClick={close}><X size={20} /></button></div>{children}
  </dialog>;
}
