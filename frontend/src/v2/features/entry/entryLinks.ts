import { checkInviteLink } from '../../validators'

const inviteKey = 'v2-sso-invitation'
const ssoReturnKey = 'v2-sso-return'
let invitation = ''
let verification: string | undefined

export function safeEntryNext(next: unknown) {
  if (next === 'invitations') return next
  if (typeof next === 'string' && /^\/(?:projects|org)\/[^/\\?#]+(?:[/?#]|$)/.test(next)) {
    const base = new URL('https://builder.invalid')
    const target = new URL(next, base)
    if (target.origin === base.origin && /^\/(?:projects|org)\//.test(target.pathname)) return target.pathname + target.search
  }
}

export function setEntryVerification(token: string) {
  verification = token
}

export function consumeEntryVerification() {
  const token = verification
  verification = undefined
  return token
}


export function setEntryInvitation(token: string) {
  invitation = token
}

export function entryInvitation() {
  return invitation
}

export function clearEntryInvitation() {
  invitation = ''
}

export function startSso(url: string, next?: string) {
  try {
    if (next) {
      sessionStorage.setItem(ssoReturnKey, next)
      if (next === 'invitations' && invitation) sessionStorage.setItem(inviteKey, invitation)
    }
  } catch { /* Full-page SSO still works without session storage. */ }
  window.location.assign(url)
}

export function restoreSsoInvitation() {
  try {
    const pending = sessionStorage.getItem(inviteKey)
    const returning = safeEntryNext(sessionStorage.getItem(ssoReturnKey))
    sessionStorage.removeItem(inviteKey)
    sessionStorage.removeItem(ssoReturnKey)
    if (pending && !checkInviteLink(pending)) invitation = pending
    return returning
  } catch {
    return undefined
  }
}
