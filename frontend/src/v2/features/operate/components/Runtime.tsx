import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import type { ReactNode } from 'react'
import { RouteTranslations, useLanguage, useT } from '../../../i18n'
import { ConflictBanner, PageHeader, ReadOnlyNote } from '../../../patterns'
import type { FormField } from '../../../patterns/Form'
import { Alert, Button, Card, EmptyState, Field, Grid, Input, Pagination, Row, Select, Skeleton, Stack, Table, Textarea } from '../../../ui'
import type { SelectOption, TableRow } from '../../../ui'
import { liveRead, previewOptions, runtimeMessage, runtimeStatus, usablePreview } from '../api/live'
import type { LiveProps, Session } from '../api/live'
import { fieldErrors } from '../api/operate'
import { SectionLink, useOperateSearch } from './Common'
import english from '../liveCopy.json'

type Translate = ReturnType<typeof useT>
export const key = (id: string) => 'runtime.' + id
type RuntimeProps = { id: LiveProps; title?: string; children: (session: Session) => ReactNode; builder?: ReactNode }
export function RuntimeScreen(props: RuntimeProps) {
  return <RouteTranslations english={english}><RuntimeContents {...props} /></RouteTranslations>
}

export const runtimeEnglish = english

export function RuntimeContents({ id, title, children, builder }: RuntimeProps) {
  const { t, language } = useLanguage()
  const scope = useId()
  const { search, change } = useOperateSearch()
  const previews = useQuery(previewOptions(id.projectId))
  const available = (previews.data ?? []).filter(p => usablePreview(id.projectId, p))
  const target = search.preview ? available.find(p => p.id === search.preview) : available.find(p => id.credentials?.[p.id]) ?? available[0]
  const credential = target && id.credentials?.[target.id]
  const open = <SectionLink id={id.projectId} section="see" label={t(key(target ? 'connect' : 'startPreview'))} search={{ preview: target?.id }} />
  return <Stack gap={5}>
    {title && <PageHeader title={t(key(title))} description={t(key(title + 'Lead'))} />}
    {builder}
    {previews.isPending || previews.isError ? <RuntimeState error={previews.error} retry={previews.refetch} /> :
      !available.length ? <EmptyState title={t(key('noPreview'))} description={t(key('noPreviewHelp'))} action={open} /> :
        <Card><Stack>
          <Pick label={t(key('preview'))} value={target?.id ?? ''} onChange={preview => change({ preview, page: undefined, historyPage: undefined,
            matchPage: undefined, view: undefined, account: undefined, subject: undefined, resource: undefined, slot: undefined })}
          options={available.map(p => ({ value: p.id, label: t(key('previewItem'), { id: p.id.slice(0, 8), date: new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(p.created_at)) }) }))} />
          {target && credential ? id.renderIdentity?.(target, credential) : open}
          {credential && !credential.bearer && <p>{t(key('signInHelp'))}</p>}
        </Stack></Card>}
    {id.role === 'viewer' && <ReadOnlyNote />}
    {target && credential?.bearer && <div key={target.id + ':' + credential.revision}>{children({
      projectId: id.projectId, target, token: credential.token, bearer: credential.bearer, scope: scope + ':' + credential.revision,
    })}</div>}
  </Stack>
}

export function RuntimeState({ error, retry, lines = 6 }: { error?: unknown; retry: () => unknown; lines?: number }) {
  const t = useT()
  if (!error) return <Card><Skeleton lines={lines} /></Card>
  const status = runtimeStatus(error)
  if (status === 409) return <ConflictBanner onReload={() => void retry()}>{t(key('value'), { value: runtimeMessage(error) || t(key('conflict')) })}</ConflictBanner>
  const label = status === 403 ? 'forbidden' : status === 401 ? 'signInAgain' : status === 404 ? 'missing' : 'loadError'
  return <Alert tone={status === 403 ? 'warning' : 'danger'} action={<Button onClick={() => void retry()}>{t('common.retry')}</Button>}>{t(key(label))}</Alert>
}

export function WriteStatus({ error, reload, success, replayed }: { error?: unknown; reload: () => unknown; success?: string; replayed?: boolean }) {
  const t = useT()
  if (error && [401, 403, 409].includes(runtimeStatus(error) ?? 0)) return <RuntimeState error={error} retry={reload} />
  if (error) return <Alert tone="danger">{t(key('value'), { value: runtimeMessage(error) || t(key('writeError')) })}</Alert>
  return success ? <Alert tone="success">{replayed ? t(key('replayed')) : success}</Alert> : null
}

