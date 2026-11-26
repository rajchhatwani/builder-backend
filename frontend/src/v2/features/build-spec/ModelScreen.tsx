import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { Entity, Field, Relation } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, DataTable, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, EmptyState, Row, Stack, Table, Tabs } from '../../ui'
import { buildError, buildQueries, catalog, useBuildWrite, writeModel } from './api/build'
import type { ModelWrite } from './api/build'
import { DiagramAdapter } from './components/DiagramAdapter'
import { EntityForm, FieldForm, operationNames, RelationForm } from './components/modelForms'
import { BuildFailure, BuildLoad, BuildPage, IssueList, Pick, SectionLink, useBuildDate, WeakeningDetails, WriteAccess } from './components/shared'
import type { BuildScreenProps } from './components/shared'
import { useBuildRoute } from './routes'

const tabs = ['fields', 'api', 'relations', 'diagram'] as const
type ModelDialog =
  | { kind: 'entity'; entity?: Entity }
  | { kind: 'field'; entity: Entity; field?: Field }
  | { kind: 'relation'; relation?: Relation }

const methods = ['GET', 'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']

export default function ModelScreen({ access }: BuildScreenProps) {
  const { projectId } = useBuildRoute()
  return <BuildPage screen="model" desktop><Model key={projectId} access={access} /></BuildPage>
}

