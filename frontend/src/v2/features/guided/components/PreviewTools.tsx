import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { lazy, Suspense, useEffect, useReducer, useRef, useState } from 'react'
import { backoffDelay, cellText, createSseParser, extractRows, MAX_RECONNECTS, PAGE_SIZE, pageQuery } from '../../../../shell/ai/stageLogic'
import { evidence } from '../../../../shell/ai/seeItLogic'
import type { Entity } from '../../../../shell/ai/seeItLogic'
import { buildRequestUrl, generatePayload, parseOperations } from '../../../../shell/workbench/workbenchLogic'
import type { Json, Operation } from '../../../../shell/workbench/workbenchLogic'
import { useT } from '../../../i18n'
import { Form, SettingsSection } from '../../../patterns'
import { Alert, Badge, Button, CodeBlock, DesktopOnlyCard, EmptyState, ErrorBoundary, Field, Input, Pagination, Row, Select, Skeleton, Stack, Table, Textarea, useToast } from '../../../ui'
import { validators } from '../../../validators'
import { rolesOptions } from '../api/delivery'
import type { Preview } from '../api/delivery'
import { previewJson, previewKeys, previewRequest, proxyAddress } from '../api/preview'
import { consoleReducer, logReducer } from '../state/preview'
import type { Credential } from '../state/preview'
import { ConfirmAction } from './DeliveryControls'
import { GuidedLoadError } from './GuidedFeedback'
import { usePreviewToolSearch } from './usePreviewToolSearch'

const route = '/projects/$projectId/$section'
export const Scalar = lazy(() => import('../../../../shell/workbench/ScalarView'))
type Connection = { preview: Preview; credential: Credential }

export function PreviewTools({ preview, credential, entity, entities, doc, write }: Connection & {
  entity?: Entity; entities: Entity[]; doc: unknown; write: boolean
}) {
  const t = useT()
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const connection = { preview, credential }
  const view = search.view
  const valid = ['console', 'reference', 'data', 'logs']
  return <SettingsSection title={t('preview.tools')}>
    <Row>{valid.map(item => <Button key={item} disabled={doc == null && item !== 'logs'} aria-expanded={view === item} onClick={() => void navigate({
      search: previous => ({ ...previous, view: previous.view === item ? undefined : item, tool: undefined, page: undefined }),
    })}>{t('preview.' + item)}</Button>)}</Row>
    {view === 'console' && doc != null && <>
      <div className="v2-phone-only"><DesktopOnlyCard /></div>
      <div className="v2-phone-hidden"><RequestConsole {...connection} doc={doc} write={write} /></div>
    </>}
    {view === 'reference' && doc != null && typeof doc === 'object' && <ErrorBoundary fallback={retry => <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t('preview.apiError')}</Alert>}>
      <Suspense fallback={<Skeleton lines={8} label={t('preview.loadingApi')} />}>
        <Scalar document={doc as Record<string, unknown>} origin={proxyAddress(preview, '/').href} />
      </Suspense>
    </ErrorBoundary>}
    {view === 'data' && (entity ? <PreviewData {...connection} entity={entity} entities={entities} />
      : <p>{t('preview.noEntities')}</p>)}
    {view === 'logs' && <PreviewLogs {...connection} />}
  </SettingsSection>
}

function PreviewData({ preview, credential, entity, entities }: Connection & { entity: Entity; entities: Entity[] }) {
  const t = useT()
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const page = search.page ?? 1
  const records = useQuery({
    queryKey: [...previewKeys.proxy(preview.id, credential.revision), 'records', entity.listPath, page], retry: false, gcTime: 0,
    queryFn: async () => {
      const extracted = extractRows(await previewJson(preview, credential, entity.listPath + '?' + pageQuery(page - 1)))
      if (!extracted) throw new Error('preview_bad_records')
      return extracted
    },
  })
  return <Stack>
    <Row><Badge>{t('common.readOnly')}</Badge><Field label={t('preview.entity')}>{attrs =>
      <Select triggerProps={attrs} value={entity.name} options={entities.map(item => ({ value: item.name, label: item.name }))}
        onValueChange={entity => void navigate({ search: previous => ({ ...previous, entity, page: undefined }) })} />
    }</Field></Row>
    {records.isPending ? <Skeleton lines={4} />
      : records.isError ? <GuidedLoadError error={records.error} label={t('preview.recordsError')} retry={() => void records.refetch()} />
      : records.data.rows.length === 0 ? <EmptyState title={t('preview.noRecords')}
        action={<Button onClick={() => void records.refetch()}>{t('approval.refresh')}</Button>} />
      : <Table label={t('preview.data')} columns={records.data.columns.map(id => ({ id, label: id }))}
        rows={records.data.rows.map((record, index) => ({
          id: String(index), cells: records.data.columns.map(column => cellText(record[column])),
        }))} />}
    {records.data && <Pagination label={t('preview.data')} page={page}
      pages={records.data.total === null ? page + Number(records.data.rows.length === PAGE_SIZE) : Math.ceil(records.data.total / PAGE_SIZE)}
      onChange={page => void navigate({ search: previous => ({ ...previous, page }) })} />}
  </Stack>
}

