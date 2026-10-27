import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { MfaStatus, TotpSetup } from '../api/types'
import { useAuth } from './AuthProvider'
import { RecoveryCodes, TotpSecret } from './MfaStep'
import { useUi } from './Ui'

function message(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server."
  if (err.code === 'invalid_password') return "That password isn't right."
  if (err.code === 'invalid_mfa_code') return "That code didn't work. Try the newest code from the app."
  return err.message
}

type Flow =
  | { kind: 'idle' }
  | { kind: 'password' } // turning on: confirm the password first
  | { kind: 'scan'; setup: TotpSetup }
  | { kind: 'codes'; codes: string[] }
  | { kind: 'disable' }
  | { kind: 'regenerate' }

/** Account → Two-factor authentication (§4.4 Phase 1: TOTP + recovery codes). */
export function TwoFactorSection() {
  const { setUser } = useAuth()
  const { toast } = useUi()
  const [status, setStatus] = useState<MfaStatus | null>(null)
  const [flow, setFlow] = useState<Flow>({ kind: 'idle' })
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api
      .mfaStatus()
      .then(setStatus)
      .catch((err) => setError(message(err)))
  }, [])

  useEffect(load, [load])

  function start(next: Flow) {
    setPassword('')
    setCode('')
    setError(null)
    setFlow(next)
  }

  async function step(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (flow.kind === 'password') {
        start({ kind: 'scan', setup: await api.totpSetup(password) })
      } else if (flow.kind === 'scan') {
        // A new session that counts as MFA'd replaces the old access token.
        const session = await api.totpEnable(code.trim())
        setUser(session.user)
        start({ kind: 'codes', codes: session.recovery_codes })
        load()
      } else if (flow.kind === 'disable') {
        await api.totpDisable(password, code.trim())
        toast('Two-factor authentication is off.')
        start({ kind: 'idle' })
        api.resume().then((user) => user && setUser(user))
        load()
      } else if (flow.kind === 'regenerate') {
        const { recovery_codes } = await api.regenerateRecoveryCodes(code.trim())
        start({ kind: 'codes', codes: recovery_codes })
        load()
      }
    } catch (err) {
      setError(message(err))
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  if (!status) {
    return (
      <section className="card stack">
        <h3>Two-factor authentication</h3>
        {error ? <div role="alert" data-variant="danger">{error}</div> : <p className="empty-state">Loading…</p>}
      </section>
    )
  }

  if (status.sso_only) {
    return (
      <section className="card stack">
        <h3>Two-factor authentication</h3>
        <p className="muted">You sign in through your organization's SSO, which handles two-factor for you.</p>
      </section>
    )
  }

  const requiredBy = status.required_by
  const mustKeep = status.required_for_staff || requiredBy.length > 0
  const cancel = (
    <button type="button" className="outline" onClick={() => start({ kind: 'idle' })}>
      Cancel
    </button>
  )

  return (
    <section className="card stack">
      <div className="table-toolbar">
        <h3>Two-factor authentication</h3>
        <span className={`badge ${status.totp_enabled ? 'status-ok' : 'badge-muted'}`}>{status.totp_enabled ? 'on' : 'off'}</span>
      </div>

      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}

      {!status.totp_enabled && requiredBy.length > 0 && flow.kind === 'idle' && (
        <div role="alert" data-variant="warning">
          {requiredBy.map((o) => o.name).join(', ')} {requiredBy.length === 1 ? 'requires' : 'require'} two-factor
          authentication. Turn it on to open {requiredBy.length === 1 ? 'its' : 'their'} projects.
        </div>
      )}
      {status.totp_enabled && !status.session_mfa && flow.kind === 'idle' && (
        <div role="alert" data-variant="warning" className="small-text">
          This session was started without a code. Sign out and back in to use organizations that require two-factor.
        </div>
      )}

      {flow.kind === 'idle' &&
        (status.totp_enabled ? (
          <>
            <p className="muted small-text">
              On since {status.enabled_at ? new Date(status.enabled_at).toLocaleDateString() : 'recently'} ·{' '}
              {status.recovery_codes_left} recovery code{status.recovery_codes_left === 1 ? '' : 's'} left
            </p>
            <div className="hstack">
              <button className="outline" onClick={() => start({ kind: 'regenerate' })}>
                New recovery codes
              </button>
              {!mustKeep && (
                <button className="outline" data-variant="danger" onClick={() => start({ kind: 'disable' })}>
                  Turn off
                </button>
              )}
            </div>
            {mustKeep && (
              <p className="muted small-text">
                {status.required_for_staff
                  ? 'Platform staff accounts must keep two-factor on.'
                  : `It can't be turned off while ${requiredBy.map((o) => o.name).join(', ')} ${requiredBy.length === 1 ? 'requires' : 'require'} it.`}
              </p>
            )}
          </>
        ) : (
          <>
            <p className="muted">Ask for a code from an authenticator app each time you sign in, on top of your password.</p>
            <div>
              <button onClick={() => start({ kind: 'password' })}>Turn on</button>
            </div>
          </>
        ))}

      {flow.kind === 'codes' && <RecoveryCodes codes={flow.codes} doneLabel="Done" onDone={() => start({ kind: 'idle' })} />}

      {(flow.kind === 'password' || flow.kind === 'scan' || flow.kind === 'disable' || flow.kind === 'regenerate') && (
        <form className="stack" onSubmit={step}>
          {flow.kind === 'scan' && <TotpSecret setup={flow.setup} />}
          {(flow.kind === 'password' || flow.kind === 'disable') && (
            <label>
              Your password
              <input type="password" required autoFocus autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
          )}
          {flow.kind !== 'password' && (
            <label>
              {flow.kind === 'scan' ? 'Code from the app' : 'Current code from your authenticator app'}
              <input
                required
                autoFocus={flow.kind !== 'disable'}
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={32}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
          )}
          {flow.kind === 'regenerate' && (
            <p className="muted small-text">Your old recovery codes stop working.</p>
          )}
          <div className="hstack">
            {cancel}
            <button type="submit" disabled={busy} data-variant={flow.kind === 'disable' ? 'danger' : undefined}>
              {busy
                ? 'Please wait…'
                : flow.kind === 'password'
                  ? 'Continue'
                  : flow.kind === 'scan'
                    ? 'Turn on'
                    : flow.kind === 'disable'
                      ? 'Turn off two-factor'
                      : 'Make new codes'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
