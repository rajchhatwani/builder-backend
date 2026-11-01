/** Per-page feature flags for pages that REPLACE an existing panel (F2-2/F2-3): `ui.payments`, `ui.storage`,
 *  `ui.observability`, `ui.deployment`. ON by default (owner decision, 2026-11-02) inside the v2 shell.
 *  `?ui.payments=classic` (or `v1`) switches that page back to the classic panel and is persisted per browser,
 *  as does the form page's "Use the classic panel" button; `?ui.payments=v2` switches it on again.
 *  Pages with no old panel (webhooks, providers, jobs, workers, workflows) need no flag of their own. */
export const PAGE_FLAGS = ['payments', 'storage', 'observability', 'deployment'] as const
export type PageFlag = (typeof PAGE_FLAGS)[number]

const key = (name: PageFlag) => `ui.${name}`
const OFF = ['classic', 'v1']

export function pageFlagOn(name: PageFlag): boolean {
  try {
    const url = new URLSearchParams(window.location.search).get(key(name))
    if (url === 'v2' || url === 'classic' || url === 'v1') localStorage.setItem(key(name), url)
    return !OFF.includes(localStorage.getItem(key(name)) ?? '')
  } catch {
    return true // storage blocked: the default (on) applies
  }
}

export function setPageFlag(name: PageFlag, value: 'classic' | 'v2'): void {
  try {
    localStorage.setItem(key(name), value)
  } catch {
    /* blocked: the page stays as it is */
  }
}
