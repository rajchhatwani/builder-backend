import { Link, Outlet, useNavigate, useParams, useRouterState } from '@tanstack/react-router'
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { clearCustomerQueries, entryApi, useCustomerSession, useEntryAction, useSessionLoss } from '../features/entry/api/entry'
import { EntryNavigation } from '../features/entry/EntryNavigation'
import { EntryFrame, EntryLoading, EntryProblem } from '../features/entry/components/EntryFrame'
import { clearEntryInvitation } from '../features/entry/entryLinks'
import { useProjectStatus } from '../features/projects/api/status'
import { useLanguage, useT } from '../i18n'
import { advancedGroups, guidedSections, isGuidedSection, statusSection } from '../projectNavigation'
import { Badge, Breadcrumb, Button, Menu, Row, Sheet, Stack } from '../ui'
import { SignInRequired } from './EntryGate'
import { LanguageSuggestion } from './LanguageSwitcher'
import { screens, sectionScreen } from './routeScreens'
import { useTheme } from './theme'

type StatusData = ReturnType<typeof useProjectStatus>['data']

function ProjectNavigation({ projectId, guided, data, onNavigate }: {
  projectId: string; guided: boolean; data: StatusData; onNavigate?: () => void
}) {
  const t = useT()
  const markers = new Map(data?.sections.map(section => [statusSection(section.id), section]))

  function item(id: string) {
    const marker = markers.get(id as ReturnType<typeof statusSection>)
    const status = id === 'overview'
    return (
      <Link key={id} to={status ? '/projects/$projectId/overview' : '/projects/$projectId/$section'}
        params={{ projectId, section: id }} preload="intent" activeOptions={{ exact: true }}
        onClick={onNavigate}
        onMouseEnter={status ? screens.status.preload : sectionScreen(id).preload}
        onFocus={status ? screens.status.preload : sectionScreen(id).preload}>
        {t(`nav.${id}`)}
        {!!marker?.issue_count && <Badge tone="danger">{t('status.problems', { count: marker.issue_count })}</Badge>}
        {!marker?.issue_count && marker?.configured && (id === 'payments' || id === 'storage') && (
          <span className="v2-on-dot" role="img" aria-label={t('shell.on')} />
        )}
      </Link>
    )
  }

  return (
    <nav className="v2-nav" aria-label={t(guided ? 'shell.guided' : 'shell.navigation')}>
      {guided ? <Row>{guidedSections.map(item)}</Row> : (
        <Stack gap={3}>{advancedGroups.map(group => (
          <Stack gap={0} key={group.id}>{group.id !== 'home' && <h2 className="v2-nav-heading">{t(`groups.${group.id}`)}</h2>}
            {group.sections.map(item)}
          </Stack>
        ))}</Stack>
      )}
    </nav>
  )
}

function MobileProjectNavigation({ projectId, data }: { projectId: string; data: StatusData }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  return (
    <div className="v2-rail-toggle">
      <Sheet title={t('shell.navigation')} trigger={<Button>{t('shell.navigation')}</Button>} open={open} onOpenChange={setOpen}>
        <ProjectNavigation projectId={projectId} guided={false} data={data} onNavigate={() => setOpen(false)} />
      </Sheet>
    </div>
  )
}

