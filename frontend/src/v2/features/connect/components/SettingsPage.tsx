import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useReducer, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useLanguage, useT } from '../../../i18n'
import { ConfirmDestructive, ConflictBanner, Form, PageHeader, ReadOnlyNote, SettingsSection } from '../../../patterns'
import { Alert, Badge, Button, Dialog, Disclosure, EmptyState, Row, Skeleton, Stack, Tabs, useToast } from '../../../ui'
import { draftFrom, draftReducer } from '../state/draft'
import type { SettingsDraft } from '../state/draft'
import { errorText, fieldErrors, impactOptions, specOptions, statusOf } from '../api/connect'
import type { ConfigWrite, ConnectProps, ConnectSpec, Impact, ProjectIssue, SettingsKind, SwitchAction } from '../api/connect'
import { SettingsGroups } from './Fields'
import type { EditorProps, Group } from './Fields'

type Config = { enabled: boolean; created_at: string; updated_at: string }
type Read<T> = { data?: T | null; isError: boolean; error: unknown; refetch: () => Promise<{ data?: T | null; isSuccess: boolean }> }
type Write<T, R> = { mutateAsync: (value: ConfigWrite<T>) => Promise<R>; reset: () => void; isPending: boolean; error: unknown }
export type Model = ConnectSpec
type Editor = (props: EditorProps & { model?: Model; projectId: string }) => Group[]
type Props<T extends object, R extends Config> = ConnectProps & {
  kind: SettingsKind
  defaults: T
  read: Read<R>
  write: Write<T, R>
  useGroups: Editor
  toWrite: (draft: SettingsDraft) => T
  review: (saved: R | null) => ReactNode
  extras: (saved: R | null, model: Model | undefined) => ReactNode
  fileFields?: (model: Model | undefined) => string[]
}

export function RetryAlert({ message, error, retry }: { message: string; error?: unknown; retry?: () => void }) {
  const t = useT()
  if (statusOf(error) === 409) return <ConflictBanner onReload={retry} />
  if (statusOf(error) === 403) return <ReadOnlyNote>{t('connect.forbidden')}</ReadOnlyNote>
  return <Alert tone="danger" action={retry && <Button onClick={retry}>{t('common.retry')}</Button>}>{message}</Alert>
}

export function IssueList({ issues }: { issues: ProjectIssue[] }) {
  const t = useT()
  if (!issues.length) return null
  return <SettingsSection title={t('connect.issues')}>
    <Stack gap={1}>{issues.map((issue, index) =>
      <p key={index}>{t('connect.issue', { message: issue.message, path: issue.path })}</p>)}</Stack>
  </SettingsSection>
}

export function SettingsPage<T extends object, R extends Config>(props: Props<T, R>) {
  const { projectId, kind, read, role, roleError, rolePending, retryRole } = props
  const t = useT()
  const { tab } = useSearch({ strict: false })
  const model = useQuery(specOptions(projectId))
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const guided = tab === 'guided'
  const label = (key: string) => t('connect.' + kind + '.' + key)
  const loading = read.data === undefined && !read.isError
  const writable = role === 'owner' || role === 'editor'

  return <Stack gap={5}>
    <PageHeader title={label('title')} description={label(guided ? 'guidedIntro' : 'formIntro')} />
    {roleError && <RetryAlert message={t('connect.membersError')} retry={retryRole} />}
    {!rolePending && !roleError && (role === 'viewer' ? <ReadOnlyNote /> : !writable && <ReadOnlyNote>{t('connect.forbidden')}</ReadOnlyNote>)}
    {read.isError && read.data !== undefined && <RetryAlert message={label('loadError')} error={read.error} retry={() => void read.refetch()} />}
    {loading ? <Stack>
      <Skeleton label={t('common.loading')} lines={2} />
      <Skeleton lines={5} />
      <Skeleton lines={8} />
    </Stack>
      : read.isError && read.data === undefined
        ? <RetryAlert message={label('loadError')} error={read.error} retry={() => void read.refetch()} />
        : <SettingsContent {...props} saved={read.data ?? null} guided={guided} model={model.data}
          modelProblem={model.isError && <RetryAlert message={t('connect.modelError')} error={model.error} retry={() => void model.refetch()} />}
          writable={writable} onTab={next => void navigate({ search: current => ({ ...current, tab: next }) })} />}
  </Stack>
}