function PreviewLogs({ preview, credential }: Connection) {
  const t = useT()
  const toast = useToast()
  const [state, dispatch] = useReducer(logReducer, { lines: [], status: 'connecting' })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let timeout: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    async function connect() {
      dispatch({ type: 'status', status: attempts ? 'reconnecting' : 'connecting' })
      const started = Date.now()
      try {
        const response = await fetch(proxyAddress(preview, '/-/logs'), {
          headers: { Accept: 'text/event-stream', 'X-Preview-Token': credential.token },
          credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: controller.signal,
        })
        if (response.status === 401 || response.status === 403 || response.status === 410) {
          dispatch({ type: 'status', status: response.status === 410 ? 'gone' : 'token' })
          return
        }
        if (!response.ok || !response.body) throw new Error('preview_logs')
        dispatch({ type: 'status', status: 'live' })
        const parse = createSseParser()
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        try {
          for (;;) {
            const chunk = await reader.read()
            if (chunk.done) break
            for (const event of parse(decoder.decode(chunk.value, { stream: true }))) {
              dispatch({ type: 'line', text: event.data })
              if (event.event === 'state') dispatch({ type: 'status', status: 'sleeping' })
              if (event.event === 'end' && /switched off/i.test(event.data)) {
                dispatch({ type: 'status', status: 'gone' })
                await reader.cancel()
                return
              }
            }
          }
        } finally { reader.releaseLock() }
        if (Date.now() - started >= 10_000) attempts = 0
      } catch {
        if (controller.signal.aborted) return
      }
      if (controller.signal.aborted) return
      if (attempts >= MAX_RECONNECTS) dispatch({ type: 'status', status: 'error' })
      else timeout = setTimeout(connect, backoffDelay(attempts++))
    }
    void connect()
    return () => { controller.abort(); clearTimeout(timeout) }
  }, [credential.token, preview, retry])
  const text = (state.frozen ?? state.lines).join('\n')
  return <Stack>
    <Row><span role="status">{t('preview.logState.' + state.status)}</span>
      <Button aria-pressed={Boolean(state.frozen)} onClick={() => dispatch({ type: 'pause' })}>{t(state.frozen ? 'build.resume' : 'build.pause')}</Button>
      <Button disabled={!text} onClick={async () => {
        try { await navigator.clipboard.writeText(text); toast({ title: t('preview.copied'), tone: 'success' }) }
        catch { toast({ title: t('preview.copyFailed'), tone: 'danger' }) }
      }}>{t('preview.copy')}</Button>
      <Button onClick={() => dispatch({ type: 'clear' })}>{t('preview.clear')}</Button>
      {state.status === 'error' && <Button onClick={() => setRetry(retry + 1)}>{t('common.retry')}</Button>}
    </Row>
    {text ? <CodeBlock label={t('preview.logs')} code={text} /> : <p>{t('preview.noLogs')}</p>}
  </Stack>
}

