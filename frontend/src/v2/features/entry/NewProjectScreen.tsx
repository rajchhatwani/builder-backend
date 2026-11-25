import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useT } from '../../i18n'
import { Form, PageHeader, ReadOnlyNote } from '../../patterns'
import { Button, Card, Dialog, Input, Radio, Select, Skeleton, Stack, Textarea, useToast } from '../../ui'
import { checkProjectSlug, projectLimits, validators } from '../../validators'
import { mfaOptions } from './api/account'
import { entryError, entryKeys, organizationsOptions, useCustomerSession, useEntryAction } from './api/entry'
import { projectKeys, projectsApi } from './api/projects'
import type { QuotaDetail } from './api/projects'
import { EntryProblem } from './components/EntryFrame'
import { ProjectPlan } from './components/ProjectPlan'
import { valueOf } from './components/fields'
import { authProblem } from './components/messages'
import './components/customer.css'

const fallbackOwner = 'personal-default'

export default function NewProjectScreen() {
  const t = useT()
  const client = useQueryClient()
  const navigate = useNavigate()
  const idea = useLocation({ select: location => location.state.projectIdea ?? '' })
  const toast = useToast()
  const { data: user } = useCustomerSession()
  const organizations = useQuery(organizationsOptions(user?.id ?? ''))
  const orgs = organizations.data?.items ?? []
  const mfa = useQuery({ ...mfaOptions, enabled: orgs.some(org => org.require_mfa) })
  const [owner, setOwner] = useState<string>()
  const [quotaOpen, setQuotaOpen] = useState(false)
  const action = useEntryAction()
  const selected = owner ?? user?.default_organization_id ?? fallbackOwner
  const org = orgs.find(item => item.id === selected)
  const ownerValue = org ? selected : fallbackOwner
  const locked = Boolean(org?.deletion_requested_at)
  const needsMfa = Boolean(org?.require_mfa && !mfa.data?.session_mfa)
  const failure = entryError(action.error)
  const slugTaken = failure.status === 409 && failure.message === 'a project with this slug already exists'
  const quota = failure.status === 402 ? failure.details?.[0] as QuotaDetail | undefined : undefined
  const planMessage = failure.code === 'subscription_past_due' ? t('projectCreate.pastDue')
    : quota?.cap != null ? t('projectCreate.quota', { plan: quota.plan, count: quota.cap }) : t('projectCreate.quotaFallback')
  const failureMessage = slugTaken ? t('projectCreate.slugTaken')
    : failure.status === 402 ? planMessage
      : failure.status === 403 && failure.code === 'forbidden' ? t('projectCreate.membersOnly')
        : t(authProblem(action.error))
  const failed = organizations.isError ? organizations : mfa.isEnabled && mfa.isError ? mfa : undefined
  const pending = organizations.isPending || (mfa.isEnabled && mfa.isPending)

  function submit(values: FormData) {
    const description = valueOf(values, 'description').trim()
    action.run(async () => {
      try {
        const project = await projectsApi.create({
          name: valueOf(values, 'name').trim(), slug: valueOf(values, 'slug').trim() || undefined,
          description: description || undefined, organization_id: org?.id,
        })
        void client.invalidateQueries({ queryKey: projectKeys.lists() })
        void client.invalidateQueries({ queryKey: projectKeys.plan(org?.slug ?? '') })
        if (!org) {
          void client.invalidateQueries({ queryKey: entryKeys.organizations(user?.id ?? '') })
          void client.invalidateQueries({ queryKey: entryKeys.session() })
        }
        toast({ title: t('projectCreate.created'), tone: 'success' })
        if (valueOf(values, 'start') === 'guided') {
          void navigate({ to: '/projects/$projectId/$section', params: { projectId: project.id, section: 'intake' },
            state: { projectIdea: description } })
        } else {
          void navigate({ to: '/projects/$projectId/overview', params: { projectId: project.id } })
        }
      } catch (error) {
        if (entryError(error).status === 402) setQuotaOpen(true)
        throw error
      }
    })
  }

  return <Stack gap={5} className="v2-creation">
    <PageHeader title={t('projectCreate.title')} description={t('projectCreate.intro')} />
    {failed ? <EntryProblem error={failed.error} message={t('projectCreate.ownersFailed')} retry={() => void failed.refetch()} />
      : pending ? <Card><Skeleton lines={10} label={t('projectCreate.loading')} /></Card>
        : <Card><Stack gap={4}>
          {locked && <ReadOnlyNote>{t('entry.orgLocked')}</ReadOnlyNote>}
          {needsMfa && <Stack>
            <ReadOnlyNote>{t('projectList.mfaNote', { org: org?.name ?? t('projectList.thisOrg') })}</ReadOnlyNote>
            <Button asChild><Link to="/account">{t('projectList.openAccount')}</Link></Button>
          </Stack>}
          {action.isError && <EntryProblem error={action.error} message={failureMessage} />}
          <Form fields={[
            {
              name: 'owner', label: t('projectCreate.owner'),
              control: attributes => <Select triggerProps={attributes} disabled={attributes.disabled} value={ownerValue}
                options={[
                  ...(!orgs.some(item => item.id === user?.default_organization_id) ? [{ value: fallbackOwner, label: t(user?.default_organization_id ? 'account.defaultOrg' : 'projectCreate.personal') }] : []),
                  ...orgs.map(item => ({ value: item.id, label: item.name })),
                ]} onValueChange={value => { setOwner(value); action.reset() }} />,
            },
            {
              name: 'name', label: t('projectCreate.name'), validate: [validators.required, validators.length(projectLimits.name)],
              control: attributes => <Input {...attributes} required maxLength={projectLimits.name} placeholder={t('projectCreate.namePlaceholder')} />,
            },
            {
              name: 'slug', label: t('projectCreate.slug'), hint: t('projectCreate.slugHelp'), validate: [validators.length(projectLimits.slug), checkProjectSlug],
              control: attributes => <Input {...attributes} maxLength={projectLimits.slug} placeholder={t('projectCreate.slugPlaceholder')} />,
            },
            {
              name: 'description', label: t('projectCreate.description'), validate: [validators.length(projectLimits.description)],
              control: attributes => <Textarea {...attributes} maxLength={projectLimits.description} defaultValue={idea} />,
            },
            {
              name: 'database', label: t('projectCreate.database'), hint: t('projectCreate.databaseHelp'),
              control: attributes => <Select triggerProps={attributes} disabled value="postgres" options={[{ value: 'postgres', label: t('projectCreate.postgres') }]} />,
            },
          ]} pending={action.isPending} serverErrors={slugTaken ? { slug: { key: 'projectCreate.slugTaken' } } : undefined}
            onSubmit={submit} submitLabel={t('projectCreate.submit')} submitProps={{ disabled: locked || needsMfa }}
            actions={<Button asChild><Link to="/projects">{t('projectCreate.cancel')}</Link></Button>}>
            <fieldset disabled={action.isPending}>
              <legend>{t('projectCreate.start')}</legend>
              <Stack gap={2}>{(['guided', 'blank'] as const).map(option =>
                <Radio key={option} name="start" value={option} defaultChecked={option === 'guided'}
                  label={<Stack gap={1}><strong>{t(`projectCreate.${option}`)}</strong>
                    <span className="v2-muted">{t(`projectCreate.${option}Help`)}</span></Stack>} />)}</Stack>
            </fieldset>
          </Form>
          {org && !locked && !needsMfa && <ProjectPlan slug={org.slug} name={org.name} />}
        </Stack></Card>}
    {failure.status === 402 && <Dialog open={quotaOpen} onOpenChange={setQuotaOpen} title={t('projectCreate.limit')}
      description={planMessage} closeLabel={t('projectCreate.notNow')} actions={(quota?.organization_slug || org?.slug) && <Button asChild>
        <Link to="/org/$slug" params={{ slug: quota?.organization_slug ?? org?.slug ?? '' }} search={{ tab: 'plan' }}>{t('projectCreate.seePlans')}</Link>
      </Button>}><p>{t('projectCreate.limitHelp')}</p></Dialog>}
  </Stack>
}
