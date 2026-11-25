import { useEffect, useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useT } from '../../../i18n'
import type { SectionSearch } from '../../../projectNavigation'
import { ConfirmDestructive, Form } from '../../../patterns'
import type { FormField } from '../../../patterns'
import { Alert, Badge, Button, Card, Checkbox, CodeBlock, Dialog, EmptyState, Field, Input, Pagination, Row, Select, Stack, Table, useToast } from '../../../ui'
import { validators, webhookLiveLimits, webhookSecret } from '../../../validators'
import { errorText, statusOf } from '../api/connect'
import {
  createSubscription, deleteSubscription, disableSubscription, enableSubscription, liveErrorCode, liveKey, rotateSubscription,
  updateSubscription, webhookEventsOptions, webhookInboundOptions, webhookPreviewsOptions, webhookSubscriptionOptions,
  webhookSubscriptionsOptions, writeInboundSecret,
} from '../api/liveWebhooks'
import type { LiveSession, PreviewCredential, PreviewInstance, Subscription, SubscriptionInput } from '../api/liveWebhooks'
import { BlockLoad, SectionLink } from './BlockStatus'
import { deliveryLimit, formatWebhookDate, WebhookDeliveries } from './WebhookDeliveries'

type Props = {
  id: string; enabled: boolean; readOnly: boolean; overlap: number; multiTenant: boolean;
  credentials: Record<string, PreviewCredential>;
}
const live = (preview: PreviewInstance) => preview.is_preview === true && ['running', 'sleeping'].includes(preview.state)

export function WebhookLive({ id, enabled, credentials, ...props }: Props) {
  const t = useT()
  const search = useSearch({ strict: false })
  if (!enabled) return <EmptyState title={t('connectA2.live.off')} description={t('connectA2.live.offHelp')}
    action={<SectionLink projectId={id} section="webhooks" preview={search.preview} label={t('connectA2.webhooks.settings')} />} />
  return <PreviewConnection id={id} enabled={enabled} credentials={credentials} {...props} />
}

function PreviewConnection({ id, credentials, ...props }: Props) {
  const t = useT()
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const previews = useQuery(webhookPreviewsOptions(id))
  const running = previews.data?.filter(live) ?? []
  const target = (search.preview ? running.find(item => item.id === search.preview) : running.find(item => credentials[item.id])) ?? running[0]
  const credential = target && credentials[target.id]
  const openPreview = <SectionLink projectId={id} section="see" preview={target?.id} workspace={target?.workspace_id ?? undefined} label={t('connectA2.preview.open')} />
  if (!previews.data) return <BlockLoad error={previews.error} retry={() => void previews.refetch()} errorKey="connectA2.preview.loadError" />
  return <Stack>
    {previews.isRefetchError && <Alert tone="warning" action={<Button onClick={() => void previews.refetch()}>{t('common.retry')}</Button>}>{t('connectA2.preview.loadError')}</Alert>}
    {running.length === 0 ? <EmptyState title={t('connectA2.preview.none')} description={t('connectA2.preview.noneHelp')} action={openPreview} />
      : <Card><Stack>
        <Field label={t('connectA2.preview.select')}>{attrs => <Select triggerProps={attrs} value={target?.id} options={running.map(item => ({
          value: item.id, label: t('connectA2.preview.item', { id: item.id.slice(0, 8), date: formatWebhookDate(item.created_at) }),
        }))} onValueChange={preview => void navigate({ search: previous => ({
          ...previous, preview, subscription: undefined, delivery: undefined, page: undefined, view: undefined,
        }) })} />}</Field>
        {target && credential ? <LiveConnection key={target.id + ':' + credential.revision} id={id}
          target={target} credential={credential} {...props} />
          : <EmptyState title={t('connectA2.preview.disconnected')} description={t('connectA2.preview.connectHelp')} action={openPreview} />}
      </Stack></Card>}
  </Stack>
}

