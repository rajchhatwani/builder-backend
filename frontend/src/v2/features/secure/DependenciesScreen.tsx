import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, PageHeader, SettingsSection } from '../../patterns'
import { Badge, Button, EmptyState, Grid, Input, Pagination, Row, Stack, Table } from '../../ui'
import { dependencyChecks } from '../../validators'
import { controlsApi, dependencyOptions, type DependencyRequest } from './api/controls'
import { codeOf, fieldErrors, useSecureMutation } from './api/security'
import { canEdit, LoadFailure, readText, SecureLoading, SecureRole, textField, useSecureSearch, WriteNotice, type SecureProps } from './SecureForm'

const pageSize = 10
const statuses = ['pending', 'approved', 'denied', 'revoked', 'expired'] as const
type Decision = 'approve' | 'deny' | 'revoke'
const date = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(value))

function RequestForm({ id, reload }: { id: string; reload: () => void }) {
  const t = useT()
  const [revision, reset] = useState(0)
  const [draft, setDraft] = useState({ package: '', version: '', reason: '' })
  const change = (key: keyof typeof draft) => (value: string) => setDraft(current => ({ ...current, [key]: value }))
  const incomplete = !draft.package.trim() || !draft.version.trim() || Boolean(dependencyChecks.reason(draft.reason))
  const write = useSecureMutation(id, (body: Parameters<typeof controlsApi.requestDependency>[1]) =>
    controlsApi.requestDependency(id, body), 'dependencies')
  const fields = [
    textField('package', t('dependency.package'), '', { required: true, max: 100, checks: [dependencyChecks.package], change: change('package') }),
    textField('version', t('dependency.version'), '', { required: true, max: 50, checks: [dependencyChecks.version], hint: t('dependency.exactVersion'), change: change('version') }),
    textField('reason', t('dependency.reason'), '', { area: true, max: 2000, checks: [dependencyChecks.reason], change: change('reason') }),
    textField('hashes', t('dependency.hashes'), '', { area: true, checks: [dependencyChecks.hashes], hint: t('dependency.hashHint') }),
  ]
  return <SettingsSection title={t('dependency.request')}>
    <Form key={revision} fields={fields} pending={write.isPending} serverErrors={fieldErrors(write.error)}
      submitLabel={t('dependency.send')} submitProps={{ disabled: incomplete }} onSubmit={data => {
        const hashes = readText(data, 'hashes').split(/\s+/).filter(Boolean)
        write.mutate({ package: readText(data, 'package'), version: readText(data, 'version'), reason: readText(data, 'reason'),
          ...(hashes.length ? { hashes } : {}) }, { onSuccess: () => { setDraft({ package: '', version: '', reason: '' }); reset(value => value + 1) } })
      }} />
    <WriteNotice error={write.error} message={codeOf(write.error) === 'dependency_already_allowed' ? t('dependency.alreadyAllowed') : t('dependency.requestError')}
      saved={write.isSuccess ? t('dependency.updated') : undefined} reload={() => { write.reset(); reload() }} />
  </SettingsSection>
}

