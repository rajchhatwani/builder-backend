import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../../../api/client'
import { connectProjectEvents } from '../../../../realtime/projectStream'
import type { PresenceUser, StreamStatus } from '../../../../realtime/projectStream'
import { projectKeys } from './status'

export function useProjectLive(id: string, section: string) {
  const client = useQueryClient()
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const key = [...projectKeys.project(id), 'presence'] as const
  const presence = useQuery({
    queryKey: key, queryFn: () => api.listPresence(id), enabled: Boolean(id) && status === 'live',
    retry: false, refetchInterval: 15_000,
  })

  useEffect(() => {
    if (!id) return
    let closed = false
    const connection = connectProjectEvents({
      projectId: id,
      onStatus: next => { if (!closed) setStatus(next) },
      onPresence: users => { if (!closed) client.setQueryData<PresenceUser[]>([...projectKeys.project(id), 'presence'], users) },
      onEvent: event => {
        if (!closed && ['spec.changed', 'import.committed', 'resync'].includes(event.type)) {
          void client.invalidateQueries({ queryKey: projectKeys.project(id),
            predicate: query => query.queryKey.at(-1) !== 'presence' })
        }
      },
    })
    return () => { closed = true; connection.close() }
  }, [client, id])

  useEffect(() => {
    if (!id || status !== 'live') return
    const beat = () => { if (!document.hidden) void api.presenceHeartbeat(id, section).catch(() => undefined) }
    beat()
    const interval = setInterval(beat, 15_000)
    return () => clearInterval(interval)
  }, [id, section, status])

  return { status, users: Array.isArray(presence.data) ? presence.data : [] }
}
