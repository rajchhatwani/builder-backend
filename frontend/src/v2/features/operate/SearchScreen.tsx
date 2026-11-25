import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { entitiesOf } from '../../../shell/metrics/metricsLogic'
import { useT } from '../../i18n'
import { SettingsSection } from '../../patterns'
import { Alert, Button, Card, CodeBlock, Disclosure, EmptyState, Field, Grid, Input, Row, Select, Stack, Table } from '../../ui'
import { canWrite, errorInfo, rolesOptions, searchOptions, specOptions, useReindex } from './api/operate'
import type { OperateProps } from './api/operate'
import { LoadState, OperateScreen, RoleNotice, SectionLink, useOperateSearch, useOptions } from './components/Common'
import './operate.css'

export default function SearchScreen(props: OperateProps) {
  return <OperateScreen title={'operate.search.title'} lead="operate.search.lead"><Search {...props} /></OperateScreen>
}

function Search(props: OperateProps) {
  const { projectId: id } = props
  const t = useT()
  const { search } = useOperateSearch()
  const spec = useQuery(specOptions(id))
  const entities = spec.data ? entitiesOf(spec.data).map(entity => entity.name) : []
  return <Stack gap={4}>
    <RoleNotice {...props} />
    {!spec.data ? <LoadState error={spec.error} retry={spec.refetch} /> : <>
      {entities.length ? <SearchRecords key={search.q ?? ''} entities={entities} {...props} /> :
        <EmptyState title={t('operate.search.empty')} action={<SectionLink id={id} section="model" label={t('operate.model')} />} />}
      <SearchIndex {...props} />
      <Row>{entities.length > 0 && <SectionLink id={id} section="model" label={t('operate.model')} />}
        <SectionLink id={id} section="import" label={t('operate.search.import')} /></Row>
    </>}
  </Stack>
}