function SettingsContent<T extends object, R extends Config>({
  projectId, kind, saved, defaults, read, write, useGroups, toWrite, review, extras, fileFields, guided, model, modelProblem, writable, onTab,
}: Props<T, R> & {
  saved: R | null; guided: boolean; model?: Model; modelProblem: ReactNode; writable: boolean; onTab: (tab: string) => void
}) {
  const t = useT()
  const label = (key: string) => t('connect.' + kind + '.' + key)
  const toast = useToast()
  const { language } = useLanguage()
  const [edits, dispatch] = useReducer(draftReducer, {} as SettingsDraft)
  const [formRevision, setFormRevision] = useState(0)
  const [editingAction, setEditingAction] = useState<SwitchAction | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const switchTrigger = useRef<HTMLButtonElement>(null)
  const draft = { ...draftFrom(saved ?? defaults), ...edits }
  const groups = useGroups({
    projectId, guided, draft, model,
    change: (name, value) => dispatch({ type: 'change', name, value }),
  })
  const enabled = saved?.enabled ?? false
  const action = enabled ? 'disable' : 'enable'
  const authOff = model && !model.auth?.enabled
  const conflict = statusOf(write.error) === 409
  const fields = groups.flatMap(group => group.fields)
  const dirty = Object.keys(edits).length > 0
  const errors = fieldErrors(write.error)
  const unmatched = Object.entries(errors).filter(([name]) => !fields.some(field => field.name === name))
  const rejection = write.error && !editingAction && !conflict && statusOf(write.error) !== 403
    ? Object.keys(errors).length ? undefined : t('common.actionFailed')
    : undefined
  function clearForm() {
    dispatch({ type: 'replace', values: {} })
    setFormRevision(current => current + 1)
    write.reset()
  }
  async function save() {
    try {
      await write.mutateAsync({ settings: toWrite(draft) })
      clearForm()
      toast({ title: label('saved'), tone: 'success' })
    } catch { /* The form renders the mutation error. */ }
  }
  async function switchSettings() {
    if (!editingAction) return
    await write.mutateAsync({ action: editingAction })
    toast({ title: label(editingAction === 'enable' ? 'enabledToast' : 'disabledToast'), tone: 'success' })
  }
  function setAction(open: boolean) {
    if (!open && !write.isPending) {
      setEditingAction(null)
      write.reset()
    }
  }
  const form = <Stack>
    {modelProblem}
    {guided && authOff && <Alert tone="warning" action={<Button asChild>
      <Link to="/projects/$projectId/$section" params={{ projectId, section: 'auth' }}>{t('connect.openAuth')}</Link>
    </Button>}>{label('authNotice')}</Alert>}
    <h2 ref={heading} tabIndex={-1}>{t('connect.settings')}</h2>
    <Form key={formRevision} fields={fields} layout={controls => <SettingsGroups groups={groups} controls={controls} />}
      serverErrors={errors} formError={rejection} onSubmit={() => void save()} pending={write.isPending}
      readOnly={!writable} submitProps={{ hidden: !writable, disabled: conflict || Boolean(saved && !dirty) }}
      submitLabel={guided ? label('save') : t('common.save')}
      actions={writable && <Button disabled={!dirty || write.isPending} onClick={clearForm}>{t('common.discard')}</Button>}>
      {unmatched.map(([name, issue]) => <Alert tone="danger" key={name}>{t(issue.key, { ...issue.values, field: name })}</Alert>)}
    </Form>
  </Stack>
  const overview = <Stack>
    {!saved && <EmptyState title={label('first')} description={t('connect.defaults')}
      action={writable && <Button onClick={() => heading.current?.focus()}>{t('connect.configure')}</Button>} />}
    <SettingsSection title={label('statusTitle')} description={label(saved ? enabled ? 'on' : 'off' : 'first')}>
      <Row>
        <Badge tone={enabled ? 'success' : 'neutral'}>{t(enabled ? 'connect.on' : 'connect.off')}</Badge>
        {guided && writable && <Button ref={switchTrigger} variant={enabled ? 'danger' : 'primary'}
          disabled={!saved || (action === 'enable' && Boolean(authOff)) || write.isPending}
          onClick={() => { write.reset(); setEditingAction(action) }}>
          {t(enabled ? 'connect.turnOff' : 'connect.turnOn')}
        </Button>}
      </Row>
      {!guided && <p className="v2-muted">{t('connect.switchHelp')}</p>}
      {guided && <ImpactPreview projectId={projectId} kind={kind} action={action} />}
      {saved && <p className="v2-muted">{t('connect.timestamps', {
        created: displayDate(saved.created_at, language), updated: displayDate(saved.updated_at, language),
      })}</p>}
    </SettingsSection>
    {!editingAction && conflict && <ConflictBanner onReload={() => void read.refetch().then(result => {
      if (result.isSuccess) clearForm()
    })} />}
    {!editingAction && statusOf(write.error) === 403 && <ReadOnlyNote>{t('connect.forbidden')}</ReadOnlyNote>}
  </Stack>
  const reload = <Button disabled={write.isPending} onClick={() => void read.refetch().then(result => {
    if (result.isSuccess) clearForm()
  })}>{t('connect.reload')}</Button>
  return <Stack>
    <SettingsTabs guided={guided} onTab={onTab} form={<Stack>
      <Alert action={reload}>{t('connect.sharedDraft')}</Alert>
      {overview}{guided && review(saved)}{form}
    </Stack>} extras={extras(saved, model)} />
    {editingAction && <SwitchDialog key={editingAction} projectId={projectId} kind={kind} action={editingAction}
      onClose={setAction} onConfirm={switchSettings} pending={write.isPending} error={write.error} reset={write.reset}
      files={fileFields?.(model) ?? []} returnFocus={switchTrigger} />}
  </Stack>
}

