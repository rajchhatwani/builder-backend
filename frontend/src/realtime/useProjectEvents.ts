import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { publishTopics } from './bus'
import { keysForEvent, topicsForEvent, type RealtimeEvent } from './eventRouting'
import { connectProjectEvents, type PresenceUser, type StreamStatus } from './projectStream'

export const HEARTBEAT_MS = 15_000

/** Apply one event: invalidate the stale queries and nudge effect-loaded pages. */
export function applyEvent(qc: Pick<QueryClient, 'invalidateQueries'>, projectId: string, ev: RealtimeEvent): void {
  for (const queryKey of keysForEvent(ev, projectId)) void qc.invalidateQueries({ queryKey })
  publishTopics(topicsForEvent(ev))
}

/** Mounted once per open project in the v2 shell: one stream + a presence heartbeat for the current section. */
export function useProjectEvents(projectId: string, section: string): { status: StreamStatus; users: PresenceUser[] } {
  const qc = useQueryClient()
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const [users, setUsers] = useState<PresenceUser[]>([])

  useEffect(() => {
    setStatus('connecting'); setUsers([])
    const conn = connectProjectEvents({
      projectId, onStatus: setStatus, onPresence: setUsers, onEvent: (ev) => applyEvent(qc, projectId, ev),
    })
    return () => conn.close()
  }, [projectId, qc])

  useEffect(() => {
    if (status === 'stopped') return
    let dead = false
    const beat = async () => {
      try {
        await api.presenceHeartbeat(projectId, section)
        const list = await api.listPresence(projectId)
        if (!dead) setUsers(list)
      } catch { /* presence is best effort */ }
    }
    void beat()
    const t = setInterval(() => void beat(), HEARTBEAT_MS)
    return () => { dead = true; clearInterval(t) }
  }, [projectId, section, status === 'stopped'])

  return { status, users }
}
