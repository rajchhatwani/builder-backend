import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { Form, SettingsSection } from '../../patterns'
import { Alert, Button, EmptyState, Grid, Pagination, Row, Stack, Table } from '../../ui'
import { controlsApi, matrixOptions, type AccessDiff, type AuthorizationModel, type AuthorizationSettings,
  type ProjectRole, type ProjectSpec, type RecommendAnswers } from './api/controls'
import { checkField, LoadFailure, numberField, pickField, readNumber, readText, SecureLink, SecureLoading, useSecureSearch } from './SecureForm'
import type { AuthorizationEdit } from './state/access'
import { AccessFieldRules } from './AccessFieldRules'

export type AccessEditorProps = {
  id: string; spec: ProjectSpec; settings: AuthorizationSettings; roles: ProjectRole[]
  editable: boolean; busy: boolean; submit: (edit: AuthorizationEdit, removePolicies?: boolean) => Promise<boolean>
}
const models = ['rbac', 'abac', 'pbac'] as const
const flags = ['ownership_rules', 'tenant_rules', 'time_or_network_rules', 'per_record_rules', 'deny_rules', 'audit_needs', 'public_routes'] as const

export function AccessDiffTable({ diff }: { diff: AccessDiff }) {
  const t = useT()
  return <Stack gap={2}>
    <p>{t('authorization.diffCounts', { gains: diff.counts.gain, losses: diff.counts.lose, changes: diff.changes.length })}</p>
    {!!diff.changes.length && <Table label={t('authorization.reviewDiff')} columns={['role', 'slot', 'before', 'after'].map(key =>
      ({ id: key, label: t(`authorization.${key}`) }))} rows={diff.changes.slice(0, 100).map((row, index) => ({
        id: String(index), cells: [row.role, t('authorization.slotName', { entity: row.entity, operation: row.target }),
          row.before ?? t('authorization.none'), row.after ?? t('authorization.none')],
      }))} />}
    {diff.changes.length > 100 && <p>{t('authorization.diffLimit')}</p>}
  </Stack>
}

