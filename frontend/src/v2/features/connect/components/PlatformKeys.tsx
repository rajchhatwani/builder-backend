import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useReducer, useState } from 'react'
import { useT } from '../../../i18n'
import { ConfirmDestructive, Form } from '../../../patterns'
import { Alert, Badge, Button, Card, Checkbox, CodeBlock, Disclosure, EmptyState, Input, Pagination, Row, Select, Stack, Table } from '../../../ui'
import { platformKeyIssue, validators } from '../../../validators'
import { statusOf } from '../api/connect'
import type { LiveSession } from '../api/liveWebhooks'
import { auditSize, catalogueOptions, createPlatformKey, platformAuditOptions, platformKeysOptions, revokePlatformKey } from '../api/platform'
import type { Catalogue, CreateKey, PlatformKey } from '../api/platform'
import { PlatformProblem, PlatformSecret, usePlatformAction, usePlatformDate } from './PlatformState'
import { initialGrant, scopeGrantReducer } from '../state/scopeGrant'

const pageSize = 10
export function KeyManager({ id, session, readOnly }: { id: string; session: LiveSession; readOnly: boolean }) {
  const t = useT()
  const date = usePlatformDate()
  const pageSearch = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const catalogue = useQuery(catalogueOptions(id, session))
  const keys = useQuery(platformKeysOptions(id, session))
  const { secret, reveal, dismiss, refresh } = usePlatformAction(id, session)
  const [formRevision, resetForm] = useState(0)
  const write = useMutation({
    mutationFn: async (action: { revoke: string } | { create: CreateKey }) => {
      if ('revoke' in action) {
        await revokePlatformKey(session, action.revoke)
        return 'revoked'
      }
      const key = await createPlatformKey(session, action.create)
      if (typeof key.key !== 'string' || !key.key) throw new Error('key_reply')
      reveal({ title: t('connectB.keys.created', { name: key.name }),
        summary: t('connectB.keys.createdMeta', { prefix: key.prefix, expires: date(key.expires_at),
          environment: t('connectB.keys.' + key.environment), scopes: key.scopes.join(', ') }),
        fields: [{ label: t('connectB.keys.secret'), value: key.key }] })
      resetForm(current => current + 1)
      return 'created'
    },
    onSuccess: refresh,
  })
  const retry = () => { write.reset(); void refresh() }
  const rows = keys.data ?? []
  const pages = Math.max(1, Math.ceil(rows.length / pageSize))
  const page = Math.min(pageSearch.page ?? 1, pages)
  const catalogueError = catalogue.error
  const keysError = keys.error
  if (!catalogue.data || !keys.data) return <Stack>
    {secret && <PlatformSecret secret={secret} dismiss={dismiss} />}
    <div data-testid="keys-error"><PlatformProblem error={catalogueError ?? keysError} retry={retry} errorKey="connectB.keys.loadError" /></div>
  </Stack>
  const current = catalogue.data
  const unavailable = Boolean(catalogueError || keysError)
  return <Stack>
    {unavailable && <div data-testid="keys-error"><PlatformProblem error={catalogueError ?? keysError} retry={retry} errorKey="connectB.keys.loadError" /></div>}
    {write.isError && <div data-testid="key-action-error"><PlatformProblem error={write.error} retry={retry} /></div>}
    {write.data === 'revoked' && <div data-testid="key-note"><Alert tone="success">{t('connectB.keys.revokeSuccess')}</Alert></div>}
    {secret && <PlatformSecret secret={secret} dismiss={dismiss} />}
    <Card><Stack>
      <h2>{t('connectB.keys.keys')}</h2>
      <p data-testid="catalogue-limits">{t('connectB.keys.limits', { production: current.rate_limit, sandbox: current.sandbox_rate_limit, days: current.key_ttl_days })}</p>
      {!current.entities.length ? <EmptyState title={t('connectB.keys.noEntities')}
        action={<Button onClick={() => void navigate({ search: previous => ({ ...previous, tab: 'settings' }) })}>{t('connectB.keys.settings')}</Button>} /> :
        !readOnly && !unavailable && <KeyForm key={formRevision} catalogue={current} pending={write.isPending || statusOf(write.error) === 409} write={input => write.mutate({ create: input })} />}
      {rows.length ? <>
        <div data-testid="keys-table"><Table label={t('connectB.keys.keys')} columns={['name', 'status', 'prefix', 'environment', 'scopes', 'expires', 'lastUsed', 'details', 'actions']
          .map(key => ({ id: key, label: t('connectB.keys.' + key) }))}
          rows={rows.slice((page - 1) * pageSize, page * pageSize).map(key => ({ id: key.id, cells: [
            t(key.app ? 'connectB.keys.appName' : 'schema.option', { value: key.name, app: key.app ?? '' }),
            <Badge tone={key.status === 'active' ? 'success' : 'neutral'}>{t('connectB.keys.' + key.status)}</Badge>,
            key.prefix, t('connectB.keys.' + key.environment), key.scopes.join(', '), date(key.expires_at), date(key.last_used_at),
            <KeyDetails item={key} />,
            !readOnly && !unavailable && key.status === 'active' ? <ConfirmDestructive
              trigger={<Button variant="danger" aria-label={t('connectB.keys.revokeName', { name: key.name })} disabled={write.isPending || statusOf(write.error) === 409}>{t('connectB.keys.revoke')}</Button>}
              title={t('connectB.keys.revokeName', { name: key.name })} description={t(key.app ? 'connectB.keys.revokeAppHelp' : 'connectB.keys.revokeHelp')}
              action={t('connectB.keys.revokeYes')} onConfirm={async () => { await write.mutateAsync({ revoke: key.id }) }} /> : null,
          ] }))} /></div>
        <Pagination label={t('connectB.keys.keys')} page={page} pages={pages}
          onChange={page => void navigate({ search: previous => ({ ...previous, page }) })} />
      </> : <EmptyState title={t('connectB.keys.noKeys')} description={t('connectB.keys.noKeysHelp')} />}
    </Stack></Card>
    <Card><Stack>
      <h2>{t('connectB.keys.publicApi')}</h2>
      <p>{t('connectB.keys.publicHelp')}</p>
      <CodeBlock code={t('connectB.keys.example')} />
      {current.entities.map(entity => <p key={entity.entity}>{t('connectB.keys.path', {
        path: '/public/v1/' + entity.plural_path.replace(/^\/+/, ''), fields: entity.fields.join(', '),
      })}</p>)}
    </Stack></Card>
  </Stack>
}

