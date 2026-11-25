import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useT } from '../../../../i18n'
import { ConfirmDestructive, Form, ReadOnlyNote, SettingsSection } from '../../../../patterns'
import { Alert, Badge, Button, Grid, Row, Stack } from '../../../../ui'
import { projectLimits, validators } from '../../../../validators'
import { organizationsOptions } from '../../api/entry'
import { allProjectsOptions } from '../../api/projects'
import { orgApi, orgQueries } from '../../api/org'
import type { OrgPlan, PlanInfo } from '../../api/org'
import { canAdmin, money, orgDate, OrgData, OrgPager, OrgProblem, OrgTabButton, OrgTable, ProjectBack, textValue, useOrgAction, useOrgFields } from './shared'
import type { OrgProps } from './shared'

export function OrgProjects(props: OrgProps & { paused: boolean }) {
  const { org, user, paused } = props
  const t = useT()
  const navigate = useNavigate()
  const fields = useOrgFields()
  const action = useOrgAction(props)
  const projects = useQuery(orgQueries.projects(org.slug))
  const admin = canAdmin(org)
  const mine = useQuery({ ...allProjectsOptions, enabled: admin })
  const orgs = useQuery({ ...organizationsOptions(user.id), enabled: org.my_role === 'owner' })
  const targets = orgs.data?.items.filter(target => target.my_role === 'owner' && target.slug !== org.slug && !target.deletion_scheduled_for) ?? []

  return <Stack gap={4}>
    {action.isError && <OrgProblem error={action.error} />}
    {orgs.isError && <OrgProblem error={orgs.error} retry={() => void orgs.refetch()} />}
    <SettingsSection title={t('org.tab.projects')}>
      <Form fields={[fields.input('projectName', { maxLength: projectLimits.name }, [validators.required, validators.length(projectLimits.name)])]}
        readOnly={paused} pending={action.isPending} submitLabel={t('org.newProject')} onSubmit={data => action.submit(async () => {
          const project = await orgApi.createProject({ name: textValue(data, 'projectName'), organization_id: org.id })
          void navigate({ to: '/projects/$projectId/$section', params: { projectId: project.id, section: 'overview' } })
        }, 'org.projectCreated', 'projects')} />
      {paused && <OrgTabButton slug={org.slug} tab="plan">{t('org.seePlans')}</OrgTabButton>}
    </SettingsSection>
    <OrgData query={projects}>{data => {
      const table = (ids?: Set<string>) => <OrgTable navigation={props} label={t('org.tab.projects')}
        fields={['project', 'access', 'updated', ...(admin ? ['actions'] : [])]}
        empty={t(admin ? 'org.noProjects' : 'org.noMyProjects')} action={<ProjectBack />}
        rows={data.items.map(project => {
          const joined = ids?.has(project.id) ?? true
          return { id: project.id, cells: [
            <Stack gap={1}>{joined ? <Link to="/projects/$projectId/$section" params={{ projectId: project.id, section: 'overview' }}>{project.name}</Link> : <strong>{project.name}</strong>}
              {project.description && <span className="v2-muted">{project.description}</span>}</Stack>,
            <Badge>{t(joined ? 'org.role.member' : 'org.noAccess')}</Badge>, orgDate(project.updated_at),
            <Stack>
              {!joined && <Form fields={[fields.select('projectRole', ['editor', 'viewer', 'owner'])]} pending={action.isPending}
                submitLabel={t('org.addMe')} onSubmit={data => action.submit(() => orgApi.joinProject(org.slug, project.id,
                  textValue(data, 'projectRole') as 'editor' | 'viewer' | 'owner'), 'org.projectJoined', 'projects')} />}
              {targets.map(target => <ConfirmDestructive key={target.id}
                trigger={<Button disabled={action.isPending}>{t('org.moveTo', { org: target.name })}</Button>}
                title={t('org.moveTitle', { project: project.name, org: target.name })} description={t('org.moveBody', { org: target.name })}
                action={t('org.moveProject')} onConfirm={() => action.perform(() => orgApi.transferProject(org.slug, project.id, target.slug), 'org.projectMoved', 'projects')} />)}
            </Stack>,
          ] }
        })} />
      return admin ? <OrgData query={mine}>{items => table(new Set(items.map(project => project.id)))}</OrgData> : table()
    }}</OrgData>
  </Stack>
}

function PlanFeatures({ plan }: { plan: PlanInfo }) {
  const t = useT()
  return <Row>
    {plan.allow_sso && <Badge>{t('org.sso')}</Badge>}
    {plan.allow_scim && <Badge>{t('org.scim')}</Badge>}
    {plan.allow_mcp && <Badge>{t('org.mcpTokens')}</Badge>}
  </Row>
}

