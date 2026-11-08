import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach } from 'vitest'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** Shared render harness for the AI-shell component tests: mounts into the DOM and unmounts after each test. */
let root: Root | null = null
let host: HTMLElement | null = null
afterEach(() => { if (root) act(() => root?.unmount()); host?.remove(); root = null; host = null })

export const flush = async (n = 5) => { for (let i = 0; i < n; i++) await act(async () => { await Promise.resolve() }) }
export async function mount(el: ReturnType<typeof createElement>): Promise<HTMLElement> {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root!.render(el) }); await flush()
  return host
}
export const q = (id: string) => host?.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
export const qa = (id: string) => Array.from(host?.querySelectorAll(`[data-testid="${id}"]`) ?? []) as HTMLElement[]
export const click = async (el: Element | null) => { await act(async () => { (el as HTMLElement).click() }); await flush() }
export const typeInto = async (el: HTMLTextAreaElement, v: string) => {
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
export const unmount = () => { act(() => root?.unmount()); root = null }
