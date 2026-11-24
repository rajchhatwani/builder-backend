import { Link, Outlet, useNavigate, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { useProjectStatus } from '../features/projects/api/status'
import { useLanguage, useT } from '../i18n'
import { advancedGroups, guidedSections, isGuidedSection, statusSection } from '../projectNavigation'
import { Badge, Breadcrumb, Button, Menu, Row, Sheet, Stack } from '../ui'
import { LanguageSuggestion } from './LanguageSwitcher'
import { screens } from './routeScreens'
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
        onMouseEnter={status ? screens.status.preload : screens.unavailable.preload}
        onFocus={status ? screens.status.preload : screens.unavailable.preload}>
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
  const { projectId, section } = useParams({ strict: false })
  const guided = Boolean(section && isGuidedSection(section))

  function mode(next: 'guided' | 'advanced') {
    if (!projectId || guided === (next === 'guided')) return
    if (next === 'advanced') void navigate({ to: '/projects/$projectId/overview', params: { projectId } })
    else void navigate({ to: '/projects/$projectId/$section', params: { projectId, section: guidedSections[0] } })
  }

  const advancedProject = !guided && projectId
  const { data } = useProjectStatus(projectId ?? '')

  return (
    <div className="v2-shell">
      <a className="v2-skip" href="#v2-main">{t('shell.skip')}</a>
      <header className="v2-top">
        <Row className="v2-top-inner" gap={3}>
          {advancedProject && <MobileProjectNavigation projectId={advancedProject} data={data} />}
          <Link to="/projects" preload="intent" className="v2-brand"><span aria-hidden />{t('shell.product')}</Link>
          {projectId && <Breadcrumb items={[{ id: 'projects', content: <Link to="/projects">{t('shell.projects')}</Link> }, {
            id: 'project', content: t('shell.projectId', { id: projectId }),
          }]} />}
          {projectId && (
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
          ]} />
        </Row>
      </header>
      <div className="v2-shell-body" data-rail={Boolean(advancedProject) || undefined}>
        {advancedProject && <aside className="v2-rail"><ProjectNavigation projectId={advancedProject} guided={false} data={data} /></aside>}
        <main id="v2-main" tabIndex={-1} className="v2-main">
          <Stack gap={5}>
            <LanguageSuggestion />
            {guided && projectId && <ProjectNavigation projectId={projectId} guided data={data} />}
            <Outlet />
          </Stack>
        </main>
      </div>
    </div>
  )
}
