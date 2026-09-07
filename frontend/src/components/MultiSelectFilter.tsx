import { useCallback, useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { ChevronDown, Search } from "lucide-react";
import "../styles/multi-select.css";

export type MultiSelectFilterProps = {
  label: string;
  allLabel?: string;
  options: { value: string; label: string }[];
  value: string[] | null;
  onChange: (value: string[] | null) => void;
  searchable?: boolean;
};

export default function MultiSelectFilter({
  label,
  allLabel = `All ${label.toLowerCase()}`,
  options,
  value,
  onChange,
  searchable = false,
}: MultiSelectFilterProps) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const allCheckbox = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState<CSSProperties>({});
  const selected = new Set(value ?? options.map((option) => option.value));
  const selectedCount = options.filter((option) => selected.has(option.value)).length;
  const allSelected = value === null;
  const mixed = selectedCount > 0 && value !== null;
  const caption = allSelected
    ? allLabel
    : selectedCount === 0
      ? `${label}: none`
      : selectedCount === 1
        ? options.find((option) => selected.has(option.value))!.label
        : `${label} (${selectedCount})`;
  const visibleOptions = options.filter((option) =>
    option.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );

  const updatePosition = useCallback(() => {
    if (!trigger.current) return;
    const bounds = trigger.current.getBoundingClientRect();
    const viewport = window.visualViewport;
    const viewportLeft = viewport?.offsetLeft ?? 0;
    const viewportTop = viewport?.offsetTop ?? 0;
    const viewportWidth = viewport?.width ?? window.innerWidth;
    const viewportHeight = viewport?.height ?? window.innerHeight;
    const margin = 12;
    const gap = 8;
    const width = Math.min(320, viewportWidth - margin * 2);
    const below = viewportTop + viewportHeight - bounds.bottom - gap - margin;
    const above = bounds.top - viewportTop - gap - margin;
    const placeBelow = below >= 240 || below >= above;
    setPosition({
      width,
      left: Math.max(viewportLeft + margin, Math.min(bounds.left, viewportLeft + viewportWidth - width - margin)),
      ...(placeBelow ? { top: bounds.bottom + gap } : { bottom: window.innerHeight - bounds.top + gap }),
      maxHeight: Math.max(0, placeBelow ? below : above),
    });
  }, []);

  const close = useCallback((returnFocus = false) => {
    setOpen(false);
    setQuery("");
    if (returnFocus) trigger.current?.focus();
  }, []);

  useEffect(() => {
    if (allCheckbox.current) allCheckbox.current.indeterminate = mixed;
  }, [mixed, open]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) close();
    };
    updatePosition();
    document.addEventListener("pointerdown", outside);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    window.visualViewport?.addEventListener("resize", updatePosition);
    window.visualViewport?.addEventListener("scroll", updatePosition);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
      window.visualViewport?.removeEventListener("resize", updatePosition);
      window.visualViewport?.removeEventListener("scroll", updatePosition);
    };
  }, [open, close, updatePosition]);

  function toggle(option: string) {
    const next = new Set(value ?? options.map((item) => item.value));
    if (next.has(option)) next.delete(option);
    else next.add(option);
    onChange([...next]);
  }

  return (
    <div
      className="multi-select-filter"
      ref={root}
      onKeyDown={(event) => {
        if (open && event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          close(true);
        }
      }}
      onBlur={(event) => {
        if (open && event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)) close();
      }}
    >
      <button
        ref={trigger}
        type="button"
        className={`multi-select-trigger${value === null ? "" : " is-filtered"}`}
        aria-label={!allSelected && selectedCount === 1 ? `${label}: ${caption}` : undefined}
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onClick={() => {
          if (open) close();
          else {
            updatePosition();
            setOpen(true);
          }
        }}
      >
        <span>{caption}</span>
        <ChevronDown aria-hidden="true" size={16} />
      </button>
      {open && (
        <div className="multi-select-panel" id={`${id}-panel`} style={position}>
          {searchable && (
            <div className="multi-select-search">
              <Search aria-hidden="true" size={16} />
              <input
                type="search"
                aria-label={`Search ${label.toLowerCase()} options`}
                placeholder={`Search ${label.toLowerCase()}`}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
          )}
          <fieldset className="multi-select-fieldset">
            <legend className="sr-only">{label}</legend>
            <div className="multi-select-actions">
              <label className="multi-select-option multi-select-all">
                <input
                  ref={allCheckbox}
                  type="checkbox"
                  checked={allSelected}
                  aria-checked={mixed ? "mixed" : allSelected}
                  onChange={() => onChange(null)}
                />
                <span>Select all</span>
              </label>
              <button type="button" className="multi-select-clear" onClick={() => onChange([])}>Clear</button>
            </div>
            <div className="multi-select-options">
              {visibleOptions.map((option) => (
                <label key={option.value} className="multi-select-option">
                  <input type="checkbox" checked={selected.has(option.value)} onChange={() => toggle(option.value)} />
                  <span>{option.label}</span>
                </label>
              ))}
              {visibleOptions.length === 0 && <p className="multi-select-empty" role="status">No matching options</p>}
            </div>
          </fieldset>
        </div>
      )}
    </div>
  );
}