export function AccessModel(props: AccessEditorProps) {
  const { id, settings, roles, spec, editable, busy, submit } = props
  const t = useT()
  const { tab } = useSecureSearch()
  const [draft, setDraft] = useState<AuthorizationModel>()
  const model = draft ?? settings.model
  const recommend = useMutation({ mutationFn: (answers?: RecommendAnswers) => answers ?
    controlsApi.recommendAuthorization(id, answers) : controlsApi.recommendFromProject(id) })
  function apply(next: AuthorizationModel) {
    const drop = next === 'rbac'
    void submit({ kind: 'settings', settings: { ...settings, model: next,
      policies: drop ? [] : settings.policies, attachments: next === 'pbac' ? settings.attachments : {} } },
    drop && (settings.policies.length > 0 || Object.keys(settings.attachments).length > 0)).then(accepted => {
      if (accepted) setDraft(undefined)
    })
  }
  const fields = [
    numberField('roles', t('authorization.rolesCount'), Math.min(roles.length, 100), { min: 0, max: 100, integer: true }),
    pickField('policy_editors', t('authorization.editors'), 'developers', ['developers', 'admins'].map(value =>
      ({ value, label: t(`authorization.${value}`) }))),
    ...flags.map(key => checkField(key, t(`authorization.${key}`), false)),
  ]
  const setFields = (settings: AuthorizationSettings) => { void submit({ kind: 'settings', settings }) }
  return <Stack gap={4}>
    {model !== 'rbac' && <Alert tone="warning"><Stack gap={1}>
      <p>{t('authorization.modelNote', { model: t(`authorization.abbrev_${model}`) })}</p>
      {spec.auth?.enabled !== true && <Row><p>{t('authorization.authOff', { model: t(`authorization.abbrev_${model}`) })}</p>
        <SecureLink id={id} section="auth" label={t('authorization.authentication')} /></Row>}
    </Stack></Alert>}
    <SettingsSection title={t('authorization.modelTitle')}>
      {settings.version === 0 && !roles.length && !spec.entities.length && <EmptyState title={t('authorization.modelEmpty')}
        action={<Button onClick={() => tab('roles')}>{t('authorization.tab_roles')}</Button>} />}
      <Grid role="group" aria-label={t('authorization.modelTitle')}>
        {models.map(value => <Stack key={value} gap={2} className="v2-card">
          <Button aria-pressed={value === model} variant={value === model ? 'primary' : 'default'}
            disabled={!editable || busy} onClick={() => setDraft(value)}>{t(`authorization.model_${value}`)}</Button>
          <p>{t(`authorization.hint_${value}`)}</p><p className="v2-muted">{t(`authorization.fit_${value}`)}</p>
        </Stack>)}
      </Grid>
      {editable && <Row><Button variant="primary" disabled={busy || model === settings.model} onClick={() => apply(model)}>{t('common.save')}</Button></Row>}
    </SettingsSection>
    <SettingsSection title={t('authorization.recommendTitle')}>
      <Form fields={fields} pending={recommend.isPending} submitLabel={t('authorization.recommend')}
        layout={controls => <Grid>{fields.map(field => controls[field.name])}</Grid>}
        actions={<Button disabled={recommend.isPending} onClick={() => recommend.mutate(undefined)}>{t('authorization.recommendProject')}</Button>}
        onSubmit={data => recommend.mutate({ roles: readNumber(data, 'roles'),
          policy_editors: readText(data, 'policy_editors') === 'admins' ? 'admins' : 'developers',
          ownership_rules: data.has('ownership_rules'), tenant_rules: data.has('tenant_rules'), time_or_network_rules: data.has('time_or_network_rules'),
          per_record_rules: data.has('per_record_rules'), deny_rules: data.has('deny_rules'), audit_needs: data.has('audit_needs'), public_routes: data.has('public_routes'),
        })} />
      {recommend.isError && <LoadFailure error={recommend.error} message={t('authorization.recommendError')}
        retry={() => recommend.mutate(recommend.variables)} />}
      {recommend.data && <Stack gap={2}>
        <h3>{t('authorization.suggested', { model: t(`authorization.model_${recommend.data.model}`) })}</h3>
        <ul>{recommend.data.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        <dl>{models.map(model => <div key={model}><dt>{t(`authorization.model_${model}`)}</dt>
          <dd>{t('authorization.score', { score: recommend.data.scores[model] ?? 0 })}</dd></div>)}</dl>
        {recommend.data.cautions.length > 0 && <ul>{recommend.data.cautions.map(caution => <li key={caution}>{caution}</li>)}</ul>}
        {recommend.data.alternatives.length > 0 && <details><summary>{t('authorization.alternatives')}</summary>
          <ul>{recommend.data.alternatives.map(alternative => <li key={alternative}>{models.some(option => option === alternative) ?
            t(`authorization.model_${alternative}`) : alternative}</li>)}</ul></details>}
        {editable && <Row><Button variant="primary" disabled={busy || recommend.data.model === settings.model}
          onClick={() => { if (recommend.data) apply(recommend.data.model) }}>
          {t('authorization.useModel', { model: t(`authorization.model_${recommend.data.model}`) })}</Button></Row>}
      </Stack>}
    </SettingsSection>
    <SettingsSection title={t('authorization.savedSettings')}>
      <p>{t('authorization.currentModel', { model: t(`authorization.model_${settings.model}`) })}</p>
      <p>{t('compliance.version', { version: settings.version })}</p>
      {settings.updated_at && <p>{t('compliance.updated', { date: new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(settings.updated_at)) })}</p>}
      <details><summary>{t('authorization.fieldAccess')}</summary><AccessFieldRules {...props} onSave={setFields} /></details>
      <EffectiveAccess id={id} />
      <Row><SecureLink id={id} section="permissions" label={t('authorization.buildMatrix')} />
        <SecureLink id={id} section="history" label={t('authorization.history')} /></Row>
      <p className="v2-muted">{t('authorization.platformAccess')}</p>
    </SettingsSection>
  </Stack>
}

function EffectiveAccess({ id }: { id: string }) {
  const t = useT()
  const [expanded, setExpanded] = useState(false)
  const { search, page: setPage } = useSecureSearch()
  const query = useQuery({ ...matrixOptions(id), enabled: expanded })
  const cells = query.data?.cells ?? []
  const pages = Math.ceil(cells.length / 20)
  const page = Math.min(search.page ?? 1, Math.max(1, pages))
  return <details onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary>{t('authorization.effectiveAccess')}</summary>
    {expanded && (query.isPending ? <SecureLoading label={t('common.loading')} /> : query.isError ?
      <LoadFailure error={query.error} message={t('authorization.loadError')} retry={() => void query.refetch()} /> :
      <Stack gap={2}>
        {cells.length ? <Table label={t('authorization.effectiveAccess')} columns={['entity', 'layer', 'role', 'slot', 'accessValue'].map(key =>
          ({ id: key, label: t(`authorization.${key}`) }))} rows={cells.slice((page - 1) * 20, page * 20).map((row, index) => ({
            id: String(index), cells: [row.entity, row.layer, row.role, row.target, row.value],
          }))} /> : <p>{t('authorization.none')}</p>}
        {pages > 1 && <Pagination label={t('authorization.effectiveAccess')} page={page} pages={pages} onChange={setPage} />}
      </Stack>)}
  </details>
}
