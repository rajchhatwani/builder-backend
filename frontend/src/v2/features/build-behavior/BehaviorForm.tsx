import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useId, useReducer, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { MemberRole, ValidationIssue } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, PageHeader, ReadOnlyNote, SaveBar } from '../../patterns'
import { Alert, Button, Card, Checkbox, DesktopOnlyCard, Field, Grid, Input, Row, Select, Skeleton, Stack, Textarea } from '../../ui'
import { validators } from '../../validators'
import type { Validator } from '../../validators'
import { behaviorKeys, errorIssues, errorStatus, issuesOptions, saveErrorKey } from './api/behavior'
import type { section } from './api/behavior'
import { draftReducer } from './state/draft'
import './behavior.css'

export type BehaviorProps = {
  projectId: string
  role?: MemberRole
  rolePending?: boolean
  roleError?: boolean
  retryRole?: () => void
}

export const canEdit = (role?: MemberRole) => role === 'owner' || role === 'editor'

export function BehaviorPage({ ownerOnly, title, description, desktop, access, children }: {
  title: string; description?: string; desktop?: boolean; ownerOnly?: boolean; access: BehaviorProps; children: ReactNode
}) {
  const t = useT()
  return <Stack gap={4}>
    <PageHeader title={title} description={description} />
    {desktop && <div className="v2-phone-only"><DesktopOnlyCard /></div>}
    <Stack className={desktop ? 'v2-phone-hidden' : undefined}>
      {access.roleError && <LoadError retry={access.retryRole} />}
      {!access.role && access.rolePending && <Skeleton />}
      {!access.rolePending && !(ownerOnly ? access.role === 'owner' : canEdit(access.role)) &&
        <ReadOnlyNote>{ownerOnly ? t('behavior.ownerOnly') : undefined}</ReadOnlyNote>}
      {children}
    </Stack>
  </Stack>
}

export function LoadError({ retry, status, title }: { retry?: () => void; status?: number; title?: string }) {
  const t = useT()
  return <Alert tone="danger" action={retry && <Button onClick={retry}>{t('common.retry')}</Button>}>
    {status === 403 ? t('behavior.forbidden') : title ?? t('behavior.loadError')}
  </Alert>
}

export function issuePath(path: string) {
  return path.replace(/\[(\d+)\]/g, '.$1')
}

export function IssueList({ issues }: { issues: ValidationIssue[] }) {
  const t = useT()
  if (!issues.length) return null
  return <Alert tone="warning"><Stack gap={1}>
    <strong>{t('behavior.problems', { count: issues.length })}</strong>
    <ul className="behavior-list">{issues.map((item, index) => <li key={index}>
      <code>{item.path}</code> {t('behavior.issue', { code: item.code, message: item.message })}
    </li>)}</ul>
  </Stack></Alert>
}

type FormState = { disabled: boolean; tried: boolean; issues: ValidationIssue[]; prefix: string }
const FormContext = createContext<FormState>({ disabled: false, tried: false, issues: [], prefix: '' })

function useField(path: string) {
  const { prefix, ...form } = useContext(FormContext)
  const cleanPath = path && (prefix ? prefix + '.' + path : path)
  return {
    ...form,
    messages: cleanPath ? form.issues.filter(item => {
      const normalized = issuePath(item.path)
      return normalized === cleanPath || normalized.startsWith(cleanPath + '.') && /^\d+$/.test(normalized.slice(cleanPath.length + 1))
    }).map(item => item.message) : [],
  }
}