function KeyForm({ catalogue, pending, write }: { catalogue: Catalogue; pending: boolean; write: (input: CreateKey) => void }) {
  const t = useT()
  const [draft, dispatch] = useReducer(scopeGrantReducer, initialGrant)
  const [scopeError, setScopeError] = useState(false)
  const eligible = catalogue.entities.filter(entity => draft.environment === 'prod' || entity.sandbox)
  const selected = eligible.filter(entity => draft.picked.includes(entity.entity)).map(entity => entity.entity)
  const label = t('connectB.keys.scopes')
  return <div data-testid="key-form"><Form pending={pending} submitLabel={t('connectB.keys.create')}
    fields={[
      { name: 'name', label: t('connectB.keys.keyName'), validate: [validators.required, validators.length(80)],
        control: attrs => <Input {...attrs} maxLength={80} /> },
      { name: 'environment', label: t('connectB.keys.environment'), control: ({ disabled, ...attrs }) => <Select
        triggerProps={attrs} disabled={disabled} value={draft.environment}
        options={['prod', 'sandbox'].map(value => ({ value, label: t('connectB.keys.' + value) }))}
        onValueChange={environment => dispatch({ type: 'environment', environment: environment === 'sandbox' ? 'sandbox' : 'prod' })} /> },
      { name: 'ttl', label: t('connectB.keys.ttl'), hint: t('connectB.keys.ttlHelp', { max: catalogue.key_ttl_days }),
        validate: [value => platformKeyIssue(value, catalogue.key_ttl_days)],
        control: attrs => <Input {...attrs} type="number" min={1} max={catalogue.key_ttl_days} /> },
    ]} onSubmit={values => {
      if (!selected.length || selected.length > 64) {
        setScopeError(true)
        document.getElementById('platform-key-scopes')?.focus()
        return
      }
      const ttl = String(values.get('ttl') ?? '').trim()
      write({ name: String(values.get('name')).trim(), environment: draft.environment, scopes: selected, ttl_days: ttl ? Number(ttl) : null })
    }}>
    <Card role="group" aria-label={label} tabIndex={-1} id="platform-key-scopes"><Stack>
      <h3>{label}</h3>
      {scopeError && (!selected.length || selected.length > 64) && <Alert tone="danger">{t('connectB.validation.keyScopes')}</Alert>}
      {!eligible.length && <p>{t('connectB.keys.noSandbox')}</p>}
      {eligible.map(entity => <Checkbox key={entity.entity} disabled={pending}
        data-testid="key-scope"
        label={t('connectB.keys.scopeFields', { entity: entity.entity, fields: entity.fields.join(', ') })}
        checked={selected.includes(entity.entity)} onChange={event => dispatch({ type: 'scope', scope: entity.entity, checked: event.target.checked })} />)}
    </Stack></Card>
  </Form></div>
}

