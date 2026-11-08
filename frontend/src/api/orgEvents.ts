/**
 * "The list of my organizations changed" (created, joined, left, deleted). The sidebar
 * listens so its org switcher stays current without a reload.
 */
const EVENT = 'orgs:changed'

export function notifyOrgsChanged(): void {
  window.dispatchEvent(new Event(EVENT))
}

export function onOrgsChanged(listener: () => void): () => void {
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}
