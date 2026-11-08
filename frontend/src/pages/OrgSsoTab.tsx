import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { ssoTestText } from '../api/ssoErrors'
import type { Organization, OrgMember, SsoCheck, SsoConfig, SsoConfigWrite, SsoDomain, SsoProtocol } from '../api/types'
import { AskAdmin } from '../components/AskAdmin'
import { Copyable } from '../components/Copyable'
import { link } from '../components/Sidebar'
import { useUi } from '../components/Ui'
import { OrgScimSection } from './OrgScimSection'

const ERRORS: Record<string, string> = {
  domain_taken: 'Another organization already claimed this domain.',
  public_email_domain: "Public email domains (gmail.com and the like) can't be used for SSO.",
  invalid_domain: "That doesn't look like a domain name.",
  last_verified_domain: "This is the last verified domain and SSO is on. Turn SSO off first.",
  domain_not_verified: "The TXT record isn't visible yet. DNS changes can take a while; check the record and try again.",
  no_verified_domain: 'Verify at least one domain before turning SSO on.',
  sso_not_configured: 'Save the identity provider settings first.',
  invalid_certificate: "The certificate couldn't be read. Paste the PEM text, including the BEGIN/END lines.",
  insecure_url: 'The URL must be https and point at a public address.',
  invalid_url: "That URL isn't valid.",
  oidc_client_secret_required: 'Enter the client secret.',
}

function message(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server."
  return ERRORS[err.code] ?? err.message
}

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

/** The `sso_test` result in `#/org/<slug>/sso?sso_test=<result>`. */
function testResultFromHash(): string | null {
  const query = window.location.hash.split('?')[1]
  return query ? new URLSearchParams(query).get('sso_test') : null
}

const CHECK_LABEL: Record<string, string> = {
  plan: 'Plan includes SSO',
  verified_domain: 'Verified domain',
  configuration: 'Configuration',
  active: 'Turned on',
  certificate: 'IdP certificate',
  client_secret: 'Client secret',
  discovery: 'OIDC discovery document',
  jwks: 'Signing keys (JWKS)',
  last_test: 'Last test sign-in',
}

