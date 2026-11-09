import { useProjectEvents } from './useProjectEvents'
import type { PresenceUser, StreamStatus } from './projectStream'

export const STATUS_TEXT: Record<StreamStatus, string> = {
  connecting: 'Connecting…', live: 'Live', reconnecting: 'Reconnecting…', stopped: 'Updates paused',
}

/** Names of the other people here, newest roster; empty when alone. Pure. */
export function othersHere(users: PresenceUser[], selfId: string | null): PresenceUser[] {
  return users.filter((u) => u.user_id !== selfId)
}

export function alsoHereText(others: PresenceUser[]): string {
  if (others.length === 0) return ''
  const names = others.slice(0, 3).map((u) => u.display)
  const more = others.length - names.length
  return `Also here: ${names.join(', ')}${more > 0 ? ` +${more}` : ''}`
}

/** View only: reserved width so a changing roster never shifts the header. */
export function LiveView({ status, users, selfId }: { status: StreamStatus; users: PresenceUser[]; selfId: string | null }) {
  const text = alsoHereText(othersHere(users, selfId))
  return (
    <span className="live-indicator small-text muted" data-testid="live-indicator">
      <span data-testid="live-status" data-status={status} className="live-status">{STATUS_TEXT[status]}</span>
      <span className="live-here" aria-live="polite" aria-atomic="true" data-testid="also-here" title={text}>{text}</span>
    </span>
  )
}

export function LiveIndicator({ projectId, section, selfId }: { projectId: string; section: string; selfId: string | null }) {
  const { status, users } = useProjectEvents(projectId, section)
  return <LiveView status={status} users={users} selfId={selfId} />
}