export function Shell() {
  const t = useT()
  const { theme, choose } = useTheme()
  const { language, choose: chooseLanguage } = useLanguage()
  const navigate = useNavigate()
  const { pathname, searchStr } = useRouterState({ select: state => state.location })
  const customerArea = pathname === '/projects' || pathname === '/invitations' || pathname.startsWith('/org/')
  const client = useQueryClient()
  const { projectId, section } = useParams({ strict: false })
  const session = useCustomerSession(customerArea || Boolean(projectId))
  const user = session.data
  const logout = useEntryAction()
  const guided = Boolean(section && isGuidedSection(section))

  function mode(next: 'guided' | 'advanced') {
    if (!projectId || guided === (next === 'guided')) return
    if (next === 'advanced') void navigate({ to: '/projects/$projectId/overview', params: { projectId } })
    else void navigate({ to: '/projects/$projectId/$section', params: { projectId, section: guidedSections[0] } })
  }

  useSessionLoss()

  function signOut() {
    logout.run(async () => {
      try {
        await entryApi.logout()
      } finally {
        clearEntryInvitation()
        clearCustomerQueries(client)
        void navigate({ to: '/login', search: {}, replace: true })
      }
    })
  }

  const activeProject = user && !user.must_change_password ? projectId : undefined
  const editor = Boolean(activeProject && section === 'code')
  const advancedProject = !guided && activeProject
  const { data } = useProjectStatus(activeProject ?? '')
  let projectGate
  if (projectId) {
    if (session.isPending) projectGate = <EntryFrame title={t('shell.projects')}><EntryLoading /></EntryFrame>
    else if (session.isError && !user) projectGate = <EntryFrame title={t('shell.projects')}>
      <EntryProblem error={session.error} message={t('entry.network')} retry={() => void session.refetch()} />
    </EntryFrame>
    else if (!user) projectGate = <SignInRequired next={pathname + searchStr} />
    else if (user.must_change_password) projectGate = <screens.choosePassword.Component user={user} />
  }

  return (
    <div className="v2-shell">
      <a className="v2-skip" href="#v2-main">{t('shell.skip')}</a>
      <header className="v2-top">
        <Row className="v2-top-inner" gap={3}>
          {advancedProject && !editor && <MobileProjectNavigation projectId={advancedProject} data={data} />}
          <Link to="/projects" preload="intent" className="v2-brand"><span aria-hidden />{t('shell.product')}</Link>
          {activeProject && <Breadcrumb items={[{ id: 'projects', content: <Link to="/projects">{t('shell.projects')}</Link> }, {
            id: 'project', content: t('shell.projectId', { id: activeProject }),
          }]} />}
          {activeProject && (
            <Row gap={0} role="group" aria-label={t('shell.mode')}>
              <Button variant={guided ? 'primary' : 'default'} aria-pressed={guided} onClick={() => mode('guided')}>{t('shell.guided')}</Button>
              <Button variant={guided ? 'default' : 'primary'} aria-pressed={!guided} onClick={() => mode('advanced')}>{t('shell.advanced')}</Button>
            </Row>
          )}
          {advancedProject && data && <Badge tone={data.ready ? 'success' : 'warning'}>
            {t(data.ready ? 'shell.ready' : 'status.blocked')}
          </Badge>}
          <Menu trigger={<Button>{t('shell.accountMenu')}</Button>} items={[
            { id: 'theme', label: t(theme === 'dark' ? 'shell.light' : 'shell.dark'), onSelect: () => choose(theme === 'dark' ? 'light' : 'dark') },
            { id: 'language', label: t('language.menu', { language: t(`language.${language}`) }), onSelect: () => chooseLanguage(language) },
            ...(user ? [{ id: 'logout', label: t('entry.signOut'), onSelect: signOut }] : []),
          ]} />
        </Row>
      </header>
      <div className="v2-shell-body" data-rail={Boolean((advancedProject && !editor) || (customerArea && user && !user.must_change_password)) || undefined} data-editor={editor || undefined}>
        {advancedProject && !editor && <aside className="v2-rail"><ProjectNavigation projectId={advancedProject} guided={false} data={data} /></aside>}
        {customerArea && user && !user.must_change_password && <aside className="v2-entry-rail"><EntryNavigation /></aside>}
        <main id="v2-main" tabIndex={-1} className="v2-main">
          <Stack gap={editor ? 0 : 5}>
            <LanguageSuggestion />
            {guided && activeProject && <ProjectNavigation projectId={activeProject} guided data={data} />}
            {projectGate ?? <Outlet />}
          </Stack>
        </main>
      </div>
    </div>
  )
}