export function BehaviorField({ label, path = '', value, change, hint, checks = [], maxLength, area, type, disabled }: {
  label: string; path?: string; value?: string | number | boolean | null; change: (value: string) => void; hint?: string;
  checks?: Validator[]; maxLength?: number; area?: boolean; type?: 'date' | 'text'; disabled?: boolean
}) {
  const t = useT()
  const form = useField(path)
  const [blurred, setBlurred] = useState(false)
  const [edited, setEdited] = useState<string | undefined>()
  const text = value == null ? '' : String(value)
  const issue = [...checks, ...(maxLength === undefined ? [] : [validators.length(maxLength)])].map(check => check(text)).find(Boolean)
  const blocked = form.disabled || disabled
  const serverError = form.messages.map(message => t('behavior.backendText', { message })).join(' ')
  const error = (form.tried || blurred) && issue ? t(issue.key, { ...issue.values, field: label })
    : edited !== serverError ? serverError : undefined
  return <Field label={label} hint={hint} error={error}>{attributes => {
    const props = {
      ...attributes, value: text, maxLength, disabled: blocked,
      'data-behavior-invalid': !blocked && issue ? true : undefined,
      onBlur: () => setBlurred(true),
      onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        setEdited(serverError)
        change(event.target.value)
      },
    }
    return area ? <Textarea {...props} /> : <Input {...props} type={type} />
  }}</Field>
}

export function WholeNumber({ value, change, min, max, optional, ...props }: Omit<Parameters<typeof BehaviorField>[0], 'change' | 'value' | 'checks'> & {
  value?: number | null; change: (value: number | null) => void; min: number; max: number; optional?: boolean
}) {
  // A raw draft preserves partial entries such as a leading minus or an empty field.
  const [raw, setRaw] = useState<string>()
  const numeric = (text: string) => text.trim() === '' ? optional ? null : NaN
    : /^[+-]?\d+$/.test(text.trim()) ? Number(text) : NaN
  const text = raw !== undefined && Object.is(numeric(raw), value) ? raw : Number.isNaN(value) ? '' : value
  return <BehaviorField {...props} value={text} checks={[
    ...(optional ? [] : [validators.required]),
    validators.number({ min, max, digits: String(max).length, integer: true }),
  ]} change={next => {
    setRaw(next)
    change(numeric(next))
  }} />
}

type Option = { value: string; label: string; group?: string }
export const optionsFor = (values: readonly string[]): Option[] => values.map(value => ({ value, label: value }))

export function BehaviorSelect({ label, path = '', value, change, options, hint, disabled, optional, placeholder, requirement }: {
  label: string; path?: string; value?: string | null; change: (value: string) => void; options: readonly (string | Option)[];
  hint?: string; disabled?: boolean; optional?: boolean; placeholder?: string; requirement?: string
}) {
  const t = useT()
  const form = useField(path)
  const normalized = options.map(option => typeof option === 'string' ? { value: option, label: option } : option)
  const none = '__behavior_none__'
  const items = optional ? [{ value: none, label: t('behavior.none') }, ...normalized] : [...normalized]
  if (value && !items.some(option => option.value === value)) items.unshift({ value, label: t('behavior.unavailableOption', { value }) })
  const error = (form.tried && requirement ? [requirement] : [])
    .concat(form.messages.map(message => t('behavior.backendText', { message }))).join(' ')
  return <Field label={label} hint={hint} error={error}>{attributes =>
    <Select value={value || (optional ? none : '')} onValueChange={next => change(next === none ? '' : next)}
      disabled={form.disabled || disabled} options={items}
      triggerProps={{ ...attributes, ...(!form.disabled && !disabled && requirement ? { 'data-behavior-invalid': true } : {}) }}
      placeholder={placeholder} />
  }</Field>
}

export function BehaviorCheck({ label, value, change, path = '', disabled, requirement, invalidGroup }: {
  label: string; value?: boolean; change: (value: boolean) => void; path?: string; disabled?: boolean;
  requirement?: string; invalidGroup?: boolean
}) {
  const t = useT()
  const form = useField(path)
  const id = useId()
  const invalid = !!requirement && !value || !!invalidGroup
  const messages = [...(form.tried && requirement && !value ? [requirement] : []),
    ...form.messages.map(message => t('behavior.backendText', { message }))]
  return <Stack gap={1}>
    <Checkbox label={label} checked={Boolean(value)} disabled={form.disabled || disabled}
      aria-describedby={messages.length ? id : undefined} data-behavior-invalid={invalid && !form.disabled && !disabled ? true : undefined}
      aria-invalid={messages.length ? true : undefined} onChange={event => change(event.target.checked)} />
    {messages.length > 0 && <span id={id} className="v2-field-error">{messages.join(' ')}</span>}
  </Stack>
}

