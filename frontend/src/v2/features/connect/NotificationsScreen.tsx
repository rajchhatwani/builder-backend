import { useReducer, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useT } from '../../i18n'
import type { SectionSearch } from '../../projectNavigation'
import { ConflictBanner, Form, PageHeader } from '../../patterns'
import { Alert, Button, Card, Checkbox, CodeBlock, Disclosure, EmptyState, Field, Grid, Input, Pagination, Row, Select, Skeleton, Stack, Table, Tabs, Textarea } from '../../ui'
import { notificationBodyMax, notificationTemplateIssue } from '../../validators'
import { blockFieldErrors, blockOptions, notificationChannels, useBlockWrite } from './api/blocks'
import type { Notifications, NotificationType, Template } from './api/blocks'
import { errorText, statusOf } from './api/connect'
import type { ConnectProps } from './api/connect'
import { BlockLoad, BlockRole, Issues, SectionLink } from './components/BlockStatus'
import { applyTemplate, initialTemplateDraft, renderTemplate, templateDraftReducer } from './state/templateDraft'

const tabs = ['templates', 'preferences', 'deliveries'] as const
const example: NotificationType = {
  name: 'welcome', category: 'optional', channels: ['email'], variables: ['name'], default_enabled: true,
  on_event: null, recipient_key_field: null, address_fields: {},
  templates: [],
}

type TemplateProps = {
  type: NotificationType; typeIndex: number; channel: string; version: number; block: Notifications | null
  readOnly: boolean; projectId: string; reload: () => Promise<boolean>
  selectors: (dirty: boolean) => React.ReactNode
}
function TemplateEditor({ type, typeIndex, channel, version, block, readOnly, projectId, reload, selectors }: TemplateProps) {
  const t = useT()
  const [draft, dispatch] = useReducer(templateDraftReducer, initialTemplateDraft)
  const [reloading, setReloading] = useState(false)
  const mutation = useBlockWrite(projectId, 'notifications')
  const templateIndex = type.templates.findIndex(item => item.channel === channel)
  const original = type.templates[templateIndex] ?? { channel, subject: '', body: '', html: false }
  const template = { ...original, ...draft.edits }
  if (channel === 'sms') template.subject = ''
  if (channel !== 'email') template.html = false
  const dirty = draft.version !== undefined
  const conflict = statusOf(mutation.error) === 409
  const savedErrors = blockFieldErrors(mutation.error, 'notifications')
  const prefix = 'types.' + typeIndex + '.templates.' + (templateIndex < 0 ? type.templates.length : templateIndex) + '.'
  const fields = Object.fromEntries(Object.entries(savedErrors).filter(([key]) => key.startsWith(prefix))
    .map(([key, messages]) => [key.slice(prefix.length), { key: 'schema.message', values: { message: messages.join(' ') } }]))
  const disabled = readOnly || reloading
  const samples = Object.fromEntries(type.variables.map(variable => [variable, Object.hasOwn(draft.samples, variable)
    ? draft.samples[variable] : t('connectA2.template.sample', { variable })]))
  const edit = (changes: Partial<Template>) => dispatch({ type: 'edit', changes, version })
  function save() {
    if (!block || !dirty || readOnly || conflict) return
    const updated = { ...block, types: block.types.map((row, index) => index === typeIndex ? applyTemplate(row, template) : row) }
    mutation.mutate({ block: updated, version: draft.version ?? version }, { onSuccess: () => dispatch({ type: 'reset' }) })
  }
  async function refresh() {
    setReloading(true)
    try {
      if (await reload()) {
        mutation.reset()
        dispatch({ type: 'reset' })
      }
    } finally { setReloading(false) }
  }
  const subjectLabel = t(channel === 'push' ? 'connectA2.template.pushTitle' : 'connectA2.template.subject')
  const title = t('connectA2.template.title')
  return <Stack>
    {selectors(dirty || mutation.isPending || reloading)}
    {conflict && <ConflictBanner onReload={() => void refresh()} />}
    {mutation.isSuccess && <Alert tone="success">{t('connectA2.template.saved', { type: type.name, channel })}</Alert>}
    <p>{t('connectA2.template.' + (type.category === 'transactional' ? 'transactional' : 'optional'))}</p>
    <Grid>
      <Card><Stack><h2>{title}</h2>
        <p className="v2-muted">{t('connectA2.template.variables', { variables: type.variables.join(', ') || t('connectA2.template.none') })}</p>
        <Form fields={[
          ...(channel === 'sms' ? [] : [{
            name: 'subject', label: subjectLabel,
            validate: [(value: string) => notificationTemplateIssue(value, 'subject', channel, type.variables)],
            control: (attrs: React.ComponentProps<typeof Input>) => <Input {...attrs} maxLength={200} value={template.subject}
              onChange={event => edit({ subject: event.target.value })} />,
          }]),
          { name: 'body', label: t('connectA2.template.body'),
            validate: [value => notificationTemplateIssue(value, 'body', channel, type.variables)],
            control: attrs => <Textarea {...attrs} rows={6} maxLength={notificationBodyMax(channel)} value={template.body}
              onChange={event => edit({ body: event.target.value })} /> },
          ...(channel !== 'email' ? [] : [{
            name: 'html', label: t('connectA2.template.html'), ownLabel: true,
            control: (attrs: Omit<React.ComponentProps<typeof Checkbox>, 'label'>) => <Checkbox {...attrs}
              label={t('connectA2.template.html')} checked={template.html} onChange={event => edit({ html: event.target.checked })} />,
          }]),
        ]} readOnly={disabled} pending={mutation.isPending} onSubmit={save} submitLabel={t('connectA2.template.save')}
          submitProps={{ hidden: readOnly, disabled: !dirty || conflict || !block }} serverErrors={fields}
          formError={mutation.isError && !conflict ? t('connectA2.writeError', { message: errorText(mutation.error) ?? t('common.actionFailed') }) : undefined}
          actions={<Button disabled={!dirty || mutation.isPending || reloading} onClick={() => {
            if (conflict) { void refresh(); return }
            mutation.reset()
            dispatch({ type: 'reset' })
          }}>{t('common.discard')}</Button>} />
      </Stack></Card>
      <Card aria-label={t('connectA2.template.preview')}><Stack><h2>{t('connectA2.template.preview')}</h2>
        {channel !== 'sms' && <div data-testid="nt-preview-subject"><CodeBlock label={subjectLabel} code={renderTemplate(template.subject, samples, false)} /></div>}
        <div data-testid="nt-preview-body"><CodeBlock label={t('connectA2.template.body')} code={renderTemplate(template.body, samples, template.html && channel === 'email')} /></div>
        {type.variables.length > 0 && <Disclosure label={t('connectA2.template.samples')}><Stack>
          {Object.entries(samples).map(([variable, value]) => <Field key={variable} label={t('schema.label', { label: variable })}>
            {attrs => <Input {...attrs} value={value} onChange={event => dispatch({ type: 'sample', variable, value: event.target.value })} />}
          </Field>)}
        </Stack></Disclosure>}
      </Stack></Card>
    </Grid>
  </Stack>
}

