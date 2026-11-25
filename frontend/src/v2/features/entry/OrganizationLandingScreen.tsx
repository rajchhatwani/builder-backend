import { useState } from 'react'
import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, PageHeader, ReadOnlyNote } from '../../patterns'
import { Alert, Button, Dialog, EmptyState, Row, Stack, Tabs } from '../../ui'
import { entryLimits, validators } from '../../validators'
import { entryError, entryKeys, organizationOptions, useCustomerSession } from './api/entry'
import { orgApi, orgQueries } from './api/org'
import type { Organization, UserAccount } from './api/org'
import { projectPlanOptions } from './api/projects'
import { EntryLoading } from './components/EntryFrame'
import { Invites, People } from './components/org/PeopleInvites'
import { Audit, OrgProjects, Plan, Registry } from './components/org/ProjectsPlanAudit'
import { Export, Security } from './components/org/Security'
import { Identity } from './components/org/Identity'
import { Ai, Usage } from './components/org/AiUsage'
import { canAdmin, orgDate, OrgData, OrgProblem, OrgTabButton, ProjectBack, textValue, useOrgAction, useOrgFields } from './components/org/shared'
import { isOrgTab, orgTabs } from './orgSearch'
import type { OrgProps } from './components/org/shared'

function OrgActions({ org, user, blocked }: { org: Organization; user: UserAccount; blocked: boolean }) {
  const t = useT()
  const navigate = useNavigate()
  const client = useQueryClient()
  const action = useOrgAction({ org, user })
  const fields = useOrgFields()
  const [rename, setRename] = useState(false)
  return <Stack>
    {action.isError && <OrgProblem error={action.error} />}
    <Row>
      {!blocked && canAdmin(org) && <Dialog title={t('org.rename')} trigger={<Button>{t('org.rename')}</Button>}
        open={rename} onOpenChange={setRename}>
        <Stack>
          {action.isError && <OrgProblem error={action.error} />}
          <Form fields={[fields.input('orgName', { defaultValue: org.name, maxLength: entryLimits.name }, [validators.required, validators.length(entryLimits.name)])]}
            pending={action.isPending} submitLabel={t('common.save')} onSubmit={data => action.submit(async () => {
              const updated = await orgApi.rename(org.slug, textValue(data, 'orgName'))
              client.setQueryData(entryKeys.organization(user.id, org.slug), updated)
              setRename(false)
            })} />
        </Stack>
      </Dialog>}
      <ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending}>{t('org.leave')}</Button>}
        title={t('org.leaveTitle', { org: org.name })} description={t('org.leaveBody')} action={t('org.leave')}
        onConfirm={() => action.perform(async () => {
          await orgApi.remove(org.slug, user.id)
          void client.invalidateQueries({ queryKey: entryKeys.session() })
          void navigate({ to: '/projects' })
        }, 'org.left', 'projects')} />
      {!blocked && org.my_role === 'owner' && <ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending}>{t('org.delete')}</Button>}
        title={t('org.deleteTitle', { org: org.name })} description={t('org.deleteBody')} action={t('org.requestDeletion')}
        onConfirm={() => action.perform(() => orgApi.delete(org.slug), 'org.deletionRequested', 'projects')} />}
    </Row>
  </Stack>
}

function Locked({ org, user }: { org: Organization; user: UserAccount }) {
  const t = useT()
  const action = useOrgAction({ org, user })
  return <Stack gap={4}>
    <PageHeader title={org.name} description={t('org.scheduled', { date: orgDate(org.deletion_scheduled_for) ?? t('org.na') })} />
    <Alert tone="warning">{t('org.locked')}</Alert>
    {action.isError && <OrgProblem error={action.error} />}
    {org.my_role === 'owner' ? <>
      <Row><Button variant="primary" disabled={action.isPending} onClick={() => action.submit(() => orgApi.cancelDeletion(org.slug), 'org.deletionCanceled', 'projects')}>{t('org.cancelDeletion')}</Button></Row>
      <Export org={org} user={user} />
    </> : <ReadOnlyNote>{t('org.cancelOwner')}</ReadOnlyNote>}
    <Row><ProjectBack /></Row>
  </Stack>
}

function DefaultOrg({ org, user }: Pick<OrgProps, 'org' | 'user'>) {
  const t = useT()
  const client = useQueryClient()
  const action = useOrgAction({ org, user })
  if (user.default_organization_id === org.id) return null
  return <Stack>
    <Row><Button disabled={action.isPending} onClick={() => action.submit(async () => {
      const updated = await orgApi.defaultOrg(org.id)
      client.setQueryData(entryKeys.session(), updated)
    }, 'org.defaultSaved', 'none')}>{t('org.setDefault')}</Button></Row>
    {action.isError && <OrgProblem error={action.error} />}
  </Stack>
}