export function Choices({ label, path = '', values, options, change, hint, required, max }: {
  label: string; path?: string; values: string[]; options: readonly (string | Option)[]; change: (value: string[]) => void; hint?: string;
  required?: boolean; max?: number
}) {
  const t = useT()
  const form = useField(path)
  const id = useId()
  const invalid = Boolean(required && !values.length)
  const available = options.map(option => typeof option === 'string' ? { value: option, label: option } : option)
  const error = (form.tried && invalid ? [t('behavior.chooseOne', { field: label })] : [])
    .concat(form.messages.map(message => t('behavior.backendText', { message }))).join(' ')
  return <Stack role="group" aria-label={label} aria-describedby={error ? id : undefined} gap={1}>
    <strong>{label}</strong>
    {hint && <span className="v2-muted v2-small">{hint}</span>}
    <Row>{[...available, ...optionsFor(values.filter(value => !available.some(option => option.value === value)))].map((option, index) =>
      <BehaviorCheck key={option.value} label={option.label} value={values.includes(option.value)} invalidGroup={index === 0 && invalid}
        disabled={max !== undefined && values.length >= max && !values.includes(option.value)}
        change={enabled => change(enabled ? [...values, option.value] : values.filter(value => value !== option.value))} />)}</Row>
    {error && <span id={id} className="v2-field-error">{error}</span>}
  </Stack>
}

export function RemoveAction({ onConfirm, label, description, disabled }: {
  onConfirm: () => void | Promise<void>; label?: string; description?: string; disabled?: boolean
}) {
  const t = useT()
  const form = useContext(FormContext)
  const action = label ?? t('behavior.remove')
  return <ConfirmDestructive trigger={<Button variant="danger" disabled={form.disabled || disabled}>{action}</Button>}
    title={action} description={description ?? t('behavior.removeDescription')} action={action} onConfirm={onConfirm} />
}

export function DraftForm({ disabled, tried, issues, prefix = '', children }: FormState & { children: ReactNode }) {
  return <FormContext.Provider value={{ disabled, tried, issues, prefix }}>{children}</FormContext.Provider>
}

type LoadState = { isPending: boolean; isError: boolean; error: unknown; refetch: () => Promise<unknown> }

export function queryStates(...queries: LoadState[]) {
  // Snapshot each observer while its owner renders so TanStack tracks these fields.
  return queries.map(({ isPending, isError, error, refetch }) => ({ isPending, isError, error, refetch }))
}

export function focusInvalid(form: HTMLElement | null) {
  const invalid = form?.querySelector<HTMLElement>('[data-behavior-invalid]')
  if (!invalid) return false
  const editor = invalid.closest('[hidden][data-behavior-editor]')
  if (editor) {
    editor.parentElement?.querySelector<HTMLButtonElement>('[data-behavior-edit-toggle]')?.click()
    requestAnimationFrame(() => invalid.focus())
  } else invalid.focus()
  return true
}