function LiveConnection({ id, target, credential, readOnly, overlap, multiTenant }: {
  id: string; target: PreviewInstance; credential: PreviewCredential; readOnly: boolean; overlap: number; multiTenant: boolean;
}) {
  const t = useT()
  const key = useId()
  const [connection, setConnection] = useState({ bearer: '', revision: 0 })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const change = (bearer: string) => {
    setConnection(previous => ({ bearer, revision: previous.revision + 1 }))
    void navigate({ search: previous => ({ ...previous, subscription: undefined, delivery: undefined, page: undefined, view: undefined }) })
  }
  if (!connection.bearer) return <Form fields={[{
    name: 'bearer', label: t('connectA2.live.token'), hint: t('connectA2.live.tokenHelp'), validate: [validators.required],
    control: attrs => <Input {...attrs} type="password" autoComplete="off" defaultValue={credential.bearer} />,
  }]} onSubmit={values => change(String(values.get('bearer')).trim())} submitLabel={t('connectA2.live.connect')} />
  return <LiveManager id={id} key={connection.revision} session={{
    target, token: credential.token, bearer: connection.bearer, key: key + ':' + connection.revision,
  }} readOnly={readOnly} overlap={overlap} multiTenant={multiTenant} disconnect={() => change('')} />
}

function LiveManager({ id, session, readOnly, overlap, multiTenant, disconnect }: {
  id: string; session: LiveSession; readOnly: boolean; overlap: number; multiTenant: boolean; disconnect: () => void;
}) {
  const t = useT()
  const show = useToast()
  const client = useQueryClient()
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const [secret, setSecret] = useState<string>()
  const alive = useRef(false)
  const query = useQuery(webhookSubscriptionsOptions(id, session))
  const events = useQuery(webhookEventsOptions(id, session))
  const inbound = useQuery(webhookInboundOptions(id, session))
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    if (!secret) return
    const timer = window.setTimeout(() => setSecret(undefined), 300_000)
    return () => window.clearTimeout(timer)
  }, [secret])

  const change = (values: SectionSearch) => void navigate({ search: previous => ({ ...previous, ...values }) })
  const refresh = async () => { await client.invalidateQueries({ queryKey: liveKey(id, session) }) }
  const copy = async (value: string, message: string) => {
    try { await navigator.clipboard.writeText(value); show({ title: message, tone: 'success' }) }
    catch { show({ title: t('connectA2.live.copyError'), tone: 'danger' }) }
  }
  const reveal = (value: string) => { if (alive.current) setSecret(value) }
  const label = t('connectA2.live.subscriptions')
  const pageSize = 10
  const rows = query.data ?? []
  const pages = Math.max(1, Math.ceil(rows.length / pageSize))
  const page = Math.min(search.page ?? 1, pages)
  const selected = search.subscription
  const mode = search.view
  const close = () => change({ view: undefined, subscription: undefined, delivery: undefined })
  const error = query.error ?? inbound.error ?? events.error
  const retry = () => { void Promise.all([query.refetch(), inbound.refetch(), events.refetch()]) }
  const forbidden = [401, 403].includes(statusOf(error) ?? 0)
  return <Stack>
    <Row>
      <Button onClick={disconnect}>{t('connectA2.live.switchToken')}</Button>
      <Button onClick={retry}>{t('common.reload')}</Button>
    </Row>
    {forbidden ? <Alert tone="warning">{t('connectA2.live.denied')}</Alert> : error &&
      <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t('connectA2.live.loadError')}</Alert>}
    {!forbidden && <Card><Stack><h2>{label}</h2>
      {events.data?.length === 0 && <EmptyState title={t('connectA2.live.noEvents')}
        action={<SectionLink projectId={id} section="webhooks" preview={session.target.id} label={t('connectA2.webhooks.settings')} />} />}
      {events.data && events.data.length > 0 && <p className="v2-muted">{t('connectA2.live.eventsAvailable', { events: events.data.join(', ') || t('connectA2.template.none') })}</p>}
      {!query.data && !error && <BlockLoad error={null} retry={retry} errorKey="connectA2.live.loadError" />}
      {query.data && (rows.length ? <>
        <Table label={label} columns={['url', 'event', 'status', 'version', 'actions'].map(id => ({ id, label: t('connectA2.live.' + id) }))}
          rows={rows.slice((page - 1) * pageSize, page * pageSize).map(row => ({
            id: row.id, cells: [row.url, row.event_types.join(', '),
              <Badge tone={row.status === 'active' ? 'success' : 'neutral'}>{t('connectA2.live.' + (row.status === 'active' ? 'active' : 'disabled'))}</Badge>,
              row.secret_version,
              <Row>
                <Button onClick={() => change({ subscription: row.id, view: 'details', delivery: undefined })}>{t('connectA2.live.details')}</Button>
                <Button onClick={() => change({ subscription: row.id, view: 'log', delivery: undefined })}>{t('connectA2.live.deliveries')}</Button>
              </Row>],
          }))} />
        {pages > 1 && <Pagination label={label} page={page} pages={pages} onChange={page => change({ page })} />}
      </> : <EmptyState title={t('connectA2.live.noSubscriptions')} />)}
      {!readOnly && query.data && events.data && events.data.length > 0 && <Dialog title={t('connectA2.live.newSubscription')}
        trigger={<Button variant="primary">{t('connectA2.live.newSubscription')}</Button>}
        open={mode === 'create'} onOpenChange={open => open ? change({ view: 'create' }) : close()}>
        <SubscriptionForm session={session} events={events.data} onSecret={reveal} onComplete={async () => { close(); await refresh() }} />
      </Dialog>}
    </Stack></Card>}
    {!forbidden && inbound.data && <Card><Stack><h2>{t('connectA2.live.inbound')}</h2>
      {inbound.data.length ? inbound.data.map(receiver => {
        const path = '/webhooks/in/' + encodeURIComponent(receiver.name) + (multiTenant ? '/{tenant_id}' : '')
        return <Card key={receiver.name}><Stack>
          <h3>{t('schema.label', { label: receiver.name })}</h3>
          <p>{t(receiver.has_secret ? 'connectA2.live.receiverVersion' : 'connectA2.live.noSecret', { version: receiver.secret_version ?? 0 })}</p>
          {receiver.rotating && <Badge>{t('connectA2.live.rotating')}</Badge>}
          {receiver.updated_at && <p>{formatWebhookDate(receiver.updated_at)}</p>}
          <CodeBlock code={path} />
          <Row><Button onClick={() => void copy(path, t('connectA2.live.pathCopied'))}>{t('connectA2.live.copyPath')}</Button></Row>
        </Stack></Card>
      }) : <EmptyState title={t('connectA2.live.noReceivers')}
        action={<SectionLink projectId={id} section="webhooks" preview={session.target.id} label={t('connectA2.webhooks.settings')} />} />}
      {!readOnly && inbound.data.length > 0 && <InboundForm session={session} receivers={inbound.data.map(row => row.name)}
        onComplete={async () => { show({ title: t('connectA2.live.inboundSaved'), tone: 'success' }); await refresh() }} />}
    </Stack></Card>}
    {selected && mode === 'log' && !forbidden && <WebhookDeliveries id={id} session={session} sub={selected}
      attempt={search.delivery} onAttempt={delivery => change({ delivery })}
      limit={deliveryLimit(search.limit)} onLimit={limit => change({ limit, delivery: undefined })} />}
    {selected && (mode === 'details' || mode === 'edit') && !forbidden && <Dialog
      title={t(mode === 'edit' ? 'connectA2.live.edit' : 'connectA2.live.detailsTitle')}
      open onOpenChange={open => { if (!open) close() }}>
      <SubscriptionDetails id={id} session={session} sub={selected} readOnly={readOnly} events={events.data} overlap={overlap}
        editing={mode === 'edit'} edit={() => change({ view: 'edit' })} onSecret={reveal} refresh={refresh} close={close} />
    </Dialog>}
    {secret && <Dialog title={t('connectA2.live.secretTitle')} description={t('connectA2.live.secretHelp')}
      open closeLabel={t('connectA2.live.secretStored')} onOpenChange={open => { if (!open) setSecret(undefined) }}
      actions={<Button onClick={() => void copy(secret, t('connectA2.live.secretCopied'))}>{t('connectA2.live.copySecret')}</Button>}>
      <CodeBlock code={secret} />
    </Dialog>}
  </Stack>
}

