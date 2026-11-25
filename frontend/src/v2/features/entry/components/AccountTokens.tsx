import { useNavigate, useSearch } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useLanguage, useT } from '../../../i18n'
import { ConfirmDestructive, SettingsSection } from '../../../patterns'
import { Alert, Badge, Button, EmptyState, Pagination, Row, Skeleton, Stack, Table, useToast } from '../../../ui'
import { tokenLimits } from '../../../validators'
import { accountApi, accountKeys, tokenOptions } from '../api/account'
import type { ApiTokenInfo } from '../api/account'
import { entryError, organizationsOptions } from '../api/entry'
import type { UserAccount } from '../api/entry'
import { allProjectsOptions, projectKeys } from '../api/projects'
import { EntryProblem } from './EntryFrame'
import { useCopy } from './SecondFactor'
import { TokenCreator } from './TokenCreator'
import { formatEntryDate } from './entryData'
import { authProblem } from './messages'

const pageSize = 10
const columns = ['tokenName', 'can', 'for', 'lastUsed', 'lastMcp', 'expires', 'actions']

function tokenStatus(token: ApiTokenInfo) {
  if (token.revoked_at) return 'revoked'
  return Date.parse(token.expires_at) <= Date.now() ? 'expired' : 'active'
}

function RevokeToken({ token }: { token: ApiTokenInfo }) {
  const t = useT()
  const client = useQueryClient()
  const toast = useToast()
  const action = useMutation({
    mutationFn: () => accountApi.revokeToken(token.id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: accountKeys.tokens() })
      void client.invalidateQueries({ queryKey: projectKeys.plans() })
      toast({ title: t('account.tokenRevoked'), tone: 'success' })
    },
  })
  return <ConfirmDestructive trigger={<Button variant="danger" onClick={() => action.reset()}>{t('account.revoke')}</Button>}
    title={t('account.revokeTitle', { name: token.name })} description={t('account.revokeHelp')} action={t('account.revokeToken')}
    onConfirm={async () => { await action.mutateAsync() }}
    error={action.isError ? t(entryError(action.error).status === 404 ? 'account.tokenMissing' : authProblem(action.error)) : undefined} />
}

export function AccountTokens({ user }: { user: UserAccount }) {
  const t = useT()
  const { language } = useLanguage()
  const client = useQueryClient()
  const copy = useCopy()
  const toast = useToast()
  const search = useSearch({ from: '/account' })
  const navigate = useNavigate({ from: '/account' })
  const [creating, setCreating] = useState(false)
  const [fresh, setFresh] = useState<string>()
  const tokens = useQuery(tokenOptions)
  const projects = useQuery(allProjectsOptions)
  const organizations = useQuery(organizationsOptions(user.id))
  const failed = [tokens, projects].find(query => query.isError)
  const active = tokens.data?.filter(token => tokenStatus(token) === 'active') ?? []
  const visible = search.history ? tokens.data ?? [] : active
  const pages = Math.max(1, Math.ceil(visible.length / pageSize))
  const page = Math.min(search.page ?? 1, pages)
  const names = new Map(projects.data?.map(project => [project.id, project.name]))
  const date = (value?: string | null) => formatEntryDate(value, language, t('account.never'))
  const canCreate = !fresh && active.length < tokenLimits.active
  const newToken = <Button variant="primary" disabled={!canCreate} onClick={() => setCreating(true)}>{t('account.newToken')}</Button>

  const rows = visible.slice((page - 1) * pageSize, page * pageSize).map(token => {
    const status = tokenStatus(token)
    return {
      id: token.id,
      cells: [
        <Stack gap={1}><strong>{token.name}</strong>{token.description && <span className="v2-muted">{token.description}</span>}
          {search.history && <Stack gap={1}><code>{token.public_id}</code>
            <span className="v2-muted">{t('account.tokenCreated', { date: date(token.created_at) })}</span>
            <span>{token.revoked_at ? t('account.tokenRevokedOn', { date: date(token.revoked_at) }) : t(`account.status.${status}`)}</span>
          </Stack>}
        </Stack>,
        <Stack gap={1}><span>{token.scopes.map(scope => t('account.scopeValue', { scope })).join(t('account.separator'))}</span>
          {token.scopes.some(scope => scope.startsWith('mcp:')) && <Badge>{t('account.mcpBadge')}</Badge>}</Stack>,
        token.project_id ? names.get(token.project_id) ?? t('account.aProject') : t('account.allProjects'),
        date(token.last_used_at), date(token.last_mcp_use_at), date(token.expires_at),
        status === 'active' && <RevokeToken token={token} />,
      ],
    }
  })

  return <SettingsSection title={t('account.tokens')}>
    {fresh && <Stack>
      <Alert>{t('account.saveToken')}</Alert>
      <code className="v2-token-value">{fresh}</code>
      <Row>
        <Button onClick={() => void copy(fresh, 'account.tokenCopied')}>{t('entry.copy')}</Button>
        <Button variant="primary" onClick={() => setFresh(undefined)}>{t('account.tokenSaved')}</Button>
      </Row>
    </Stack>}
    {failed ? <EntryProblem error={failed.error} message={t('account.tokensFailed')}
      retry={() => { void tokens.refetch(); void projects.refetch() }} /> : tokens.isPending || projects.isPending
      ? <Skeleton lines={7} label={t('account.loadingTokens')} /> : <>
        <Row>
          {rows.length > 0 && newToken}
          <Button aria-pressed={Boolean(search.history)} onClick={() => void navigate({
            search: { history: search.history ? undefined : true, page: undefined },
          })}>{t(search.history ? 'account.hideHistory' : 'account.showHistory')}</Button>
          <span className="v2-muted">{t('account.tokenCapacity', { count: active.length, cap: tokenLimits.active })}</span>
        </Row>
        {!canCreate && !fresh && <Alert tone="warning">{t('account.userTokenLimit')}</Alert>}
        {rows.length ? <Table label={t('account.tokens')} columns={columns.map(id => ({ id, label: t(`account.${id}`) }))} rows={rows} />
          : <EmptyState title={t(search.history ? 'account.noTokenHistory' : 'account.noTokens')} action={newToken} />}
        {pages > 1 && <Pagination label={t('account.tokens')} page={page} pages={pages} onChange={next => void navigate({
          search: previous => ({ ...previous, page: next > 1 ? next : undefined }),
        })} />}
      </>}
    {creating && (organizations.isError || organizations.isPending
      ? <Stack>
        {organizations.isError ? <EntryProblem error={organizations.error} message={t('projectCreate.ownersFailed')}
          retry={() => void organizations.refetch()} /> : <Skeleton label={t('projectCreate.loading')} />}
        <Row><Button onClick={() => setCreating(false)}>{t('projectCreate.cancel')}</Button></Row>
      </Stack> : <TokenCreator projects={projects.data ?? []} orgs={organizations.data.items} user={user}
        onClose={() => setCreating(false)} onCreated={token => {
          setFresh(token)
          setCreating(false)
          void client.invalidateQueries({ queryKey: accountKeys.tokens() })
          void client.invalidateQueries({ queryKey: projectKeys.plans() })
          toast({ title: t('account.tokenCreatedToast'), tone: 'success' })
        }} />)}
  </SettingsSection>
}