export function Plan(props: OrgProps & { data: OrgPlan }) {
  const { org, data, search } = props
  const t = useT()
  const action = useOrgAction(props)
  const { plan, usage, subscription } = data
  const admin = canAdmin(org)
  const price = (amount?: number) => amount ? t('org.price', { amount: money(amount / 100) }) : t('org.free')
  const quota = (amount?: number | null) => amount == null ? t('org.unlimited') : t('org.number', { number: amount })
  const counters = [
    { key: 'seats', used: usage.seats_used, cap: usage.seats_cap, hint: usage.pending_invites ? t('org.pendingSeats', { count: usage.pending_invites }) : undefined },
    { key: 'projects', used: usage.projects_used, cap: usage.projects_cap },
    { key: 'apiTokens', used: usage.api_tokens_used, cap: usage.api_tokens_cap, hint: t('org.perMember') },
    { key: 'mcpTokens', used: usage.mcp_tokens_used, cap: usage.mcp_tokens_cap },
  ]
  return <Stack gap={4}>
    {action.isError && <OrgProblem error={action.error} />}
    {search.checkout && <Alert tone={search.checkout === 'success' ? 'success' : 'info'}>{t('org.checkout.' + search.checkout)}</Alert>}
    <SettingsSection title={t('org.planUsage')}>
      <Row><strong>{plan.display_name}</strong><span>{price(plan.monthly_price_usd)}</span>
        <Badge>{t('org.status.' + subscription.status)}</Badge></Row>
      <PlanFeatures plan={plan} />
      {subscription.trial_ends_at && <p>{t('org.trialEnds', { date: orgDate(subscription.trial_ends_at) ?? '' })}</p>}
      {subscription.current_period_end && <p>{t('org.periodEnds', { date: orgDate(subscription.current_period_end) ?? '' })}</p>}
      {subscription.seat_override != null && <p>{t('org.seatOverride', { count: subscription.seat_override })}</p>}
      {subscription.project_override != null && <p>{t('org.projectOverride', { count: subscription.project_override })}</p>}
      {admin && data.portal_available && <Row><Button disabled={action.isPending} onClick={() => action.submit(async () => {
        window.location.assign((await orgApi.portal(org.slug)).url)
      }, '', 'none')}>{t('org.manageBilling')}</Button></Row>}
    </SettingsSection>
    <Grid gap={3}>{counters.map(({ key, used, cap, hint }) => {
      const tone = cap == null ? 'neutral' : used >= cap ? 'danger' : used >= cap * 0.8 ? 'warning' : 'neutral'
      return <SettingsSection key={key} title={t('org.' + key)}>
        <Row><Badge tone={tone}>{t('org.usedOf', { used: used ?? 0, cap: quota(cap) })}</Badge>{hint && <span>{hint}</span>}</Row>
      </SettingsSection>
    })}</Grid>
    {admin ? data.checkout_available ? <Grid>
      {(data.upgrades ?? []).map(upgrade => <SettingsSection key={upgrade.id} title={upgrade.display_name} description={price(upgrade.monthly_price_usd)}>
        <p>{t('org.planCaps', { seats: quota(upgrade.max_seats), projects: quota(upgrade.max_projects) })}</p>
        <PlanFeatures plan={upgrade} />
        <Row><Button variant="primary" disabled={action.isPending} onClick={() => action.submit(async () => {
          window.location.assign((await orgApi.checkout(org.slug, upgrade.id)).url)
        }, '', 'none')}>{t('org.upgrade', { plan: upgrade.display_name })}</Button></Row>
      </SettingsSection>)}
      {!data.upgrades?.length && <p>{t('org.highestPlan')}</p>}
    </Grid> : <ReadOnlyNote>{t('org.billingUnavailable')}</ReadOnlyNote> : <ReadOnlyNote>{t('org.billingReadOnly', { owners: props.owners })}</ReadOnlyNote>}
  </Stack>
}

export function Audit({ org, search, setSearch }: OrgProps) {
  const t = useT()
  const page = search.page ?? 1
  const query = useQuery(orgQueries.audit(org.slug, page))
  const label = t('org.tab.audit')
  return <OrgData query={query}>{data => <Stack>
    <OrgTable label={label} fields={['when', 'who', 'what', 'target', 'targetId', 'projectId', 'result']}
      empty={t('org.noAudit')} action={<Button onClick={() => { if (page > 1) setSearch({ tab: 'audit' }); else void query.refetch() }}>{t('common.reload')}</Button>}
      rows={data.items.map(row => ({ id: String(row.id), cells: [
        orgDate(row.at), row.actor_email ?? (row.via === 'scim' ? t('org.scim') : row.via),
        row.action, row.target_type ?? t('org.na'), row.target_id ?? t('org.na'), row.project_id ?? t('org.na'), t('org.result.' + row.result),
      ] }))} />
    <OrgPager label={label} page={page} size={50} total={data.total} onChange={page => setSearch({ tab: 'audit', page })} />
  </Stack>}</OrgData>
}

export function Registry(props: OrgProps) {
  const { org } = props
  const t = useT()
  const query = useQuery(orgQueries.registry(org.slug))
  return <OrgData query={query}>{data => <SettingsSection title={t('org.tab.registry')}>
    <OrgTable navigation={props} label={t('org.tab.registry')} fields={['project', 'specVersion', 'blockVersions', 'hooks', 'unapproved', 'dependencies']}
      empty={t('org.noProjects')} action={<OrgTabButton slug={org.slug} tab="projects">{t('org.tab.projects')}</OrgTabButton>}
      rows={data.map(row => ({ id: row.project_id, cells: [
        row.name, row.spec_version, row.block_versions, row.hooks, row.hooks_unapproved, row.dependencies,
      ].map(value => typeof value === 'number' ? t('org.number', { number: value }) : value) }))} />
  </SettingsSection>}</OrgData>
}
