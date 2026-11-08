import { useEffect, useState } from 'react'
import { api } from '../../api/client'

/** The signed-in user's role in this project (owner | editor | viewer), or null when it cannot be read.
 *  Null never blocks a decision: the server is the authority and answers 403. */
export function useMyRole(projectId: string): string | null {
  const [role, setRole] = useState<string | null>(null)
  useEffect(() => {
    let off = false
    Promise.all([api.me(), api.listMembers(projectId)]).then(([me, members]) => {
      if (!off) setRole(members.find((m) => m.user_id === me.id)?.role ?? null)
    }, () => undefined)
    return () => { off = true }
  }, [projectId])
  return role
}
