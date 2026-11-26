import { useMutation, useQuery } from '@tanstack/react-query'
import { useReducer } from 'react'
import type { AccessDiff, AccessDiffRequest, AccessLayer, PermissionRule } from '../../../api/types'
import { editableRoles, fieldAccessOf, fieldNames, fieldRolesOf, groupTable, permissionsOf, setFieldRoles, withEdits } from '../../../shell/access/accessLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Checkbox, EmptyState, Grid, Row, Stack, Table, Tabs } from '../../ui'
import { buildError, buildQueries, record, replaceAccess, reviewAccess, useBuildWrite } from './api/build'
import { BuildFailure, BuildLoad, BuildPage, ChoiceGroup, choices, Pick, SectionLink, WeakeningDetails, WriteAccess } from './components/shared'
import type { BuildScreenProps } from './components/shared'
import { useBuildRoute } from './routes'
import { accessDraft } from './state/accessDraft'

const layers = ['object', 'field', 'row'] as const
type Review = AccessDiff & { unprotected_entities?: string[]; renames?: { kind: string; entity: string; before: string; after: string }[] }

export default function PermissionsScreen({ access }: BuildScreenProps) {
  const { projectId } = useBuildRoute()
  return <BuildPage screen="permissions" desktop><Permissions key={projectId} access={access} /></BuildPage>
}

