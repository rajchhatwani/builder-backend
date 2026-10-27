import type { OrgMember } from '../api/types'

/** §8: non-admins get told who to ask, instead of a dead end. */
export function AskAdmin({ members, what }: { members: OrgMember[]; what: string }) {
  const owners = members.filter((m) => m.role === 'owner')
  return (
    <div role="alert" data-variant="warning">
      Only owners and admins can {what}.{' '}
      {owners.length > 0 && (
        <>
          Ask{' '}
          {owners.map((o, i) => (
            <span key={o.user_id}>
              {i > 0 && (i === owners.length - 1 ? ' or ' : ', ')}
              <a href={`mailto:${o.email}`}>{o.name || o.email}</a>
            </span>
          ))}
          .
        </>
      )}
    </div>
  )
}
