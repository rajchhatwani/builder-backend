import { entryError } from '../api/entry'

const messages: Record<string, string> = {
  signup_closed: 'signupClosed',
  weak_password: 'weakPassword',
  invalid_email: 'invalidEmail',
  invalid_credentials: 'invalidCredentials',
  invalid_mfa_code: 'invalidCode',
  invalid_mfa_token: 'expiredChallenge',
  must_change_password: 'forcedHint',
  email_not_verified: 'acceptFromEmail',
  seat_limit: 'seatLimit',
  subscription_past_due: 'invitePastDue',
  org_mfa_required: 'inviteMfaRequired',
  org_deletion_pending: 'orgLocked',
}

export function authProblem(error: unknown) {
  const { code, status } = entryError(error)
  if (code === 'account_locked') return 'entry.locked'
  if (status === 429) return 'entry.rateLimit'
  if (Object.hasOwn(messages, code)) return `entry.${messages[code]}`
  if (status === 403) return 'entry.forbidden'
  return status ? 'entry.requestFailed' : 'entry.network'
}

export function authProblemValues(error: unknown) {
  const { code, message } = entryError(error)
  if (code === 'account_locked') {
    const count = message.match(/try again in (\d+) minute/)
    return count ? { count: Number(count[1]) } : undefined
  }
}

export function inviteProblem(error: unknown) {
  const { status, message } = entryError(error)
  if (status === 409) return 'entry.inviteAccepted'
  if (status === 410) return 'entry.inviteExpired'
  if (status === 404) return message === 'invitation was revoked' ? 'entry.inviteRevoked' : 'entry.inviteInvalid'
  return authProblem(error)
}

export function invitationProblemValues(error: unknown, email: string): Record<string, string | number> {
  const { details } = entryError(error)
  const quota = details?.[0] as { plan?: unknown; cap?: unknown; used?: unknown } | undefined
  return typeof quota?.plan === 'string' && typeof quota.cap === 'number' && typeof quota.used === 'number'
    ? { email, plan: quota.plan, cap: quota.cap, used: quota.used } : { email }
}

export function passwordProblemKey(message: string) {
  if (message.includes('too easy to guess')) return 'entry.passwordEasy'
  if (message.includes('needs more variety')) return 'validation.passwordVariety'
  if (message === 'the new password must differ from the current one') return 'entry.samePassword'
  return 'entry.weakPassword'
}
