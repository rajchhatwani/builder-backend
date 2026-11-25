import { Link, Outlet, useNavigate, useParams, useRouterState, useSearch } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clearCustomerQueries, entryApi, organizationsOptions, useCustomerSession, useEntryAction, useSessionLoss } from '../features/entry/api/entry'
import { EntryNavigation } from '../features/entry/EntryNavigation'
import { EntryFrame, EntryLoading, EntryProblem } from '../features/entry/components/EntryFrame'
import { clearEntryInvitation } from '../features/entry/entryLinks'
import { PreviewCredentials } from '../features/guided/components/PreviewCredentials'
import { ShareProject } from '../features/projects/ShareProject'
import { WorkspaceContext } from '../features/projects/workspaceContext'
import { useProjectLive } from '../features/projects/api/live'
import { statusCode, useProjectStatus } from '../features/projects/api/status'
import { keycloakOptions, projectOptions, useWorkspaceRole, workspaceError } from '../features/projects/api/workspace'
import { useLanguage, useT } from '../i18n'
import { advancedGroups, defaultSectionSearch, guidedSections, isBehaviorSection, isConnectSection, isSecureSection, isGuidedSection, statusSection } from '../projectNavigation'
import { CommandPalette } from '../patterns/CommandPalette'
import { Alert, Badge, Breadcrumb, Button, EmptyState, Menu, Row, Sheet, Stack } from '../ui'
import { lazyScreen } from './lazy'
import { Presence } from './shell/Presence'
import { WorkspaceNotices } from './shell/WorkspaceNotices'
import { SignInRequired } from './EntryGate'
import { LanguageSuggestion } from './LanguageSwitcher'
import { screens, sectionScreen } from './routeScreens'
import { useTheme } from './theme'

const workbench = lazyScreen(() => import('../features/guided/Workbench'))

type StatusData = ReturnType<typeof useProjectStatus>['data']
type Panel = 'palette' | 'workbench' | 'share' | 'presence'

