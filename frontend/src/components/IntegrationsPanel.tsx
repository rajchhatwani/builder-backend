import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Member, ProjectToken } from '../api/types'
import { BASE_URL } from '../api/session'
import { useUser } from './AuthProvider'
import { useUi } from './Ui'

interface IntegrationsPanelProps {
  projectId: string
}

function when(iso: string | null): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'never' : d.toLocaleString()
}

/** The MCP endpoint URL for this builder, derived from BASE_URL (never from user input). */
function mcpEndpoint(): string {
  try {
    const url = new URL(BASE_URL, window.location.origin)
    return `${url.origin}${url.pathname.replace(/\/$/, '')}/mcp`
  } catch {
    return '/mcp'
  }
}

/** Settings page for MCP server access on a single project.
 *
 * Security surface:
 *  - Enabling MCP for a member asks for explicit confirmation and names the implications.
 *  - Only owners see the toggles; non-owners see read-only state and the endpoint URL.
 *  - Pinned-token revocation also asks for confirmation.
 *  - Raw tokens never pass through this page: new tokens are created on the Account page,
 *    and only their last-use timestamps and metadata are shown here.
 */
export function IntegrationsPanel({ projectId }: IntegrationsPanelProps) {
  const me = useUser()
  const { confirm, toast } = useUi()
  const [members, setMembers] = useState<Member[]>([])
  const [tokens, setTokens] = useState<ProjectToken[]>([])
  const [tokensLoaded, setTokensLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyUserId, setBusyUserId] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const endpoint = mcpEndpoint()

  const load = useCallback(async () => {
    setError(null)
    try {
      const next = await api.listMembers(projectId)
      setMembers(next)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't load the members.")
    }
  }, [projectId])

  const loadTokens = useCallback(async () => {
    try {
      const next = await api.listProjectTokens(projectId)
      setTokens(next)
      setTokensLoaded(true)
    } catch {
      // Non-owners get 403 here; silently leave the pinned-tokens section hidden.
      setTokensLoaded(true)
    }
  }, [projectId])

  useEffect(() => {
    load()
    loadTokens()
  }, [load, loadTokens])

  const iAmOwner = members.some((m) => m.user_id === me.id && m.role === 'owner')

  async function toggleMcp(member: Member) {
    const next = !member.mcp_enabled
    const message = next
      ? `This lets ${member.email} read and change this project's model through AI tools (Claude Desktop, Cursor and similar) and automation using an API token.`
      : `AI tools and scripts using ${member.email}'s tokens will immediately lose access to this project.`
    const ok = await confirm({
      title: next ? `Allow MCP access for ${member.email}?` : `Revoke MCP access for ${member.email}?`,
      message,
      confirmLabel: next ? 'Allow MCP access' : 'Revoke MCP access',
      danger: !next,
    })
    if (!ok) return
    setBusyUserId(member.user_id)
    try {
      await api.setMemberMcp(projectId, member.user_id, next)
      toast(next ? 'MCP access granted.' : 'MCP access revoked.')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't update MCP access.")
    } finally {
      setBusyUserId(null)
    }
  }

  async function copyEndpoint() {
    try {
      await navigator.clipboard.writeText(endpoint)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      toast('MCP endpoint copied.')
    } catch {
      toast('Copy failed. Select and copy manually.', 'danger')
    }
  }

  async function revokeToken(token: ProjectToken) {
    const ok = await confirm({
      title: `Revoke "${token.name}"?`,
      message: `This token belongs to ${token.user_email}. Anything using it stops working immediately.`,
      confirmLabel: 'Revoke token',
      danger: true,
    })
    if (!ok) return
    try {
      await api.revokeProjectToken(projectId, token.id)
      toast('Token revoked.')
      await loadTokens()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't revoke this token.")
    }
  }

  const enabledMembers = members.filter((m) => m.mcp_enabled)

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Integrations</h1>
          <p>
            Let AI tools and automation read and change this project through the Model Context
            Protocol (MCP). Access is off by default and controlled per member.
          </p>
        </div>
      </div>

      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}

      <section className="card stack">
        <h3>MCP server endpoint</h3>
        <p className="muted small-text">
          Point an MCP client (Claude Desktop, Cursor, custom scripts) at this URL. The client
          sends your personal API token in an <code>Authorization: Bearer</code> header; it never
          goes in the URL.
        </p>
        <div className="hstack">
          <code className="token-box" style={{ flex: 1 }}>
            {endpoint}
          </code>
          <button className="small" onClick={copyEndpoint}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <p className="muted small-text">
          Create a token on your <a href="#/account">Account</a> page. Give it only the MCP scopes
          you need (<code>mcp:read</code>, <code>mcp:write</code>, <code>mcp:generate</code>) and
          pin it to this project to narrow its reach.
        </p>
      </section>

      <section className="card stack">
        <div className="table-toolbar">
          <h3>Who may use MCP on this project</h3>
          <span className="muted small-text">
            {enabledMembers.length} of {members.length} member
            {members.length === 1 ? '' : 's'} enabled
          </span>
        </div>
        {!iAmOwner && (
          <p className="muted small-text">
            Only the project owner can grant or revoke MCP access. Ask your owner if you need it.
          </p>
        )}
        <table>
          <thead>
            <tr>
              <th>Member</th>
              <th>Role</th>
              <th>MCP access</th>
              {iAmOwner && <th />}
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id}>
                <td>
                  {m.email}
                  {m.user_id === me.id && <span className="muted"> (you)</span>}
                </td>
                <td>{m.role}</td>
                <td>
                  <span className={`badge ${m.mcp_enabled ? 'status-ok' : 'status-warn'}`}>
                    {m.mcp_enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </td>
                {iAmOwner && (
                  <td className="row-actions">
                    <button
                      type="button"
                      className={m.mcp_enabled ? 'ghost small' : 'small'}
                      data-variant={m.mcp_enabled ? 'danger' : undefined}
                      disabled={busyUserId === m.user_id}
                      onClick={() => toggleMcp(m)}
                    >
                      {busyUserId === m.user_id
                        ? 'Updating…'
                        : m.mcp_enabled
                          ? 'Disable'
                          : 'Enable'}
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {members.length === 0 && (
              <tr>
                <td colSpan={iAmOwner ? 4 : 3} className="muted">
                  No members yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {tokensLoaded && iAmOwner && (
        <section className="card stack">
          <h3>Tokens pinned to this project</h3>
          <p className="muted small-text">
            These are personal API tokens that any member has pinned to this project. As owner you
            can revoke any of them &mdash; useful if a teammate leaves or a token leaks.
          </p>
          {tokens.length === 0 ? (
            <p className="muted">No tokens are pinned to this project.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Owner</th>
                  <th>Scopes</th>
                  <th>Last used</th>
                  <th>Last MCP use</th>
                  <th>Expires</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {tokens.map((t) => (
                  <tr key={t.id}>
                    <td>
                      {t.name}
                      {t.description && (
                        <div className="muted small-text">{t.description}</div>
                      )}
                    </td>
                    <td>{t.user_email}</td>
                    <td>
                      <code className="small-text">{t.scopes.join(', ')}</code>
                      {t.last_mcp_use_at && (
                        <>
                          {' '}
                          <span className="badge status-ok" title="This token has been used by an MCP client">
                            MCP
                          </span>
                        </>
                      )}
                    </td>
                    <td>{when(t.last_used_at)}</td>
                    <td>{when(t.last_mcp_use_at)}</td>
                    <td>{when(t.expires_at)}</td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="ghost small"
                        data-variant="danger"
                        onClick={() => revokeToken(t)}
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  )
}
