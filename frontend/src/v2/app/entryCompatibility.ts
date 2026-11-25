import { restoreSsoInvitation, setEntryInvitation, setEntryVerification } from '../features/entry/entryLinks'
import { inviteTokenFrom } from '../validators'

// Accept links issued by the existing backend before handing the address to the path router.
export function normalizeEntryAddress() {
  const { pathname, hash, search } = window.location
  const fragment = hash.slice(1)
  let target: string | undefined

  if (fragment.startsWith('/invite/') || pathname.startsWith('/invite/')) {
    const token = inviteTokenFrom(fragment.startsWith('/invite/') ? hash : pathname)
    setEntryInvitation(token || '!')
    target = '/invitations'
  } else if (fragment === '/invitations') {
    target = '/invitations'
  } else if (pathname === '/verify-email' || fragment === '/verify-email' || fragment.startsWith('/verify-email?')) {
    const token = new URLSearchParams(fragment.startsWith('/verify-email') ? fragment.split('?')[1] : search).get('token')
    if (token !== null) setEntryVerification(token)
    target = '/verify-email'
  } else if (fragment === '/sso/complete' || pathname === '/sso/complete' || pathname === '/sso-complete') {
    const next = restoreSsoInvitation()
    const params = new URLSearchParams(search)
    if (next) params.set('next', next)
    target = '/sso/complete' + (params.size ? '?' + params.toString() : '')
  } else if (fragment === '/login' || fragment.startsWith('/login?')) {
    const params = new URLSearchParams(fragment.split('?')[1])
    const next = restoreSsoInvitation()
    if (next) params.set('next', next)
    target = '/login' + (params.size ? '?' + params.toString() : '')
  } else if ((pathname === '/login' || pathname === '/sign-in' || pathname === '/signin') && new URLSearchParams(search).has('sso_error')) {
    const params = new URLSearchParams(search)
    const next = restoreSsoInvitation()
    if (next) params.set('next', next)
    target = pathname + '?' + params.toString()
  }

  if (target && target !== pathname + search + hash) history.replaceState(history.state, '', target)
}
