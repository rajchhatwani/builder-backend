import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type {
  AuthProvider,
  IdentityProvider,
  IdpType,
  KeycloakConfig,
  KeycloakImpact,
  KeycloakMode,
  KeycloakWrite,
  MfaMode,
  Project,
  ValidationIssue,
} from '../api/types'
import { Modal } from './Modal'
import { link } from './Sidebar'
import { useUi } from './Ui'

interface KeycloakPanelProps {
  project: Project
  provider: AuthProvider
  issues: ValidationIssue[] | null
  /** Called after anything changed so the project page can reload. */
  onChanged: () => void
}

const IDP_LABELS: Record<IdpType, string> = {
  google: 'Google',
  microsoft: 'Microsoft Entra ID',
  github: 'GitHub',
  oidc: 'Other (OpenID Connect)',
}

const IDP_HELP: Record<IdpType, string> = {
  google: 'Sign in with a Google account. You can limit it to one Google Workspace domain.',
  microsoft:
    'Sign in with your company Microsoft account. It is limited to your own directory (tenant).',
  github: 'Sign in with a GitHub account.',
  oidc: 'Any provider that speaks OpenID Connect (Okta, Auth0, ...). Copy its endpoints from its discovery document.',
}

/** The environment variable that holds a login's client secret (matches the generator). */
export function secretEnvName(alias: string): string {
  return 'KC_IDP_' + alias.toUpperCase().replace(/-/g, '_') + '_CLIENT_SECRET'
}

function emptyProvider(type: IdpType, alias: string): IdentityProvider {
  return {
    alias,
    type,
    display_name: IDP_LABELS[type],
    client_id: '',
    tenant_id: null,
    hosted_domain: null,
    issuer: null,
    authorization_url: null,
    token_url: null,
    jwks_url: null,
    userinfo_url: null,
  }
}

function nullIfBlank(value: string | null): string | null {
  const trimmed = (value ?? '').trim()
  return trimmed === '' ? null : trimmed
}

interface Form {
  mode: KeycloakMode
  realm: string
  apiClientId: string
  webClientId: string
  redirectUris: string
  passwordMinLength: number
  mfa: MfaMode
  sessionIdleMinutes: number
  sessionMaxHours: number
  auditRetentionDays: number
  providers: IdentityProvider[]
  sourceProjectId: string
}

const DEFAULT_FORM: Form = {
  mode: 'own',
  realm: '',
  apiClientId: '',
  webClientId: '',
  redirectUris: 'http://localhost:3000/',
  passwordMinLength: 12,
  mfa: 'optional',
  sessionIdleMinutes: 30,
  sessionMaxHours: 10,
  auditRetentionDays: 90,
  providers: [],
  sourceProjectId: '',
}

function formFrom(config: KeycloakConfig): Form {
  return {
    mode: config.mode,
    realm: config.realm,
    apiClientId: config.api_client_id,
    webClientId: config.web_client_id,
    redirectUris: config.redirect_uris.join('\n'),
    passwordMinLength: config.password_min_length,
    mfa: config.mfa,
    sessionIdleMinutes: config.session_idle_minutes,
    sessionMaxHours: config.session_max_hours,
    auditRetentionDays: config.audit_retention_days,
    providers: config.identity_providers,
    sourceProjectId: config.source_project_id ?? '',
  }
}

function toWrite(form: Form): KeycloakWrite {
  return {
    mode: form.mode,
    realm: nullIfBlank(form.realm),
    api_client_id: nullIfBlank(form.apiClientId),
    web_client_id: nullIfBlank(form.webClientId),
    redirect_uris: form.redirectUris
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line !== ''),
    password_min_length: Number(form.passwordMinLength),
    mfa: form.mfa,
    session_idle_minutes: Number(form.sessionIdleMinutes),
    session_max_hours: Number(form.sessionMaxHours),
    audit_retention_days: Number(form.auditRetentionDays),
    identity_providers: form.mode === 'own' ? form.providers : [],
    source_project_id: form.mode === 'shared' ? nullIfBlank(form.sourceProjectId) : null,
  }
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