export default function DependenciesScreen(props: SecureProps) {
  const { projectId: id } = props
  const t = useT()
  const { search, page: setPage } = useSecureSearch()
  const data = useQuery(dependencyOptions(id))
  const form = useRef<HTMLDivElement>(null)
  const [decision, setDecision] = useState<{ action: Decision; request: DependencyRequest }>()
  const [note, setNote] = useState('')
  const write = useSecureMutation(id, async (action: { hook: string } | { action: Decision; request: DependencyRequest; note: string }) => {
    if ('hook' in action) return controlsApi.approveRegistryHook(id, action.hook)
    if (action.action === 'approve') return controlsApi.approveDependency(id, action.request, action.note)
    return action.action === 'deny' ? controlsApi.denyDependency(id, action.request.id, action.note)
      : controlsApi.revokeDependency(id, action.request.id, action.note)
  }, 'dependencies')
  const reload = () => {
    setDecision(undefined)
    write.reset()
    void data.refetch()
  }
  const pin = (entry: { package: string; version: string }) => t('dependency.pin', entry)
  const message = (code: string | undefined) => {
    const known = ['dependency_approval_mismatch', 'dependency_request_stale', 'dependency_hashes_required',
      'dependency_request_decided', 'dependency_not_approved', 'hook_already_approved']
    return code && known.includes(code) ? t(`dependency.${code}`) : t('dependency.actionError')
  }
  const owner = props.role === 'owner'
  const canRequest = canEdit(props)
  const current = data.data
  const page = Math.min(search.page ?? 1, Math.max(1, Math.ceil((current?.requests.length ?? 0) / pageSize)))
  function action(request: DependencyRequest, action: Decision) {
    return <Button key={action} variant={action === 'approve' ? 'default' : 'danger'} disabled={write.isPending}
      onClick={() => { write.reset(); setNote(''); setDecision({ request, action }) }}>{t(`dependency.${action}`)}</Button>
  }
  return <Stack gap={4}>
    <PageHeader title={t('dependency.title')} description={t('dependency.lead')} />
    <SecureRole {...props} />
    {data.isPending ? <SecureLoading label={t('common.loading')} /> : data.isError ?
      <LoadFailure error={data.error} message={t('dependency.loadError')} retry={reload} /> : current && <>
        <WriteNotice error={write.error} message={message(codeOf(write.error))} reload={reload}
          saved={write.isSuccess ? t('dependency.updated') : undefined} />
        <Grid>
          <SettingsSection title={t('dependency.policy')}>
            <p>{t('dependency.pending', { count: current.policy.pending_requests })}</p>
            <p>{t('dependency.allowList', { names: current.policy.allow_list.join(', ') || t('dependency.none') })}</p>
            <p className="v2-muted">{t('dependency.manifest')}</p>
            {!!Object.keys(current.policy.curated_sets).length && <details><summary>{t('dependency.curated')}</summary>
              <dl>{Object.entries(current.policy.curated_sets).map(([key, packages]) =>
                <div key={key}><dt>{key}</dt><dd>{Object.entries(packages).map(([name, version]) => pin({ package: name, version })).join(', ')}</dd></div>)}</dl>
            </details>}
            {!!current.policy.approved.length && <Stack gap={2}><h3>{t('dependency.approvedPins')}</h3>
              {current.policy.approved.map(item => <details key={pin(item)}>
                <summary>{item.expires_at ? t('dependency.expiry', { pin: pin(item), date: date(item.expires_at) }) : pin(item)}</summary>
                <ul>{item.hashes.map(hash => <li key={hash}><code>{hash}</code></li>)}</ul>
              </details>)}
            </Stack>}
          </SettingsSection>
          {canRequest && <div ref={form}><RequestForm id={id} reload={reload} /></div>}
        </Grid>
        <SettingsSection title={t('dependency.requests')}>
          {current.requests.length ? <>
            <Table label={t('dependency.requests')} columns={['package', 'reason', 'status', 'actions'].map(key => ({ id: key, label: t(`dependency.${key}`) }))}
              rows={current.requests.slice((page - 1) * pageSize, page * pageSize).map(request => ({
                id: request.id, testId: 'deps-row', status: request.status, cells: [
                  <details><summary>{pin(request)}</summary><Stack gap={1}>
                    {(['created_at', 'requested_by', 'decided_at', 'decided_by', 'expires_at', 'revoked_at', 'revoked_by'] as const).map(key =>
                      request[key] && <p key={key}>{t(`dependency.${key}`, { value: key.endsWith('_at') ? date(request[key]) : request[key] })}</p>)}
                    <ul>{request.hashes.map(hash => <li key={hash}><code>{hash}</code></li>)}</ul>
                  </Stack></details>,
                  <Stack gap={1}><p>{request.reason}</p>{request.decision_note && <p>{t('dependency.noteValue', { value: request.decision_note })}</p>}</Stack>,
                  <Badge tone={request.status === 'approved' ? 'success' : request.status === 'pending' ? 'warning' : 'neutral'}>
                    {statuses.find(value => value === request.status) ? t(`dependency.status_${request.status}`) : request.status}
                  </Badge>,
                  owner && <Row>{request.status === 'pending' ? [action(request, 'approve'), action(request, 'deny')] :
                    request.status === 'approved' ? action(request, 'revoke') : null}</Row>,
                ],
              }))} />
            {current.requests.length > pageSize && <Pagination page={page} pages={Math.ceil(current.requests.length / pageSize)} onChange={setPage} label={t('dependency.requests')} />}
          </> : <EmptyState title={t('dependency.empty')} action={canRequest ?
            <Button onClick={() => form.current?.querySelector('input')?.focus()}>{t('dependency.request')}</Button> :
            <Button onClick={reload}>{t('common.reload')}</Button>} />}
          <details><summary>{t('dependency.lifecycle')}</summary><ol>
            <li>{t('dependency.lifecyclePending')}</li><li>{t('dependency.lifecycleDecision')}</li><li>{t('dependency.lifecycleEnd')}</li>
          </ol></details>
        </SettingsSection>
        <SettingsSection title={t('dependency.registry')}>
          <Stack gap={2}><h3>{t('dependency.locked')}</h3>{current.locks.length ? current.locks.map(item =>
            <details key={item.id}><summary>{t('dependency.registryPin', { pin: pin(item), hash: item.hash.slice(0, 16) })}</summary>
              <p><code>{item.hash}</code></p><p>{date(item.created_at)}</p></details>) : <p>{t('dependency.noneRecorded')}</p>}</Stack>
          <Stack gap={2}><h3>{t('dependency.hooks')}</h3>{current.hooks.length ? current.hooks.map(item =>
            <details key={item.id}><summary>{t('dependency.hook', { name: item.hook_name, author: item.author, hash: item.content_hash.slice(0, 12) })}</summary>
              <Stack gap={2}><p><code>{item.content_hash}</code></p><p>{date(item.created_at)}</p>
                {item.approved_by ? <Badge tone="success">{t('dependency.status_approved')}</Badge> : owner &&
                  <Row><Button disabled={write.isPending} aria-label={t('dependency.approveHookNamed', { name: item.hook_name })}
                    onClick={() => write.mutate({ hook: item.id })}>{t('dependency.approveHook')}</Button></Row>}</Stack></details>) : <p>{t('dependency.noneRecorded')}</p>}</Stack>
          <Stack gap={2}><h3>{t('dependency.blocks')}</h3>{current.blocks.length ? <>
            <p>{t('dependency.blockCount', { count: current.blocks.length })}</p>
            <ul>{current.blocks.map(item => <li key={item.id}>
              {t('dependency.block', { name: String(item.name ?? ''), version: String(item.version ?? ''), date: date(item.created_at) })}
              <p><code>{String(item.content_hash ?? '')}</code></p></li>)}</ul>
          </> : <p>{t('dependency.noneRecorded')}</p>}</Stack>
        </SettingsSection>
      </>}
    {decision && <ConfirmDestructive open onOpenChange={open => { if (!open) setDecision(undefined) }}
      title={t(`dependency.${decision.action}Title`, { pin: pin(decision.request) })} action={t(`dependency.${decision.action}`)}
      description={t(`dependency.${decision.action}Help`, { pin: pin(decision.request), count: decision.request.hashes.length })}
      error={write.error ? message(codeOf(write.error)) : undefined}
      pending={write.isPending}
      disabled={Boolean(write.error) && codeOf(write.error) !== undefined}
      onConfirm={() => write.mutateAsync({ ...decision, note }).then(() => undefined)}>
      <label><Stack gap={1}>{t('dependency.note')}<Input value={note} onChange={event => setNote(event.target.value)} maxLength={500} /></Stack></label>
      {decision.action === 'approve' && <ul>{decision.request.hashes.map(hash => <li key={hash}><code>{hash}</code></li>)}</ul>}
      {write.error && <Row><Button onClick={reload}>{t('common.reload')}</Button></Row>}
    </ConfirmDestructive>}
  </Stack>
}
