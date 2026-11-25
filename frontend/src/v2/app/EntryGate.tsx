import { useLocation, useRouter, useSearch } from '@tanstack/react-router'
import { useLayoutEffect } from 'react'
import type { ReactNode } from 'react'
import { useCustomerSession } from '../features/entry/api/entry'
import { EntryCard, EntryFrame, EntryLoading, EntryProblem } from '../features/entry/components/EntryFrame'
import { useT } from '../i18n'
import { LanguageSwitcher } from './LanguageSwitcher'
import { screens } from './routeScreens'

export function EntryGate({ children, kind }: { children: ReactNode; kind: 'login' | 'signup' | 'sso' | 'protected' | 'invitations' }) {
  const t = useT()
  const session = useCustomerSession()
  const { next } = useSearch({ strict: false })
  const { pathname, searchStr } = useLocation()
  const user = session.data

  if (user?.must_change_password) return <screens.choosePassword.Component user={user} />

  if (kind === 'sso') {
    if (user && !session.isFetching) return <EntryRedirect path={next === 'invitations' ? '/invitations' : next ?? '/projects'} />
    return children
  }

  const publicEntry = kind === 'login' || kind === 'signup'
  const title = t(kind === 'signup' ? 'entry.createAccountTitle' : kind === 'invitations' ? 'entry.invitations'
    : kind === 'protected' ? 'shell.projects' : 'shell.signIn')
  if (session.isPending) return <EntryFrame title={title}><EntryLoading label={t('entry.pleaseWait')} /></EntryFrame>
  if (session.isError && !user) return <EntryFrame title={title}><EntryCard>
    <EntryProblem error={session.error} message={t('entry.network')} retry={() => void session.refetch()} />
  </EntryCard></EntryFrame>

  if (publicEntry) {
    if (user) return <EntryRedirect path={next === 'invitations' ? '/invitations' : next ?? '/projects'} />
    return <>{children}<div className="v2-entry-language"><LanguageSwitcher /></div></>
  }
  if (!user) return <SignInRequired next={kind === 'invitations' ? 'invitations' : pathname.startsWith('/org/') ? pathname + searchStr : undefined} />
  return children
}

export function SignInRequired({ next }: { next?: string }) {
  const path = next ? '/login?' + new URLSearchParams({ next }) : '/login'
  return <EntryRedirect path={path} />
}

function EntryRedirect({ path }: { path: string }) {
  const router = useRouter()
  useLayoutEffect(() => {
    if (router.history.location.href !== path) router.history.replace(path)
  }, [path, router])
  return null
}