function Preferences({ types, action }: { types: NotificationType[]; action: React.ReactNode }) {
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const t = useT()
  const label = t('connectA2.notifications.matrix')
  const pageSize = 10
  const pages = Math.max(1, Math.ceil(types.length / pageSize))
  const page = Math.min(search.page ?? 1, pages)
  if (!types.length) return <EmptyState title={t('connectA2.types.empty')} action={action} />
  return <Card><Stack><h2>{label}</h2><p>{t('connectA2.notifications.matrixHelp')}</p>
    <Table label={label} columns={[
      { id: 'type', label: t('connectA2.template.type') }, ...notificationChannels.map(id => ({ id, label: t('connectA2.channel.' + id) })),
    ]} rows={types.slice((page - 1) * pageSize, page * pageSize).map((type, index) => ({ id: String(index), cells: [type.name || t('connectA2.template.unnamed'), ...notificationChannels.map(channel =>
      t('connectA2.preference.' + (!type.channels.includes(channel) ? 'unused' : type.category === 'transactional' ? 'always' : type.default_enabled ? 'on' : 'off')))] }))} />
    {pages > 1 && <Pagination label={label} page={page} pages={pages}
      onChange={page => void navigate({ search: previous => ({ ...previous, page }) })} />}
  </Stack></Card>
}

