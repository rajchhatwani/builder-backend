import type { KeyboardEvent as ReactKeyboardEvent } from 'react'

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

/** Keeps Tab and Shift+Tab inside `container`: from the last control Tab goes to the first and Shift+Tab from the first (or from the
 *  container itself) goes to the last. Returns true when it handled the key. With no focusable child the container keeps focus. */
export function trapTab(e: Pick<ReactKeyboardEvent, 'key' | 'shiftKey' | 'preventDefault'>, container: HTMLElement | null): boolean {
  if (e.key !== 'Tab' || !container) return false
  const items = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute('hidden'))
  if (items.length === 0) { e.preventDefault(); container.focus(); return true }
  const first = items[0]
  const last = items[items.length - 1]
  const active = document.activeElement
  if (e.shiftKey && (active === first || active === container || !container.contains(active))) { e.preventDefault(); last.focus(); return true }
  if (!e.shiftKey && (active === last || !container.contains(active))) { e.preventDefault(); first.focus(); return true }
  return false
}
