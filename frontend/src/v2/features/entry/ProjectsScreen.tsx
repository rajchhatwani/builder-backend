import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useQueries, useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { Form, PageHeader, SettingsSection } from '../../patterns'
import { Button, Card, EmptyState, Field, Input, Pagination, Row, Select, Skeleton, Stack } from '../../ui'
import { projectLimits, validators } from '../../validators'
import { mfaOptions } from './api/account'
import { organizationsOptions, useCustomerSession } from './api/entry'
import { allProjectsOptions, projectHealthOptions, projectPageOptions, projectPageSize } from './api/projects'
import { CreateOrganization } from './components/CreateOrganization'
import { EntryProblem } from './components/EntryFrame'
import { ProjectPlan } from './components/ProjectPlan'
import { ProjectRow } from './components/ProjectRow'
import { projectLocked } from './components/entryData'
import { valueOf } from './components/fields'
import './components/customer.css'

export default function ProjectsScreen() {
  const t = useT()
  const { data: user } = useCustomerSession()
  const search = useSearch({ from: '/projects' })
  const navigate = useNavigate({ from: '/projects' })
  const page = search.page ?? 1
  const query = search.q?.trim().toLowerCase()
  const local = search.sort !== 'oldest' || Boolean(query || search.owner || search.health)
  const all = useQuery({ ...allProjectsOptions, enabled: local })
  const paged = useQuery({ ...projectPageOptions(page), enabled: !local })
  const organizations = useQuery(organizationsOptions(user?.id ?? ''))
  const orgs = organizations.data?.items ?? []
  const orgById = new Map(orgs.map(org => [org.id, org]))
  const mfa = useQuery({ ...mfaOptions, enabled: orgs.some(org => org.require_mfa) })
  const defaultOrg = orgById.get(user?.default_organization_id ?? '')
  const listQuery = local ? all : paged
  const candidates = (local ? all.data : paged.data?.items)?.filter(project =>
    (!search.owner || project.organization_id === search.owner) &&
    (!query || [project.name, project.slug, project.description].some(text => text?.toLowerCase().includes(query)))) ?? []
  const healthCandidates = search.health ? candidates.filter(project => {
    const org = orgById.get(project.organization_id ?? '')
    return !projectLocked(project, org) && (!org?.require_mfa || mfa.data?.session_mfa)
  }) : []
  const health = useQueries({ queries: healthCandidates.map(project => projectHealthOptions(project.id, true)) })
  const awaitingHealth = health.some(check => check.isPending)
  const healthError = health.find(check => check.isError)
  const matching = search.health
    ? healthCandidates.filter((_, index) => health[index].data?.valid === (search.health === 'ready'))
    : candidates
  if (search.sort !== 'oldest') matching.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  const total = local ? matching.length : paged.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / projectPageSize))
  const currentPage = Math.min(page, pages)
  const visible = local ? matching.slice((currentPage - 1) * projectPageSize, currentPage * projectPageSize) : matching
  const listTotal = local ? all.data?.length : paged.data?.total
  const hasFilters = Boolean(query || search.owner || search.health)
  const errorQuery = [listQuery, organizations, mfa].find(item => item.isEnabled && item.isError)
  const pending = listQuery.isPending || organizations.isPending || (mfa.isEnabled && mfa.isPending)

  function resetFilters() {
    void navigate({ search: { q: undefined, owner: undefined, health: undefined, page: undefined, sort: search.sort } })
  }
  function newProject(label: string) {
    return <Button variant="primary" asChild><Link to="/projects/new">{label}</Link></Button>
  }

  return <Stack gap={5}>
    <PageHeader title={t('shell.projects')} description={t('projectList.intro')}
      actions={Boolean(listTotal) && newProject(t('projectList.new'))} />
    {errorQuery ? <EntryProblem error={errorQuery.error} message={t('projectList.loadFailed')} retry={() => void errorQuery.refetch()} />
      : pending ? <Card><Skeleton lines={8} label={t('projectList.loading')} /></Card> : <>
      {listTotal === 0 ? <EmptyState title={t('projectList.empty')} description={t('projectList.emptyHelp')}
        action={newProject(t('projectList.create'))} /> : <>
        <SettingsSection title={t('projectList.idea')}>
          <Form fields={[{
            name: 'idea', label: t('projectList.ideaLabel'),
            validate: [validators.required, validators.length(projectLimits.description)],
            control: attributes => <Input {...attributes} placeholder={t('projectList.ideaPlaceholder')} maxLength={projectLimits.description} />,
          }]} submitLabel={t('projectList.ideaStart')} onSubmit={values => void navigate({
            to: '/projects/new', state: { projectIdea: valueOf(values, 'idea').trim() },
          })} />
        </SettingsSection>
        <Row className="v2-project-filters">
          <Field label={t('projectList.find')}>{attributes => <Input {...attributes} type="search" value={search.q ?? ''}
            placeholder={t('projectList.findPlaceholder')} onChange={event => void navigate({
              search: previous => ({ ...previous, q: event.target.value || undefined, page: undefined }), replace: true,
            })} />}</Field>
          <Field label={t('projectCreate.owner')}>{attributes => <Select triggerProps={attributes} value={search.owner ?? 'all'}
            options={[{ value: 'all', label: t('projectList.allOwners') }, ...orgs.map(org => ({ value: org.id, label: org.name }))]}
            onValueChange={owner => void navigate({ search: previous => ({ ...previous, owner: owner === 'all' ? undefined : owner, page: undefined }) })} />}</Field>
          <Field label={t('projectList.status')}>{attributes => <Select triggerProps={attributes} value={search.health ?? 'all'}
            options={['all', 'ready', 'fix'].map(value => ({ value, label: t(`projectList.health.${value}`) }))}
            onValueChange={health => void navigate({ search: previous => ({
              ...previous, health: health === 'ready' || health === 'fix' ? health : undefined, page: undefined,
            }) })} />}</Field>
          <Field label={t('projectList.sort')}>{attributes => <Select triggerProps={attributes} value={search.sort ?? 'updated'}
            options={['updated', 'oldest'].map(value => ({ value, label: t(`projectList.order.${value}`) }))}
            onValueChange={sort => void navigate({ search: previous => ({
              ...previous, sort: sort === 'oldest' ? sort : undefined, page: undefined,
            }) })} />}</Field>
        </Row>
        {healthError ? <EntryProblem error={healthError.error} message={t('projectList.healthFailed')}
          retry={() => { for (const check of health) if (check.isError) void check.refetch() }} />
          : awaitingHealth ? <Card><Skeleton lines={6} label={t('projectList.loading')} /></Card>
            : visible.length ? <Stack gap={2}>{visible.map(project => <ProjectRow key={project.id} project={project} userId={user?.id ?? ''}
              org={orgById.get(project.organization_id ?? '')} sessionMfa={mfa.data?.session_mfa ?? false} />)}</Stack>
              : <EmptyState title={t(hasFilters ? 'projectList.noMatch' : 'projectList.noPage')}
                action={<Button onClick={resetFilters}>{t(hasFilters ? 'common.clearFilter' : 'projectList.firstPage')}</Button>} />}
        {pages > 1 && <Pagination label={t('shell.projects')} page={currentPage} pages={pages} onChange={page => void navigate({
          search: previous => ({ ...previous, page: page > 1 ? page : undefined }),
        })} />}
        {defaultOrg && !defaultOrg.deletion_requested_at && (!defaultOrg.require_mfa || mfa.data?.session_mfa) &&
          <ProjectPlan slug={defaultOrg.slug} name={defaultOrg.name} />}
      </>}
      <Card><details className="v2-project-organizations">
        <summary>{t('projectList.organizations')}</summary>
        <Stack gap={2}>
          {orgs.length > 0 && <ul>{orgs.map(org => <li key={org.id}><Link to="/org/$slug" params={{ slug: org.slug }}>{org.name}</Link></li>)}</ul>}
          {user && <Row><CreateOrganization userId={user.id} /></Row>}
        </Stack>
      </details></Card>
    </>}
  </Stack>
}