function SettingsTabs({ guided, onTab, form, extras }: { guided: boolean; onTab: (tab: string) => void; form: ReactNode; extras: ReactNode }) {
  const t = useT()
  return <Tabs label={t('connect.tabs')} value={guided ? 'guided' : 'form'} onChange={onTab} items={[
    { id: 'form', label: t('connect.form'), content: !guided && form },
    { id: 'guided', label: t('connect.guided'), content: guided && <Stack>{form}{extras}</Stack> },
  ]} />
}

function SwitchDialog({ projectId, kind, action, onClose, onConfirm, pending, error, reset, files, returnFocus }: {
  projectId: string; kind: SettingsKind; action: SwitchAction; onClose: (open: boolean) => void; onConfirm: () => Promise<void>
  pending: boolean; error: unknown; reset: () => void; files: string[]; returnFocus: React.RefObject<HTMLButtonElement | null>
}) {
  const t = useT()
  const impact = useQuery(impactOptions(projectId, kind, action, true))
  const disable = action === 'disable'
  const title = t('connect.' + kind + '.' + action)
  const disabled = impact.isError || impact.isFetching || !impact.data?.can_proceed || [403, 409].includes(statusOf(error) ?? 0)
  const problem = statusOf(error) === 409 ? <ConflictBanner onReload={() => { reset(); void impact.refetch() }} />
    : statusOf(error) === 403 ? <ReadOnlyNote>{t('connect.forbidden')}</ReadOnlyNote>
    : error ? <Alert tone="danger">{t('common.serverText', { text: errorText(error) ?? t('common.actionFailed') })}</Alert> : null
  const body = <Stack>
    <ImpactContent impact={impact} />
    {disable && files.length > 0 && <Stack>
      <p>{t('connect.storage.filesImpact', { fields: files.join(', ') })}</p>
      <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'model' }}>{t('connect.openModel')}</Link></Button>
    </Stack>}
    {problem}
  </Stack>
  const dialog = { title, description: t('connect.impactDescription'), open: true, onOpenChange: onClose, returnFocus }
  if (disable) return <ConfirmDestructive {...dialog} action={title} disabled={disabled} pending={pending} onConfirm={onConfirm}>{body}</ConfirmDestructive>
  return <Dialog {...dialog} actions={<Button variant="primary" disabled={disabled || pending} onClick={() =>
    void onConfirm().then(() => onClose(false), () => undefined)}>{title}</Button>}>{body}</Dialog>
}

function ImpactContent({ impact }: { impact: { data?: Impact; isPending: boolean; isError: boolean; error: unknown; refetch: () => Promise<unknown> } }) {
  const t = useT()
  return <Stack>
    {impact.isPending && <Skeleton label={t('common.loading')} />}
    {impact.isError && <RetryAlert message={t('connect.impactError')} error={impact.error} retry={() => void impact.refetch()} />}
    {!impact.isError && impact.data?.blockers.map(line => <Alert tone="danger" key={line}>{t('common.serverText', { text: line })}</Alert>)}
    {!impact.isError && impact.data?.warnings.map(line => <p key={line}>{t('common.serverText', { text: line })}</p>)}
  </Stack>
}

function ImpactPreview({ projectId, kind, action }: { projectId: string; kind: SettingsKind; action: SwitchAction }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const impact = useQuery(impactOptions(projectId, kind, action, open))
  return <Disclosure label={t('connect.impactPreview')} onToggle={event => setOpen(event.currentTarget.open)}>
    {open && <ImpactContent impact={impact} />}
  </Disclosure>
}

export function displayDate(value: string | null | undefined, language: string) {
  if (!value || Number.isNaN(Date.parse(value))) return ''
  return new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
