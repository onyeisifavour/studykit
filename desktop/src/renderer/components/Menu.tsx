import { useEffect, useRef, useState } from 'react';

export interface MenuItem {
  key: string;
  label: string;
  onSelect: () => void;
  /** Renders in the danger colour. */
  danger?: boolean;
  /**
   * When set, the item becomes a two-step action: the first click swaps the
   * row to `confirmLabel`, the second runs onSelect. Keeps destructive actions
   * behind an extra click without needing a modal or a new IPC dialog.
   */
  confirm?: string;
  disabled?: boolean;
}

interface Props {
  items: MenuItem[];
  /** Which edge of the trigger the popover lines up with. */
  align?: 'left' | 'right';
  ariaLabel?: string;
}

/**
 * A 3-dot overflow menu. Styled to match the existing `.sim-dots` / `.sim-menu`
 * language so it reads as native to the rest of the app. Closes on outside
 * click, on Escape, and after an item is chosen.
 */
export default function Menu({ items, align = 'right', ariaLabel = 'More actions' }: Props) {
  const [open, setOpen] = useState(false);
  const [armed, setArmed] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Reset any armed confirm whenever the menu closes, so reopening always
  // starts from a neutral state.
  useEffect(() => {
    if (!open) setArmed(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (items.length === 0) return null;

  const pick = (item: MenuItem) => {
    if (item.disabled) return;
    if (item.confirm && armed !== item.key) {
      setArmed(item.key);
      return;
    }
    setOpen(false);
    item.onSelect();
  };

  return (
    <div className="menu3" ref={wrapRef}>
      <button
        type="button"
        className="menu3-trigger"
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        ⋯
      </button>

      {open && (
        <div
          className="menu3-pop"
          data-align={align}
          role="menu"
          onClick={(e) => e.stopPropagation()}
        >
          {items.map((item) => {
            const isArmed = item.confirm && armed === item.key;
            return (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                className={
                  'menu3-item'
                  + (item.danger ? ' danger' : '')
                  + (isArmed ? ' armed' : '')
                }
                onClick={() => pick(item)}
              >
                {isArmed ? item.confirm : item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