export function SectionForm<T>({ projectId, config, writable, supporting, render }: {
  projectId: string; config: ReturnType<typeof section<T>>; writable: boolean;
  supporting?: LoadState[];
  render: (state: { value: T; edit: (value: T) => void; disabled: boolean; saved: T }) => ReactNode
}) {
  const t = useT()
  const query = useQuery(config.query(projectId))
  const issues = useQuery(issuesOptions(projectId))
  const client = useQueryClient()
  const [draft, dispatch] = useReducer(draftReducer<T>, null)
  const [tried, setTried] = useState(false)
  const [blockedSave, setBlockedSave] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const form = useRef<HTMLDivElement>(null)
  const queries = [query, issues, ...(supporting ?? [])]
  const mutation = useMutation({
    scope: { id: [projectId, config.name].join(':') },
    mutationFn: ({ value, version }: NonNullable<typeof draft>) => config.save(projectId, value, version),
    onSuccess: async data => {
      await client.cancelQueries({ queryKey: config.query(projectId).queryKey })
      client.setQueryData(config.query(projectId).queryKey, data)
      dispatch({ type: 'clear' })
      setTried(false)
      await client.invalidateQueries({ queryKey: behaviorKeys.root(projectId).slice(0, 2), predicate: item =>
        ['issues', 'spec', 'status'].includes(String(item.queryKey.at(-1))) })
    },
  })
  const error = queries.find(query => query.isError)
  const retry = () => void Promise.all(queries.map(query => query.refetch()))
  if (error && !query.data) return <LoadError retry={retry} status={errorStatus(error.error)} title={t('behavior.loadSectionError', { section: t('behavior.section.' + config.name) })} />
  if (!query.data || supporting?.some(query => query.isPending)) return <Card><Skeleton lines={5} /></Card>
  if (supporting?.some(query => query.isError)) return <LoadError retry={retry} status={errorStatus(error?.error)} />
  const saved = query.data
  const value = draft ? draft.value : saved.value
  const conflict = errorStatus(mutation.error) === 409 || Boolean(draft && draft.version !== saved.version)
  const forbidden = errorStatus(mutation.error) === 403
  const disabled = !writable || mutation.isPending || refreshing || forbidden
  const prefix = config.name.replace('-', '_')
  const matchingIssues = (issues.data?.issues ?? []).filter(item => {
    const path = issuePath(item.path)
    return path === prefix || path.startsWith(prefix + '.')
  })
  const saveIssues = errorIssues(mutation.error).map(item => ({
    ...item, path: issuePath(item.path).startsWith(prefix) ? issuePath(item.path) : prefix + '.' + issuePath(item.path),
  }))
  const reload = async () => {
    setRefreshing(true)
    try {
      const result = await query.refetch()
      if (!result.isError) {
        dispatch({ type: 'clear' })
        setTried(false)
        mutation.reset()
      }
      await issues.refetch()
    } finally {
      setRefreshing(false)
    }
  }
  const submit = () => {
    if (!draft || disabled || conflict) return
    setTried(true)
    const invalid = focusInvalid(form.current)
    setBlockedSave(invalid)
    if (!invalid) mutation.mutate(draft)
  }
  return <Stack gap={4} ref={form}>
    {error && <LoadError retry={retry} status={errorStatus(error.error)} />}
    {conflict && <ConflictBanner onReload={() => void reload()} />}
    {forbidden && <ReadOnlyNote>{t('behavior.forbidden')}</ReadOnlyNote>}
    {blockedSave && draft &&
      <Alert tone="danger">{t('behavior.checkFields')}</Alert>}
    {mutation.isError && !conflict && !forbidden && <Alert tone="danger">{t(saveErrorKey(mutation.error))}</Alert>}
    <IssueList issues={[...matchingIssues, ...saveIssues]} />
    <DraftForm prefix={prefix} disabled={disabled} tried={tried} issues={[...matchingIssues, ...saveIssues]}>
      {render({ value, saved: saved.value, disabled, edit: next => {
        setBlockedSave(false)
        dispatch({ type: 'edit', value: next, version: saved.version })
      } })}
    </DraftForm>
    {writable && <SaveBar dirty={Boolean(draft)} pending={mutation.isPending || refreshing} readOnly={disabled || conflict}
      onSave={submit} onDiscard={() => void reload()} />}
    {mutation.isSuccess && <Alert tone="success">{t('behavior.savedVersion', { version: mutation.data.version })}</Alert>}
    {saved.version > 0 && <p className="v2-muted v2-small">{t('behavior.version', { version: saved.version })}
      {saved.updated_at && !Number.isNaN(Date.parse(saved.updated_at)) &&
        <> {t('behavior.updated', { date: new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(saved.updated_at)) })}</>}
    </p>}
  </Stack>
}

export function Summary({ entries, testId }: { entries: { label: string; value: ReactNode }[]; testId?: string }) {
  return <dl className="behavior-summary" data-testid={testId}>
    {entries.map(entry => <div key={entry.label}><dt>{entry.label}</dt><dd>{entry.value}</dd></div>)}
  </dl>
}

export function FormGrid({ children }: { children: ReactNode }) {
  return <Grid gap={3} className="behavior-grid">{children}</Grid>
}

export const replaceAt = <T,>(items: T[], index: number, value: T) => items.map((item, position) => position === index ? value : item)
export const removeAt = <T,>(items: T[], index: number) => items.filter((_, position) => position !== index)
