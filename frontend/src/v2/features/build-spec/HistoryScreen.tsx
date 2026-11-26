import { useQuery } from '@tanstack/react-query'
import { useReducer, useState } from 'react'
import type { HistoryBody } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, SaveBar, SettingsSection } from '../../patterns'
import { Alert, Button, EmptyState, Field, Input, Row, Stack } from '../../ui'
import { buildLimits, historyRetention, secretHistoryField } from '../../validators'
import { buildQueries, catalog, saveHistory, useBuildWrite } from './api/build'
import { BuildFailure, BuildLoad, BuildPage, ChoiceGroup, choices, IssueList, Pick, SectionLink, useBuildDate, WriteAccess } from './components/shared'
import type { BuildScreenProps } from './components/shared'
import { useBuildRoute } from './routes'
import { sectionDraft } from './state/sectionDraft'

type HistoryDraft = Omit<HistoryBody, 'retention_days'> & { retention_days: string }

export default function HistoryScreen({ access }: BuildScreenProps) {
  const { projectId } = useBuildRoute()
  return <BuildPage screen="history"><History key={projectId} access={access} /></BuildPage>
}

function History({ access }: BuildScreenProps) {
  const t = useT()
  const date = useBuildDate()
  const { projectId, search, update } = useBuildRoute()
  const section = useQuery(buildQueries.history(projectId))
  const spec = useQuery(buildQueries.spec(projectId))
  const machines = useQuery(buildQueries.machines(projectId))
  const issues = useQuery(buildQueries.issues(projectId))
  const roles = useQuery(buildQueries.roles(projectId))
  const save = useBuildWrite(projectId, saveHistory)
  const [draft, dispatch] = useReducer(sectionDraft<HistoryDraft>, null)
  const [validated, setValidated] = useState(false)

  const entities = catalog(spec.data ?? {})
  const rows = draft?.rows ?? section.data?.history.map(row => ({ ...row, retention_days: String(row.retention_days) })) ?? []
  const available = entities.filter(entity => !rows.some(row => row.entity === entity.name))
  const entityName = available.find(entity => entity.name === search.entity)?.name ?? available[0]?.name
  const disabled = !access.writable || save.isPending
  const problems = issues.data?.issues.filter(issue => /^history(?:\.|\[|$)/.test(issue.path)) ?? []
  const reset = () => {
    dispatch({ type: 'reset' })
    setValidated(false)
    save.reset()
  }
  const reload = async () => {
    if ((await section.refetch()).isSuccess) reset()
    void issues.refetch()
  }
  const changeRows = (next: HistoryDraft[]) => {
    if (!section.data) return
    dispatch({ type: 'set', version: section.data.version, rows: next })
  }
  const changeRow = (index: number, patch: Partial<HistoryDraft>) =>
    changeRows(rows.map((row, i) => i === index ? { ...row, ...patch } : row))

  const invalid = rows.map(row => {
    const retention = historyRetention(row.retention_days)
    return {
      fields: !row.fields?.length ? t('buildSpec.history.selectField') :
        row.fields.some(name => secretHistoryField(name) || machines.data?.state_machines.some(machine => machine.entity === row.entity && machine.field === name))
          ? t('buildSpec.history.removeProtected') : undefined,
      retention: !row.retention_days.trim() ? t('buildSpec.history.enterDays') : retention ? t(retention.key, retention.values) : undefined,
    }
  })

  async function submit() {
    if (!draft || disabled) return
    setValidated(true)
    const first = invalid.findIndex(error => error.fields || error.retention)
    if (first !== -1) {
      const node = document.getElementById('history-row-' + first)
      node?.querySelector<HTMLElement>(invalid[first].fields ? 'input[type=checkbox]:not(:disabled)' : 'input[type=number]')?.focus()
      return
    }
    try {
      await save.mutateAsync({ rows: rows.map(row => ({ ...row, retention_days: Number(row.retention_days) })), version: draft.version })
      dispatch({ type: 'reset' })
      setValidated(false)
    } catch { /* Shown beside the form. */ }
  }

  return <BuildLoad reads={[section, spec, machines, issues, roles]}>
    <WriteAccess access={access} />
    <BuildFailure error={save.error} reload={() => void reload()} />
    {problems.length > 0 && <Alert tone="warning"><IssueList issues={problems} /></Alert>}
    {!rows.length && <EmptyState title={t('buildSpec.history.empty')} description={t('buildSpec.history.emptyDetail')}
      action={!available.length ? <SectionLink projectId={projectId} section="model">{t('buildSpec.openModel')}</SectionLink> : undefined} />}
    {rows.map((row, index) => {
      const entity = entities.find(item => item.name === row.entity)
      const state = machines.data?.state_machines.find(machine => machine.entity === row.entity)?.field
      const names = new Set([...(entity?.fields.map(field => field.name) ?? []), ...(row.fields ?? [])])
      const fieldOptions = [...names].map(name => {
        const reason = name === state ? 'stateField' : secretHistoryField(name) ? 'secretField' : undefined
        return { value: name, label: reason ? t('buildSpec.history.disabledField', { name, reason: t('buildSpec.history.' + reason) }) : name, disabled: Boolean(reason && !row.fields?.includes(name)) }
      })
      const rowIssue = (path: string) => problems.find(issue => issue.path.startsWith(`history[${index}].${path}`) || issue.path.startsWith(`history.${index}.${path}`))?.message
      const roleOptions = choices([...new Set([...(roles.data?.roles.map(role => role.name) ?? []), ...(row.view_roles ?? [])])])
      return <SettingsSection key={row.entity} title={row.entity}>
        <Stack id={'history-row-' + index} data-testid="history-row">
          <ChoiceGroup label={t('buildSpec.history.fields')} options={fieldOptions} selected={row.fields ?? []} disabled={disabled}
            onChange={fields => changeRow(index, { fields })} error={(validated ? invalid[index].fields : undefined) ?? rowIssue('fields')} />
          <Field label={t('buildSpec.history.retention')} hint={t('buildSpec.history.retentionHint')} error={(validated ? invalid[index].retention : undefined) ?? rowIssue('retention_days')}>
            {attrs => <Input {...attrs} type="number" min={1} max={buildLimits.retention} value={row.retention_days}
              onChange={event => changeRow(index, { retention_days: event.target.value })} disabled={disabled} />}
          </Field>
          <ChoiceGroup label={t('buildSpec.history.roles')} options={roleOptions} selected={row.view_roles ?? []} disabled={disabled}
            onChange={view_roles => changeRow(index, { view_roles })} error={rowIssue('view_roles')} />
          <p className="v2-muted">{t('buildSpec.history.rolesHint')}</p>
          <Row><ConfirmDestructive title={t('buildSpec.history.remove')} description={t('buildSpec.history.removeDetail', { entity: row.entity })}
            action={t('buildSpec.remove')} trigger={<Button variant="danger" disabled={disabled}>{t('buildSpec.remove')}</Button>}
            onConfirm={() => changeRows(rows.filter((_, i) => i !== index))} /></Row>
        </Stack>
      </SettingsSection>
    })}
    {available.length > 0 && <SettingsSection title={t('buildSpec.history.add')}>
      <Pick label={t('buildSpec.history.entity')} options={choices(available.map(entity => entity.name))} value={entityName}
        onChange={entity => update({ entity })} disabled={disabled} />
      <Row><Button variant="primary" disabled={!entityName || disabled} onClick={() => {
        if (entityName) changeRows([...rows, { entity: entityName, fields: [], retention_days: '365', view_roles: [] }])
      }}>{t('buildSpec.history.record')}</Button></Row>
    </SettingsSection>}
    {entities.length > 0 && !available.length && <p className="v2-muted">{t('buildSpec.history.all')}</p>}
    {section.data?.updated_at && <p className="v2-muted">{t('buildSpec.versionUpdated', { version: section.data.version, date: date(section.data.updated_at) })}</p>}
    <SaveBar dirty={Boolean(draft)} pending={save.isPending} saved={save.isSuccess} readOnly={disabled} onSave={() => void submit()} onDiscard={() => void reload()} />
  </BuildLoad>
}
