import { useReducer, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, SettingsSection } from '../../patterns'
import { Badge, Button, Dialog, EmptyState, Grid, Pagination, Row, Stack, Table } from '../../ui'
import { AccessDiffTable, type AccessEditorProps } from './AccessModel'
import { controlsApi, permissionsOptions, weakeningDetails, type AuthOperation, type Entity, type PermissionEntry, type RowRule } from './api/controls'
import { codeOf, secureKeys } from './api/security'
import { operations, permissionReducer, type PermissionChanges } from './state/access'
import { checkField, LoadFailure, pickField, readText, SecureLink, SecureLoading, textField, useSecureSearch, WriteNotice } from './SecureForm'

const rules = ['owner', 'role_scoped', 'tenant', 'custom_filter'] as const
const pageSize = 8
type Slot = { entity: Entity; operation: AuthOperation }
const slotKey = (id: string, operation: string) => id + ':' + operation

class PermissionWriteFailure extends Error {
  readonly step: string
  constructor(step: string, cause: unknown) {
    super('Permission write failed', { cause })
    this.step = step
  }
}

export function AccessPermissions({ id, roles, spec, editable }: AccessEditorProps) {
  const t = useT()
  const queryClient = useQueryClient()
  const query = useQuery(permissionsOptions(id))
  const [draft, dispatch] = useReducer(permissionReducer, {})
  const [selected, setSelected] = useState<Slot>()
  const [review, setReview] = useState(false)
  const [rowRule, setRowRule] = useState<RowRule | null>(null)
  const { search, page: setPage } = useSecureSearch()
  const data = query.data
  const saved = new Map(data?.permissions.map(item => [slotKey(item.entity_id, item.operation), item]))
  const entities = new Map(data?.entities.map(entity => [entity.id, entity.name]))
  const preview = useMutation({
    mutationFn: async (changes: PermissionChanges) => {
      const proposed = new Map<string, PermissionEntry>(saved)
      for (const [key, change] of Object.entries(changes)) {
        if (change.value) proposed.set(key, change.value)
        else proposed.delete(key)
      }
      return controlsApi.diffAccess(id, { permissions:
        [...proposed.values()].flatMap(item => {
          const entity = entities.get(item.entity_id)
          return entity ? [{ entity, operation: item.operation, roles: item.roles ?? [], row_rule: item.row_rule,
            custom_filter_field: item.custom_filter_field, custom_filter_value: item.custom_filter_value }] : []
        }),
      })
    },
  })
  const write = useMutation({
    mutationFn: async ({ changes, confirmStep }: { changes: PermissionChanges; confirmStep?: string }) => {
      async function apply(step: string, send: (confirm: boolean) => Promise<unknown>) {
        try { await send(confirmStep === step) } catch (error) { throw new PermissionWriteFailure(step, error) }
      }
      const entries = Object.entries(changes)
      const upserts = entries.flatMap(([key, change]) => change.value ? [[key, change.value] as const] : [])
      for (let offset = 0; offset < upserts.length; offset += 500) {
        const batch = upserts.slice(offset, offset + 500)
        await apply(batch[0][0], confirm => controlsApi.bulkUpsertPermissions(id, batch.map(([, value]) => value), confirm))
        dispatch({ type: 'applied', keys: batch.map(([key]) => key) })
      }
      for (const [key, change] of entries) {
        const current = change.current
        if (!change.value && current) await apply(key, confirm => controlsApi.deletePermission(current.id, confirm))
        if (!change.value) dispatch({ type: 'applied', keys: [key] })
      }
    },
    onSettled: async () => { await queryClient.invalidateQueries({ queryKey: secureKeys.project(id) }) },
  })
  if (query.isPending) return <SecureLoading label={t('common.loading')} />
  if (!data || query.isError) return <LoadFailure error={query.error} message={t('authorization.permissionLoadError')} retry={() => void query.refetch()} />
  const failure = write.error instanceof PermissionWriteFailure ? write.error : undefined
  const writeError = failure ? failure.cause : write.error
  const confirmStep = codeOf(writeError) === 'access_weakened' ? failure?.step : undefined
  const opLabel = (operation: AuthOperation) => t(`authorization.op_${operation}`)
  const pages = Math.ceil(data.entities.length / pageSize)
  const page = Math.min(search.page ?? 1, Math.max(1, pages))
  const itemKey = selected && slotKey(selected.entity.id, selected.operation)
  const current = itemKey ? (draft[itemKey] ? draft[itemKey].value : saved.get(itemKey)) : undefined
  const customFields = spec.entities.find(item => item.name === selected?.entity.name)?.fields
    .filter(field => ['string', 'enum', 'integer', 'boolean'].includes(field.type)) ?? []
  const rulesAvailable = rules.filter(rule => rule !== 'tenant' || spec.auth?.multi_tenant || rule === rowRule)
    .filter(rule => rule !== 'role_scoped' || roles.some(item => item.name === 'admin') || rule === rowRule)
  const roleChoices = [...roles.map(item => ({ name: item.name, label: item.label })),
    ...(current?.roles ?? []).filter(name => !roles.some(item => item.name === name)).map(name => ({ name, label: name }))]
  const modal = selected ? [
    ...roleChoices.map(item => checkField(`role.${item.name}`, item.label, current?.roles?.includes(item.name) ?? false)),
    pickField('row_rule', t('authorization.rowRule'), rowRule ?? '_none',
      [{ value: '_none', label: t('authorization.none') }, ...rulesAvailable.map(value => ({ value, label: t(`authorization.rule_${value}`) }))],
      { change: value => setRowRule(value === '_none' ? null : value as RowRule) }),
    ...rowRule === 'custom_filter' ? [
      pickField('custom_filter_field', t('authorization.filterField'), current?.custom_filter_field ?? '',
        customFields.map(item => ({ value: item.name, label: item.name })), { required: true, placeholder: t('authorization.choose') }),
      textField('custom_filter_value', t('authorization.filterValue'), current?.custom_filter_value, { required: true, max: 500,
        validateWith(value, values) {
          const field = customFields.find(item => item.name === readText(values, 'custom_filter_field'))
          const valid = field?.type === 'enum' ? field.enum_values?.includes(value) : field?.type === 'integer' ?
            /^[+-]?\d+$/.test(value) : field?.type === 'boolean' ? /^(true|false)$/i.test(value) : true
          return valid ? undefined : { key: 'validation.accessFilterValue' }
        } }),
    ] : [],
  ] : []
  function openSlot(entity: Entity, operation: AuthOperation) {
    const key = slotKey(entity.id, operation)
    setRowRule((draft[key] ? draft[key].value : saved.get(key))?.row_rule ?? null)
    setSelected({ entity, operation })
  }
  function stage(value: PermissionEntry | null) {
    if (!itemKey) return
    const original = saved.get(itemKey)
    if (value || original) dispatch({ type: 'stage', key: itemKey, change: { current: original, value } })
    else dispatch({ type: 'applied', keys: [itemKey] })
    setSelected(undefined)
  }
  const reload = () => { write.reset(); setReview(false); void query.refetch() }
  const hasDraft = Object.keys(draft).length > 0
  const canPreview = saved.size + Object.entries(draft).filter(([key, change]) => !saved.has(key) && change.value).length <= 1000
  return <SettingsSection title={t('authorization.tab_permissions')} description={t('authorization.permissionsHelp')}>
    <WriteNotice error={review ? null : writeError} message={t('authorization.permissionSaveError')}
      saved={write.isSuccess ? t('common.saved') : undefined} reload={reload} />
    {editable && hasDraft && <Row>
      <Button variant="primary" disabled={write.isPending || preview.isPending} onClick={() => {
        write.reset(); preview.reset()
        if (canPreview) preview.mutate(draft, { onSuccess: () => setReview(true) })
        else setReview(true)
      }}>{t('authorization.saveAll')}</Button>
      <Button disabled={write.isPending || preview.isPending} onClick={() => dispatch({ type: 'reset' })}>{t('common.discard')}</Button>
    </Row>}
    {preview.isError && <LoadFailure error={preview.error} message={t('authorization.diffError')} retry={() =>
      preview.mutate(draft, { onSuccess: () => setReview(true) })} />}
    {data.entities.length ? <>
      <Table label={t('authorization.tab_permissions')} columns={[{ id: 'entity', label: t('authorization.entity') },
        ...operations.map(id => ({ id, label: opLabel(id) }))]} rows={data.entities.slice((page - 1) * pageSize, page * pageSize).map(entity => ({
          id: entity.id, cells: [entity.name, ...operations.map(operation => {
            const key = slotKey(entity.id, operation)
            const enabled = entity.options.operations.includes(operation)
            const entry = draft[key] ? draft[key].value : saved.get(key)
            if (!enabled) return <Badge>{t('authorization.operationDisabled')}</Badge>
            const label = entry ? entry.roles?.length ? entry.roles.join(', ') : t('authorization.public') : t('authorization.publicInherited')
            const content = <Stack gap={1}><span>{label}</span>{entry?.row_rule && <Badge>{t(`authorization.rule_${entry.row_rule}`)}</Badge>}</Stack>
            return editable ? <Button disabled={write.isPending || preview.isPending} onClick={() => openSlot(entity, operation)} aria-label={t('authorization.editSlot', {
              entity: entity.name, operation: opLabel(operation), access: label,
            })}>{content}</Button> : content
          })],
        }))} />
      {pages > 1 && <Pagination page={page} pages={pages} onChange={setPage} label={t('authorization.tab_permissions')} />}
    </> : <EmptyState title={t('authorization.noEntities')} action={<SecureLink id={id} section="model" label={t('authorization.dataModel')} />} />}
    {selected && <Dialog open onOpenChange={open => { if (!open) setSelected(undefined) }}
      title={t('authorization.slotName', { entity: selected.entity.name, operation: opLabel(selected.operation) })}
      description={t('authorization.permissionsHelp')}>
      <Form fields={modal} submitLabel={t('common.save')} actions={current && <ConfirmDestructive
        trigger={<Button variant="danger">{t('authorization.clearRule')}</Button>} title={t('authorization.clearRule')}
        description={t('authorization.clearRuleHelp')} action={t('authorization.clearRule')} onConfirm={() => stage(null)} />}
        layout={controls => <Grid>{modal.map(field => controls[field.name])}</Grid>}
        onSubmit={data => {
          const roles = roleChoices.filter(item => data.has(`role.${item.name}`)).map(item => item.name)
          stage(roles.length || rowRule ? { entity_id: selected.entity.id, operation: selected.operation, row_rule: rowRule, roles,
            custom_filter_field: rowRule === 'custom_filter' ? readText(data, 'custom_filter_field') : null,
            custom_filter_value: rowRule === 'custom_filter' ? readText(data, 'custom_filter_value') : null } : null)
        }} />
      {rowRule === 'tenant' && <p>{t(spec.auth?.provider === 'keycloak' ? 'authorization.keycloakTenant' : 'authorization.tenantHelp')}</p>}
    </Dialog>}
    {review && <ConfirmDestructive open onOpenChange={setReview}
      title={t(preview.data?.weakens || confirmStep ? 'authorization.weaken' : 'authorization.reviewDiff')}
      description={t('authorization.weakenHelp')} action={t('authorization.saveAnyway')}
      pending={write.isPending}
      onConfirm={() => write.mutateAsync({ changes: draft, confirmStep })}>
      {preview.data && <AccessDiffTable diff={preview.data} />}
      {!canPreview && <p>{t('authorization.previewLimit')}</p>}
      <ul>{weakeningDetails(writeError).map((item, index) => <li key={index}>{t('authorization.gaining', item)}</li>)}</ul>
      {Boolean(writeError) && !confirmStep && <WriteNotice error={writeError} message={t('authorization.permissionSaveError')} reload={reload} />}
    </ConfirmDestructive>}
  </SettingsSection>
}
