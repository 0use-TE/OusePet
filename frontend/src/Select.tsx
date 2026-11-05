import { Children, isValidElement, useId, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";

type Option = { value: string; label: ReactNode; group?: string };
function optionsFrom(children: ReactNode, group?: string): Option[] {
  return Children.toArray(children).flatMap((child): Option[] => {
    if (!isValidElement<{ value?: string; label?: string; children?: ReactNode }>(child)) return [];
    if (child.type === "option") return [{ value: child.props.value ?? "", label: child.props.children, group }];
    return optionsFrom(child.props.children, child.type === "optgroup" ? child.props.label : group);
  });
}

export default function Select({ children, value, defaultValue = "", onChange, ...props }: {
  children: ReactNode;
  value?: string;
  defaultValue?: string;
  "aria-label"?: string;
  disabled?: boolean;
  onChange: (event: { target: { value: string } }) => void;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [internal, setInternal] = useState(defaultValue);
  const [open, setOpen] = useState(false);
  const options = optionsFrom(children);
  const current = value ?? internal;
  const close = () => { menu.current?.hidePopover(); trigger.current?.focus(); };
  const choose = (option: Option) => {
    setInternal(option.value);
    close();
    // A fresh target also supports callers that reset an uncontrolled picker.
    const target = { value: option.value };
    const result = onChange({ target }) as unknown;
    Promise.resolve(result).then(() => { if (value === undefined) setInternal(target.value); }, () => {});
  };
  const show = (last = false) => {
    const rect = trigger.current!.getBoundingClientRect();
    const popup = menu.current!;
    const height = Math.min(300, window.innerHeight - 24);
    const below = window.innerHeight - rect.bottom - 12;
    popup.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - Math.max(rect.width, 200) - 12))}px`;
    popup.style.width = `${Math.min(Math.max(rect.width, 200), window.innerWidth - 24)}px`;
    popup.style.maxHeight = `${Math.max(80, Math.min(height, below >= 180 ? below : rect.top - 12))}px`;
    popup.style.top = below >= 180 ? `${rect.bottom + 6}px` : "auto";
    popup.style.bottom = below >= 180 ? "auto" : `${window.innerHeight - rect.top + 6}px`;
    popup.showPopover();
    const buttons = popup.querySelectorAll<HTMLButtonElement>("[role=option]");
    const index = options.findIndex((o) => o.value === current);
    buttons[last ? buttons.length - 1 : Math.max(0, index)]?.focus();
  };
  return (
    <div className="select-control">
      <button {...props} ref={trigger} className="select-trigger" type="button"
        aria-haspopup="listbox" aria-expanded={open} aria-controls={id}
        onClick={() => open ? close() : show()}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault(); show(event.key === "End");
          }
        }}>
        <span>{options.find((o) => o.value === current)?.label || "请选择"}</span>
        <ChevronDown size={15} />
      </button>
      <div ref={menu} id={id} popover="auto" role="listbox" aria-label={props["aria-label"]}
        className="select-menu" onToggle={(event) => setOpen(event.newState === "open")}
        onKeyDown={(event) => {
          const buttons = [...menu.current!.querySelectorAll<HTMLButtonElement>("[role=option]")];
          const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
              : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
            buttons[next]?.focus();
          } else if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            close();
          } else if (event.key === "Tab") close();
        }}>
        {options.map((option, index) => (
          <div key={option.value}>
            {option.group && option.group !== options[index - 1]?.group && <div className="select-group">{option.group}</div>}
            <button type="button" role="option" aria-selected={current === option.value}
              onClick={() => choose(option)}><span>{option.label}</span>{current === option.value && <Check size={15} />}</button>
          </div>
        ))}
      </div>
    </div>
  );
}
