import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type {
  AuthConfig,
  AuthConfigUpdate,
  AuthProvider,
  SmtpConfig,
  SmsConfig,
  TokenStore,
  JwtAlgorithm,
  DeletionMode,
  SmsProvider,
} from '../api/types'

export interface AuthConfigPanelProps {
  projectId: string
}

export function AuthConfigPanel({ projectId }: AuthConfigPanelProps) {
  const [loading, setLoading] = useState(true)
  const [notConfigured, setNotConfigured] = useState(false)
  const [settingUp, setSettingUp] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  // Who manages users: with Keycloak, token, SMS and rate-limit settings do not apply.
  const [provider, setProvider] = useState<AuthProvider>('builtin')
  const keycloak = provider === 'keycloak'

  // General
  const [enabled, setEnabled] = useState(true)
  const [deletionMode, setDeletionMode] = useState<DeletionMode>('soft')

  // Tokens
  const [tokenStore, setTokenStore] = useState<TokenStore>('db')
  const [accessTokenTtlMinutes, setAccessTokenTtlMinutes] = useState(15)
  const [refreshTokenTtlDays, setRefreshTokenTtlDays] = useState(7)
  const [jwtAlgorithm, setJwtAlgorithm] = useState<JwtAlgorithm>('HS256')

  // Email & SMTP
  const [emailMagicLinkEnabled, setEmailMagicLinkEnabled] = useState(false)
  const [emailVerificationRequired, setEmailVerificationRequired] = useState(true)
  const [smtpHost, setSmtpHost] = useState('')
  const [smtpPort, setSmtpPort] = useState(587)
  const [smtpUseTls, setSmtpUseTls] = useState(true)
  const [smtpFromEmail, setSmtpFromEmail] = useState('')
  const [smtpFromName, setSmtpFromName] = useState('')

  // SMS
  const [smsOtpEnabled, setSmsOtpEnabled] = useState(false)
  const [smsProvider, setSmsProvider] = useState<SmsProvider>('twilio')
  const [smsFromNumber, setSmsFromNumber] = useState('')
  const [otpTtlMinutes, setOtpTtlMinutes] = useState(10)

  // Registration
  const [inviteOnly, setInviteOnly] = useState(false)
  const [multiTenant, setMultiTenant] = useState(false)

  // Rate Limits
  const [loginRateLimit, setLoginRateLimit] = useState('5/15minutes')
  const [registerRateLimit, setRegisterRateLimit] = useState('10/hour')
  const [resetRateLimit, setResetRateLimit] = useState('3/hour')

  // Branding
  const [securityHeadersEnabled, setSecurityHeadersEnabled] = useState(true)
  const [appName, setAppName] = useState('')
  const [appUrl, setAppUrl] = useState('')

  const populateForm = useCallback((cfg: AuthConfig) => {
    setProvider(cfg.provider)
    setEnabled(cfg.enabled)
    setDeletionMode(cfg.deletion_mode)

    setTokenStore(cfg.token_store)
    setAccessTokenTtlMinutes(cfg.access_token_ttl_minutes)
    setRefreshTokenTtlDays(cfg.refresh_token_ttl_days)
    setJwtAlgorithm(cfg.jwt_algorithm)

    setEmailMagicLinkEnabled(cfg.email_magic_link_enabled)
    setEmailVerificationRequired(cfg.email_verification_required)
    if (cfg.smtp_config) {
      setSmtpHost(cfg.smtp_config.host ?? '')
      setSmtpPort(cfg.smtp_config.port ?? 587)
      setSmtpUseTls(cfg.smtp_config.use_tls ?? true)
      setSmtpFromEmail(cfg.smtp_config.from_email ?? '')
      setSmtpFromName(cfg.smtp_config.from_name ?? '')
    } else {
      setSmtpHost('')
      setSmtpPort(587)
      setSmtpUseTls(true)
      setSmtpFromEmail('')
      setSmtpFromName('')
    }

    setSmsOtpEnabled(cfg.sms_otp_enabled)
    setSmsProvider(cfg.sms_provider ?? 'twilio')
    setSmsFromNumber(cfg.sms_config?.from_number ?? '')
    setOtpTtlMinutes(cfg.otp_ttl_minutes)

    setInviteOnly(cfg.invite_only)
    setMultiTenant(cfg.multi_tenant)

    setLoginRateLimit(cfg.login_rate_limit ?? '5/15minutes')
    setRegisterRateLimit(cfg.register_rate_limit ?? '10/hour')
    setResetRateLimit(cfg.reset_rate_limit ?? '3/hour')

    setSecurityHeadersEnabled(cfg.security_headers_enabled)
    setAppName(cfg.app_name ?? '')
    setAppUrl(cfg.app_url ?? '')
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setMessage(null)

    api
      .getAuthConfig(projectId)
      .then((cfg) => {
        if (cancelled) return
        populateForm(cfg)
        setNotConfigured(false)
        setLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          setNotConfigured(true)
        } else {
          const text =
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : 'Failed to load auth configuration.'
          setMessage({ ok: false, text })
        }
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [projectId, populateForm])

  async function handleSetupAuth() {
    setSettingUp(true)
    setMessage(null)
    try {
      const created = await api.createAuthConfig(projectId, {
        email_magic_link_enabled: false,
        sms_otp_enabled: false,
      })
      populateForm(created)
      setNotConfigured(false)
      setMessage({ ok: true, text: 'Auth configuration created.' })
    } catch (err) {
      const text =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to create auth configuration.'
      setMessage({ ok: false, text })
    } finally {
      setSettingUp(false)
    }
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setMessage(null)

    const smtpNeeded = keycloak ? smtpHost.trim() !== '' : emailMagicLinkEnabled
    const smtpConfig: SmtpConfig | null = smtpNeeded
      ? {
          host: smtpHost,
          port: Number(smtpPort),
          use_tls: smtpUseTls,
          from_email: smtpFromEmail,
          from_name: smtpFromName,
        }
      : null

    const smsConfig: SmsConfig | null = smsOtpEnabled
      ? {
          from_number: smsFromNumber,
        }
      : null

    // What both providers use.
    const shared: AuthConfigUpdate = {
      enabled,
      access_token_ttl_minutes: Number(accessTokenTtlMinutes),
      email_verification_required: emailVerificationRequired,
      smtp_config: smtpConfig,
      invite_only: inviteOnly,
      multi_tenant: multiTenant,
      security_headers_enabled: securityHeadersEnabled,
      app_name: appName.trim() || null,
    }
    // Only built-in sign-in has these. With Keycloak they are left alone, except that SMS codes
    // and the magic link, which Keycloak cannot offer, are switched off.
    const builtinOnly: AuthConfigUpdate = {
      deletion_mode: deletionMode,
      token_store: tokenStore,
      refresh_token_ttl_days: Number(refreshTokenTtlDays),
      jwt_algorithm: jwtAlgorithm,
      email_magic_link_enabled: emailMagicLinkEnabled,
      sms_otp_enabled: smsOtpEnabled,
      sms_provider: smsOtpEnabled ? smsProvider : null,
      sms_config: smsConfig,
      otp_ttl_minutes: Number(otpTtlMinutes),
      login_rate_limit: loginRateLimit,
      register_rate_limit: registerRateLimit,
      reset_rate_limit: resetRateLimit,
      app_url: appUrl.trim() || null,
    }
    const updateData: AuthConfigUpdate = keycloak
      ? { ...shared, email_magic_link_enabled: false, sms_otp_enabled: false }
      : { ...shared, ...builtinOnly }

    try {
      const updated = await api.updateAuthConfig(projectId, updateData)
      populateForm(updated)
      setMessage({ ok: true, text: 'Auth configuration saved.' })
    } catch (err) {
      const text =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to save auth configuration.'
      setMessage({ ok: false, text })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="card">
        <p className="empty-state">Loading auth configuration…</p>
      </div>
    )
  }

  if (notConfigured) {
    return (
      <div className="card empty-state">
        <h3>Auth not configured</h3>
        <p style={{ marginBlockEnd: 'var(--space-4)' }}>
          Authentication has not been set up for this project yet.
        </p>
        {message && (
          <div
            role="alert"
            data-variant={message.ok ? 'success' : 'danger'}
            style={{ marginBlockEnd: 'var(--space-4)' }}
          >
            {message.text}
          </div>
        )}
        <button onClick={handleSetupAuth} disabled={settingUp}>
          {settingUp ? 'Setting up…' : 'Set up auth'}
        </button>
      </div>
    )
  }

  return (
    <form className="card" onSubmit={handleSave}>
      {message && (
        <div
          role="alert"
          data-variant={message.ok ? 'success' : 'danger'}
          style={{ marginBlockEnd: 'var(--space-4)' }}
        >
          {message.text}
        </div>
      )}

      {/* General */}
      <details open className="auth-section">
        <summary>General</summary>
        <div className="auth-section-body">
          <div style={{ marginBlockEnd: 'var(--space-4)' }}>
            <label>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />{' '}
              Auth enabled
            </label>
          </div>
          {keycloak && (
            <p className="muted">
              Keycloak handles sign-in, passwords, tokens and sessions. The settings below are the
              ones this project still uses. Set up logins and security in the{' '}
              <a href={`#/p/${projectId}/keycloak`}>Keycloak</a> section.
            </p>
          )}
          <div className="field-grid" hidden={keycloak}>
            <label>
              Deletion mode
              <select
                value={deletionMode}
                onChange={(e) => setDeletionMode(e.target.value as DeletionMode)}
              >
                <option value="soft">soft</option>
                <option value="hard">hard</option>
              </select>
            </label>
          </div>
        </div>
      </details>

      {/* Tokens */}
      <details open className="auth-section">
        <summary>Tokens</summary>
        <div className="auth-section-body">
          <div className="field-grid">
            <label hidden={keycloak}>
              Token store
              <select
                value={tokenStore}
                onChange={(e) => setTokenStore(e.target.value as TokenStore)}
              >
                <option value="db">db</option>
                <option value="redis">redis (needs the redis package)</option>
              </select>
            </label>
            <label>
              {keycloak ? 'Access token lifetime (minutes)' : 'Access token TTL (minutes)'}
              <input
                type="number"
                min={1}
                max={1440}
                required
                value={accessTokenTtlMinutes}
                onChange={(e) => setAccessTokenTtlMinutes(Number(e.target.value))}
              />
            </label>
            <label hidden={keycloak}>
              Refresh token TTL (days)
              <input
                type="number"
                min={1}
                max={365}
                required
                value={refreshTokenTtlDays}
                onChange={(e) => setRefreshTokenTtlDays(Number(e.target.value))}
              />
            </label>
            <label hidden={keycloak}>
              JWT algorithm
              <select
                value={jwtAlgorithm}
                onChange={(e) => setJwtAlgorithm(e.target.value as JwtAlgorithm)}
              >
                <option value="HS256">HS256</option>
                <option value="RS256">RS256 (needs the cryptography package)</option>
              </select>
            </label>
          </div>
        </div>
      </details>

      {/* Email & SMTP */}
      <details open className="auth-section">
        <summary>Email &amp; SMTP</summary>
        <div className="auth-section-body">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', marginBlockEnd: emailMagicLinkEnabled || keycloak ? 'var(--space-4)' : 0 }}>
            {!keycloak && (
              <label>
                <input
                  type="checkbox"
                  checked={emailMagicLinkEnabled}
                  onChange={(e) => setEmailMagicLinkEnabled(e.target.checked)}
                />{' '}
                Enable email magic link
              </label>
            )}
            <label>
              <input
                type="checkbox"
                checked={emailVerificationRequired}
                onChange={(e) => setEmailVerificationRequired(e.target.checked)}
              />{' '}
              Require email verification
            </label>
          </div>

          {(emailMagicLinkEnabled || keycloak) && (
            <fieldset style={{ marginBlockStart: 'var(--space-4)' }}>
              <legend>{keycloak ? 'SMTP settings (Keycloak sends the emails)' : 'SMTP Settings'}</legend>
              <div className="field-grid">
                <label>
                  SMTP host
                  <input
                    type="text"
                    required={keycloak ? emailVerificationRequired : emailMagicLinkEnabled}
                    placeholder="smtp.example.com"
                    value={smtpHost}
                    onChange={(e) => setSmtpHost(e.target.value)}
                  />
                </label>
                <label>
                  SMTP port
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    required={keycloak ? emailVerificationRequired : emailMagicLinkEnabled}
                    value={smtpPort}
                    onChange={(e) => setSmtpPort(Number(e.target.value))}
                  />
                </label>
                <label>
                  From email
                  <input
                    type="email"
                    required={keycloak ? emailVerificationRequired : emailMagicLinkEnabled}
                    placeholder="noreply@example.com"
                    value={smtpFromEmail}
                    onChange={(e) => setSmtpFromEmail(e.target.value)}
                  />
                </label>
                <label>
                  From name
                  <input
                    type="text"
                    required={keycloak ? emailVerificationRequired : emailMagicLinkEnabled}
                    placeholder="App Notifications"
                    value={smtpFromName}
                    onChange={(e) => setSmtpFromName(e.target.value)}
                  />
                </label>
              </div>
              <div style={{ marginBlockStart: 'var(--space-3)' }}>
                <label>
                  <input
                    type="checkbox"
                    checked={smtpUseTls}
                    onChange={(e) => setSmtpUseTls(e.target.checked)}
                  />{' '}
                  Use TLS
                </label>
              </div>
            </fieldset>
          )}
        </div>
      </details>

      {/* SMS */}
      <details open className="auth-section" hidden={keycloak && !smsOtpEnabled}>
        <summary>SMS</summary>
        <div className="auth-section-body">
          <div style={{ marginBlockEnd: 'var(--space-4)' }}>
            <label>
              <input
                type="checkbox"
                checked={smsOtpEnabled}
                onChange={(e) => setSmsOtpEnabled(e.target.checked)}
              />{' '}
              Enable SMS OTP
            </label>
          </div>

          {smsOtpEnabled && (
            <fieldset style={{ marginBlockEnd: 'var(--space-4)' }}>
              <legend>SMS Provider Settings</legend>
              <div className="field-grid">
                <label>
                  SMS provider
                  <select
                    value={smsProvider}
                    onChange={(e) => setSmsProvider(e.target.value as SmsProvider)}
                  >
                    <option value="twilio">twilio</option>
                    <option value="aws_sns">aws_sns</option>
                    <option value="vonage">vonage</option>
                  </select>
                </label>
                <label>
                  From number
                  <input
                    type="tel"
                    required={smsOtpEnabled}
                    placeholder="+1234567890"
                    value={smsFromNumber}
                    onChange={(e) => setSmsFromNumber(e.target.value)}
                  />
                </label>
              </div>
            </fieldset>
          )}

          <div className="field-grid">
            <label>
              OTP TTL (minutes)
              <input
                type="number"
                min={1}
                max={60}
                required
                value={otpTtlMinutes}
                onChange={(e) => setOtpTtlMinutes(Number(e.target.value))}
              />
            </label>
          </div>
        </div>
      </details>

      {/* Registration */}
      <details open className="auth-section">
        <summary>Registration</summary>
        <div className="auth-section-body">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            <label>
              <input
                type="checkbox"
                checked={inviteOnly}
                onChange={(e) => setInviteOnly(e.target.checked)}
              />{' '}
              {keycloak
                ? 'Invite only (turns self-registration off; you create users in Keycloak)'
                : 'Invite only (admins send invitation emails; needs SMTP, an app URL and an "admin" role)'}
            </label>
            <label>
              <input
                type="checkbox"
                checked={multiTenant}
                onChange={(e) => setMultiTenant(e.target.checked)}
              />{' '}
              {keycloak
                ? 'Multi-tenant (each Keycloak organization is a tenant; you create organizations and add people to them in Keycloak)'
                : 'Multi-tenant (sign-up creates a tenant and its admin; invitations join one; cannot be combined with invite-only sign-up)'}
            </label>
          </div>
        </div>
      </details>

      {/* Rate Limits */}
      <details open className="auth-section" hidden={keycloak}>
        <summary>Rate Limits</summary>
        <div className="auth-section-body">
          <div className="field-grid">
            <label>
              Login rate limit
              <input
                type="text"
                placeholder="5/15minutes"
                value={loginRateLimit}
                onChange={(e) => setLoginRateLimit(e.target.value)}
              />
            </label>
            <label>
              Register rate limit
              <input
                type="text"
                placeholder="10/hour"
                value={registerRateLimit}
                onChange={(e) => setRegisterRateLimit(e.target.value)}
              />
            </label>
            <label>
              Reset rate limit
              <input
                type="text"
                placeholder="3/hour"
                value={resetRateLimit}
                onChange={(e) => setResetRateLimit(e.target.value)}
              />
            </label>
          </div>
        </div>
      </details>

      {/* Branding */}
      <details open className="auth-section">
        <summary>Branding</summary>
        <div className="auth-section-body">
          <div style={{ marginBlockEnd: 'var(--space-4)' }}>
            <label>
              <input
                type="checkbox"
                checked={securityHeadersEnabled}
                onChange={(e) => setSecurityHeadersEnabled(e.target.checked)}
              />{' '}
              Security headers enabled
            </label>
          </div>
          <div className="field-grid">
            <label>
              App name
              <input
                type="text"
                placeholder="My Application"
                value={appName}
                onChange={(e) => setAppName(e.target.value)}
              />
            </label>
            <label hidden={keycloak}>
              App URL
              <input
                type="text"
                placeholder="https://app.example.com"
                value={appUrl}
                onChange={(e) => setAppUrl(e.target.value)}
              />
            </label>
          </div>
        </div>
      </details>

      <div style={{ marginBlockStart: 'var(--space-4)' }}>
        <button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

export default AuthConfigPanel
