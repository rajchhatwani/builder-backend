import { ResendVerification } from './ResendVerification'

/** Shown after sign-up (the server answers 202 and issues no session). */
export function CheckInbox({ email, message, onBack }: { email: string; message: string; onBack: () => void }) {
  return (
    <div className="stack" data-testid="check-inbox">
      <h2>Check your inbox</h2>
      <p>{message}</p>
      <p className="muted small-text">
        We sent a confirmation link to <strong>{email}</strong>. It works once and expires after a day. You can sign in now, but
        generating and downloading a backend need a confirmed address.
      </p>
      <ResendVerification email={email} startCooling />
      <p className="muted small-text auth-switch">
        <a href="#/" onClick={(e) => { e.preventDefault(); onBack() }}>Back to sign in</a>
      </p>
    </div>
  )
}