function SubscriptionForm({ session, events, subscription, onSecret, onComplete }: {
  session: LiveSession; events: string[]; subscription?: Subscription;
  onSecret?: (secret: string) => void; onComplete: () => Promise<void>;
}) {
  const t = useT()
  const mutation = useMutation({
    gcTime: 0,
    mutationFn: async (input: SubscriptionInput) => {
      if (subscription) await updateSubscription(session, subscription.id, input)
      else onSecret?.((await createSubscription(session, input)).secret)
    },
    onSuccess: onComplete,
  })
  const known = [...new Set([...events, ...(subscription?.event_types ?? [])])]
  const fields: FormField[] = [
    { name: 'url', label: t('connectA2.live.url'), validate: [validators.required, validators.url, validators.length(webhookLiveLimits.url)],
      control: attrs => <Input {...attrs} type="url" defaultValue={subscription?.url} maxLength={webhookLiveLimits.url} /> },
    { name: 'description', label: t('connectA2.live.description'), validate: [validators.length(webhookLiveLimits.description)],
      control: attrs => <Input {...attrs} defaultValue={subscription?.description} maxLength={webhookLiveLimits.description} /> },
    { name: 'event_types', label: t('connectA2.live.event'), ownLabel: true,
      validateWith: (_, data) => events.some(event => data.has('event:' + event)) ? undefined : { key: 'connectA2.live.selectEvent' },
      control: attrs => <Stack role="group" tabIndex={-1} aria-label={t('connectA2.live.event')} id={attrs.id}
        aria-invalid={attrs['aria-invalid']} aria-describedby={attrs['aria-describedby']}>
        {known.map(event => <Checkbox key={event} name={'event:' + event} label={t('schema.option', { value: event })}
          defaultChecked={subscription?.event_types.includes(event)} disabled={attrs.disabled || !events.includes(event)} />)}
      </Stack> },
  ]
  const message = errorText(mutation.error)
  const urlError = liveErrorCode(mutation.error) === 'url_not_allowed' && message
  return <Form fields={fields} pending={mutation.isPending}
    onSubmit={values => mutation.mutate({
      url: String(values.get('url')).trim(), description: String(values.get('description')),
      event_types: events.filter(event => values.has('event:' + event)),
    })} submitLabel={t(subscription ? 'common.save' : 'connectA2.live.create')}
    serverErrors={urlError ? { url: { key: 'schema.message', values: { message: urlError } } } : undefined}
    formError={mutation.isError && !urlError ? t('connectA2.writeError', { message: message ?? t('common.actionFailed') }) : undefined} />
}

