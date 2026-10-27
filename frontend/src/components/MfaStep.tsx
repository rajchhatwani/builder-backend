import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, type MfaStepApi } from '../api/client'
import type { MfaChallenge, SessionResponse, TotpSetup } from '../api/types'
import { useUi } from './Ui'

/** "ABCD EFGH …" so a secret typed by hand is easier to read. */
function grouped(secret: string): string {
  return secret.replace(/(.{4})/g, '$1 ').trim()
}

/**
 * The otpauth URI as a QR code (an SVG image). The library is loaded on demand so it stays out of
 * the main bundle; if it fails to load, the key and link below still work.
 */
function TotpQr({ uri }: { uri: string }) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    import('qrcode')
      .then((QR) => QR.toString(uri, { type: 'svg', errorCorrectionLevel: 'M', margin: 2 }))
      .then((svg) => !cancelled && setSrc(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`))
      .catch(() => !cancelled && setSrc(null))
    return () => {
      cancelled = true
    }
  }, [uri])
  if (!src) return null
  return <img className="totp-qr" src={src} width={180} height={180} alt="QR code for your authenticator app" />
}

/**
 * The authenticator-app details for a new TOTP secret: a QR code to scan, the key to type by hand,
 * and the otpauth link for a phone.
 */
export function TotpSecret({ setup }: { setup: TotpSetup }) {
  const { toast } = useUi()
  return (
    <div className="stack">
      <p className="small-text">
        In your authenticator app (Google Authenticator, 1Password, Authy…), scan this QR code:
      </p>
      <TotpQr uri={setup.otpauth_uri} />
      <p className="small-text">Or add an account and enter this key:</p>
      <code className="token-box">{grouped(setup.secret)}</code>
      <div className="hstack">
        <button
          type="button"
          className="small"
          onClick={() => navigator.clipboard.writeText(setup.secret).then(() => toast('Key copied.'))}
        >
          Copy key
        </button>
        <a className="button outline small" href={setup.otpauth_uri}>
          Open in authenticator app
        </a>
      </div>
      <p className="muted small-text">Time-based, 6 digits. The link works on a phone that has an authenticator app.</p>
    </div>
  )
}

/** Recovery codes are shown once: copy or download, then confirm before going on. */
export function RecoveryCodes({ codes, onDone, doneLabel = 'Continue' }: { codes: string[]; onDone: () => void; doneLabel?: string }) {
  const { toast } = useUi()
  const [saved, setSaved] = useState(false)
  const text = codes.join('\n')

  function download() {
    const url = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'backend-builder-recovery-codes.txt'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="stack">
      <div role="alert" data-variant="warning">
        Save these recovery codes somewhere safe. Each one signs you in once if you lose your phone. They will not be
        shown again.
      </div>
      <code className="token-box recovery-codes">
        {codes.map((c) => (
          <span key={c}>{c}</span>
        ))}
      </code>
      <div className="hstack">
        <button type="button" className="small" onClick={() => navigator.clipboard.writeText(text).then(() => toast('Codes copied.'))}>
          Copy
        </button>
        <button type="button" className="outline small" onClick={download}>
          Download
        </button>
      </div>
      <label className="check-row">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>I saved my recovery codes</span>
      </label>
      <div>
        <button type="button" disabled={!saved} onClick={onDone}>
          {doneLabel}
        </button>
      </div>
    </div>
  )
}

/**
 * Each setup call stores a new secret on the server, so ask once per challenge: a second call
 * (React StrictMode, a re-render) would show one key while the server kept another.
 */
const setupCalls = new Map<string, Promise<TotpSetup>>()

function setupOnce(steps: MfaStepApi, mfaToken: string): Promise<TotpSetup> {
  let call = setupCalls.get(mfaToken)
  if (!call) {
    call = steps.setup(mfaToken)
    setupCalls.set(mfaToken, call)
    call.catch(() => setupCalls.delete(mfaToken))
  }
  return call
}

/** Human text for a refused sign-in step. */
function stepError(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server."
  if (err.status === 429) return 'Too many attempts. Wait a few minutes and try again.'
  if (err.code === 'invalid_mfa_code') return "That code didn't work. Check the time on your phone and try the newest code."
  return err.message
}

/** These end the sign-in attempt: the 5-minute step expired, or the account got locked. */
function isFatal(err: unknown): boolean {
  return err instanceof ApiError && (err.code === 'invalid_mfa_token' || err.code === 'invalid_credentials')
}

interface MfaStepProps {
  challenge: MfaChallenge
  steps: MfaStepApi
  onSignedIn: (session: SessionResponse) => void
  /** Back to the password form, with a reason to show there. */
  onRestart: (reason: string | null) => void
}

/**
 * The second sign-in step (§4.4). Either a code from the authenticator app (or a recovery code),
 * or, for platform staff without TOTP yet, setting it up right now.
 */
export function MfaStep({ challenge, steps, onSignedIn, onRestart }: MfaStepProps) {
  const enrolling = challenge.enrollment_required
  const [setup, setSetup] = useState<TotpSetup | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<{ session: SessionResponse; codes: string[] } | null>(null)

  useEffect(() => {
    if (!enrolling) return
    let cancelled = false
    setupOnce(steps, challenge.mfa_token)
      .then((s) => !cancelled && setSetup(s))
      .catch((err) => {
        if (cancelled) return
        if (isFatal(err)) onRestart(stepError(err))
        else setError(stepError(err))
      })
    return () => {
      cancelled = true
    }
  }, [enrolling, steps, challenge.mfa_token, onRestart])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const value = code.trim()
      if (enrolling) {
        const session = await steps.enable(challenge.mfa_token, value)
        setDone({ session, codes: session.recovery_codes })
      } else {
        onSignedIn(await steps.verify(challenge.mfa_token, value))
      }
    } catch (err) {
      if (isFatal(err)) {
        onRestart(
          err instanceof ApiError && err.code === 'invalid_mfa_token'
            ? 'That took too long. Sign in again.'
            : stepError(err),
        )
        return
      }
      setError(stepError(err))
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <>
        <h2>Two-factor is on</h2>
        <RecoveryCodes codes={done.codes} onDone={() => onSignedIn(done.session)} />
      </>
    )
  }

  const recoveryAllowed = challenge.methods.includes('recovery_code')
  return (
    <>
      <h2>{enrolling ? 'Set up two-factor authentication' : 'Two-factor authentication'}</h2>
      {enrolling && (
        <p className="muted small-text">
          Platform staff always sign in with a second factor. Set it up once now; next time you'll only need the code.
        </p>
      )}
      <form onSubmit={submit}>
        {error && (
          <div role="alert" data-variant="danger">
            {error}
          </div>
        )}
        {enrolling && (setup ? <TotpSecret setup={setup} /> : !error && <p className="empty-state">Loading…</p>)}
        <label>
          {enrolling ? 'Code from the app' : recoveryAllowed ? '6-digit code (or a recovery code)' : '6-digit code'}
          <input
            required
            autoFocus
            autoComplete="one-time-code"
            inputMode={enrolling || !recoveryAllowed ? 'numeric' : 'text'}
            maxLength={32}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy || !code.trim() || (enrolling && !setup)}>
          {busy ? 'Checking…' : enrolling ? 'Turn on and sign in' : 'Verify'}
        </button>
      </form>
      <p className="muted small-text auth-switch">
        <a
          href="#/"
          onClick={(e) => {
            e.preventDefault()
            onRestart(null)
          }}
        >
          Use a different account
        </a>
      </p>
    </>
  )
}