function Model({ access }: BuildScreenProps) {
  const t = useT()
  const date = useBuildDate()
  const { projectId, search, update } = useBuildRoute()
  const entitiesRead = useQuery(buildQueries.entities(projectId))
  const relations = useQuery(buildQueries.relations(projectId))
  const spec = useQuery(buildQueries.spec(projectId))
  const status = useQuery(buildQueries.status(projectId))
  const write = useBuildWrite(projectId, writeModel)
  const [dialog, setDialog] = useState<ModelDialog>()
  const [weakening, setWeakening] = useState<ModelWrite>()
  const [showWeakening, setShowWeakening] = useState(false)
  const entities = entitiesRead.data?.items ?? []
  const entity = entities.find(item => item.name === search.entity)
  const related = (relations.data ?? []).filter(item => entity?.id === item.from_entity_id || entity?.id === item.to_entity_id)
  const fieldsRead = useQuery({ ...buildQueries.fields(projectId, entity?.id ?? ''), enabled: Boolean(entity) })
  const fields = fieldsRead.data?.items ?? []
  const tab = tabs.find(value => value === search.tab) ?? 'fields'
  const disabled = !access.writable || write.isPending
  const matches = entities.filter(item => !search.q || [item.name, item.plural_path].some(value => value.toLowerCase().includes(search.q!.toLowerCase())))
  const entityCounts = new Map(catalog(spec.data ?? {}).map(item => [item.name, item.fields.length]))
  const problems = status.data?.issues.filter(issue => /^(entities|fields|relations)(?:\.|\[|$)/.test(issue.path)) ?? []
  const entityName = (id: string) => entities.find(item => item.id === id)?.name ?? id
  const newEntity = () => { write.reset(); setDialog({ kind: 'entity' }) }
  const newRelation = () => { write.reset(); setDialog({ kind: 'relation' }) }
  const reload = () => {
    void entitiesRead.refetch()
    void relations.refetch()
    void spec.refetch()
    void status.refetch()
    if (entity) void fieldsRead.refetch()
    write.reset()
  }
  async function save(command: ModelWrite) {
    if (!access.writable) return
    try {
      await write.mutateAsync(command)
      setDialog(undefined)
      setWeakening(undefined)
      if (command.kind === 'addEntity') update({ entity: command.data.name, tab: undefined, q: undefined })
      if (command.kind === 'entity' && command.data.name !== command.entity.name) update({ entity: command.data.name })
      if (command.kind === 'removeEntity') update({ entity: undefined, tab: undefined })
    } catch (error) {
      if (!command.confirm && buildError(error)?.code === 'access_weakened') {
        setDialog(undefined)
        setWeakening(command)
        return
      }
      throw error
    }
  }

  const remove = (name: string, input: ModelWrite) => <ConfirmDestructive
    title={t('buildSpec.model.removeNamed', { name })} action={t('buildSpec.remove')} description={t('buildSpec.model.removeDetail', { name })}
    trigger={<Button variant="danger" disabled={disabled}>{t('buildSpec.remove')}</Button>} onConfirm={() => save(input)} />
  const fkFields = related.filter(relation => relation.to_entity_id === entity?.id && relation.kind !== 'many_to_many')
    .map(relation => relation.to_name + '_id')
  const automatic = ['id', 'created_at', 'updated_at', ...(entity?.options.soft_delete ? ['deleted_at'] : []), ...fkFields]

  function entitySection() {
    if (!entity) return null
    const targetFields = ['name', 'type', 'required', 'unique', 'indexed', 'details']
    const details = (field: Field) => [
      field.max_length && t('buildSpec.model.maxChars', { count: field.max_length }),
      field.min_value !== null && t('buildSpec.model.minimum', { amount: field.min_value }),
      field.max_value !== null && t('buildSpec.model.maximum', { amount: field.max_value }),
      field.enum_values?.join(', '),
      field.default !== null && field.default !== undefined && t('buildSpec.model.defaultValue', { value: JSON.stringify(field.default) }),
    ].filter(Boolean).join(' · ')
    const sortBy = (id: string) => update({ sort: id, technical: search.sort === id && !search.technical || undefined })
    const sortColumns = targetFields.map(id => ({
      id, label: t('buildSpec.model.' + id),
      sort: search.sort === id ? search.technical ? 'descending' as const : 'ascending' as const : undefined,
      heading: <Button variant="ghost" onClick={() => sortBy(id)}>{t('buildSpec.model.' + id)}</Button>,
    }))
    const sorted = [...fields]
    const key = search.sort
    if (key && targetFields.includes(key)) {
      const value = (field: Field) => key === 'details' ? details(field) : String(field[key as keyof Field])
      sorted.sort((a, b) => value(a).localeCompare(value(b), undefined, { numeric: true }) * (search.technical ? -1 : 1))
    }
    const options = entity.options
    const contents = {
      fields: <BuildLoad reads={[fieldsRead]}><Stack className="v2-data-table">
        <Row className="v2-spread"><Badge>{t('buildSpec.model.fieldCount', { count: fields.length })}</Badge>
          <Button variant="primary" disabled={disabled || fields.length >= 100} onClick={() => { write.reset(); setDialog({ kind: 'field', entity }) }}>{t('buildSpec.model.addField')}</Button>
        </Row>
        <Row className="v2-mobile-sort">
          <Pick label={t('buildSpec.model.sortFields')} value={key ? key + (search.technical ? '-desc' : '-asc') : undefined}
            onChange={value => { const [sort, direction] = value.split('-'); update({ sort, technical: direction === 'desc' || undefined }) }}
            options={targetFields.flatMap(id => ['asc', 'desc'].map(direction => ({
              value: id + '-' + direction, label: t('buildSpec.model.sort_' + direction, { field: t('buildSpec.model.' + id) }),
            })))} />
        </Row>
        <Table label={t('buildSpec.model.fields')} columns={[...sortColumns, { id: 'actions', label: t('buildSpec.actions') }]} rows={[
          ...automatic.map(name => ({
            id: 'derived-' + name, cells: [<code key="name">{name}</code>, t('buildSpec.fieldTypes.' + (name === 'id' || fkFields.includes(name) ? 'uuid' : 'datetime')),
              null, null, null, t(fkFields.includes(name) ? 'buildSpec.model.derived' : 'buildSpec.model.automatic'), null],
          })),
          ...sorted.map(field => ({
            id: field.id, cells: [<code key="name">{field.name}</code>, t('buildSpec.fieldTypes.' + field.type),
              ...[field.required, field.unique, field.indexed].map(on => on ? t('buildSpec.yes') : t('buildSpec.none')), details(field),
              <Row key="actions">
                <Button disabled={disabled} onClick={() => { write.reset(); setDialog({ kind: 'field', entity, field }) }}>{t('buildSpec.edit')}</Button>
                {remove(field.name, { kind: 'removeField', entity, field })}
              </Row>],
          })),
        ]} />
      </Stack></BuildLoad>,
      api: <BuildLoad reads={[fieldsRead]}>
        <SettingsSection title={t('buildSpec.model.generated')}>
          <Table label={t('buildSpec.model.generated')} columns={['route', 'operation', 'status'].map(id => ({ id, label: t('buildSpec.model.' + id) }))}
            rows={operationNames.map((op, index) => ({ id: op, cells: [
              <code key="route">{t('buildSpec.model.endpoint', { method: methods[index], path: entity.plural_path, item: op === 'list' || op === 'create' ? '' : '/{item_id}' })}</code>,
              <Stack key="operation" gap={1}>{t('buildSpec.operations.' + op)}{op === 'list' && <span className="v2-muted">
                {['limit', 'offset', ...(options.sortable.length ? ['sort'] : []), ...(options.searchable.length ? ['q'] : []), ...options.filterable].join(', ')}
              </span>}</Stack>,
              <Badge key="status" tone={options.operations.includes(op) ? 'success' : 'neutral'}>{t(options.operations.includes(op) ? 'buildSpec.on' : 'buildSpec.off')}</Badge>,
            ] }))} />
        </SettingsSection>
        <SettingsSection title={t('buildSpec.model.options')}>
          <EntityForm entity={entity} entities={entities} fields={fields} derived={fkFields} pending={write.isPending}
            error={dialog ? null : write.error} disabled={disabled} optionsOnly onSave={data => void save({ kind: 'entity', entity, data }).catch(() => undefined)} />
        </SettingsSection>
      </BuildLoad>,
      relations: <SettingsSection title={t('buildSpec.model.relationsOf', { entity: entity.name })}>
        <Row><Button disabled={disabled || entities.length < 2} onClick={newRelation}>{t('buildSpec.model.addRelation')}</Button></Row>
        {!related.length && <p>{t('buildSpec.model.noRelations')}</p>}
        {related.map(relation => <Row key={relation.id} className="v2-spread">
          <Stack gap={1}><strong>{t('buildSpec.model.relationSummary', { from: entityName(relation.from_entity_id), kind: t('buildSpec.model.' + relation.kind), to: entityName(relation.to_entity_id) })}</strong>
            <span className="v2-muted">{t('buildSpec.model.relationDetail', { from: relation.from_name, to: relation.to_name, action: t('buildSpec.model.' + relation.on_delete) })}</span></Stack>
          <Row><Button disabled={disabled} onClick={() => { write.reset(); setDialog({ kind: 'relation', relation }) }}>{t('buildSpec.edit')}</Button>
            {remove(relation.from_name, { kind: 'removeRelation', relation })}</Row>
        </Row>)}
      </SettingsSection>,
      diagram: <Stack><DiagramAdapter label={t('buildSpec.model.diagram')} nodes={[...new Set([entity.id, ...related.flatMap(item => [item.from_entity_id, item.to_entity_id])])]
        .map(id => ({ id, label: entityName(id), initial: id === entity.id }))}
        edges={related.map(item => ({ id: item.id, source: item.from_entity_id, target: item.to_entity_id, label: item.from_name }))} />
        <SectionLink section="diagrams" projectId={projectId}>{t('buildSpec.model.fullDiagram')}</SectionLink></Stack>,
    }
    return <>
      <Row><Button variant="ghost" onClick={() => update({ entity: undefined, tab: undefined, sort: undefined, technical: undefined })}>{t('buildSpec.model.title')}</Button></Row>
      <SettingsSection title={entity.name} description={t('buildSpec.model.tablePath', { table: entity.table_name, path: entity.plural_path })}>
        <Row><Button disabled={disabled} onClick={() => { write.reset(); setDialog({ kind: 'entity', entity }) }}>{t('buildSpec.model.rename')}</Button>
          {remove(entity.name, { kind: 'removeEntity', entity })}</Row>
        <Tabs label={t('buildSpec.model.entityDetails')} value={tab} onChange={tab => update({ tab, sort: undefined, technical: undefined })}
          items={tabs.map(id => ({ id, label: t('buildSpec.model.' + id), content: id === tab ? <Stack>{contents[id]}</Stack> : null }))} />
      </SettingsSection>
    </>
  }

  return <BuildLoad reads={[entitiesRead, relations, spec]}>
    <WriteAccess access={access} />
    {!dialog && <BuildFailure error={write.error} reload={reload} onWeakening={weakening && <Button variant="danger" onClick={() => setShowWeakening(true)}>{t('buildSpec.reviewAccess')}</Button>} />}
    {weakening && <WeakeningDetails error={write.error} />}
    <ConfirmDestructive open={showWeakening} onOpenChange={setShowWeakening} title={t('buildSpec.weakeningTitle')}
      description={t('buildSpec.weakening')} action={t('buildSpec.confirmAccess')}
      onConfirm={() => weakening ? save({ ...weakening, confirm: true }) : undefined} />
    {problems.length > 0 && <Alert tone="warning"><IssueList issues={problems} /></Alert>}
    {write.isSuccess && <Alert tone="success"
      action={<SectionLink projectId={projectId} section="specdiff">{t('buildSpec.model.reviewMigration')}</SectionLink>}>
      {t('common.saved')}
    </Alert>}
    {entity ? entitySection() : <>
      <Row className="v2-spread">
        <SectionLink projectId={projectId} section="diagrams">{t('buildSpec.model.diagram')}</SectionLink>
        <Row><Button disabled={disabled || entities.length < 2} onClick={newRelation}>{t('buildSpec.model.addRelation')}</Button>
          <Button variant="primary" disabled={disabled || entities.length >= 100} onClick={newEntity}>{t('buildSpec.model.add')}</Button></Row>
      </Row>
      {!entities.length ? <EmptyState title={t('buildSpec.model.empty')} description={t('buildSpec.model.emptyDetail')}
        action={<Button disabled={disabled} onClick={newEntity}>{t('buildSpec.model.add')}</Button>} /> : <DataTable
        label={t('buildSpec.model.title')} state={{ filter: search.q ?? '', page: 1 }} pages={1}
        onChange={next => update({ q: next.filter || undefined }, true)}
        columns={['entity', 'api', 'fields', 'relations', 'status', 'updated'].map(id => ({ id, label: t('buildSpec.model.' + id) }))}
        rows={matches.map(item => ({
          id: item.id, cells: [
            <Stack key="entity" gap={1}><Button variant="ghost" onClick={() => update({ entity: item.name, tab: undefined })}>{item.name}</Button>
              <code>{t('buildSpec.model.path', { path: item.plural_path })}</code></Stack>,
            <Row key="methods">{[...new Set(operationNames.flatMap((op, index) => item.options.operations.includes(op) ? [methods[index]] : []))]
              .map(method => <Badge key={method}>{method}</Badge>)}</Row>,
            t('buildSpec.number', { count: (entityCounts.get(item.name) ?? 0) + 3 + Number(item.options.soft_delete) }),
            t('buildSpec.number', { count: relations.data?.filter(relation => item.id === relation.from_entity_id || item.id === relation.to_entity_id).length ?? 0 }),
            <Badge key="status" tone="info">{t(item.options.soft_delete ? 'buildSpec.model.softBadge' : 'buildSpec.model.configured')}</Badge>, date(item.updated_at),
          ],
        }))} />}
    </>}
    {dialog?.kind === 'entity' && <EntityForm entity={dialog.entity} entities={entities} fields={fields} derived={fkFields} pending={write.isPending}
      disabled={!access.writable} error={write.error} close={() => { setDialog(undefined); write.reset() }} onSave={data =>
        void save(dialog.entity ? { kind: 'entity', entity: dialog.entity, data } : { kind: 'addEntity', data }).catch(() => undefined)} />}
    {dialog?.kind === 'field' && <FieldForm field={dialog.field} fields={fields} reserved={automatic} pending={write.isPending} error={write.error}
      close={() => { setDialog(undefined); write.reset() }}
      onSave={data => void save({ kind: 'field', entity: dialog.entity, field: dialog.field, data }).catch(() => undefined)} />}
    {dialog?.kind === 'relation' && <RelationForm entities={entities} relation={dialog.relation} entity={entity} pending={write.isPending}
      error={write.error} close={() => { setDialog(undefined); write.reset() }}
      onSave={(from, to, data) => void save({ kind: 'relation', relation: dialog.relation, from, to, data }).catch(() => undefined)} />}
  </BuildLoad>
}