export function Refresh({ run }: { run: () => unknown }) {
  const t = useT()
  return <Button onClick={() => void run()}>{t(key('refresh'))}</Button>
}
export function Empty({ message, action, onAction }: { message: string; action?: string; onAction: () => unknown }) {
  const t = useT()
  return <EmptyState title={t(key(message))} action={<Button onClick={() => void onAction()}>{t(key(action ?? 'refresh'))}</Button>} />
}
export function Panel({ title, children }: { title: string; children: ReactNode }) {
  const t = useT()
  return <Card><Stack><h2>{t(key(title))}</h2>{children}</Stack></Card>
}
export function Columns({ names, rows, label }: { names: string[]; rows: TableRow[]; label: string }) {
  const t = useT()
  return <Table label={t(key(label))} columns={names.map(id => ({ id, label: t(key(id)) }))} rows={rows} />
}
export function Pager({ label, page, total, size, change }: { label: string; page: number; total: number; size: number; change: (page: number) => void }) {
  const t = useT()
  const pages = Math.max(1, Math.ceil(total / size))
  return pages > 1 || page > 1 ? <Pagination label={t(key(label))} page={page} pages={Math.max(page, pages)} onChange={change} /> : null
}
export function Pick({ label, options, value, onChange }: { label: string; options: SelectOption[]; value: string; onChange: (value: string) => void }) {
  const t = useT()
  return <Field label={label}>{attrs => <Select triggerProps={attrs} value={value || '_none'} placeholder={t(key('choose'))} options={options}
    onValueChange={value => onChange(value === '_none' ? '' : value)} />}</Field>
}
export const choices = (t: Translate, values: readonly string[], first = 'all') => [
  { value: '_none', label: t(key(first)) }, ...values.map(value => ({ value, label: enumLabel(t, value) })),
]
export const data = (t: Translate, value: unknown) => value == null || value === '' ? t(key('none')) : t(key('value'), { value: String(value) })
export const field = (t: Translate, name: string, options: { label?: string; value?: string; required?: boolean; max?: number; type?: string; area?: boolean; validate?: FormField['validateWith'] } = {}): FormField => ({
  name, label: t(key(options.label ?? name)),
  validateWith: (value, input) => !value.trim() && options.required ? { key: key('required') } :
    options.max && value.length > options.max ? { key: key('tooLong'), values: { max: options.max } } : options.validate?.(value, input),
  control: attrs => options.area ? <Textarea {...attrs} defaultValue={options.value} maxLength={options.max} /> :
    <Input {...attrs} defaultValue={options.value} type={options.type} maxLength={options.max} />,
})
export const selectField = (t: Translate, name: string, options: SelectOption[], value?: string): FormField => ({
  name, label: t(key(name)),
  validateWith: selected => !selected || selected === '_none' ? { key: key('required') } : undefined,
  control: ({ name, disabled, ...attrs }) => <Select name={name} disabled={disabled} triggerProps={attrs}
    defaultValue={value} placeholder={t(key('choose'))} options={options} />,
})
export const text = (form: FormData, name: string) => String(form.get(name) ?? '').trim()
export const optional = (form: FormData, name: string) => text(form, name) || undefined
export function Filter({ name, value, onChange, type, max }: { name: string; value?: string; onChange: (value?: string) => void; type?: string; max?: number }) {
  const t = useT()
  return <form key={value ?? ''} onSubmit={event => { event.preventDefault(); onChange(optional(new FormData(event.currentTarget), name)) }}>
    <Row><Field label={t(key(name))}>{attrs => <Input {...attrs} name={name} defaultValue={value} type={type} maxLength={max} />}</Field>
      <Button type="submit">{t(key('apply'))}</Button></Row>
  </form>
}
export function Details({ values }: { values: [string, ReactNode][] }) {
  const t = useT()
  return <Grid>{values.map(([label, value], index) => <Stack key={label + index} gap={1}><strong>{t(key(label))}</strong><div>{value}</div></Stack>)}</Grid>
}
export function useRuntimeQuery<T>(...args: Parameters<typeof liveRead<T>>) {
  return useQuery(liveRead<T>(...args))
}
export const enumLabel = (t: Translate, value: string) => {
  const name = key('enum.' + value)
  const label = t(name)
  return label === name ? data(t, value) : label
}

export function serverFields(error: unknown, aliases: Record<string, string> = {}, collection?: (path: string) => string | undefined) {
  return Object.fromEntries(Object.entries(fieldErrors(error)).map(([path, messages]) => [
    collection?.(path) ?? aliases[path] ?? path, { key: key('value'), values: { value: messages.join(' ') } },
  ]))
}