export function RequestConsole({ preview, credential, doc, write }: Connection & { doc: unknown; write: boolean }) {
  const t = useT()
  const search = useSearch({ strict: false })
  const updateSearch = usePreviewToolSearch()
  const { projectId = '' } = useParams({ strict: false })
  const roles = useQuery(rolesOptions(projectId))
  const role = search.role ?? (credential.bearer ? 'session' : 'anonymous')
  const userRole = roles.data?.find(item => item.name === role)
  const [token, setToken] = useState('')
  const choices = parseOperations(doc).filter(op => (write || op.method === 'get') && !/^\/(auth|oauth|token)(\/|$)/i.test(op.path))
  const chosen = choices.find(item => item.id === search.tool) ?? choices[0]
  const [history, record] = useReducer(consoleReducer, [])
  return <Stack>
    {!chosen ? <p>{t('preview.noOperations')}</p> : <>
      <Field label={t('preview.endpoint')}>{attrs => <Select triggerProps={attrs} value={chosen.id} options={choices.map(op => ({
        value: op.id, label: t('preview.operation', { method: op.method.toUpperCase(), path: op.path }),
      }))} onValueChange={tool => updateSearch({ tool })} />}</Field>
      <Field label={t('preview.actAs')}>{attrs => <Select triggerProps={attrs} value={role}
        options={[
          ...(credential.bearer ? [{ value: 'session', label: t('preview.useIdentity') }] : []),
          { value: 'anonymous', label: t('preview.noRole') },
          ...(roles.data ?? []).map(item => ({ value: item.name, label: item.label || item.name })),
        ]} onValueChange={role => { setToken(''); updateSearch({ role }) }} />}</Field>
      {roles.isPending && <Skeleton lines={2} />}
      {roles.isError && <GuidedLoadError error={roles.error} label={t('preview.rolesError')} retry={() => void roles.refetch()} />}
      {userRole && <Field label={t('preview.roleToken', { role: userRole.name })} hint={t('preview.roleHint')}>{attrs =>
        <Input {...attrs} type="password" autoComplete="off" spellCheck={false} value={token} onChange={event => setToken(event.target.value)} />
      }</Field>}
      <SendForm key={chosen.id + ':' + role} operation={chosen} doc={doc} preview={preview}
        credential={{ ...credential, bearer: role === 'session' ? credential.bearer : userRole ? token.trim() || undefined : undefined }}
        needsToken={Boolean(userRole && !token.trim())} record={record} />
    </>}
    {history.length === 0 && <p>{t('preview.noRequest')}</p>}
    {history.length > 0 && <SettingsSection title={t('preview.requestHistory')}>
      {history.map((entry, index) => <details key={index} open={index === 0 || undefined}>
        <summary>{entry.request.split('\n')[0]}</summary>
        <Stack><CodeBlock label={t('preview.request')} code={entry.request} /><CodeBlock label={t('preview.response')} code={entry.response} /></Stack>
      </details>)}
    </SettingsSection>}
  </Stack>
}

function SendForm({ operation, doc, preview, credential, record, needsToken }: Connection & {
  operation: Operation; doc: unknown; needsToken: boolean; record: (entry: { request: string; response: string }) => void
}) {
  const t = useT()
  const [body, setBody] = useState('')
  const [pendingDelete, setPendingDelete] = useState<string>()
  const [badBody, setBadBody] = useState(false)
  const request = useRef<{ path: string; parsed?: Json } | undefined>(undefined)
  const send = useMutation({
    mutationFn: async () => {
      const values = request.current
      request.current = undefined
      if (!values || needsToken) return
      const result = await previewRequest(preview, credential, operation.method, values.path, values.parsed)
      record(evidence(operation.method, values.path, values.parsed, result))
    },
    gcTime: 0,
  })
  function submit(values: FormData) {
    setBadBody(false)
    if (needsToken) return
    const origin = 'https://preview.invalid'
    let path: string
    try { path = buildRequestUrl(origin, operation.path, Object.fromEntries([...values.entries()].map(([key, value]) => [key, String(value)])), operation.params).slice(origin.length) }
    catch { setBadBody(true); return }
    if (operation.method === 'delete') { setPendingDelete(path); return }
    try {
      request.current = { path, parsed: body ? JSON.parse(body) as Json : undefined }
      send.mutate()
    }
    catch { setBadBody(true) }
  }
  return <Stack>
    <p>{t(credential.bearer ? 'preview.signedRequest' : 'preview.anonymous')}</p>
    {needsToken && <Alert>{t('preview.requiredToken')}</Alert>}
    {send.isError && <Alert tone="danger">{t('preview.network')}</Alert>}
    <Form submitLabel={t('preview.send')} pending={send.isPending} formError={badBody ? t('preview.badBody') : undefined}
      fields={[
        ...operation.params.map(param => ({
          name: param.name, label: t('preview.parameter', { name: param.name, location: param.in }),
          validate: param.required || param.in === 'path' ? [validators.required] : undefined,
          control: (attrs: Parameters<typeof Input>[0]) => <Input {...attrs} />,
        })),
        ...(operation.bodySchema ? [{ name: 'body', label: t('preview.body'), control: (attrs: Parameters<typeof Textarea>[0]) =>
          <Stack>
            <Textarea {...attrs} value={body} onChange={event => setBody(event.target.value)} />
            <Row>{(['valid', 'invalid'] as const).map(mode => <Button key={mode}
              onClick={() => setBody(JSON.stringify(generatePayload(doc, operation.bodySchema, mode), null, 2))}>{t('preview.generate.' + mode)}</Button>)}</Row>
          </Stack>,
        }] : []),
      ]} onSubmit={submit} />
    {pendingDelete && <ConfirmAction label={t('preview.delete')} title={t('preview.deleteTitle')}
      description={t('preview.deleteBody', { path: pendingDelete })} pending={send.isPending}
      onConfirm={async () => {
        if (needsToken) return
        request.current = { path: pendingDelete }
        await send.mutateAsync()
        setPendingDelete(undefined)
      }} />}
  </Stack>
}