function SearchRecords({ entities, ...props }: OperateProps & { entities: string[] }) {
  const { projectId: id } = props
  const t = useT()
  const pick = useOptions()
  const { search, change } = useOperateSearch()
  const [draft, setDraft] = useState(search.q ?? '')
  const write = canWrite(props)
  const roles = useQuery({ ...rolesOptions(id), enabled: write })
  const entity = search.entity && entities.includes(search.entity) ? search.entity : entities[0]
  const role = write ? search.role ?? '' : ''
  const limit = Math.min(100, Math.max(20, Number(search.limit) || 20))
  const term = (search.q ?? '').trim()
  const allowed = !search.role || write
  const query = useQuery(searchOptions(id, entity, allowed && term.length <= 200 ? term : '', Math.floor(limit), role))
  const result = query.data
  const rolesList = roles.data?.roles.map(item => item.name) ?? []
  return <Stack>
    <Card><form role="search" aria-label={t('operate.search.form')} onSubmit={event => {
      event.preventDefault()
      const q = draft.trim()
      if (!q || q.length > 200 || !allowed) return
      if (q === term && Number(search.limit ?? 20) === 20) void query.refetch()
      else change({ q, entity, role: role || undefined, limit: undefined })
    }}><Stack>
      <Grid>
        <Field label={t('operate.search.entity')}>{attrs => <Select triggerProps={attrs} options={pick(entities)}
          value={entity} onValueChange={value => change({ entity: value, q: undefined, limit: undefined })} />}</Field>
        {write && <Field label={t('operate.search.role')}>{attrs => <Select triggerProps={attrs}
          options={[{ value: 'own', label: t('operate.search.own') }, ...pick([...new Set([...rolesList, role])])
            .map(option => ({ ...option, value: 'role:' + option.value }))]}
          value={role ? 'role:' + role : 'own'} disabled={roles.isPending}
          onValueChange={value => change({ role: value === 'own' ? undefined : value.slice('role:'.length), q: undefined, limit: undefined })} />}</Field>}
      </Grid>
      {write && roles.isError && <LoadState error={roles.error} retry={roles.refetch} label={'operate.search.rolesError'} />}
      {!role && <p className="v2-muted">{t('operate.search.ownHelp')}</p>}
      <Grid>
        <Field label={t('operate.search.term')}>{attrs => <Input {...attrs} type="search" maxLength={200} value={draft}
          onChange={event => setDraft(event.target.value)} />}</Field>
      </Grid>
      <Row><Button variant="primary" type="submit" disabled={!draft.trim() || query.isFetching || !allowed}>
        {t(query.isFetching ? 'operate.search.working' : 'operate.search.title')}</Button></Row>
    </Stack></form></Card>
    {search.role && !props.rolePending && !write && <Alert tone="warning" action={<Button onClick={() => change({ role: undefined, q: undefined, limit: undefined })}>
      {t('operate.search.own')}</Button>}>{t('behavior.forbidden')}</Alert>}
    {query.isFetching && !result && <LoadState retry={query.refetch} lines={3} />}
    {query.isError && <LoadState error={query.error} retry={query.refetch} label={'operate.search.resultError'} detail />}
    {result && <SettingsSection title={t('operate.search.results')}>
      <Stack role="status" aria-live="polite" gap={1}>
        <strong>{t('operate.search.total', { count: result.total })}</strong>
        <p className="v2-muted">{t('operate.search.scope', { entity: result.entity, role: result.as_role || t('operate.search.own'), adapter: result.adapter })}</p>
        {result.total > result.hits.length && <p>{t('operate.search.shown', { shown: result.hits.length, total: result.total })}</p>}
      </Stack>
      {result.hits.length ? <ul aria-label={t('operate.search.results')} className="v2-operate-results">
        {result.hits.map((hit, i) => <li key={i}><Card><dl className="v2-operate-kv">
          {Object.entries(hit).map(([name, value]) => <div key={name}>
            <dt>{t('operate.data', { value: name })}</dt>
            <dd>{t('operate.data', { value: typeof value === 'string' ? value : JSON.stringify(value) ?? '' })}</dd>
          </div>)}
        </dl></Card></li>)}
      </ul> : <p>{t('operate.search.noHits')}</p>}
      {result.total > result.hits.length && (limit < 100 ? <Row><Button onClick={() => change({ limit: String(Math.min(100, limit + 20)) })}>
        {t('operate.search.more')}</Button></Row> : <p>{t('operate.search.max')}</p>)}
      <Disclosure label={t('operate.search.pipeline')}><p>{t('operate.search.pipelineHelp')}</p></Disclosure>
    </SettingsSection>}
  </Stack>
}

function SearchIndex(props: OperateProps) {
  const t = useT()
  const action = useReindex(props.projectId)
  const result = action.data
  const writable = canWrite(props)
  return <SettingsSection title={t('operate.search.index')} description={t('operate.search.indexHelp')}>
    {writable && <Row><Button disabled={action.isPending} onClick={() => action.mutate()}>
      {t(action.isPending ? 'operate.search.rebuilding' : 'operate.search.reindex')}</Button></Row>}
    {writable && action.isError && <Alert tone="danger" action={<Button onClick={() => action.mutate()}>{t('common.retry')}</Button>}>
      {t('operate.data', { value: errorInfo(action.error)?.message ?? t('operate.search.indexError') })}
    </Alert>}
    {writable && result && <Stack aria-label={t('operate.search.indexResult')}>
      <p role="status">{t('operate.search.indexCount', { count: result.indexed, index: result.index })}</p>
      <Table label={t('operate.search.indexResult')}
        columns={['entity', 'fields', 'records'].map(key => ({ id: key, label: t('operate.search.' + key) }))}
        rows={result.entities.map(row => ({ id: row.entity, cells: [row.entity, row.searchable_fields, row.records].map(value =>
          t('operate.data', { value })) }))} />
      <Disclosure label={t('operate.search.json')}><CodeBlock code={JSON.stringify(result, null, 2)} /></Disclosure>
    </Stack>}
  </SettingsSection>
}
