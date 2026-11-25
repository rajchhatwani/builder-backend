import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useReducer, useState } from 'react'
import { useLanguage, useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, Form, PageHeader, ReadOnlyNote, SettingsSection } from '../../patterns'
import { Badge, Button, Checkbox, CodeBlock, Dialog, Disclosure, EmptyState, Input, Pagination, Row, Skeleton, Stack, Table, useToast } from '../../ui'
import { checkTokenDays, tokenLimits, validators } from '../../validators'
import {
  errorText, fieldErrors, mcpEndpoint, membersOptions, pinnedTokensOptions, planOptions, statusOf, useCreatePinnedToken, useIntegrationWrite,
} from './api/connect'
import type { ConnectProps } from './api/connect'
import { CopyButton } from './components/CopyButton'
import { displayDate, RetryAlert } from './components/SettingsPage'
import { tokenReducer } from './state/token'

const scopeNames = ['mcp:read', 'mcp:write', 'mcp:generate', 'mcp:destructive']
const toolExamples = [
  ['list_projects', 'get_project_spec', 'get_data_model', 'get_openapi', 'validate_spec', 'get_project_status'],
  ['create_entity', 'add_field', 'add_relation', 'set_permissions', 'create_role', 'set_auth_config', 'apply_op'],
  ['generate_project'],
  ['apply_destructive_op', 'put_packs'],
]
const pageSize = 10
type IntegrationProps = ConnectProps & { organizationSlug?: string; openShare?: () => void }

function CreatePinnedToken({ projectId, disabled }: { projectId: string; disabled: boolean }) {
  const t = useT()
  const [flow, dispatch] = useReducer(tokenReducer, { step: 'closed' })
  const create = useCreatePinnedToken(projectId, token => dispatch({ type: 'created', token }))
  const field = (name: string) => t('connect.integrations.tokenFields.' + name)
  const close = () => {
    if (create.isPending) return
    dispatch({ type: 'close' })
    create.reset()
  }
  const conflict = statusOf(create.error) === 409
  return <Dialog open={flow.step !== 'closed'} onOpenChange={open => {
    if (open) dispatch({ type: 'open' })
    else close()
  }} title={field(flow.step === 'reveal' ? 'copy' : 'create')}
    description={field(flow.step === 'reveal' ? 'shownOnce' : 'pinned')}
    closeLabel={t(flow.step === 'reveal' ? 'connect.integrations.tokenFields.stored' : 'common.close')}
    trigger={<Button disabled={disabled}>{field('create')}</Button>}>
    {flow.step === 'create' && <Stack>
      {conflict && <ConflictBanner onReload={() => create.reset()} />}
      <Form fields={[
        { name: 'name', label: field('name'), validate: [validators.required, validators.length(tokenLimits.name)],
          control: props => <Input {...props} maxLength={tokenLimits.name} /> },
        { name: 'description', label: field('description'), validate: [validators.length(tokenLimits.description)],
          control: props => <Input {...props} maxLength={tokenLimits.description} /> },
        { name: 'expires_in_days', label: field('expires_in_days'), validate: [validators.required, checkTokenDays],
          control: props => <Input {...props} inputMode="numeric" defaultValue="90" /> },
        { name: 'scopes', label: field('scopes'), ownLabel: true,
          validateWith: (_, data) => data.getAll('scopes').length ? undefined : { key: 'validation.connectScope' },
          control: props => <Stack role="group" aria-label={field('scopes')} aria-describedby={props['aria-describedby']}>
            {scopeNames.map((scope, index) => <Checkbox key={scope} {...props} id={index === 0 ? props.id : undefined}
              label={t('connect.integrations.scopes.' + scope)} value={scope} defaultChecked={index === 0} />)}
          </Stack> },
      ]} pending={create.isPending} serverErrors={fieldErrors(create.error)} submitLabel={field('create')}
        submitProps={{ disabled: conflict }} formError={create.error && !conflict && !Object.keys(fieldErrors(create.error)).length
          ? t('common.serverText', { text: errorText(create.error) ?? t('common.actionFailed') }) : undefined}
        onSubmit={data => void create.mutate({
          name: String(data.get('name')).trim(), description: String(data.get('description')).trim() || null,
          expires_in_days: Number(data.get('expires_in_days')), scopes: data.getAll('scopes').map(String),
        })} />
    </Stack>}
    {flow.step === 'reveal' && <Stack>
      <CodeBlock code={flow.token} label={field('copy')} />
      <CopyButton value={flow.token} label={t('connect.copy')} />
    </Stack>}
  </Dialog>
}

