import { useEffect, useRef } from 'react'

/** Tiny in-page bus: the stream publishes topics, pages that load in effects subscribe and refetch. */
type Listener = () => void
const listeners = new Map<string, Set<Listener>>()

export function publishTopics(topics: string[]): void {
  for (const t of new Set(topics)) for (const l of [...(listeners.get(t) ?? [])]) l()
}

export function subscribeTopic(topic: string, fn: Listener): () => void {
  let set = listeners.get(topic)
  if (!set) listeners.set(topic, (set = new Set()))
  set.add(fn)
  return () => { set!.delete(fn); if (set!.size === 0) listeners.delete(topic) }
}

/** Run `refresh` when any of `topics` fires; the latest `refresh` is always used. */
export function useRealtimeRefresh(topics: string[], refresh: () => void): void {
  const ref = useRef(refresh)
  ref.current = refresh
  const key = topics.join('|')
  useEffect(() => {
    const offs = key.split('|').filter(Boolean).map((t) => subscribeTopic(t, () => ref.current()))
    return () => offs.forEach((o) => o())
  }, [key])
}
