import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { ApiTokenCreated, ApiTokenInfo, Project } from '../api/types'
import { useUser } from '../components/AuthProvider'
import { Modal } from '../components/Modal'
import { PasswordForm } from '../components/PasswordForm'
import { TwoFactorSection } from '../components/TwoFactorSection'
import { useUi } from '../components/Ui'

interface ScopeDef {
  id: string
  label: string
  help: string
  group: 'api' | 'mcp'
}

const SCOPES: ScopeDef[] = [
  { id: 'read', label: 'Read', help: 'See projects, models and settings', group: 'api' },
  { id: 'write', label: 'Write', help: 'Change models and settings (includes read)', group: 'api' },
  { id: 'generate', label: 'Generate', help: 'Download generated code: the zip leaves the platform', group: 'api' },
  { id: 'mcp:read', label: 'MCP read', help: 'Let an AI tool read the project through MCP', group: 'mcp' },
  { id: 'mcp:write', label: 'MCP write', help: 'Let an AI tool change the model through MCP (editor+ role required)', group: 'mcp' },
  { id: 'mcp:generate', label: 'MCP generate', help: 'Let an AI tool request a code download through MCP', group: 'mcp' },
]

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : 'never'
}

function NewTokenDialog({
  open,
  projects,
  onClose,
  onCreated,
}: {
  open: boolean
  projects: Project[]
  onClose: () => void
  onCreated: (token: ApiTokenCreated) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [scopes, setScopes] = useState<string[]>(['read'])
  const [days, setDays] = useState(90)
  const [projectId, setProjectId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await api.createApiToken({
        name,
        description: description.trim() || null,
        scopes,
        expires_in_days: days,
        project_id: projectId || null,
      })
      setName('')
      setDescription('')
      setScopes(['read'])
      onCreated(created)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    } finally {
      setBusy(false)
    }
  }

  function toggle(id: string) {
    setScopes((current) => (current.includes(id) ? current.filter((s) => s !== id) : [...current, id]))
  }

  return (
    <Modal open={open} onClose={onClose}>
      <form onSubmit={submit}>
        <header>
          <h3>New API token</h3>
          <p>For scripts, CI and tools such as Lovable. Give it only what it needs.</p>
        </header>
        <div className="stack">
          {error && (
            <div role="alert" data-variant="danger">
              {error}
            </div>
          )}
          <label>
            Name
            <input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="CI pipeline" />
          </label>
          <label>
            Description <span className="muted small-text">(optional, 255 characters)</span>
            <input
              maxLength={255}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this token for?"
            />
          </label>
          <fieldset>
            <legend>API scopes</legend>
            {SCOPES.filter((s) => s.group === 'api').map((s) => (
              <label key={s.id} className="check-row">
                <input type="checkbox" checked={scopes.includes(s.id)} onChange={() => toggle(s.id)} />
                <span>
                  <strong>{s.label}</strong> <span className="muted small-text">{s.help}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend>MCP scopes (for AI tools)</legend>
            <p className="muted small-text">
              Only enable what the client actually needs. MCP access also requires the project
              owner to enable MCP for your member in the project's Integrations page.
            </p>
            {SCOPES.filter((s) => s.group === 'mcp').map((s) => (
              <label key={s.id} className="check-row">
                <input type="checkbox" checked={scopes.includes(s.id)} onChange={() => toggle(s.id)} />
                <span>
                  <strong>{s.label}</strong> <span className="muted small-text">{s.help}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <label>
            Limit to one project (recommended)
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">All my projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Expires after
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
              <option value={365}>1 year</option>
            </select>
          </label>
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={busy || scopes.length === 0}>
            {busy ? 'Creating…' : 'Create token'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

export function AccountPage() {
  const user = useUser()
  const { confirm, toast } = useUi()
  const [tokens, setTokens] = useState<ApiTokenInfo[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [dialog, setDialog] = useState(false)
  const [fresh, setFresh] = useState<ApiTokenCreated | null>(null)

  const load = useCallback(async () => {
    const [t, p] = await Promise.all([api.listApiTokens(), api.listProjects(200, 0)])
    setTokens(t)
    setProjects(p.items)
  }, [])

  useEffect(() => {
    load().catch(() => undefined)
  }, [load])

  async function revoke(token: ApiTokenInfo) {
    const ok = await confirm({
      title: `Revoke "${token.name}"?`,
      message: 'Anything using this token stops working immediately.',
      confirmLabel: 'Revoke token',
      danger: true,
    })
    if (!ok) return
    await api.revokeApiToken(token.id)
    toast('Token revoked.')
    load()
  }

  async function signOutEverywhere() {
    const ok = await confirm({
      title: 'Sign out everywhere?',
      message: 'Every browser and device, including this one, will need to sign in again.',
      confirmLabel: 'Sign out everywhere',
    })
    if (!ok) return
    await api.logoutEverywhere()
    window.location.hash = '#/'
    window.location.reload()
  }

  const projectName = (id: string | null) =>
    id ? (projects.find((p) => p.id === id)?.name ?? 'a project') : 'All projects'
  const active = tokens.filter((t) => !t.revoked_at && new Date(t.expires_at) > new Date())

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Account</h1>
          <p>
            {user.email}
            {user.platform_role !== 'customer' && ' · platform staff'}
          </p>
        </div>
      </div>

      <section className="card stack">
        <h3>Password</h3>
        <PasswordForm />
      </section>

      <TwoFactorSection />

      <section className="card stack">
        <div className="table-toolbar">
          <h3>API tokens</h3>
          <button onClick={() => setDialog(true)}>New token</button>
        </div>
        {fresh && (
          <div role="alert" data-variant="success" className="stack">
            <strong>Copy your token now. It will not be shown again.</strong>
            <code className="token-box">{fresh.token}</code>
            <div>
              <button
                className="small"
                onClick={() => navigator.clipboard.writeText(fresh.token).then(() => toast('Copied.'))}
              >
                Copy
              </button>{' '}
              <button className="outline small" onClick={() => setFresh(null)}>
                I have saved it
              </button>
            </div>
          </div>
        )}
        {active.length === 0 ? (
          <p className="muted">No active tokens.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Can</th>
                <th>For</th>
                <th>Last used</th>
                <th>Last MCP use</th>
                <th>Expires</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {active.map((t) => {
                const hasMcpScope = t.scopes.some((s) => s.startsWith('mcp:'))
                return (
                  <tr key={t.id}>
                    <td>
                      {t.name}
                      {t.description && <div className="muted small-text">{t.description}</div>}
                    </td>
                    <td>
                      <code className="small-text">{t.scopes.join(', ')}</code>
                      {hasMcpScope && (
                        <>
                          {' '}
                          <span className="badge status-ok" title="This token can be used by MCP clients">
                            MCP
                          </span>
                        </>
                      )}
                    </td>
                    <td>{projectName(t.project_id)}</td>
                    <td>{when(t.last_used_at)}</td>
                    <td>{when(t.last_mcp_use_at)}</td>
                    <td>{when(t.expires_at)}</td>
                    <td className="row-actions">
                      <button className="ghost small" data-variant="danger" onClick={() => revoke(t)}>
                        Revoke
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="card stack">
        <h3>Sessions</h3>
        <p className="muted">Lost a device, or finished on a shared computer?</p>
        <div>
          <button className="outline" data-variant="danger" onClick={signOutEverywhere}>
            Sign out everywhere
          </button>
        </div>
      </section>

      <NewTokenDialog
        open={dialog}
        projects={projects}
        onClose={() => setDialog(false)}
        onCreated={(token) => {
          setDialog(false)
          setFresh(token)
          load()
        }}
      />
    </>
  )
}
