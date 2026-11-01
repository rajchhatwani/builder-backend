/** Feature flag `ui.shell`. The old shell is the default; `v2` switches the project workspace to the new shell.
 *  Set with `localStorage.setItem('ui.shell', 'v2')` or by opening the app once with `?ui.shell=v2`
 *  (persisted; `?ui.shell=v1` turns it off). Nothing else reads the flag. */
const KEY = 'ui.shell'

export function shellV2Enabled(): boolean {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get(KEY)
    if (fromUrl === 'v2' || fromUrl === 'v1') localStorage.setItem(KEY, fromUrl)
    return localStorage.getItem(KEY) === 'v2'
  } catch {
    return false // storage blocked: stay on the old shell
  }
}
