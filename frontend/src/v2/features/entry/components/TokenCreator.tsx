import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import { Alert, Button, Checkbox, Dialog, Input, Select, Skeleton, Stack } from '../../../ui'
import { checkTokenDays, tokenLimits, validators } from '../../../validators'
import { accountApi, mfaOptions } from '../api/account'
import { entryError, useEntryAction } from '../api/entry'
import type { UserAccount } from '../api/entry'
import { projectMemberOptions, projectPlanOptions } from '../api/projects'
import type { Organization, Project } from '../api/projects'
import { EntryProblem } from './EntryFrame'
import { projectLocked } from './entryData'
import { valueOf } from './fields'
import { authProblem } from './messages'

const apiScopes = ['read', 'write', 'generate'] as const
const mcpScopes = ['mcp:read', 'mcp:write', 'mcp:generate', 'mcp:preview', 'mcp:destructive'] as const
const allProjects = 'all-projects'

export function TokenCreator({ projects, orgs, user, onCreated, onClose }: {
  projects: Project[]; orgs: Organization[]; user: UserAccount; onCreated: (raw: string) => void; onClose: () => void
}) {
  const t = useT()
  const action = useEntryAction()
  const [pin, setPin] = useState(allProjects)
  const [selected, setSelected] = useState<string[]>([])
  const mfa = useQuery({ ...mfaOptions, enabled: orgs.some(org => org.require_mfa) })
  const orgFor = (id?: string | null) => orgs.find(org => org.id === id)
  const choices = projects.filter(project => {
    const org = orgFor(project.organization_id)
    return !projectLocked(project, org) && (!org?.require_mfa || mfa.data?.session_mfa)
  })
  const pinned = choices.find(project => project.id === pin)
  const pinMissing = pin !== allProjects && !pinned
  const members = useQuery(projectMemberOptions(pinned?.id ?? ''))
  const role = members.data?.find(member => member.user_id === user.id)?.role
  const chargedOrg = orgFor(pinned ? pinned.organization_id : user.default_organization_id)
  const chargedLocked = Boolean(chargedOrg?.deletion_requested_at)
  const plan = useQuery({ ...projectPlanOptions(chargedOrg?.slug ?? ''), enabled: Boolean(chargedOrg && !chargedLocked && (!chargedOrg.require_mfa || mfa.data?.session_mfa)) })
  const planData = plan.data
  const mcpBlocked = planData?.plan.allow_mcp === false
  const apiFull = planData && planData.usage.api_tokens_cap !== null && planData.usage.api_tokens_used >= planData.usage.api_tokens_cap
  const mcpFull = planData && planData.usage.mcp_tokens_cap !== null && planData.usage.mcp_tokens_used >= planData.usage.mcp_tokens_cap
  const isDisabled = (scope: string) => (scope.startsWith('mcp:') && (mcpBlocked || mcpFull)) ||
    (Boolean(pinned) && (scope === 'write' || scope === 'mcp:write') && role !== 'owner' && role !== 'editor')
  const activeScopes = selected.filter(scope => !isDisabled(scope))
  const failure = entryError(action.error)
  const problemKeys: Record<string, string> = {
    too_many_tokens: 'account.userTokenLimit', api_token_limit: 'account.orgTokenLimit',
    mcp_token_limit: 'account.orgMcpLimit', mcp_not_in_plan: 'account.mcpBlocked',
    invalid_scope: 'account.scopeError', not_found: 'account.projectMissing',
  }
  const problem = failure.message === 'viewers cannot create write tokens' ? 'account.tokenViewer'
    : Object.hasOwn(problemKeys, failure.code) ? problemKeys[failure.code] : authProblem(action.error)

  function scopeGroup(title: string, group: readonly string[], hint?: string) {
    return <fieldset className="v2-token-scopes" disabled={action.isPending}>
      <legend>{title}</legend>
      <Stack gap={1}>
        {group.map(scope => <Checkbox key={scope} checked={activeScopes.includes(scope)} disabled={isDisabled(scope)}
          onChange={event => setSelected(previous => event.target.checked ? [...new Set([...previous, scope])] : previous.filter(item => item !== scope))}
          label={<Stack gap={0}><strong>{t(`account.scope.${scope}.label`)}</strong>
            <span className="v2-muted">{t(`account.scope.${scope}.help`)}</span></Stack>} />)}
        {hint && <p className="v2-muted">{hint}</p>}
      </Stack>
    </fieldset>
  }

  return <Dialog open onOpenChange={open => { if (!open && !action.isPending) onClose() }}
    title={t('account.newTokenTitle')} description={t('account.newTokenIntro')} closeLabel={t('projectCreate.cancel')}>
    <Stack>
      {action.isError && <EntryProblem error={action.error} message={t(problem)} />}
      <Form fields={[
        { name: 'name', label: t('account.tokenName'), validate: [validators.required, validators.length(tokenLimits.name)],
          control: attributes => <Input {...attributes} required maxLength={tokenLimits.name} placeholder={t('account.tokenNameExample')} /> },
        { name: 'description', label: t('account.tokenDescription'), validate: [validators.length(tokenLimits.description)],
          control: attributes => <Input {...attributes} maxLength={tokenLimits.description} placeholder={t('account.tokenDescriptionExample')} /> },
        { name: 'project', label: t('account.pinToken'),
          control: attributes => <Select triggerProps={attributes} value={pin} disabled={attributes.disabled}
            options={[{ value: allProjects, label: t('account.allMyProjects') },
              ...choices.map(project => ({ value: project.id, label: project.name }))]}
            onValueChange={value => {
              setPin(value)
              setSelected(previous => previous.filter(scope => scope !== 'write' && scope !== 'mcp:write'))
              action.reset()
            }} /> },
        { name: 'days', label: t('account.expiresAfter'), hint: t('account.daysHelp'), validate: [validators.required, checkTokenDays],
          control: attributes => <Input {...attributes} required type="number" min={tokenLimits.minDays} max={tokenLimits.maxDays} step={1} defaultValue={90} /> },
      ]} submitLabel={t('account.createToken')} pending={action.isPending}
        submitProps={{ disabled: !activeScopes.length || pinMissing || chargedLocked || Boolean(apiFull) }}
        onSubmit={values => action.run(async () => {
          const result = await accountApi.createToken({
            name: valueOf(values, 'name').trim(), description: valueOf(values, 'description').trim() || null,
            project_id: pinned?.id ?? null, expires_in_days: Number(valueOf(values, 'days')), scopes: activeScopes,
          })
          onCreated(result.token)
        })}>
        {chargedOrg && <p className="v2-muted">{t('account.chargedTo', { name: chargedOrg.name })}</p>}
        {chargedLocked && <Alert tone="warning">{t('entry.orgLocked')}</Alert>}
        {pinMissing && <Alert tone="warning">{t('account.projectMissing')}</Alert>}
        {pinned && members.isPending && <Skeleton lines={1} label={t('account.loadingRole')} />}
        {pinned && members.isError && <EntryProblem error={members.error}
          message={t('account.tokenRoleFailed')} retry={() => void members.refetch()} />}
        {pinned && role === 'viewer' && <Alert>{t('account.tokenViewer')}</Alert>}
        {plan.isError && <EntryProblem error={plan.error} message={t('projectList.planFailed')} retry={() => void plan.refetch()} />}
        {(apiFull || mcpBlocked || mcpFull) && <Alert tone="warning" action={chargedOrg && <Button asChild>
          <Link to="/org/$slug" params={{ slug: chargedOrg.slug }} search={{ tab: 'plan' }}>{t('projectCreate.seePlans')}</Link>
        </Button>}>{t(apiFull ? 'account.orgTokenLimit' : mcpBlocked ? 'account.mcpBlocked' : 'account.orgMcpLimit')}</Alert>}
        {scopeGroup(t('account.apiScopes'), apiScopes)}
        {scopeGroup(t('account.mcpScopes'), mcpScopes, t('account.mcpHelp'))}
        {!activeScopes.length && <p className="v2-muted">{t('account.chooseScope')}</p>}
      </Form>
    </Stack>
  </Dialog>
}
