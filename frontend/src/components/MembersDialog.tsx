import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Member, MemberRole } from '../api/types'
import { useUser } from './AuthProvider'
import { Modal } from './Modal'
import { useUi } from './Ui'

const ROLES: { id: MemberRole; label: string; help: string }[] = [
  { id: 'viewer', label: 'Viewer', help: 'Can look at everything, change nothing' },
  { id: 'editor', label: 'Editor', help: 'Can change the model and settings' },
  { id: 'owner', label: 'Owner', help: 'Also manages people, credentials and deletion' },
]

interface MembersDialogProps {
  open: boolean
  projectId: string
  projectName: string
  onClose: () => void
}

export function MembersDialog({ open, projectId, projectName, onClose }: MembersDialogProps) {
  const me = useUser()
  const { confirm, toast } = useUi()
  const [members, setMembers] = useState<Member[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<MemberRole>('viewer')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setMembers(await api.listMembers(projectId))
  }, [projectId])

  useEffect(() => {
    if (open) load().catch(() => setError("Can't load the members."))
  }, [open, load])

  const iAmOwner = members.some((m) => m.user_id === me.id && m.role === 'owner')

  async function guarded(action: () => Promise<unknown>, done: string) {
    setError(null)
    try {
      await action()
      toast(done)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault()
    await guarded(() => api.addMember(projectId, email, role), 'Member added.')
    setEmail('')
  }

  async function remove(member: Member) {
    const ok = await confirm({
      title: `Remove ${member.email}?`,
      message: 'They lose access to this project immediately.',
      confirmLabel: 'Remove',
      danger: true,
    })
    if (ok) await guarded(() => api.removeMember(projectId, member.user_id), 'Member removed.')
  }

  return (
    <Modal open={open} onClose={onClose}>
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <header>
          <h3>People with access to {projectName}</h3>
          <p>They need an account on this platform first.</p>
        </header>
        <div className="stack">
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <table>
            <tbody>
              {members.map((m) => (
                <tr key={m.user_id}>
                  <td>
                    {m.email}
                    {m.user_id === me.id && <span className="muted"> (you)</span>}
                  </td>
                  <td>
                    {iAmOwner ? (
                      <select
                        aria-label={`Role of ${m.email}`}
                        value={m.role}
                        onChange={(e) =>
                          guarded(
                            () => api.setMemberRole(projectId, m.user_id, e.target.value as MemberRole),
                            'Role updated.',
                          )
                        }
                      >
                        {ROLES.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      m.role
                    )}
                  </td>
                  <td className="row-actions">
                    {iAmOwner && (
                      <button type="button" className="ghost small" data-variant="danger" onClick={() => remove(m)}>
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {iAmOwner ? (
            <div className="field-grid">
              <label>
                Email
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="teammate@example.com"
                />
              </label>
              <label>
                Role
                <select value={role} onChange={(e) => setRole(e.target.value as MemberRole)}>
                  {ROLES.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.label}: {r.help}
                    </option>
                  ))}
                </select>
              </label>
              <div>
                <button type="button" onClick={add} disabled={!email}>
                  Add
                </button>
              </div>
            </div>
          ) : (
            <p className="muted small-text">Only owners can change who has access.</p>
          )}
        </div>
        <footer>
          <button type="button" onClick={onClose}>
            Done
          </button>
        </footer>
      </form>
    </Modal>
  )
}