export function KeycloakPanel({ project, provider, issues, onChanged }: KeycloakPanelProps) {
  const { toast } = useUi()
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<KeycloakConfig | null>(null)
  const [form, setForm] = useState<Form>(DEFAULT_FORM)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [otherHubs, setOtherHubs] = useState<{ id: string; name: string; realm: string }[]>([])
  const [switching, setSwitching] = useState<'enable' | 'disable' | null>(null)

  const active = provider === 'keycloak'
  const slug = project.slug.replace(/_/g, '-')

  async function load() {
    setLoading(true)
    try {
      const loaded = await api.getKeycloak(project.id)
      setConfig(loaded)
      setForm(formFrom(loaded))
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setConfig(null)
        setForm(DEFAULT_FORM)
      } else {
        setMessage({ ok: false, text: errorText(err, 'Could not load the Keycloak settings.') })
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [project.id])

  // Projects whose own Keycloak this project could trust (shared mode).
  useEffect(() => {
    let cancelled = false
    api.listProjects(200, 0).then(async (page) => {
      const others = page.items.filter((p) => p.id !== project.id)
      const found = await Promise.all(
        others.map((p) =>
          api
            .getKeycloak(p.id)
            .then((c) => (c.mode === 'own' ? { id: p.id, name: p.name, realm: c.realm } : null))
            .catch(() => null),
        ),
      )
      if (!cancelled) setOtherHubs(found.filter((x): x is NonNullable<typeof x> => x !== null))
    })
    return () => {
      cancelled = true
    }
  }, [project.id])

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function updateProvider(index: number, patch: Partial<IdentityProvider>) {
    set(
      'providers',
      form.providers.map((p, i) => (i === index ? { ...p, ...patch } : p)),
    )
  }

  function addProvider(type: IdpType) {
    const taken = new Set(form.providers.map((p) => p.alias))
    let alias: string = type
    for (let n = 2; taken.has(alias); n += 1) alias = `${type}${n}`
    set('providers', [...form.providers, emptyProvider(type, alias)])
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const saved = await api.putKeycloak(project.id, toWrite(form))
      setConfig(saved)
      setForm(formFrom(saved))
      toast('Keycloak settings saved.')
      onChanged()
    } catch (err) {
      setMessage({ ok: false, text: errorText(err, 'Could not save the Keycloak settings.') })
    } finally {
      setSaving(false)
    }
  }

  const keycloakIssues = useMemo(
    () => (issues ?? []).filter((i) => i.path.startsWith('auth.keycloak')),
    [issues],
  )
  const realmPreview = form.realm.trim() || slug
  const own = form.mode === 'own'

  if (loading) {
    return (
      <div className="card">
        <p className="empty-state">Loading…</p>
      </div>
    )
  }

  return (
    <>
      <div className="card status-card" data-active={active ? 'true' : undefined}>
        <div className="status-card-text">
          <strong>{active ? 'Keycloak is on for this project' : 'Keycloak is off for this project'}</strong>
          <p className="muted">
            {active
              ? 'People sign in through Keycloak. Your backend only checks the tokens it issues.'
              : config
                ? 'The project uses built-in sign-in. Your Keycloak settings are saved: turn it on when you are ready.'
                : 'The project uses built-in sign-in. Fill in the settings below, then turn Keycloak on.'}
          </p>
        </div>
        {active ? (
          <button className="outline" data-variant="danger" onClick={() => setSwitching('disable')}>
            Turn off…
          </button>
        ) : (
          <button disabled={!config} title={config ? undefined : 'Save the settings first'} onClick={() => setSwitching('enable')}>
            Turn on…
          </button>
        )}
      </div>

      {!config && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <h3>Why Keycloak?</h3>
          <ul className="benefit-list">
            <li>
              <strong>Single sign-on.</strong> One login across all your platforms. Another project can
              use the same Keycloak.
            </li>
            <li>
              <strong>Sign in with Google, Microsoft Entra ID, GitHub</strong> or any OpenID Connect provider,
              already configured in the download.
            </li>
            <li>
              <strong>Security you do not have to build:</strong> multi-factor sign-in, password rules, lock-out after
              repeated failures, an audit log, and an admin console to manage users and roles.
            </li>
            <li>
              <strong>Ready to run.</strong> The download includes Keycloak itself (or connects to yours), with the
              settings below already applied.
            </li>
          </ul>
        </div>
      )}

      {active && keycloakIssues.length > 0 && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-3)' }}>
            {keycloakIssues.length} {keycloakIssues.length === 1 ? 'thing needs' : 'things need'} fixing before you can
            generate.
          </div>
          <ul className="issue-list">
            {keycloakIssues.map((issue, i) => (
              <li key={i}>
                <span>
                  {issue.message}
                  <small className="muted"> · {issue.path.replace('auth.keycloak.', '')}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="card" onSubmit={handleSave}>
        {message && (
          <div role="alert" data-variant={message.ok ? 'success' : 'danger'} style={{ marginBlockEnd: 'var(--space-4)' }}>
            {message.text}
          </div>
        )}

        <details open className="auth-section">
          <summary>Where Keycloak runs</summary>
          <div className="auth-section-body">
            <div className="choice-grid">
              <label className="choice" data-selected={own ? 'true' : undefined}>
                <input type="radio" name="mode" checked={own} onChange={() => set('mode', 'own')} />
                <strong>Include Keycloak in this project</strong>
                <span className="muted">
                  The download starts its own Keycloak, with your realm, clients, roles and logins already set up.
                </span>
              </label>
              <label className="choice" data-selected={!own ? 'true' : undefined}>
                <input type="radio" name="mode" checked={!own} onChange={() => set('mode', 'shared')} />
                <strong>Use a Keycloak that already exists</strong>
                <span className="muted">
                  For a second platform on the same realm: people sign in once and are signed in on both.
                </span>
              </label>
            </div>
            {!own && (
              <label style={{ marginBlockStart: 'var(--space-4)' }}>
                Which project runs it? (optional, stops it being switched off while this one uses it)
                <select
                  value={form.sourceProjectId}
                  onChange={(e) => {
                    const hub = otherHubs.find((h) => h.id === e.target.value)
                    setForm((f) => ({ ...f, sourceProjectId: e.target.value, realm: hub ? hub.realm : f.realm }))
                  }}
                >
                  <option value="">Not one of my projects</option>
                  {otherHubs.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.name} (realm {h.realm})
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </details>

        <details open className="auth-section">
          <summary>Realm and clients</summary>
          <div className="auth-section-body">
            <p className="muted">
              A realm is one set of users. Each project has its own API client, so roles never clash between
              platforms.
            </p>
            <div className="field-grid">
              <label>
                Realm
                <input value={form.realm} placeholder={slug} onChange={(e) => set('realm', e.target.value)} />
              </label>
              <label>
                API client
                <input value={form.apiClientId} placeholder={`${slug}-api`} onChange={(e) => set('apiClientId', e.target.value)} />
              </label>
              <label>
                Web client
                <input value={form.webClientId} placeholder={`${slug}-web`} onChange={(e) => set('webClientId', e.target.value)} />
              </label>
            </div>
            <label style={{ marginBlockStart: 'var(--space-4)' }}>
              Redirect URLs: where people return after signing in (one per line)
              <textarea
                rows={3}
                value={form.redirectUris}
                placeholder="https://app.example.com/auth/callback"
                onChange={(e) => set('redirectUris', e.target.value)}
              />
            </label>
            <p className="muted small-text">
              Exact addresses only, no wildcards. Use https, except for localhost while you develop.
            </p>
          </div>
        </details>

        {own && (
          <details open className="auth-section">
            <summary>Security</summary>
            <div className="auth-section-body">
              <div className="field-grid">
                <label>
                  Minimum password length
                  <input
                    type="number"
                    min={8}
                    max={128}
                    value={form.passwordMinLength}
                    onChange={(e) => set('passwordMinLength', Number(e.target.value))}
                  />
                </label>
                <label>
                  Second factor (authenticator app)
                  <select value={form.mfa} onChange={(e) => set('mfa', e.target.value as MfaMode)}>
                    <option value="off">Off</option>
                    <option value="optional">Optional: people can turn it on</option>
                    <option value="required">Required for everyone</option>
                  </select>
                </label>
                <label>
                  Sign out after this many idle minutes
                  <input
                    type="number"
                    min={5}
                    value={form.sessionIdleMinutes}
                    onChange={(e) => set('sessionIdleMinutes', Number(e.target.value))}
                  />
                </label>
                <label>
                  Longest session (hours)
                  <input
                    type="number"
                    min={1}
                    max={720}
                    value={form.sessionMaxHours}
                    onChange={(e) => set('sessionMaxHours', Number(e.target.value))}
                  />
                </label>
                <label>
                  Keep the audit log for (days)
                  <input
                    type="number"
                    min={7}
                    max={3650}
                    value={form.auditRetentionDays}
                    onChange={(e) => set('auditRetentionDays', Number(e.target.value))}
                  />
                </label>
              </div>
              <p className="muted small-text">
                Always on: lock-out after 5 failed attempts, refresh tokens that cannot be replayed, a record of every
                sign-in and admin change. Email verification, self-registration and the access token lifetime come from{' '}
                <a href={link(`/p/${project.id}/auth`)}>Authentication</a>; roles from{' '}
                <a href={link(`/p/${project.id}/access`)}>Roles &amp; access</a>.
              </p>
            </div>
          </details>
        )}

        {own && (
          <details open className="auth-section">
            <summary>Sign-in with other accounts</summary>
            <div className="auth-section-body">
              {form.providers.length === 0 && (
                <p className="muted">
                  Add the accounts people can sign in with, in addition to a Keycloak password. You will need an app
                  registered with each provider.
                </p>
              )}
              {form.providers.map((idp, index) => (
                <div className="idp-card" key={index}>
                  <div className="idp-card-head">
                    <strong>{IDP_LABELS[idp.type]}</strong>
                    <button
                      type="button"
                      className="ghost small"
                      data-variant="danger"
                      onClick={() =>
                        set(
                          'providers',
                          form.providers.filter((_, i) => i !== index),
                        )
                      }
                    >
                      Remove
                    </button>
                  </div>
                  <p className="muted small-text">{IDP_HELP[idp.type]}</p>
                  <div className="field-grid">
                    <label>
                      Name on the sign-in button
                      <input
                        value={idp.display_name ?? ''}
                        onChange={(e) => updateProvider(index, { display_name: e.target.value })}
                      />
                    </label>
                    <label>
                      Short name (used in addresses)
                      <input
                        value={idp.alias}
                        pattern="^[a-z][a-z0-9-]*$"
                        onChange={(e) => updateProvider(index, { alias: e.target.value })}
                      />
                    </label>
                    <label>
                      Client ID
                      <input
                        value={idp.client_id}
                        onChange={(e) => updateProvider(index, { client_id: e.target.value })}
                      />
                    </label>
                    {idp.type === 'google' && (
                      <label>
                        Only this Google Workspace domain (optional)
                        <input
                          value={idp.hosted_domain ?? ''}
                          placeholder="example.com"
                          onChange={(e) => updateProvider(index, { hosted_domain: e.target.value })}
                        />
                      </label>
                    )}
                    {idp.type === 'microsoft' && (
                      <label>
                        Directory (tenant) ID
                        <input
                          value={idp.tenant_id ?? ''}
                          placeholder="00000000-0000-0000-0000-000000000000"
                          onChange={(e) => updateProvider(index, { tenant_id: e.target.value })}
                        />
                      </label>
                    )}
                  </div>
                  {idp.type === 'oidc' && (
                    <div className="field-grid" style={{ marginBlockStart: 'var(--space-3)' }}>
                      <label>
                        Issuer
                        <input value={idp.issuer ?? ''} onChange={(e) => updateProvider(index, { issuer: e.target.value })} />
                      </label>
                      <label>
                        Authorization URL
                        <input
                          value={idp.authorization_url ?? ''}
                          onChange={(e) => updateProvider(index, { authorization_url: e.target.value })}
                        />
                      </label>
                      <label>
                        Token URL
                        <input value={idp.token_url ?? ''} onChange={(e) => updateProvider(index, { token_url: e.target.value })} />
                      </label>
                      <label>
                        Keys (JWKS) URL
                        <input value={idp.jwks_url ?? ''} onChange={(e) => updateProvider(index, { jwks_url: e.target.value })} />
                      </label>
                      <label>
                        User info URL (optional)
                        <input
                          value={idp.userinfo_url ?? ''}
                          onChange={(e) => updateProvider(index, { userinfo_url: e.target.value })}
                        />
                      </label>
                    </div>
                  )}
                  <p className="muted small-text">
                    In {IDP_LABELS[idp.type]}&apos;s console, register this redirect address (use your real Keycloak address in
                    place of localhost):{' '}
                    <code>
                      http://localhost:8081/realms/{realmPreview}/broker/{idp.alias || 'alias'}/endpoint
                    </code>
                    . Its secret never goes here: after you download, put it in <code>.env</code> as{' '}
                    <code>{secretEnvName(idp.alias || 'alias')}</code>.
                  </p>
                </div>
              ))}
              <div className="hstack" style={{ gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                {(Object.keys(IDP_LABELS) as IdpType[]).map((type) => (
                  <button key={type} type="button" className="outline small" onClick={() => addProvider(type)}>
                    + {IDP_LABELS[type]}
                  </button>
                ))}
              </div>
            </div>
          </details>
        )}

        <div style={{ marginBlockStart: 'var(--space-4)' }}>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>

      <SwitchDialog
        projectId={project.id}
        action={switching}
        onClose={() => setSwitching(null)}
        onDone={() => {
          setSwitching(null)
          load()
          onChanged()
        }}
      />
    </>
  )
}

interface SwitchDialogProps {
  projectId: string
  action: 'enable' | 'disable' | null
  onClose: () => void
  onDone: () => void
}

/** Shows what turning Keycloak on or off changes before the user agrees to it. */
function SwitchDialog({ projectId, action, onClose, onDone }: SwitchDialogProps) {
  const { toast } = useUi()
  const [impact, setImpact] = useState<KeycloakImpact | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setImpact(null)
    setError(null)
    if (action === null) return
    let cancelled = false
    api
      .keycloakImpact(projectId, action)
      .then((result) => {
        if (!cancelled) setImpact(result)
      })
      .catch((err) => {
        if (!cancelled) setError(errorText(err, 'Could not check what this changes.'))
      })
    return () => {
      cancelled = true
    }
  }, [projectId, action])

  async function confirm(event: FormEvent) {
    event.preventDefault()
    if (action === null) return
    setBusy(true)
    setError(null)
    try {
      await api.switchKeycloak(projectId, action)
      toast(action === 'enable' ? 'Keycloak is on.' : 'Keycloak is off. Your settings are kept.')
      onDone()
    } catch (err) {
      setError(errorText(err, 'Could not switch.'))
    } finally {
      setBusy(false)
    }
  }

  const turningOn = action === 'enable'
  return (
    <Modal open={action !== null} onClose={onClose}>
      <form onSubmit={confirm}>
        <header>
          <h3>{turningOn ? 'Turn on Keycloak?' : 'Turn off Keycloak?'}</h3>
          <p>
            {turningOn
              ? 'Your backend will check Keycloak tokens instead of issuing its own.'
              : 'Your backend goes back to built-in sign-in.'}
          </p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              {error}
            </div>
          )}
          {!impact && !error && <p className="muted">Checking what this changes…</p>}
          {impact && impact.blockers.length > 0 && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              <div>
                <strong>Not possible yet</strong>
                <ul className="impact-list">
                  {impact.blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {impact && impact.warnings.length > 0 && (
            <>
              <strong>Before you continue</strong>
              <ul className="impact-list">
                {impact.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </>
          )}
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            data-variant={turningOn ? undefined : 'danger'}
            disabled={busy || !impact || !impact.can_proceed}
          >
            {busy ? 'Working…' : turningOn ? 'Turn on Keycloak' : 'Turn off Keycloak'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
