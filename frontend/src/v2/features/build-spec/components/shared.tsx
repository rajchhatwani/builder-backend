import { Link } from '@tanstack/react-router'
import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import type { SpecOp } from '../../../../api/types'
import { opTarget } from '../../../../shell/timeline/timelineLogic'
import { RouteTranslations, useLanguage, useT } from '../../../i18n'
import { ConflictBanner, PageHeader, ReadOnlyNote } from '../../../patterns'
import type { ProjectSection } from '../../../projectNavigation'
import { Alert, Button, Card, Checkbox, DesktopOnlyCard, Field, Select, Skeleton, Stack } from '../../../ui'
import { buildError, record, serverIssues } from '../api/build'
import { route } from '../routes'
import english from '../en.json'

type BuildPageProps = { screen: string; desktop?: boolean; children: ReactNode }

export function BuildPage(props: BuildPageProps) {
  return <RouteTranslations english={english}><BuildLayout {...props} /></RouteTranslations>
}

function BuildLayout({ screen, desktop, children }: BuildPageProps) {
  const t = useT()
  const [desktopReady, setDesktopReady] = useState(() => !document.body.clientWidth || document.body.clientWidth >= 700)
  return <Stack gap={4} ref={element => {
    if (!element || !desktop || desktopReady || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      if (document.body.clientWidth >= 700) setDesktopReady(true)
    })
    observer.observe(document.body)
    return () => observer.disconnect()
  }}>
    <PageHeader title={t('buildSpec.' + screen + '.title')} description={t('buildSpec.' + screen + '.intro')} />
    {desktop && <div className="v2-phone-only"><DesktopOnlyCard /></div>}
    {(!desktop || desktopReady) && <Stack className={desktop ? 'v2-phone-hidden' : undefined} gap={4}>{children}</Stack>}
  </Stack>
}

type Read = { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }
export function BuildLoad({ reads, children }: { reads: Read[]; children: ReactNode }) {
  const t = useT()
  const failures = reads.filter(read => read.isError)
  const retry = () => { for (const read of failures) void read.refetch() }
  if (failures.length) return <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>
    {t(failures.some(read => buildError(read.error)?.status === 403) ? 'buildSpec.forbidden' : 'buildSpec.loadError')}
  </Alert>
  if (reads.some(read => read.isPending)) return <Card className="v2-screen-placeholder"><Skeleton lines={8} /></Card>
  return children
}

export type BuildAccess = { pending: boolean; failed: boolean; writable: boolean; retry?: () => void }
export type BuildScreenProps = { access: BuildAccess }

export function WriteAccess({ access }: BuildScreenProps) {
  const t = useT()
  if (access.pending) return null
  if (access.failed) return <Alert action={<Button onClick={access.retry}>{t('common.retry')}</Button>}>{t('buildSpec.roleError')}</Alert>
  return access.writable ? null : <ReadOnlyNote />
}

export function BuildFailure({ error, reload, onWeakening }: { error: unknown; reload?: () => void; onWeakening?: ReactNode }) {
  const t = useT()
  if (!error) return null
  const api = buildError(error)
  if (api?.code === 'access_weakened') return <ConflictBanner action={onWeakening} onReload={reload}>{t('buildSpec.weakening')}</ConflictBanner>
  if (api?.code === 'nothing_to_undo' || api?.code === 'nothing_to_redo') return <Alert>{t('buildSpec.' + api.code)}</Alert>
  if (api?.status === 409 && (api.code.endsWith('conflict') || ['stale_spec', 'spec_changed', 'already_there', 'restore_mismatch'].includes(api.code))) return <ConflictBanner onReload={reload} />
  if (api?.status === 403) return <Alert tone="danger">{t('buildSpec.forbidden')}</Alert>
  const issues = serverIssues(error)
  return <Alert tone="danger">{api?.message || t('common.actionFailed')}{issues.length > 0 && <IssueList issues={issues} />}</Alert>
}

export function IssueList({ issues }: { issues: { path: string; message: string }[] }) {
  const t = useT()
  return <Stack>
    <strong>{t('buildSpec.issues', { count: issues.length })}</strong>
    <ul>{issues.map(({ path, message }, index) => <li key={index}>{t('buildSpec.issue', { path, message })}</li>)}</ul>
  </Stack>
}

