import { ApiError, api } from '../api/client'
import { ResendVerification } from './ResendVerification'

/** True when an API call was refused because the account's e-mail is not confirmed yet (403 `email_not_verified`). */
export const isEmailNotVerified = (err: unknown): boolean =>
  err instanceof ApiError && err.status === 403 && err.code === 'email_not_verified'

/** Friendly replacement for the raw 403: say what to do, and offer a new link. */
export function EmailNotVerifiedBanner() {
  return (
    <div role="alert" data-variant="warning" data-testid="email-not-verified">
      <strong>Confirm your e-mail address first.</strong> Previewing and downloading a generated backend need a confirmed address.
      Open the link we sent you, or ask for a new one.
      <ResendVerification email={async () => (await api.me()).email} />
    </div>
  )
}