function SubscriptionDetails({ id, session, sub, readOnly, events, editing, overlap, onSecret, refresh, edit, close }: {
  id: string; session: LiveSession; sub: string; readOnly: boolean; events?: string[]; editing: boolean; overlap: number;
  onSecret: (value: string) => void; refresh: () => Promise<void>; edit: () => void; close: () => void;
}) {
  const t = useT()
  const show = useToast()
  const query = useQuery(webhookSubscriptionOptions(id, session, sub))
  const row = query.data
  const [hours, setHours] = useState('')
  const [checked, setChecked] = useState(false)
  const overlapIssue = validators.number({ min: webhookLiveLimits.minOverlap, max: webhookLiveLimits.maxOverlap, integer: true })(hours)
  const mutation = useMutation({
    gcTime: 0,
    mutationFn: async (kind: 'enable' | 'disable' | 'rotate' | 'delete') => {
      if (kind === 'rotate') onSecret((await rotateSubscription(session, sub, hours ? Number(hours) : undefined)).secret)
      if (kind === 'enable') await enableSubscription(session, sub)
      if (kind === 'disable') await disableSubscription(session, sub)
      if (kind === 'delete') await deleteSubscription(session, sub)
    },
    onSuccess: async (_, kind) => {
      if (kind === 'delete' || kind === 'rotate') close()
      else show({ title: t('connectA2.live.changed'), tone: 'success' })
      await refresh()
    },
  })
  if (!row) return <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectA2.live.loadDetails" />
  if (editing && events && !readOnly) return <SubscriptionForm session={session} events={events} subscription={row}
    onComplete={async () => { close(); show({ title: t('connectA2.live.changed'), tone: 'success' }); await refresh() }} />
  const confirm = (kind: 'disable' | 'rotate' | 'delete') => <ConfirmDestructive
    trigger={<Button variant="danger" disabled={mutation.isPending}>{t('connectA2.live.' + kind)}</Button>}
    title={t('connectA2.live.' + kind + 'Title')} description={t('connectA2.live.' + kind + 'Help', { hours: overlap })}
    action={t('connectA2.live.' + kind)} pending={mutation.isPending}
    disabled={kind === 'rotate' && !!overlapIssue} onConfirm={() => mutation.mutateAsync(kind)}>
    {kind === 'rotate' && <Field label={t('connectA2.live.overlap')} error={checked && overlapIssue ? t(overlapIssue.key, {
      ...overlapIssue.values, field: t('connectA2.live.overlap'),
    }) : undefined}>{attrs => <Input {...attrs} type="number" min={1} max={720} value={hours} onBlur={() => setChecked(true)}
      placeholder={String(overlap)} onChange={event => setHours(event.target.value)} />}</Field>}
  </ConfirmDestructive>
  return <Stack>
    <dl>{Object.entries({
      url: row.url, description: row.description, event: row.event_types.join(', '),
      status: t('connectA2.live.' + (row.status === 'active' ? 'active' : 'disabled')),
      reason: row.disabled_reason && t('connectA2.live.reasonValue', { reason: row.disabled_reason }), failures: row.consecutive_failures,
      version: row.secret_version, created: formatWebhookDate(row.created_at),
    }).filter(([, value]) => value != null && value !== '').map(([key, value]) => <div key={key}>
      <dt>{t('connectA2.live.' + key)}</dt><dd>{value}</dd>
    </div>)}</dl>
    {row.rotating && <Badge>{t('connectA2.live.rotating')}</Badge>}
    {mutation.isError && <Alert tone="danger">{t('connectA2.writeError', { message: errorText(mutation.error) ?? t('common.actionFailed') })}</Alert>}
    {!readOnly && <Row>
      <Button disabled={!events?.length || mutation.isPending} onClick={edit}>{t('connectA2.live.edit')}</Button>
      {row.status === 'active' ? confirm('disable') :
        <Button disabled={mutation.isPending} onClick={() => mutation.mutate('enable')}>{t('connectA2.live.enable')}</Button>}
      {confirm('rotate')}{confirm('delete')}
    </Row>}
  </Stack>
}

