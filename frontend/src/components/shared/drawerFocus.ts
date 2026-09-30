/**
 * The drawer/sheet accessibility contract, in one place.
 *
 * `CompanionPanel` (reader drawer) and `AuditDetailPanel` (audit sheet) already
 * implement this contract: focus into the overlay on open, a Tab trap inside
 * it, `role="dialog"` + `aria-modal`, inert background, and focus returned to
 * the trigger on close. This module does not replace that logic — it *is* that
 * logic, hoisted so a third consumer (the catalyst evidence drawer) joins the
 * same tested behaviour instead of copying it a third time.
 *
 * The two existing panels keep their own markup and their own narrow/drawer
 * split; only the mechanism is shared. `useDrawerFocus` is what the evidence
 * drawer calls, and its tests assert the same four properties design 4.4
 * requires: focus management, Esc, background inert, and focus return.
 */
import { useCallback, useEffect, useRef, useState } from "react";

/** The same selector list the Companion and Audit panels already use. */
export const FOCUSABLE = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/** Elements a modal overlay may focus, ignoring anything hidden by inert. */
export function focusableWithin(root: HTMLElement | null): HTMLElement[] {
  return Array.from(root?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter(
    (item) => !item.closest('[aria-hidden="true"]') && !item.closest("[inert]"),
  );
}

/**
 * Move focus to `fallback` unless the recorded trigger is still connected.
 * Copied verbatim from AuditCenter's `restoreFocus`, including its reason: a
 * trigger that unmounted (a tab switch, a run switch) must not be focused back
 * into, and the reader surface is the next sensible place.
 */
export function restoreFocus(target: HTMLElement | null): void {
  if (target?.isConnected) {
    const inertAncestor = target.closest("[inert]") as (HTMLElement & { inert: boolean }) | null;
    if (inertAncestor !== null) {
      inertAncestor.inert = false;
      inertAncestor.removeAttribute("aria-hidden");
    }
    target.focus({ preventScroll: true });
    return;
  }
  const fallback = document.querySelector<HTMLElement>(".reader-surface h2, main");
  if (fallback !== null) {
    if (!fallback.hasAttribute("tabindex")) fallback.setAttribute("tabindex", "-1");
    fallback.focus({ preventScroll: true });
  }
}

/** `max-width: 1399px` — the same breakpoint AuditCenter uses for its sheet. */
const NARROW_QUERY = "(max-width: 1399px)";

/** Narrow-screen detection, shared with the audit sheet's own rule. */
export function useNarrowOverlay(): boolean {
  const [narrow, setNarrow] = useState(() =>
    typeof window.matchMedia === "function" ? window.matchMedia(NARROW_QUERY).matches : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(NARROW_QUERY);
    const change = (event: MediaQueryListEvent): void => setNarrow(event.matches);
    setNarrow(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  return narrow;
}

export interface DrawerFocusOptions {
  open: boolean;
  /** `narrow` overlays trap focus eagerly; a desktop drawer may not. */
  trap: boolean;
  /** Elements made inert while the overlay is open. */
  background: ReadonlyArray<HTMLElement | null>;
  onClose(): void;
}

export interface DrawerFocus {
  panelRef: React.RefObject<HTMLElement>;
  /** Attach to the overlay root: handles the Tab wrap. */
  onKeyDown(event: React.KeyboardEvent<HTMLElement>): void;
}

/**
 * Focus management, Esc, and background inert for one overlay.
 *
 * Behaviour, taken from the two existing panels:
 *  * on open, focus the close control (deferred one tick, as both panels do, so
 *    the node exists);
 *  * Tab from the last focusable wraps to the first, Shift+Tab the reverse;
 *  * Esc closes;
 *  * every registered background element gets `inert` + `aria-hidden`, and
 *    both are restored exactly as they were on close;
 *  * focus returns to the recorded trigger, or to the reader surface if the
 *    trigger is gone.
 */
export function useDrawerFocus({
  open,
  trap,
  background,
  onClose,
}: DrawerFocusOptions): DrawerFocus {
  // `useRef<HTMLElement>(null)` — not `useRef<HTMLElement | null>(null)`. The
  // former yields `RefObject<HTMLElement>`, which is what a `ref` prop on
  // `<aside>` accepts under the React 18 types; the latter is a second,
  // non-assignable type. The existing Companion and Audit panels declare
  // their panel refs this way for the same reason.
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => {
      const close = panelRef.current?.querySelector<HTMLElement>(
        "[data-autofocus], button, [href], [tabindex]:not([tabindex='-1'])",
      );
      close?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const restore: Array<() => void> = [];
    for (const target of background) {
      if (target === null) continue;
      const element = target as HTMLElement & { inert: boolean };
      // jsdom (and older browsers) expose no `inert` at all, so reading it
      // back yields undefined. Normalising to a boolean keeps the restore
      // symmetric: an element that had no inert attribute returns to having
      // none, not to `inert: undefined`.
      const previousInert = element.inert === true;
      const previousHidden = element.getAttribute("aria-hidden");
      // Set both the property and the attribute. A real browser reflects one to
      // the other; jsdom does not, and the attribute is what assistive tech
      // and the existing WorkbenchLayout code path actually read.
      element.inert = true;
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
      restore.push(() => {
        element.inert = previousInert;
        if (previousInert) element.setAttribute("inert", "");
        else element.removeAttribute("inert");
        if (previousHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", previousHidden);
      });
    }
    return () => {
      for (const undo of restore) undo();
    };
  }, [background, open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLElement>): void => {
      if (!trap || event.key !== "Tab") return;
      const focusable = focusableWithin(panelRef.current);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    },
    [trap],
  );

  return { panelRef, onKeyDown: handleKeyDown };
}

/**
 * Remember the element that opened the overlay, and return focus to it on close.
 * Kept separate from `useDrawerFocus` so a component can own when the record
 * happens (a click handler) rather than in an effect.
 */
export function useReturnFocus(): {
  remember(trigger: HTMLElement | null): void;
  release(): void;
} {
  const triggerRef = useRef<HTMLElement | null>(null);
  const remember = useCallback((trigger: HTMLElement | null): void => {
    triggerRef.current = trigger;
  }, []);
  const release = useCallback((): void => {
    restoreFocus(triggerRef.current);
    triggerRef.current = null;
  }, []);
  return { remember, release };
}
