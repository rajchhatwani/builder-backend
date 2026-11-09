/** Feature flag `ui.shell`. The new shell (v2) is the DEFAULT (CO4-2); `?ui.shell=v1` switches back to the classic shell.
 *  Set with `localStorage.setItem('ui.shell', 'v2')` or by opening the app once with `?ui.shell=v2`
 *  (persisted; `?ui.shell=v1` turns the new shell off). This is the ONE flag: it turns every new page on (no per-feature flags). */
const KEY = 'ui.shell'

export function shellV2Enabled(): boolean {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get(KEY)
    if (fromUrl === 'v2' || fromUrl === 'v1') localStorage.setItem(KEY, fromUrl)
    return localStorage.getItem(KEY) !== 'v1'
  } catch {
    return true // storage blocked: default shell
  }
}