function ProjectNavigation({ projectId, guided, data, keycloak, onNavigate }: {
  projectId: string; guided: boolean; data: StatusData; keycloak?: boolean; onNavigate?: () => void
}) {
  const t = useT()
  const { preview } = useSearch({ strict: false })
  const markers = new Map(data?.sections?.map(section => [statusSection(section.id), section]))

  function item(id: string) {
    const marker = markers.get(id as ReturnType<typeof statusSection>)
    const status = id === 'overview'
    const preload = status ? screens.status.preload : id === 'diagrams' || isConnectSection(id) ? screens[id].preload : sectionScreen(id).preload
    return (
      <Link key={id} to={status ? '/projects/$projectId/overview' : '/projects/$projectId/$section'}
        params={{ projectId, section: id }} search={{ ...defaultSectionSearch(id), preview }} preload="intent" activeOptions={{ exact: true }}
        onClick={onNavigate}
        onMouseEnter={preload} onFocus={preload}>
        {t(`nav.${id}`)}
        {!!marker?.issue_count && <Badge tone="danger">{t('status.problems', { count: marker.issue_count })}</Badge>}
        {!marker?.issue_count && (id === 'keycloak' ? keycloak : marker?.configured && (id === 'payments' || id === 'storage')) && (
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

function MobileProjectNavigation({ projectId, data, keycloak }: { projectId: string; data: StatusData; keycloak?: boolean }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  return (
    <div className="v2-rail-toggle">
      <Sheet title={t('shell.navigation')} trigger={<Button>{t('shell.navigation')}</Button>} open={open} onOpenChange={setOpen}>
        <ProjectNavigation projectId={projectId} guided={false} data={data} keycloak={keycloak} onNavigate={() => setOpen(false)} />
      </Sheet>
    </div>
  )
}

export function Shell() {
  const { projectId } = useParams({ strict: false })
  return <PreviewCredentials key={projectId}><WorkspaceShell /></PreviewCredentials>
}

function WorkspaceShell() {
  const t = useT()
  const { theme, choose } = useTheme()
  const { language, choose: chooseLanguage } = useLanguage()
  const navigate = useNavigate()
  const { pathname, searchStr } = useRouterState({ select: state => state.location })
  const customerArea = pathname === '/projects' || pathname === '/account' || pathname === '/invitations' || pathname.startsWith('/org/')
  const client = useQueryClient()
  const { projectId, section } = useParams({ strict: false })
  const { preview } = useSearch({ strict: false })
  const session = useCustomerSession(customerArea || pathname === '/projects/new' || Boolean(projectId))
  const user = session.data
  const logout = useEntryAction()
  const [panel, setPanel] = useState<Panel>()
  const [logoutError, setLogoutError] = useState(false)
  const moreButton = useRef<HTMLButtonElement>(null)

  useEffect(() => { setPanel(undefined) }, [pathname])
  useEffect(() => {
    if (!projectId || !user || user.must_change_password) return
    function key(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase() !== 'k') return
      event.preventDefault()
      if (!event.repeat && !document.querySelector('[role="dialog"][aria-modal="true"], [role="dialog"][data-state="open"]')) setPanel('palette')
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [projectId, user])
  const guided = Boolean(section && isGuidedSection(section))

  function mode(next: 'guided' | 'advanced') {
    if (!projectId || guided === (next === 'guided')) return
    if (next === 'advanced') void navigate({ to: '/projects/$projectId/overview', params: { projectId }, search: { preview } })
    else void navigate({ to: '/projects/$projectId/$section', params: { projectId, section: guidedSections[0] }, search: { preview } })
  }

  useSessionLoss()

  function signOut() {
    logout.run(async () => {
      setLogoutError(false)
      try { await entryApi.logout() } catch { setLogoutError(true); return }
      clearEntryInvitation()
      clearCustomerQueries(client)
      void navigate({ to: '/login', search: {}, replace: true })
    })
  }

  const activeProject = user && !user.must_change_password ? projectId : undefined
  const home = Boolean(activeProject && !section)
  const editor = Boolean(activeProject && section === 'code')
  const advancedProject = !guided && activeProject
  const status = useProjectStatus(activeProject ?? '')
  const project = useQuery(projectOptions(activeProject ?? ''))
  const organizations = useQuery({ ...organizationsOptions(user?.id ?? ''), enabled: Boolean(project.data?.organization_id) })
  const organization = organizations.data?.items?.find(item => item.id === project.data?.organization_id)
  const orgName = organization?.kind === 'personal' ? t('shell.personal') : organization?.name
  const { role, members } = useWorkspaceRole((home || section === 'diagrams' || (section && (isBehaviorSection(section) || isSecureSection(section) || (isConnectSection(section) && section !== 'forms'))) || panel === 'workbench' || panel === 'share') ? activeProject ?? '' : '', user?.id ?? '')
  const keycloak = useQuery(keycloakOptions(activeProject ?? '', Boolean(status.data?.sections?.find(item => item.id === 'auth')?.configured))).data?.active
  const { data } = status
  const guardedError = [401, 403, 404, 423].includes(statusCode(status.error) ?? 0) ? status.error : undefined
  const presence = useProjectLive(!guardedError ? activeProject ?? '' : '', section ?? 'overview')
  const projectName = project.data?.name ?? activeProject
  const projectWritable = role === 'owner' || role === 'editor'
  const projectVerified = Boolean(user?.email_verified_at || (user?.platform_role && user.platform_role !== 'customer'))
  const links = [
    { id: 'projects', label: t('shell.allProjects'), hint: t('shell.goTo'), run: () => void navigate({ to: '/projects', search: {} }) },
    ...(organization ? [{ id: 'organization', label: t('common.serverText', { text: orgName ?? '' }), hint: t('shell.organization'),
      run: () => void navigate({ to: '/org/$slug', params: { slug: organization.slug } }) }] : []),
    { id: 'account', label: t('account.title'), hint: t('shell.goTo'), run: () => void navigate({ to: '/account', search: {} }) },
    ...(!guardedError ? [
      { id: 'workbench', label: t('shell.workbenchCommand'), hint: t('shell.action'), run: () => setPanel('workbench') },
      { id: 'share', label: t('share.command'), hint: t('shell.action'), run: () => setPanel('share') },
    ] : []),
    { id: 'theme', label: t('shell.toggleTheme'), hint: t('shell.action'), run: () => choose(theme === 'dark' ? 'light' : 'dark') },
    { id: 'logout', label: t('entry.signOut'), hint: t('shell.action'), run: signOut },
  ]
  const commands = [
    ...[advancedGroups[0], { id: 'guided', sections: guidedSections }, ...advancedGroups.slice(1)].flatMap(group => group.sections.map(id => ({
      id, label: t('nav.' + id), hint: t('groups.' + group.id),
      run: () => activeProject && void (id === 'overview'
        ? navigate({ to: '/projects/$projectId/overview', params: { projectId: activeProject }, search: { preview } })
        : navigate({ to: '/projects/$projectId/$section', params: { projectId: activeProject, section: id }, search: { ...defaultSectionSearch(id), preview } })),
    }))),
    ...links,
  ]
  let projectGate
  if (projectId) {
    if (session.isPending) projectGate = <EntryFrame title={t('shell.projects')}><EntryLoading /></EntryFrame>
    else if (session.isError && !user) projectGate = <EntryFrame title={t('shell.projects')}>
      <EntryProblem error={session.error} message={t('entry.network')} retry={() => void session.refetch()} />
    </EntryFrame>
    else if (!user) projectGate = <SignInRequired next={pathname + searchStr} />
    else if (user.must_change_password) projectGate = <screens.choosePassword.Component user={user} />
    else if (guardedError) {
      const locked = statusCode(guardedError) === 423
      const mfa = workspaceError(guardedError) === 'org_mfa_required'
      projectGate = <EmptyState title={t(locked ? 'shell.lockedTitle' : mfa ? 'shell.mfaTitle'
        : statusCode(guardedError) === 404 ? 'status.missing' : 'status.forbidden')}
        description={t(locked ? 'shell.lockedBody' : mfa ? 'shell.mfaBody' : 'shell.projectUnavailable')}
        action={<Row>
          <Button asChild><Link to="/projects" search={{}}>{t('status.back')}</Link></Button>
          {mfa && <Button asChild><Link to="/account" search={{}}>{t('account.title')}</Link></Button>}
        </Row>} />
    }
  }

  const accountMenu = (
    <Menu trigger={<Button ref={moreButton}>{t('shell.accountMenu')}</Button>}
      label={user?.email && t('common.serverText', { text: user.email })} items={[
        ...(activeProject && !home ? [
          { id: 'palette', label: t('shell.search'), onSelect: () => setPanel('palette') },
          ...(!guardedError ? [
            { id: 'workbench', label: t('shell.workbench'), onSelect: () => setPanel('workbench') },
            { id: 'share', label: t('share.open'), onSelect: () => setPanel('share') },
            { id: 'presence', label: t('shell.presenceLabel', { status: t('shell.live.' + presence.status) }), onSelect: () => setPanel('presence') },
          ] : []),
        ] : []),
        { id: 'theme', label: t(theme === 'dark' ? 'shell.light' : 'shell.dark'), onSelect: () => choose(theme === 'dark' ? 'light' : 'dark') },
        { id: 'language', label: t('language.menu', { language: t(`language.${language}`) }), onSelect: () => chooseLanguage(language) },
        ...(user && !user.must_change_password ? [{ id: 'account', label: t('account.title'), onSelect: () => void navigate({ to: '/account', search: {} }) }] : []),
        ...(user ? [{ id: 'logout', label: t('entry.signOut'), onSelect: signOut }] : []),
      ]} />
  )

  const returnFocus = home ? undefined : moreButton
  const panelChange = (name: Panel) => (open: boolean) => setPanel(current => open ? name : current === name ? undefined : current)
  const projectActions = activeProject && <>
    <CommandPalette label={t('shell.search')} commands={commands} open={panel === 'palette'}
      onOpenChange={panelChange('palette')} returnFocus={returnFocus} />
    {!guardedError && <>
      <Sheet title={t('shell.workbench')} open={panel === 'workbench'} onOpenChange={panelChange('workbench')}
        returnFocus={returnFocus} trigger={home ? <Button data-testid="workbench-toggle">{t('shell.workbench')}</Button> : undefined}>
        {panel === 'workbench' && <workbench.Component project={activeProject} write={projectWritable} verified={projectVerified} />}
      </Sheet>
      <ShareProject id={activeProject} role={role} members={members} open={panel === 'share'}
        onOpenChange={panelChange('share')} returnFocus={returnFocus} />
      <Presence {...presence} user={user?.id ?? ''} open={panel === 'presence'}
        onOpenChange={panelChange('presence')} returnFocus={returnFocus} />
    </>}
  </>
  const readiness = advancedProject && data && <Badge tone={data.ready ? 'success' : 'warning'}>
    {t(data.ready ? 'shell.ready' : 'status.blocked')}
  </Badge>

  return (
    <div className="v2-shell">
      <a className="v2-skip" href="#v2-main">{t('shell.skip')}</a>
      <header className="v2-top">
        <Stack gap={2}><Row className="v2-top-inner" gap={3}>
          {advancedProject && !editor && <MobileProjectNavigation projectId={advancedProject} data={data} keycloak={keycloak} />}
          <Link to="/projects" preload="intent" className="v2-brand"><span aria-hidden />{t('shell.product')}</Link>
          {activeProject && <Breadcrumb items={[
            { id: 'projects', content: <Link to="/projects" search={{}}>{t('shell.projects')}</Link> },
            ...(organization ? [{ id: 'organization', content: <Link to="/org/$slug" params={{ slug: organization.slug }}>
              {t('common.serverText', { text: orgName ?? '' })}</Link> }] : []),
            { id: 'project', content: home
              ? <strong data-testid="shell-project">{t('shell.projectId', { id: projectName ?? activeProject })}</strong>
              : t('shell.projectId', { id: projectName ?? activeProject }) },
          ]} />}
          {activeProject && (
            <Row gap={0} role="group" aria-label={t('shell.mode')}>
              <Button variant={guided ? 'primary' : 'default'} aria-pressed={guided} onClick={() => mode('guided')}>{t('shell.guided')}</Button>
              <Button variant={guided ? 'default' : 'primary'} aria-pressed={!guided} onClick={() => mode('advanced')}>{t('shell.advanced')}</Button>
            </Row>
          )}
          {!home && readiness}
          {!home && accountMenu}
        </Row>
        {home && <Row className="v2-top-actions" gap={2}>
          {projectActions}
          {readiness}
          {accountMenu}
        </Row>}</Stack>
      </header>
      {!home && projectActions}
      <div className="v2-shell-body" data-rail={Boolean((advancedProject && !editor) || (customerArea && user && !user.must_change_password)) || undefined} data-editor={editor || undefined}>
        {advancedProject && !editor && <aside className={home ? 'v2-rail v2-home-rail' : 'v2-rail'}><ProjectNavigation projectId={advancedProject} guided={false} data={data} keycloak={keycloak} /></aside>}
        {customerArea && user && !user.must_change_password && <aside className="v2-entry-rail"><EntryNavigation /></aside>}
        <main id="v2-main" tabIndex={-1} className="v2-main">
          <Stack gap={editor ? 0 : 5}>
            <LanguageSuggestion />
            {logoutError && <Alert tone="danger" action={<Button onClick={signOut}>{t('common.retry')}</Button>}>{t('shell.logoutError')}</Alert>}
            {activeProject && <WorkspaceNotices organization={organization?.slug} />}
            {home && !guardedError && project.isError && !status.isError && statusCode(project.error) !== 404 && <Alert tone="danger"
              action={<Button onClick={() => void project.refetch()}>{t('shell.retry')}</Button>}>{t('shell.projectError')}</Alert>}
            {guided && activeProject && <ProjectNavigation projectId={activeProject} guided data={data} />}
            {projectGate ?? <WorkspaceContext.Provider value={{
              role, rolePending: members.isPending, roleError: members.isError,
              retryRole: () => void members.refetch(), project: project.data?.name, organization: orgName, organizationSlug: organization?.slug, openShare: () => setPanel('share'), version: project.data?.version,
            }}><Outlet /></WorkspaceContext.Provider>}
          </Stack>
        </main>
      </div>
    </div>
  )
}