function KeyDetails({ item }: { item: PlatformKey }) {
  const t = useT()
  const date = usePlatformDate()
  return <Disclosure label={t('connectB.keys.details')}><Stack>
    <p>{t('connectB.keys.keyId', { id: item.id })}</p>
    <p>{t('connectB.keys.kind', { kind: item.kind })}</p>
    <p>{t('connectB.keys.addedAt', { date: date(item.created_at) })}</p>
    {item.revoked_at && <p>{t('connectB.keys.revokedAt', { date: date(item.revoked_at) })}</p>}
  </Stack></Disclosure>
}

export function KeyAudit({ id, session }: { id: string; session: LiveSession }) {
  const t = useT()
  const date = usePlatformDate()
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const page = search.auditPage ?? 1
  const query = useQuery(platformAuditOptions(id, session, page))
  const go = (auditPage: number) => void navigate({ search: previous => ({ ...previous, auditPage }) })
  const label = t('connectB.keys.audit')
  return <Card><Stack>
    <h2>{label}</h2>
    {!query.data || query.isError ? <PlatformProblem error={query.error} retry={() => void query.refetch()} errorKey="connectB.keys.auditError" /> :
      <>
        {query.data.length ? <div data-testid="audit-table"><Table label={label}
          columns={['time', 'actor', 'operation', 'target', 'details'].map(id => ({ id, label: t('connectB.keys.' + id) }))}
          rows={query.data.map(row => ({ id: row.id, cells: [date(row.at), row.actor, row.action, row.target ?? t('connectB.platform.noDate'),
            <Disclosure label={t('connectB.keys.details')}><CodeBlock code={JSON.stringify(row.detail, null, 2)} /></Disclosure>] }))} /></div> :
          <EmptyState title={t('connectB.keys.noAudit')} action={<Button onClick={() => page > 1 ? go(1) : void query.refetch()}>{t('common.reload')}</Button>} />}
        <Row>
          <Button disabled={page === 1} onClick={() => go(page - 1)}>{t('common.previous')}</Button>
          <span aria-live="polite">{t('connectB.keys.auditPage', { page })}</span>
          <Button disabled={query.data.length < auditSize || page >= 20_001} onClick={() => go(page + 1)}>{t('connectB.keys.showMore')}</Button>
        </Row>
      </>}
  </Stack></Card>
}