export function SectionLink({ projectId, section, children }: { projectId: string; section: ProjectSection; children: ReactNode }) {
  return <Button asChild><Link to={route} params={{ projectId, section }}>{children}</Link></Button>
}

export type Choice = { value: string; label: string; disabled?: boolean }
export const choices = (values: readonly string[]) => values.map(value => ({ value, label: value }))
export function Pick({ label, options, value, onChange, disabled, error }: {
  label: string; options: Choice[]; value?: string; onChange: (value: string) => void; disabled?: boolean; error?: string
}) {
  const t = useT()
  return <Field label={label} error={error}>{attrs =>
    <Select triggerProps={attrs} options={options} value={value ?? ''} onValueChange={onChange} disabled={disabled || !options.length} placeholder={t('buildSpec.choose')} />
  }</Field>
}

export function ChoiceGroup({ label, options, selected, onChange, disabled, error }: {
  label: string; options: Choice[]; selected: readonly string[]; onChange: (values: string[]) => void; disabled?: boolean; error?: string
}) {
  const id = useId()
  return <Stack gap={1} role="group" aria-labelledby={id}>
    <strong id={id}>{label}</strong>
    {options.map(option => <Checkbox key={option.value} value={option.value} label={option.label} checked={selected.includes(option.value)}
      disabled={disabled || option.disabled} onChange={event => onChange(event.target.checked
        ? [...selected, option.value] : selected.filter(value => value !== option.value))} />)}
    {error && <span role="alert" className="v2-field-error">{error}</span>}
  </Stack>
}

export function useBuildDate() {
  const { language, t } = useLanguage()
  const formatter = new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })
  return (iso?: string | null) => iso && Number.isFinite(Date.parse(iso)) ? formatter.format(new Date(iso)) : t('buildSpec.none')
}

const opTypes = new Set([
  'add_entity', 'update_entity', 'remove_entity', 'add_field', 'update_field', 'remove_field', 'add_relation',
  'update_relation', 'remove_relation', 'set_section', 'replace_spec', 'define_custom_field', 'update_custom_field',
  'remove_custom_field', 'promote_custom_field',
])

const specSectionLabels: Record<string, string> = {
  entities: 'nav.model', relations: 'buildSpec.model.relations', auth: 'nav.auth', authorization: 'nav.access',
  state_machines: 'nav.machines', history: 'nav.history', hooks: 'nav.hooks', hook_effects: 'nav.hookeffects',
  events: 'nav.events', settings: 'nav.settings', seed: 'nav.seed',
}

export function useVersionLabel() {
  const { language, t } = useLanguage()
  const list = new Intl.ListFormat(language)
  return (op: SpecOp) => {
    const kind = opTypes.has(op.op_type) ? op.op_type : 'other'
    let change = t('buildSpec.ops.' + kind)
    let target = opTarget(op) ?? ''
    if (op.origin === 'restore') {
      change = t('buildSpec.timeline.restored', { version: op.ref_seq ?? t('buildSpec.none') })
    } else if (op.origin === 'undo' || op.origin === 'redo') {
      change = t('buildSpec.timeline.' + (op.origin === 'undo' ? 'undid' : 'redid'), {
        change, version: op.ref_seq ?? t('buildSpec.none'),
      })
    } else if (kind === 'replace_spec') {
      const before = record(op.inverse.payload.spec)
      const after = record(op.payload.spec)
      if (Object.keys(before).length && Object.keys(after).length) {
        const sections = Object.entries(specSectionLabels)
          .filter(([section]) => JSON.stringify(before[section]) !== JSON.stringify(after[section]))
          .map(([, label]) => t(label))
        if (sections.length) {
          change = t('buildSpec.timeline.changedSections', {
            sections: list.format([...new Set(sections)]),
          })
        }
      }
    } else if (kind === 'set_section') {
      const section = op.payload.section
      if (typeof section === 'string' && Object.hasOwn(specSectionLabels, section)) target = t(specSectionLabels[section])
    }
    return t('buildSpec.timeline.version', { seq: op.seq, change, target }).trimEnd()
  }
}


export function WeakeningDetails({ error }: { error: unknown }) {
  const t = useT()
  const roles = [...new Set((buildError(error)?.details ?? []).map(item => record(item).role).filter(role => typeof role === 'string'))]
  return roles.length > 0 && <p>{t('buildSpec.affectedRoles', { roles: roles.join(', ') })}</p>
}
