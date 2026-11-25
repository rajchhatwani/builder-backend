import type { ComponentProps, ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { useLanguage, useT } from '../../../../i18n'
import { Button, EmptyState, Input, Pagination, Select, Stack, Table, useToast } from '../../../../ui'
import type { ValidationIssue } from '../../../../validators'
import type { FormField } from '../../../../patterns'
import type { Organization, OrgRole, UserAccount } from '../../api/org'
import { useOrgMutation } from '../../api/org'
import { entryError } from '../../api/entry'
import type { OrgSearch } from '../../orgSearch'
import { EntryLoading, EntryProblem } from '../EntryFrame'
import { authProblem } from '../messages'

export type OrgProps = {
  org: Organization
  user: UserAccount
  owners: string
  search: OrgSearch
  setSearch: (search: OrgSearch) => void
}

export const canAdmin = (org: Organization) => org.my_role !== 'member'
export const roles: OrgRole[] = ['member', 'admin', 'owner']
export const textValue = (data: FormData, field: string) => String(data.get(field) ?? '').trim()

export function orgDate(date?: string | null) {
  if (!date || Number.isNaN(Date.parse(date))) return undefined
  return new Intl.DateTimeFormat(document.documentElement.lang, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date))
}

export function money(dollars: number) {
  return new Intl.NumberFormat(document.documentElement.lang, { style: 'currency', currency: 'USD', maximumFractionDigits: 6 }).format(dollars)
}

export function useOrgAction({ org, user }: Pick<OrgProps, 'org' | 'user'>) {
  const t = useT()
  const toast = useToast()
  const action = useOrgMutation(org.slug, user.id)
  return {
    ...action,
    async perform(operation: () => Promise<unknown>, key = 'common.saved', refresh?: 'org' | 'projects' | 'none') {
      await action.run(operation, refresh)
      if (key) toast({ title: t(key), tone: 'success' })
    },
    submit(operation: () => Promise<unknown>, key?: string, refresh?: 'org' | 'projects' | 'none') {
      void action.run(operation, refresh).then(() => {
        if (key !== '') toast({ title: t(key ?? 'common.saved'), tone: 'success' })
      }).catch(() => {})
    },
  }
}

const errors = new Set([
  'org_mfa_required', 'org_deletion_pending', 'enable_mfa_first', 'domain_taken', 'public_email_domain',
  'invalid_domain', 'last_verified_domain', 'domain_not_verified', 'no_verified_domain', 'sso_not_configured',
  'invalid_certificate', 'private_address', 'last_owner', 'sole_project_owner', 'org_has_billing',
  'live_subscription', 'not_an_org_member', 'insecure_url', 'invalid_url', 'oidc_client_secret_required', 'invalid_sso_config',
  'scim_not_configured', 'scim_not_in_plan', 'session_required', 'seat_limit', 'project_limit', 'subscription_past_due',
])

export function OrgProblem({ error, retry, message }: { error: unknown; retry?: () => void; message?: string }) {
  const t = useT()
  const { status, code } = entryError(error)
  const fallback = status === 409 ? 'org.conflict' : status === 402 ? 'org.limitReached' : status === 422 ? 'org.checkFields' : authProblem(error)
  return <EntryProblem error={error} message={message ?? t(errors.has(code) ? 'org.errors.' + code : fallback)}
    retry={retry} retryLabel={t('org.retry')} />
}

export function orgFieldError(error: unknown, fields: Record<string, string>): Record<string, ValidationIssue> | undefined {
  const { code, details, message } = entryError(error)
  const locations = details?.map(detail => detail && typeof detail === 'object' && 'loc' in detail ? detail.loc : undefined)
  const bodyField = locations?.find(location => Array.isArray(location) && location[0] === 'body')
  const backendField = Array.isArray(bodyField) ? String(bodyField[1]) : message.split(' ')[0]
  const field = Object.hasOwn(fields, backendField) ? fields[backendField] : undefined
  if (!field || !code) return undefined
  return { [field]: { key: errors.has(code) ? 'org.errors.' + code : 'org.fieldRejected' } }
}

export function OrgData<T>({ query, children }: {
  query: { isPending: boolean; isError: boolean; data: T | undefined; error: unknown; refetch: () => unknown }
  children: (data: T) => ReactNode
}) {
  const t = useT()
  if (query.isPending) return <EntryLoading label={t('org.loading')} lines={8} />
  if (query.isError) return <OrgProblem error={query.error} retry={() => void query.refetch()} />
  return query.data === undefined ? null : children(query.data)
}

export function OrgTable({ label, fields, rows, empty, action, navigation }: {
  label: string; fields: string[]; rows: ComponentProps<typeof Table>['rows']; empty?: string; action?: ReactNode
  navigation?: Pick<OrgProps, 'search' | 'setSearch'>
}) {
  const t = useT()
  const size = 20
  const page = Math.min(navigation?.search.page ?? 1, Math.max(1, Math.ceil(rows.length / size)))
  const visible = navigation ? rows.slice((page - 1) * size, page * size) : rows
  return <Stack>{rows.length ? <>
    <Table label={label} rows={visible} columns={fields.map(id => ({ id, label: t('org.field.' + id) }))} />
    {navigation && <OrgPager label={label} page={page} size={size} total={rows.length} onChange={next =>
      navigation.setSearch({ ...navigation.search, page: next > 1 ? next : undefined })} />}
  </> : <EmptyState title={empty ?? t('common.noResults')} action={action} />}</Stack>
}

export function OrgPager({ page, size, total, label, onChange }: {
  page: number; size: number; total: number; label: string; onChange: (page: number) => void
}) {
  const t = useT()
  return total > size || page > 1 ? <Stack>
    <p>{t('org.range', { from: Math.min((page - 1) * size + 1, total), to: Math.min(page * size, total), total })}</p>
    <Pagination label={label} page={page} pages={Math.ceil(total / size)} onChange={onChange} />
  </Stack> : null
}

export function ProjectBack() {
  const t = useT()
  return <Button asChild><Link to="/projects">{t('org.backProjects')}</Link></Button>
}

export function OrgTabButton({ slug, tab, children }: { slug: string; tab: OrgSearch['tab']; children: ReactNode }) {
  return <Button asChild><Link to="/org/$slug" params={{ slug }} search={{ tab }}>{children}</Link></Button>
}

export function useOrgFields() {
  const { t } = useLanguage()
  return {
    input(name: string, props: ComponentProps<typeof Input> & { 'data-testid'?: string } = {}, validate?: FormField['validate']): FormField {
      return { name, label: t('org.field.' + name), validate, control: attributes => <Input {...props} {...attributes} /> }
    },
    select(name: string, values: readonly string[], initial?: string, namespace = name): FormField {
      return { name, label: t('org.field.' + name), control: ({ name, disabled, ...triggerProps }) =>
        <Select name={name} disabled={disabled} triggerProps={triggerProps} defaultValue={initial ?? values[0]}
          options={values.map(value => ({ value, label: t('org.' + namespace + '.' + value) }))} /> }
    },
  }
}