export default function IntegrationsScreen({ projectId, role, rolePending, organizationSlug, openShare }: IntegrationProps) {
  const t = useT()
  const copy = (key: string, values?: Record<string, string | number>) => t('connect.integrations.' + key, values)
  const { language } = useLanguage()
  const dateText = (value: string | null) => displayDate(value, language) || copy('never')
  const members = useQuery(membersOptions(projectId))
  const owner = role === 'owner'
  const tokens = useQuery(pinnedTokensOptions(projectId, owner))
  const plan = useQuery(planOptions(organizationSlug ?? ''))
  const write = useIntegrationWrite(projectId)
  const toast = useToast()
  const changeAccess = async (user: string, enabled: boolean) => {
    await write.mutateAsync({ user, enabled })
    toast({ title: copy(enabled ? 'granted' : 'revokedAccess'), tone: 'success' })
  }
  const revokeToken = async (token: string) => {
    await write.mutateAsync({ token })
    toast({ title: copy('tokenRevoked'), tone: 'success' })
  }
  const { page = 1, tokensPage = 1 } = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const endpoint = mcpEndpoint()
  const list = members.data ?? []
  const pinned = tokens.data ?? []
  const pages = Math.max(1, Math.ceil(list.length / pageSize))
  const tokenPages = Math.max(1, Math.ceil(pinned.length / pageSize))
  const currentPage = Math.min(page, pages)
  const currentTokenPage = Math.min(tokensPage, tokenPages)
  const changePage = (key: 'page' | 'tokensPage', value: number) =>
    void navigate({ search: current => ({ ...current, [key]: value === 1 ? undefined : value }) })
  const tokenRestricted = plan.data?.plan.allow_mcp === false

  const columns = ['member', 'role', 'access', ...(owner ? ['actions'] : [])].map(id => ({ id, label: copy('columns.' + id) }))
  const tokenColumns = ['name', 'owner', 'scopes', 'last_used_at', 'last_mcp_use_at', 'expires_at', 'actions']
    .map(id => ({ id, label: copy('columns.' + id) }))
  const errors = write.error && <Stack>
    {statusOf(write.error) === 409 ? <ConflictBanner onReload={() => {
      write.reset()
      void members.refetch()
      if (owner) void tokens.refetch()
    }} /> : <RetryAlert message={t('common.serverText', { text: errorText(write.error) ?? t('common.actionFailed') })} error={write.error} />}
  </Stack>

  return <Stack gap={5}>
    <PageHeader title={copy('title')} description={copy('intro')} />
    {!owner && !rolePending && !members.isError && <ReadOnlyNote>{copy('readOnly')}</ReadOnlyNote>}
    <SettingsSection title={copy('endpoint')} description={copy('endpointHelp')}>
      <CodeBlock code={endpoint} label={copy('endpoint')} />
      <p>{copy('accountHelp')}</p>
      <Row>
        <CopyButton value={endpoint} label={t('connect.copy')} />
        <CopyButton value={JSON.stringify({ url: endpoint, headers: { Authorization: 'Bearer <your personal API token>' } }, null, 2)}
          label={copy('copyClient')} />
        <Button asChild><Link to="/account" search={{}}>{t('account.title')}</Link></Button>
      </Row>
      <Disclosure label={copy('scopeHelp')}>
        <Stack gap={2}>{scopeNames.map((scope, index) => <Stack key={scope} gap={1}>
          <strong>{copy('scopes.' + scope)}</strong>
          <p>{copy('tools', { tools: toolExamples[index].join(', ') })}</p>
        </Stack>)}</Stack>
      </Disclosure>
    </SettingsSection>
    {errors}
    <SettingsSection title={copy('who')}>
      {members.isPending && <Skeleton label={t('common.loading')} lines={4} />}
      {members.isError && <RetryAlert message={copy('membersError')} error={members.error} retry={() => void members.refetch()} />}
      {members.isSuccess && <>
        <Row>
          <Badge>{copy('enabledCount', { enabled: list.filter(member => member.mcp_enabled).length, count: list.length })}</Badge>
          {owner && openShare && <Button onClick={openShare}>{copy('manageMembers')}</Button>}
        </Row>
        {list.length ? <Table label={copy('who')} columns={columns} rows={list.slice((currentPage - 1) * pageSize, currentPage * pageSize).map(member => ({
          id: member.user_id,
          cells: [
            <Stack gap={1}><strong>{member.name || member.email}</strong>{member.name && <span>{member.email}</span>}
              <span className="v2-muted">{copy('memberSince', { date: dateText(member.created_at) })}</span></Stack>,
            t('connect.integrations.roles.' + member.role),
            <Badge tone={member.mcp_enabled ? 'success' : 'neutral'}>{t(member.mcp_enabled ? 'connect.on' : 'connect.off')}</Badge>,
            ...(owner ? [<MemberAction key={member.user_id} member={member} pending={write.isPending}
              reset={write.reset} error={write.error} change={enabled => changeAccess(member.user_id, enabled)} />] : []),
          ],
        }))} /> : <EmptyState title={copy('emptyMembers')} action={owner && openShare && <Button onClick={openShare}>{copy('manageMembers')}</Button>} />}
        {pages > 1 && <Pagination label={copy('who')} page={currentPage} pages={pages} onChange={value => changePage('page', value)} />}
      </>}
    </SettingsSection>
    {owner && <SettingsSection title={copy('tokensTitle')} description={copy('tokensHelp')}>
      {tokens.isPending && <Skeleton label={t('common.loading')} lines={4} />}
      {tokens.isError && <RetryAlert message={copy('tokensError')} error={tokens.error} retry={() => void tokens.refetch()} />}
      {tokens.isSuccess && (pinned.length ? <>
        <Table label={copy('tokensTitle')} columns={tokenColumns} rows={pinned.slice((currentTokenPage - 1) * pageSize, currentTokenPage * pageSize).map(token => ({
          id: token.id,
          cells: [
            <Stack gap={1}><strong>{token.name}</strong>{token.description && <p>{token.description}</p>}
              {token.last_mcp_use_at && <span title={copy('usedMcp')}><Badge>{copy('mcp')}</Badge></span>}
              <Disclosure label={copy('details')}><Stack gap={1}>
                <p>{copy('publicId', { id: token.public_id })}</p>
                <p>{copy('created', { date: dateText(token.created_at) })}</p>
                <p>{copy('revoked', { date: dateText(token.revoked_at) })}</p>
              </Stack></Disclosure></Stack>,
            token.user_email, <Stack gap={1}>{token.scopes.map(scope => <code key={scope}>{scope}</code>)}</Stack>,
            dateText(token.last_used_at), dateText(token.last_mcp_use_at),
            dateText(token.expires_at),
            <ConfirmDestructive key={token.id} trigger={<Button variant="danger" onClick={() => write.reset()}>{copy('revoke')}</Button>}
              title={copy('revokeTitle', { name: token.name })} description={copy('revokeHelp', { email: token.user_email })}
              action={copy('revokeToken')} pending={write.isPending} onConfirm={() => revokeToken(token.id)} />,
          ],
        }))} />
        {tokenPages > 1 && <Pagination label={copy('tokensTitle')} page={currentTokenPage} pages={tokenPages} onChange={value => changePage('tokensPage', value)} />}
      </> : <p>{copy('emptyTokens')}</p>)}
      <Row><CreatePinnedToken projectId={projectId} disabled={tokenRestricted} /></Row>
      <p className="v2-muted">{copy('unpinned')}</p>
    </SettingsSection>}
    <SettingsSection title={copy('chain')}>
      <ol>{['token', 'member', 'role', 'organization', 'tool'].map(step => <li key={step}>{copy('steps.' + step)}</li>)}</ol>
    </SettingsSection>
    <SettingsSection title={copy('plan')} description={copy('orgChecks')}>
      {organizationSlug && plan.isPending && <Skeleton label={t('common.loading')} />}
      {plan.isError && <RetryAlert message={copy('planError')} error={plan.error} retry={() => void plan.refetch()} />}
      {plan.data && <Stack gap={1}>
        <Badge tone={tokenRestricted ? 'warning' : 'success'}>{copy(tokenRestricted ? 'planNoMcp' : 'planMcp', { name: plan.data.plan.display_name })}</Badge>
        {!tokenRestricted && <p>{plan.data.usage.mcp_tokens_cap == null ? copy('mcpUnlimited', { used: plan.data.usage.mcp_tokens_used })
          : copy('mcpQuota', { used: plan.data.usage.mcp_tokens_used, max: plan.data.usage.mcp_tokens_cap })}</p>}
      </Stack>}
      <p>{copy('audit')}</p>
    </SettingsSection>
  </Stack>
}

function MemberAction({ member, pending, error, reset, change }: {
  member: { email: string; mcp_enabled: boolean }; pending: boolean; error: unknown; reset: () => void; change: (enabled: boolean) => Promise<void>
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const enabled = member.mcp_enabled
  const copy = (key: string) => t('connect.integrations.' + key, { email: member.email })
  const title = copy(enabled ? 'disableTitle' : 'enableTitle')
  const description = copy(enabled ? 'disableHelp' : 'enableHelp')
  const trigger = <Button variant={enabled ? 'danger' : 'default'} disabled={pending}
    onClick={reset}>{copy(enabled ? 'disable' : 'enable')}</Button>
  if (enabled) return <ConfirmDestructive trigger={trigger} title={title} description={description} action={copy('revokeMcp')}
    onConfirm={() => change(false)} pending={pending} />
  return <Dialog title={title} description={description} trigger={trigger} open={open} onOpenChange={setOpen}
    actions={<Button variant="primary" disabled={pending} onClick={() => void change(true).then(() => setOpen(false), () => undefined)}>{copy('allowMcp')}</Button>}>
    {error ? <RetryAlert message={t('common.serverText', { text: errorText(error) ?? t('common.actionFailed') })} error={error} /> : null}
  </Dialog>
}