function InboundForm({ session, receivers, onComplete }: {
  session: LiveSession; receivers: string[]; onComplete: () => Promise<void>;
}) {
  const t = useT()
  const form = useRef<HTMLDivElement>(null)
  const [receiver, setReceiver] = useState(receivers[0])
  const mutation = useMutation({
    gcTime: 0,
    mutationFn: async (name: string) => {
      const input = form.current?.querySelector<HTMLInputElement>('[name="value"]')
      if (!input) throw new Error('secret_input_unavailable')
      const value = input.value
      input.value = ''
      await writeInboundSecret(session, name, value)
    },
    onSuccess: async () => {
      form.current?.querySelector('form')?.reset()
      await onComplete()
    },
  })
  return <div ref={form}><Form fields={[
    { name: 'receiver', label: t('connectA2.live.receiver'), validate: [validators.required],
      control: ({ name, disabled, ...attrs }) => <Select name={name} disabled={disabled} triggerProps={attrs}
        value={receivers.includes(receiver) ? receiver : receivers[0]} options={receivers.map(value => ({ value, label: t('schema.option', { value }) }))}
        onValueChange={setReceiver} /> },
    { name: 'value', label: t('connectA2.live.inboundSecret'), validate: [webhookSecret],
      control: attrs => <Input {...attrs} type="password" autoComplete="off" maxLength={webhookLiveLimits.maxSecret} /> },
  ]} onSubmit={data => {
    mutation.mutate(String(data.get('receiver')))
  }} pending={mutation.isPending} submitLabel={t('connectA2.live.storeSecret')}
    formError={mutation.isError ? t('connectA2.writeError', { message: errorText(mutation.error) ?? t('common.actionFailed') }) : undefined} /></div>
}
