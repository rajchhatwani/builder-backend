/** Pure: which cached queries a realtime event makes stale, and which page-level topics to nudge. */
export interface RealtimeEvent {
  id: number | null
  topic: string
  type: string
  data: Record<string, unknown>
}

export type QueryKey = readonly unknown[]

/** Prefix keys: invalidating ['spec', pid] also refreshes every deeper key that starts with it. */
export const projectKeys = {
  status: (pid: string): QueryKey => ['project-status', pid],
  spec: (pid: string): QueryKey => ['spec', pid],
  ops: (pid: string): QueryKey => ['ops', pid],
  timeline: (pid: string): QueryKey => ['timeline', pid],
  history: (pid: string): QueryKey => ['history', pid],
  imports: (pid: string): QueryKey => ['imports', pid],
  records: (pid: string): QueryKey => ['records', pid],
}

const ALL = (pid: string): QueryKey[] => Object.values(projectKeys).map((k) => k(pid))

/** Event -> query keys to invalidate. Unknown events invalidate nothing (a newer server never breaks an older page);
 *  `resync` (the server could not replay what was missed) invalidates everything for the project. */
export function keysForEvent(ev: Pick<RealtimeEvent, 'topic' | 'type'>, projectId: string): QueryKey[] {
  if (ev.type === 'resync') return ALL(projectId)
  const k = projectKeys
  if (ev.type === 'spec.changed') return [k.spec(projectId), k.status(projectId), k.ops(projectId), k.timeline(projectId), k.history(projectId)]
  if (ev.type === 'import.committed') return [k.imports(projectId), k.records(projectId), k.status(projectId)]
  return []
}

/** Event -> page topics that pages without Query (they load in effects) subscribe to with useRealtimeRefresh. */
export function topicsForEvent(ev: Pick<RealtimeEvent, 'topic' | 'type'>): string[] {
  if (ev.type === 'resync') return ['spec', 'imports']
  if (ev.type === 'spec.changed') return ['spec']
  if (ev.type === 'import.committed') return ['imports']
  return []
}

/** Tolerant envelope reader: a frame whose data is not a JSON object is dropped (returns null). */
export function parseEnvelope(frame: { id?: string; event: string; data: string }): RealtimeEvent | null {
  let body: unknown
  try { body = JSON.parse(frame.data) } catch { return null }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return null
  const o = body as Record<string, unknown>
  const idText = frame.id ?? (typeof o.id === 'number' ? String(o.id) : '')
  const id = /^\d{1,15}$/.test(idText) ? Number(idText) : null
  const data = typeof o.data === 'object' && o.data !== null && !Array.isArray(o.data) ? (o.data as Record<string, unknown>) : {}
  return { id, topic: typeof o.topic === 'string' ? o.topic : '', type: typeof o.type === 'string' ? o.type : frame.event, data }
}