export default function NotificationsScreen(props: ConnectProps) {
  const { projectId, role, rolePending } = props
  const t = useT()
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const [exampleOpen, setExampleOpen] = useState(false)
  const query = useQuery(blockOptions(projectId, 'notifications'))
  const read = query.data
  const block = read?.block ?? null
  const types = exampleOpen ? [{ ...example, templates: [{ channel: 'email', html: false,
    subject: t('connectA2.template.exampleSubject').replace('{name}', '{{ name }}'), body: t('connectA2.template.exampleBody').replace('{name}', '{{ name }}'),
  }] }] : block?.types ?? []
  const typeOptions = types.map((type, index) => ({
    value: type.name && types.filter(item => item.name === type.name).length === 1 ? type.name : ':' + index,
    label: type.name ? t('schema.option', { value: type.name }) : t('connectA2.template.unnamed'),
  }))
  const typeIndex = Math.max(0, typeOptions.findIndex(option => option.value === search.notificationType))
  const type = types[typeIndex]
  const channels = [...new Set(type?.channels.filter(Boolean) ?? [])]
  const channel = channels.find(channel => channel === search.channel) ?? channels[0] ?? ''
  const change = (values: SectionSearch) => void navigate({ search: previous => ({ ...previous, ...values }) })
  const tab = tabs.find(item => item === search.tab) ?? 'templates'
  const selectors = (disabled: boolean) => <Row>
    <Field label={t('connectA2.template.type')}>{attrs => <Select triggerProps={attrs} value={typeOptions[typeIndex]?.value} disabled={disabled}
      onValueChange={notificationType => change({ notificationType, channel: undefined })}
      options={typeOptions} />}</Field>
    <Field label={t('connectA2.template.channel')}>{attrs => <Select triggerProps={attrs} value={channel} disabled={disabled || !channels.length}
      onValueChange={channel => change({ channel })} options={channels.map(value =>
        ({ value, label: notificationChannels.some(channel => channel === value) ? t('connectA2.channel.' + value) : t('schema.option', { value }) }))} />}</Field>
  </Row>
  const links = <SectionLink projectId={projectId} section="notiftypes" label={t('connectA2.types.title')} preview={search.preview} />
  const templates = <Stack>
    {exampleOpen && <Alert tone="info" action={<Button onClick={() => setExampleOpen(false)}>{t('connectA2.notifications.closeExample')}</Button>}>
      {t('connectA2.notifications.example')}
    </Alert>}
    {type && channel ? <TemplateEditor key={typeIndex + ':' + channel + ':' + exampleOpen} type={type} typeIndex={typeIndex} channel={channel}
      projectId={projectId} version={read?.version ?? 0} block={exampleOpen ? null : block}
      readOnly={!exampleOpen && (!role || role === 'viewer' || Boolean(rolePending))} selectors={selectors}
      reload={async () => (await query.refetch()).isSuccess} />
      : type ? <EmptyState title={t('connectA2.notifications.noChannel')} action={<Stack>{selectors(false)}<Row>{links}</Row></Stack>} />
        : <EmptyState title={t(block?.enabled ? 'connectA2.notifications.empty' : 'connectA2.notifications.emptyOff')}
          description={t('connectA2.notifications.emptyHelp')}
          action={<><Button variant="primary" onClick={() => setExampleOpen(true)}>{t('connectA2.notifications.tryExample')}</Button>{links}</>} />}
    <Issues id={projectId} block="notifications" />
  </Stack>
  return <Stack>
    <PageHeader title={t('connectA2.notifications.title')} description={t('connectA2.notifications.intro')}
      actions={<>{links}<SectionLink projectId={projectId} section="history" preview={search.preview} label={t('connectA2.history')} /></>} />
    <BlockRole {...props} />
    <Alert>{t('connectA2.notifications.note')}</Alert>
    {!read && (query.isPending ? <Card><Skeleton lines={7} /></Card> :
      <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectA2.notifications.error" />)}
    {read && query.isRefetchError && <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectA2.notifications.error" />}
    {read && <Tabs label={t('connectA2.notifications.tabs')} value={tab} onChange={tab => change({ tab, page: undefined })} keepMounted
      items={[
        { id: 'templates', label: t('connectA2.notifications.templates'), content: templates },
        { id: 'preferences', label: t('connectA2.notifications.preferences'), content: <Preferences types={block?.types ?? []} action={links} /> },
        { id: 'deliveries', label: t('connectA2.notifications.deliveries'), content: <EmptyState title={t('connectA2.notifications.deliveries')}
          description={t('connectA2.notifications.deliveryHelp')}
          action={<SectionLink projectId={projectId} section="see" preview={search.preview} label={t('connectA2.preview.open')} />} /> },
      ]} />}
  </Stack>
}
