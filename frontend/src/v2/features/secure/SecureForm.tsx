import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useT } from '../../i18n'
import { ConflictBanner, ReadOnlyNote, SettingsSection, type FormField } from '../../patterns'
import { Alert, Button, Card, Checkbox, Grid, Input, Select, Skeleton, Stack, Textarea } from '../../ui'
import { validators } from '../../validators'
import type { ValidationIssue, Validator } from '../../validators'
import { statusOf } from './api/security'

export type SecureProps = {
  projectId: string
  role?: 'owner' | 'editor' | 'viewer'
  rolePending?: boolean
  roleError?: boolean
  retryRole?: () => void
}
const route = '/projects/$projectId/$section'
export function useSecureSearch() {
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  return { search, tab: (tab: string) => void navigate({ search: old => ({ ...old, tab, page: undefined, view: undefined, kind: undefined }) }),
    filter: (filter: { kind?: string; view?: string; entity?: string; q?: string }, resetPage = true) =>
      void navigate({ search: old => ({ ...old, ...filter, page: resetPage ? undefined : old.page }) }),
    page: (page: number) => void navigate({ search: old => ({ ...old, page: page > 1 ? page : undefined }) }) }
}
export function SecureLink({ id, section, label }: { id: string; section: string; label: string }) {
  return <Link to={route} params={{ projectId: id, section }}>{label}</Link>
}
export const canEdit = (props: SecureProps) => props.role === 'owner' || props.role === 'editor'
export const readText = (data: FormData, key: string) => String(data.get(key) ?? '').trim()
export const readNullable = (data: FormData, key: string) => readText(data, key) || null
export const readNumber = (data: FormData, key: string) => Number(readText(data, key))
export const readOptionalNumber = (data: FormData, key: string) => readText(data, key) ? readNumber(data, key) : null
export const readLines = (value: string) => value.split('\n').map(line => line.trim()).filter(Boolean)

export function textField(name: string, label: string, value: string | number | null | undefined, options: {
  max?: number; checks?: Validator[]; required?: boolean; area?: boolean; hint?: string; placeholder?: string
  type?: string; locked?: boolean; change?: (value: string) => void; controlled?: boolean
  validateWith?: FormField['validateWith']
} = {}): FormField {
  return {
    name, label, hint: options.hint, validateWith: options.validateWith,
    validate: [...(options.required ? [validators.required] : []), ...(options.max ? [validators.length(options.max)] : []), ...(options.checks ?? [])],
    control: ({ disabled, ...attributes }) => {
      const valueProps = options.controlled ? { value: value ?? '' } : { defaultValue: value ?? '' }
      const props = { ...attributes, ...valueProps, disabled: disabled || options.locked, maxLength: options.max,
        placeholder: options.placeholder,
        onChange: options.change ? (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => options.change?.(event.target.value) : undefined }
      return options.area ? <Textarea {...props} /> : <Input {...props} type={options.type} />
    },
  }
}
export function numberField(name: string, label: string, value: number | null | undefined,
  bounds: { min?: number; max?: number; integer?: boolean; digits?: number } = {}, required = true,
  validateWith?: FormField['validateWith']): FormField {
  return textField(name, label, value, { type: 'number', required, checks: [validators.number(bounds)], validateWith })
}
export function checkField(name: string, label: string, value: boolean, change?: (value: boolean) => void): FormField {
  return { name, label, ownLabel: true, control: ({ disabled, ...attributes }) => <Checkbox {...attributes} disabled={disabled}
    label={label} {...(change ? { checked: value, onChange: event => change(event.target.checked) } : { defaultChecked: value })} /> }
}
export function pickField(name: string, label: string, value: string, choices: { value: string; label: string }[],
  options: { change?: (value: string) => void; locked?: boolean; hint?: string; required?: boolean; placeholder?: string } = {}): FormField {
  return { name, label, hint: options.hint, validate: options.required ? [validators.required] : undefined,
    control: ({ name, disabled, ...attributes }) => <Select name={name} disabled={disabled || options.locked}
      {...(options.change ? { value, onValueChange: options.change } : { defaultValue: value })}
      options={choices} placeholder={options.placeholder} triggerProps={attributes} /> }
}

export function groups(sections: { key?: number; title: string; hint?: string; fields: FormField[]; extra?: ReactNode; actions?: ReactNode }[]) {
  return {
    fields: sections.flatMap(section => section.fields),
    layout: (controls: Record<string, ReactNode>) => <Stack gap={4}>{sections.map(section =>
      <SettingsSection key={section.key ?? section.title} title={section.title} description={section.hint}>
        {!!section.fields.length && <Grid>{section.fields.map(field => controls[field.name])}</Grid>}
        {section.extra}{section.actions}
      </SettingsSection>)}</Stack>,
  }
}

export function SecureRole({ role, roleError, retryRole }: SecureProps) {
  const t = useT()
  if (roleError) return <LoadFailure error={undefined} message={t('secure.roleError')} retry={retryRole} />
  return role === 'viewer' ? <ReadOnlyNote /> : null
}
export function SecureLoading({ label }: { label: string }) {
  return <Stack gap={4}>{[0, 1, 2].map(index => <Card key={index} aria-hidden={index > 0 || undefined}>
    <Skeleton label={index === 0 ? label : undefined} lines={4} />
  </Card>)}</Stack>
}
export function LoadFailure({ error, message, retry }: { error: unknown; message: string; retry?: () => void }) {
  const t = useT()
  const forbidden = statusOf(error) === 403
  return <Alert tone="danger" action={retry && <Button onClick={retry}>{t('common.retry')}</Button>}>
    {forbidden ? t('secure.forbidden') : message}
  </Alert>
}
export function WriteNotice({ error, message, saved, reload }: { error: unknown; message: string; saved?: string; reload?: () => void }) {
  if (statusOf(error) === 409) return <ConflictBanner onReload={reload}>{message}</ConflictBanner>
  if (error) return <LoadFailure error={error} message={message} />
  return saved ? <Alert tone="success">{saved}</Alert> : null
}
export function Findings({ issues }: { issues: { path: string; message: string; code?: string }[] }) {
  const t = useT()
  return <Stack gap={2}>{issues.map((issue, index) => <Alert key={index} tone="warning">
    {t('secure.finding', { path: issue.path, message: issue.message })}
  </Alert>)}</Stack>
}
export function requiredWhen(enabled: boolean): Validator {
  return value => enabled ? validators.required(value) : undefined
}
export function duplicateValue(value: string, taken: readonly string[]): ValidationIssue | undefined {
  return value && taken.includes(value) ? { key: 'validation.secureDuplicate' } : undefined
}