function Permissions({ access }: BuildScreenProps) {
  const t = useT()
  const { projectId, search, update } = useBuildRoute()
  const data = useQuery(buildQueries.access(projectId))
  const [draft, dispatch] = useReducer(accessDraft, null)
  const review = useMutation({ mutationFn: (edits: AccessDiffRequest): Promise<Review> => reviewAccess(projectId, edits) })
  const apply = useBuildWrite(projectId, replaceAccess)
  const { matrix, spec, version, seq } = data.data ?? {}
  const conflict = Boolean(draft && (draft.version !== version || draft.seq !== seq))
  const disabled = !access.writable || conflict || review.isPending || apply.isPending
  const layer = layers.find(value => value === search.tab) ?? 'object'
  const entity = matrix?.entities.find(value => value === search.entity) ?? matrix?.entities[0]
  const permissions = draft?.edits.permissions ?? (spec ? permissionsOf(spec) : [])
  const fields = draft?.edits.field_access ?? (spec ? fieldAccessOf(spec) : [])
  const roles = matrix ? choices(editableRoles(matrix)) : []
  const auth = record(spec?.auth)
  const model = record(spec?.authorization).model ?? 'rbac'
  const publicRole = (role: string) => role === '(public)' ? t('buildSpec.permissions.public') : role
  const reload = async () => {
    const result = await data.refetch()
    if (result.isSuccess) reset()
  }
  function reset() {
    dispatch({ type: 'reset' })
    review.reset()
    apply.reset()
  }
  function change(edits: AccessDiffRequest) {
    if (version === undefined || seq === undefined || disabled) return
    dispatch({ type: 'edit', version, seq, edits })
    review.reset()
    apply.reset()
  }
  async function save(confirm: boolean) {
    if (!spec || !draft || disabled) return
    await apply.mutateAsync({ spec: withEdits(spec, draft.edits), version: draft.version, seq: draft.seq, confirm })
    dispatch({ type: 'reset' })
    review.reset()
  }

  function panel(id: AccessLayer) {
    if (!matrix || !entity) return null
    const table = groupTable(matrix, id, entity)
    const targets = id === 'field' ? fieldNames(matrix, entity) : table.targets
    const target = targets.find(value => value === search.target) ?? targets[0]
    const title = t('buildSpec.permissions.matrix', { layer: t('buildSpec.layers.' + id), entity })
    const cell = (value?: string) => {
      if (value?.startsWith('policy:')) return t('buildSpec.permissions.policy')
      return value === 'yes' || value === 'no' || value === 'conditional' ? t('buildSpec.permissions.' + value) : value ?? t('buildSpec.none')
    }
    const slot = permissions.find(rule => rule.entity === entity && rule.operation === target)
    const setSlot = (patch: Partial<PermissionRule>) => {
      if (!target) return
      const next = { entity, operation: target, roles: [], ...slot, ...patch }
      change({ permissions: [...permissions.filter(rule => rule.entity !== entity || rule.operation !== target), next] })
    }
    const editable = Boolean(auth.enabled) && (id === 'field' || model === 'rbac')
    const fieldRule = target ? fieldRolesOf(fields, entity, target) : undefined
    return <Stack>
      <Pick label={t('buildSpec.entity')} options={choices(matrix.entities)} value={entity} onChange={entity => update({ entity, target: undefined })} />
      {table.targets.length > 0 ? <Table label={title}
        columns={[{ id: 'target', label: t('buildSpec.permissions.target') }, ...table.roles.map(role => ({ id: role, label: publicRole(role) }))]}
        rows={table.targets.map(target => ({ id: target, cells: [target, ...table.roles.map(role => cell(table.values[role]?.[target]))] }))}
      /> : <p>{t('buildSpec.permissions.layerEmpty', { entity })}</p>}
      {id === 'row' && <p className="v2-muted">{t('buildSpec.permissions.rowHint')}</p>}
      {id === 'row' && <SectionLink projectId={projectId} section="access">{t('buildSpec.permissions.openAuthz')}</SectionLink>}
      {id !== 'row' && !editable && <Alert>{t(!auth.enabled ? 'buildSpec.permissions.enable' : 'buildSpec.permissions.policyOnly')}</Alert>}
      {id !== 'row' && !editable && <SectionLink projectId={projectId} section={auth.enabled ? 'access' : 'auth'}>
        {t(auth.enabled ? 'buildSpec.permissions.openAuthz' : 'buildSpec.permissions.openAuth')}
      </SectionLink>}
      {id !== 'row' && editable && target && <SettingsSection title={t('buildSpec.permissions.edit')}>
        <Pick label={t(id === 'field' ? 'buildSpec.field' : 'buildSpec.permissions.operation')} options={choices(targets)} value={target} onChange={target => update({ target })} disabled={disabled} />
        {id === 'object' && <>
          <p className="v2-muted">{t('buildSpec.permissions.objectHint')}</p>
          <ChoiceGroup label={t('buildSpec.permissions.allowed', { operation: target })} options={roles}
            selected={slot?.roles ?? []} onChange={roles => setSlot({ roles })} disabled={disabled} />
          {!(slot?.roles.length) && <Row><Badge tone="warning">{t('buildSpec.permissions.public')}</Badge></Row>}
        </>}
        {id === 'field' && fieldRule && <Grid>{(['read_roles', 'write_roles'] as const).map(key => {
          const label = t('buildSpec.permissions.' + key)
          const set = (value: string[] | null) => change({ field_access: setFieldRoles(fields, entity, target, { ...fieldRule, [key]: value }) })
          return <Stack key={key}>
            <Checkbox label={t('buildSpec.permissions.inherit', { label })} checked={fieldRule[key] === null} disabled={disabled}
              onChange={event => set(event.target.checked ? null : [])} />
            <ChoiceGroup label={label} options={roles} selected={fieldRule[key] ?? []} onChange={set} disabled={disabled || fieldRule[key] === null} />
          </Stack>
        })}</Grid>}
      </SettingsSection>}
    </Stack>
  }

  const result = review.data
  const mustConfirm = Boolean(result?.weakens || buildError(apply.error)?.code === 'access_weakened')
  return <BuildLoad reads={[data]}>
    <WriteAccess access={access} />
    {conflict && <ConflictBanner onReload={() => void reload()} />}
    <BuildFailure error={review.error} reload={() => void reload()} />
    <BuildFailure error={apply.error} reload={() => void reload()} />
    {buildError(apply.error)?.code === 'access_weakened' && <WeakeningDetails error={apply.error} />}
    {apply.isSuccess && <Alert tone="success">{t('buildSpec.permissions.applied')}</Alert>}
    {!entity ? <EmptyState title={t('buildSpec.permissions.empty')} description={t('buildSpec.permissions.emptyDetail')}
      action={<SectionLink projectId={projectId} section="model">{t('buildSpec.openModel')}</SectionLink>} /> :
      <Tabs label={t('buildSpec.permissions.layers')} value={layer} onChange={tab => update({ tab, target: undefined })}
        items={layers.map(id => ({ id, label: t('buildSpec.layers.' + id), content: id === layer ? panel(id) : null }))} />}
    {draft && <Row>
      <Button disabled={apply.isPending} onClick={reset}>{t('common.discard')}</Button>
      <Button variant="primary" disabled={disabled} onClick={() => review.mutate(draft.edits)}>{t('buildSpec.reviewAccess')}</Button>
    </Row>}
    {result && draft && !conflict && <SettingsSection title={t('buildSpec.reviewAccess')}>
      {Object.entries(result.roles_gaining).map(([role, targets]) => <Alert tone="warning" key={role}>
        {t('buildSpec.permissions.gain', { role: publicRole(role), targets: targets.join(', ') })}
      </Alert>)}
      {Object.entries(result.roles_losing).map(([role, targets]) => <p key={role}>
        {t('buildSpec.permissions.lose', { role: publicRole(role), targets: targets.join(', ') })}
      </p>)}
      {result.unprotected_entities?.length ? <Alert tone="warning">{t('buildSpec.permissions.unprotected', { entities: result.unprotected_entities.join(', ') })}</Alert> : null}
      {result.renames?.map((rename, index) => <p key={index}>{t('buildSpec.permissions.rename', { ...rename })}</p>)}
      {!result.changes.length && <p>{t('buildSpec.permissions.noChanges')}</p>}
      {result.changes.length > 0 && <details><summary className="v2-status-disclosure">{t('buildSpec.permissions.diffDetails', { count: result.changes.length })}</summary>
        <ul>{result.changes.map((change, index) => <li key={index}>{t('buildSpec.permissions.cell', {
          ...change, role: publicRole(change.role), layer: t('buildSpec.layers.' + change.layer),
          before: change.before ?? t('buildSpec.none'), after: change.after ?? t('buildSpec.none'),
        })}</li>)}</ul>
      </details>}
      <Row>{mustConfirm ? <ConfirmDestructive title={t('buildSpec.weakeningTitle')} description={t('buildSpec.weakening')}
        action={t('buildSpec.confirmAccess')} trigger={<Button variant="danger" disabled={disabled}>{t('buildSpec.confirmAccess')}</Button>}
        onConfirm={() => save(true)} /> : <Button variant="primary" disabled={disabled} onClick={() => { void save(false).catch(() => undefined) }}>{t('buildSpec.permissions.apply')}</Button>}</Row>
    </SettingsSection>}
  </BuildLoad>
}