function Console({ org, user, refresh }: { org: Organization; user: UserAccount; refresh: () => void }) {
  const t = useT()
  const { tab = 'people', ...rest } = useSearch({ from: '/org/$slug' })
  const navigate = useNavigate({ from: '/org/$slug' })
  const search = { ...rest, tab }
  const members = useQuery(orgQueries.members(org.slug))
  const blocked = entryError(members.error).code === 'org_mfa_required'
  const plan = useQuery({ ...projectPlanOptions(org.slug), enabled: members.isSuccess })
  const admin = canAdmin(org)
  const owners = members.data?.items.filter(member => member.role === 'owner').map(member => member.email).join(', ') || t('org.owners')
  const props: OrgProps = { org, user, owners, search, setSearch: search => { void navigate({ search }) } }
  const planData = plan.data
  const pastDue = planData?.subscription.status === 'past_due'
  const atSeatLimit = planData?.usage.seats_cap != null && planData.usage.seats_used + (planData.usage.pending_invites ?? 0) >= planData.usage.seats_cap
  const atProjectLimit = planData?.usage.projects_cap != null && planData.usage.projects_used >= planData.usage.projects_cap
  const allowed = { people: true, invites: true, projects: true, plan: true, audit: true, sso: org.kind === 'team', security: true, ai: admin, usage: true, registry: admin }
  const protectedTab = tab === 'invites' || tab === 'audit' || tab === 'sso' || tab === 'ai' || tab === 'registry'
  const panels = {
    people: <OrgData query={members}>{data => <People {...props} members={data.items} />}</OrgData>,
    invites: <Invites {...props} paused={Boolean(pastDue || atSeatLimit)} />,
    projects: <OrgProjects {...props} paused={Boolean(pastDue || atProjectLimit)} />,
    plan: <OrgData query={plan}>{data => <Plan {...props} data={data} />}</OrgData>,
    audit: <Audit {...props} />,
    sso: <Identity {...props} />,
    security: <Security {...props} />,
    ai: <Ai {...props} />,
    usage: <Usage {...props} />,
    registry: <Registry {...props} />,
  }

  if (blocked) return <Stack gap={4}>
    <PageHeader title={org.name} description={t('org.mfaRequired', { org: org.name })} />
    <Alert tone="danger">{t(user.mfa_enabled ? 'org.mfaReauth' : 'org.mfaSetup')}</Alert>
    <Row><Button asChild><Link to="/account">{t('org.openAccount')}</Link></Button>
      <Button onClick={() => void members.refetch()}>{t('org.retry')}</Button></Row>
    {org.kind === 'team' && <OrgActions org={org} user={user} blocked />}
  </Stack>

  const locked = entryError(members.error).status === 423
  return <Stack gap={5}>
    <PageHeader title={org.name} description={t('org.subtitle', { count: org.member_count ?? 0, role: t('org.role.' + org.my_role) })}
      actions={org.kind === 'team' && !locked && <OrgActions org={org} user={user} blocked={false} />} />
    {locked ? <OrgProblem error={members.error} retry={refresh} /> : <>
      {members.isSuccess && <DefaultOrg {...props} />}
      {planData && <p className="v2-muted">{t('org.planSummary', { plan: planData.plan.display_name, status: t('org.status.' + planData.subscription.status) })}</p>}
      {(pastDue || (org.kind === 'team' && planData?.plan.id === 'free' && atSeatLimit)) && <Alert tone="warning"
        action={<OrgTabButton slug={org.slug} tab="plan">{t('org.seePlans')}</OrgTabButton>}>
        {t(pastDue ? 'org.pastDue' : 'org.freeSeats', { org: org.name, count: planData?.usage.seats_cap ?? 0 })}
      </Alert>}
      <Tabs label={t('org.tabLabel')} value={allowed[tab] ? tab : ''} onChange={tab => {
        if (isOrgTab(tab)) props.setSearch({ tab: tab === 'people' ? undefined : tab })
      }} items={orgTabs.filter(tab => allowed[tab]).map(id => ({
        id, label: t('org.tab.' + id),
        content: !members.isSuccess && id !== 'people' ? <OrgData query={members}>{() => null}</OrgData>
          : protectedTab && !admin && id === tab ? <ReadOnlyNote>{t('org.adminOnly', { owners })}</ReadOnlyNote> : panels[id],
      }))} />
      {!allowed[tab] && (tab === 'ai' ? <div data-testid="ai-noaccess"><ReadOnlyNote>{t('org.aiNoAccess')}</ReadOnlyNote></div> :
        <ReadOnlyNote>{t(tab === 'sso' ? 'org.teamOnly' : 'org.adminOnly', { owners })}</ReadOnlyNote>)}
    </>}
  </Stack>
}

export default function OrganizationLandingScreen() {
  const t = useT()
  const { slug } = useParams({ from: '/org/$slug' })
  const { data: user } = useCustomerSession()
  const org = useQuery({ ...organizationOptions(user?.id ?? '', slug), enabled: Boolean(user) })
  if (org.isPending || !user) return <Stack gap={4}>
    <PageHeader title={t('entry.organization')} /><EntryLoading label={t('org.loading')} lines={9} />
  </Stack>
  if (org.isError) return <Stack gap={4}>
    {entryError(org.error).status === 404 ? <EmptyState title={t('org.notFound')} description={t('org.notFoundBody')} action={<ProjectBack />} /> :
      <><PageHeader title={t('org.loadFailed')} /><OrgProblem error={org.error} retry={() => void org.refetch()} /><Row><ProjectBack /></Row></>}
  </Stack>
  return org.data.deletion_scheduled_for ? <Locked key={slug} org={org.data} user={user} /> :
    <Console key={slug} org={org.data} user={user} refresh={() => void org.refetch()} />
}