/** Renders a configuration check (`…/sso/check`); also used by the admin console. */
export function SsoChecklist({ check }: { check: SsoCheck }) {
  return (
    <div className="stack">
      <div role="alert" data-variant={check.ok ? 'success' : 'warning'}>
        {check.ok ? 'Everything needed for SSO is in place.' : 'Some things need attention.'}
      </div>
      <ul className="checklist">
        {check.checks.map((c) => (
          <li key={c.name}>
            <span className={`badge ${c.status === 'ok' ? 'status-ok' : c.status === 'warning' ? 'status-warn' : 'status-err'}`}>
              {c.status}
            </span>{' '}
            <strong>{CHECK_LABEL[c.name] ?? c.name}</strong>
            {c.detail && <span className="muted small-text"> — {c.detail}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function DomainRow({ slug, domain, onChanged, setError }: { slug: string; domain: SsoDomain; onChanged: () => void; setError: (m: string | null) => void }) {
  const { confirm, toast } = useUi()
  const [showRecord, setShowRecord] = useState(!domain.verified_at)

  async function verify() {
    setError(null)
    try {
      await api.verifySsoDomain(slug, domain.domain)
      toast(`${domain.domain} is verified.`)
      onChanged()
    } catch (err) {
      setShowRecord(true)
      setError(message(err))
    }
  }

  async function remove() {
    const ok = await confirm({
      title: `Remove ${domain.domain}?`,
      message: 'People with addresses on this domain can no longer sign in through your identity provider.',
      confirmLabel: 'Remove domain',
      danger: true,
    })
    if (!ok) return
    setError(null)
    try {
      await api.removeSsoDomain(slug, domain.domain)
      onChanged()
    } catch (err) {
      setError(message(err))
    }
  }

  return (
    <li className="stack">
      <div className="table-toolbar">
        <span>
          <strong>{domain.domain}</strong>{' '}
          {domain.verified_at ? (
            <span className="badge status-ok">verified</span>
          ) : (
            <span className="badge status-warn">waiting for DNS</span>
          )}
        </span>
        <span className="hstack">
          {!domain.verified_at && (
            <button type="button" className="small" onClick={verify}>
              Verify
            </button>
          )}
          {domain.verified_at && (
            <button type="button" className="ghost small" onClick={() => setShowRecord((s) => !s)}>
              {showRecord ? 'Hide record' : 'DNS record'}
            </button>
          )}
          <button type="button" className="ghost small" data-variant="danger" onClick={remove}>
            Remove
          </button>
        </span>
      </div>
      {showRecord && (
        <div className="stack">
          {!domain.verified_at && (
            <p className="small-text">Add this DNS record at your domain host, then press Verify. It can stay in place afterwards.</p>
          )}
          <Copyable label="Type" value={domain.dns_record_type ?? 'TXT'} />
          <Copyable label="Name" value={domain.dns_record_name} />
          <Copyable label="Value" value={domain.dns_record_value} />
        </div>
      )}
    </li>
  )
}

function ConfigForm({ slug, config, onSaved }: { slug: string; config: SsoConfig; onSaved: (c: SsoConfig) => void }) {
  const { toast } = useUi()
  const [protocol, setProtocol] = useState<SsoProtocol>(config.protocol ?? 'saml')
  const [entityId, setEntityId] = useState(config.idp_entity_id ?? '')
  const [ssoUrl, setSsoUrl] = useState(config.idp_sso_url ?? '')
  const [certPem, setCertPem] = useState('')
  const [discoveryUrl, setDiscoveryUrl] = useState(config.oidc_discovery_url ?? '')
  const [clientId, setClientId] = useState(config.oidc_client_id ?? '')
  const [clientSecret, setClientSecret] = useState('')
  const [jit, setJit] = useState(config.jit_enabled ?? false)
  const [jitRole, setJitRole] = useState<'member' | 'admin'>(config.jit_role ?? 'member')
  const [trustUnverified, setTrustUnverified] = useState(config.trust_unverified_email ?? false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const sameProtocol = config.configured && config.protocol === protocol
  const hasCert = sameProtocol && !!config.idp_certificate
  const hasSecret = sameProtocol && !!config.oidc_client_secret_set

  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const data: SsoConfigWrite = { protocol, jit_enabled: jit, jit_role: jitRole }
    if (protocol === 'saml') {
      data.idp_entity_id = entityId.trim()
      data.idp_sso_url = ssoUrl.trim()
      // Blank keeps the stored certificate.
      if (certPem.trim()) data.idp_cert_pem = certPem.trim()
    } else {
      data.oidc_discovery_url = discoveryUrl.trim()
      data.oidc_client_id = clientId.trim()
      data.trust_unverified_email = trustUnverified
      // Write-only: blank keeps the stored secret.
      if (clientSecret) data.oidc_client_secret = clientSecret
    }
    try {
      const saved = await api.saveSsoConfig(slug, data)
      setCertPem('')
      setClientSecret('')
      toast('SSO settings saved.')
      onSaved(saved)
    } catch (err) {
      setError(message(err)) // 402 sso_not_in_plan also opens the upgrade prompt
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card stack" onSubmit={save}>
      <h3>Identity provider</h3>
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      <label>
        Protocol
        <select value={protocol} onChange={(e) => setProtocol(e.target.value as SsoProtocol)}>
          <option value="saml">SAML 2.0 (Okta, Entra ID, OneLogin…)</option>
          <option value="oidc">OpenID Connect (Google Workspace, Okta, Auth0…)</option>
        </select>
      </label>
      {protocol === 'saml' ? (
        <>
          <label>
            IdP entity ID (issuer)
            <input required value={entityId} onChange={(e) => setEntityId(e.target.value)} placeholder="http://www.okta.com/exk…" />
          </label>
          <label>
            IdP single sign-on URL
            <input required type="url" value={ssoUrl} onChange={(e) => setSsoUrl(e.target.value)} placeholder="https://…/sso/saml" />
          </label>
          <label>
            IdP signing certificate (PEM)
            {hasCert && config.idp_certificate && (
              <small className="muted field-note">
                Current: {config.idp_certificate.subject} · expires {new Date(config.idp_certificate.not_after).toLocaleDateString()} · SHA-256{' '}
                <code>{config.idp_certificate.sha256_fingerprint}</code>. Leave blank to keep it.
              </small>
            )}
            <textarea
              required={!hasCert}
              rows={6}
              spellCheck={false}
              value={certPem}
              onChange={(e) => setCertPem(e.target.value)}
              placeholder="-----BEGIN CERTIFICATE-----"
            />
          </label>
        </>
      ) : (
        <>
          <label>
            Discovery URL
            <input
              required
              type="url"
              value={discoveryUrl}
              onChange={(e) => setDiscoveryUrl(e.target.value)}
              placeholder="https://…/.well-known/openid-configuration"
            />
          </label>
          <label>
            Client ID
            <input required value={clientId} onChange={(e) => setClientId(e.target.value)} />
          </label>
          <label>
            Client secret
            <input
              type="password"
              autoComplete="off"
              required={!hasSecret}
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder={hasSecret ? 'Set. Leave blank to keep it' : ''}
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={trustUnverified}
              onChange={(e) => setTrustUnverified(e.target.checked)}
            />
            <span>
              <strong>Accept sign-ins that don't say the e-mail is verified</strong>{' '}
              <span className="muted small-text">
                Needed for providers such as Microsoft Entra ID that send no email_verified claim. Only turn this
                on if people can't change their own e-mail address in your identity provider; otherwise someone
                could sign in as a colleague.
              </span>
            </span>
          </label>
        </>
      )}
      <label className="check-row">
        <input type="checkbox" checked={jit} onChange={(e) => setJit(e.target.checked)} />
        <span>
          <strong>Create accounts on first sign-in</strong>{' '}
          <span className="muted small-text">
            People on your verified domains join the organization when they first sign in through SSO (uses a seat).
            Otherwise they need an invitation first.
          </span>
        </span>
      </label>
      {jit && (
        <label>
          Role for new members
          <select value={jitRole} onChange={(e) => setJitRole(e.target.value as 'member' | 'admin')}>
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
        </label>
      )}
      <div>
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

/** `#/org/<slug>/sso` — single sign-on and SCIM settings for a team org (§8, §12.D.6, §12.E.5). */
export function OrgSsoTab({ org, members }: { org: Organization; members: OrgMember[] }) {
  const { confirm, toast } = useUi()
  const canAdmin = org.my_role === 'owner' || org.my_role === 'admin'
  const [config, setConfig] = useState<SsoConfig | null>(null)
  const [check, setCheck] = useState<SsoCheck | null>(null)
  const [testResult, setTestResult] = useState<string | null>(testResultFromHash)
  const [newDomain, setNewDomain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api
      .ssoConfig(org.slug)
      .then(setConfig)
      .catch((err) => setError(message(err)))
  }, [org.slug])

  useEffect(() => {
    if (canAdmin) load()
  }, [canAdmin, load])

  if (!canAdmin) return <AskAdmin members={members} what="see and change single sign-on and SCIM provisioning" />
  if (!config) return error ? <div role="alert" data-variant="danger">{error}</div> : <p className="empty-state">Loading…</p>

  const planHref = link(`/org/${encodeURIComponent(org.slug)}/plan`)
  const verified = config.domains.filter((d) => d.verified_at)
  const lastTestOk = config.last_test?.result === 'ok'

  async function act(action: () => Promise<unknown>, done?: string) {
    setBusy(true)
    setError(null)
    try {
      await action()
      if (done) toast(done)
    } catch (err) {
      setError(message(err))
    } finally {
      setBusy(false)
    }
  }

  async function addDomain(event: FormEvent) {
    event.preventDefault()
    await act(async () => {
      await api.addSsoDomain(org.slug, newDomain.trim().toLowerCase())
      setNewDomain('')
      load()
    })
  }

  async function startTest() {
    await act(async () => {
      const { login_url } = await api.startSsoTest(org.slug)
      window.location.href = login_url // full navigation; comes back with ?sso_test=<result>
    })
  }

  async function toggle(on: boolean) {
    if (on && !lastTestOk) {
      const ok = await confirm({
        title: 'Turn on SSO without a passing test?',
        message: 'Run "Test with my own e-mail" first to make sure people can sign in. Turn it on anyway?',
        confirmLabel: 'Turn on',
      })
      if (!ok) return
    }
    if (!on) {
      const ok = await confirm({
        title: 'Turn off SSO?',
        message: 'People on your domains go back to signing in with a password. Anyone who only ever used SSO has no password yet.',
        confirmLabel: 'Turn off',
        danger: true,
      })
      if (!ok) return
    }
    await act(async () => setConfig(await api.activateSso(org.slug, on)), on ? 'SSO is on.' : 'SSO is off.')
  }

  async function removeConfig() {
    const ok = await confirm({
      title: 'Remove the SSO configuration?',
      message: 'The identity provider settings are deleted. Verified domains stay.',
      confirmLabel: 'Remove',
      danger: true,
    })
    if (ok) await act(async () => {
      await api.deleteSsoConfig(org.slug)
      setCheck(null)
      load()
    }, 'SSO configuration removed.')
  }

  return (
    <div className="stack">
      {testResult && (
        <div role="alert" data-variant={testResult === 'ok' ? 'success' : 'danger'} className="table-toolbar">
          <span>{ssoTestText(testResult)}</span>
          <button
            type="button"
            className="ghost small"
            onClick={() => {
              setTestResult(null)
              window.history.replaceState(null, '', link(`/org/${encodeURIComponent(org.slug)}/sso`))
            }}
          >
            Dismiss
          </button>
        </div>
      )}
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}

      {!config.allowed_by_plan && (
        <div role="alert" data-variant="warning">
          Single sign-on isn't included in {org.name}'s plan. <a href={planHref}>See plans</a> to upgrade.
        </div>
      )}

      <section className="card stack">
        <div className="table-toolbar">
          <h3>Status</h3>
          {config.configured ? (
            <span className={`badge ${config.active ? 'status-ok' : 'badge-muted'}`}>
              {config.protocol?.toUpperCase()} · {config.active ? 'on' : 'off'}
            </span>
          ) : (
            <span className="badge badge-muted">not set up</span>
          )}
        </div>
        <p className="small-text">
          Last test:{' '}
          {config.last_test ? (
            <>
              <span className={lastTestOk ? 'status-ok' : 'status-warn'}>{config.last_test.result}</span> ·{' '}
              {when(config.last_test.at)}
              {config.last_test.tested_by_email && ` by ${config.last_test.tested_by_email}`}
            </>
          ) : (
            'never'
          )}
        </p>
        {config.configured && (
          <div className="hstack">
            <button type="button" className="outline" disabled={busy} onClick={startTest}>
              Test with my own e-mail
            </button>
            <button type="button" className="outline" disabled={busy} onClick={() => act(async () => setCheck(await api.checkSso(org.slug)))}>
              Check configuration
            </button>
            {config.active ? (
              <button type="button" className="outline" data-variant="danger" disabled={busy} onClick={() => toggle(false)}>
                Turn off SSO
              </button>
            ) : (
              <button type="button" disabled={busy || verified.length === 0 || !config.allowed_by_plan} onClick={() => toggle(true)}>
                Turn on SSO
              </button>
            )}
            <button type="button" className="ghost" data-variant="danger" disabled={busy || config.active} onClick={removeConfig}>
              Remove configuration
            </button>
          </div>
        )}
        <p className="muted small-text">
          The test signs you in at your identity provider and checks the answer, without changing your session. It works
          before SSO is turned on.
        </p>
        {check && <SsoChecklist check={check} />}
      </section>

      <section className="card stack">
        <h3>Service provider details</h3>
        <p className="muted small-text">Copy these into your identity provider when you create the app.</p>
        <strong className="small-text">SAML</strong>
        <Copyable label="Entity ID" value={config.sp.entity_id} />
        <Copyable label="ACS URL" value={config.sp.acs_url} />
        <Copyable label="Metadata URL" value={config.sp.metadata_url} />
        <strong className="small-text">OpenID Connect</strong>
        <Copyable label="Redirect URI" value={config.sp.oidc_redirect_uri} />
        <strong className="small-text">Sign-in link</strong>
        <Copyable label="Start SSO" value={config.sp.login_url} />
      </section>

      <section className="card stack" id="sso-domains">
        <h3>Domains</h3>
        <p className="muted small-text">
          Your identity provider can only sign in addresses on domains you have verified. Prove ownership with a DNS TXT
          record.
        </p>
        {config.domains.length > 0 && (
          <ul className="plain-list stack">
            {config.domains.map((d) => (
              <DomainRow key={d.domain} slug={org.slug} domain={d} onChanged={load} setError={setError} />
            ))}
          </ul>
        )}
        <form className="hstack" onSubmit={addDomain}>
          <input aria-label="Domain" placeholder="example.com" value={newDomain} onChange={(e) => setNewDomain(e.target.value)} />
          <button type="submit" disabled={busy || !newDomain.trim()}>
            Add domain
          </button>
        </form>
      </section>

      {config.allowed_by_plan || config.configured ? (
        <ConfigForm key={`${config.protocol}-${config.updated_at ?? ''}`} slug={org.slug} config={config} onSaved={(c) => setConfig(c)} />
      ) : null}

      <OrgScimSection org={org} verifiedDomains={verified.length} ssoActive={!!config.active} />
    </div>
  )
}
