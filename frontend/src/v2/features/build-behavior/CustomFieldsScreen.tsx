import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useRef, useState } from 'react'
import type { CustomFieldDef, PromoteCheck } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, ReadOnlyNote, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Card, CodeBlock, EmptyState, Pagination, Row, Skeleton, Stack, Table } from '../../ui'
import { behaviorIdentifier, customFieldOptions, safeJsonArray, validators } from '../../validators'
import {
  behaviorKeys, checkCustomFieldSamples, customFieldsApi, errorIssues, errorStatus, fieldsOptions, specOptions, updateCustomField,
} from './api/behavior'
import type { Promotion } from './api/behavior'
import { BehaviorCheck, BehaviorField, BehaviorPage, BehaviorSelect, DraftForm, FormGrid, IssueList, LoadError, WholeNumber, canEdit } from './BehaviorForm'
import type { BehaviorProps } from './BehaviorForm'
import { entityNames } from './blocks'

const route = '/projects/$projectId/$section'
const types = ['string', 'int', 'float', 'bool', 'date', 'datetime']
const blank: CustomFieldDef = { name: '', type: 'string', required: false }
const listSize = 20

function Definition({ initial, pending, error, save, cancel }: {
  initial?: CustomFieldDef; pending: boolean; error: unknown; save: (value: CustomFieldDef) => void; cancel: () => void
}) {
  const t = useT()
  const label = (key: string) => t('behavior.custom.' + key)
  const [value, setValue] = useState(initial ?? blank)
  const [values, setValues] = useState(initial?.enum_values?.join('\n') ?? '')
  const [tried, setTried] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const issues = errorIssues(error).map(issue => ({
    ...issue, path: issue.path.split('.').at(-1) ?? issue.path,
  }))
  return <SettingsSection title={label(initial ? 'editTitle' : 'addTitle')}>
    <Stack ref={ref}>
      <DraftForm disabled={pending} tried={tried} issues={issues} prefix="">
        <FormGrid>
          <BehaviorField label={label('fieldName')} path="name" maxLength={63} checks={[validators.required, behaviorIdentifier(63)]}
            value={value.name} change={name => setValue({ ...value, name })} />
          <BehaviorSelect label={label('type')} path="type" value={value.type} options={types}
            change={type => setValue({ ...value, type, max_length: null })} />
          <BehaviorCheck label={t('behavior.required')} path="required" value={value.required}
            change={required => setValue({ ...value, required })} />
          {value.type === 'string' && <>
            <WholeNumber label={label('length')} value={value.max_length} path="max_length" optional min={1} max={10000}
              change={max_length => setValue({ ...value, max_length })} />
            <BehaviorField label={label('values')} path="enum_values" value={values} area checks={[customFieldOptions]}
              hint={label('valuesHelp')} change={setValues} />
          </>}
        </FormGrid>
      </DraftForm>
      <Row>
        <Button disabled={pending} variant="primary" onClick={() => {
          setTried(true)
          const invalid = ref.current?.querySelector<HTMLElement>('[data-behavior-invalid]')
          if (invalid) {
            invalid.focus()
            return
          }
          const options = value.type === 'string' ? values.split('\n').map(item => item.trim()).filter(Boolean) : []
          save({ ...value, max_length: value.type === 'string' ? value.max_length ?? null : null,
            enum_values: options.length ? options : null })
        }}>{label(initial ? 'save' : 'add')}</Button>
        <Button disabled={pending} onClick={cancel}>{t('common.cancel')}</Button>
      </Row>
    </Stack>
  </SettingsSection>
}

function Promote({ name, busy, run, promote, result, clear }: {
  name: string; busy: boolean; run: (samples?: unknown[]) => void; promote: () => Promise<void>; result?: PromoteCheck; clear: () => void
}) {
  const t = useT()
  const [samples, setSamples] = useState('')
  const [ack, setAck] = useState(false)
  const [tried, setTried] = useState(false)
  const reference = useRef<HTMLDivElement>(null)
  const label = (key: string) => t('behavior.custom.' + key)
  return <SettingsSection title={t('behavior.custom.promoteTitle', { name })}>
    <Stack ref={reference}>
      <DraftForm tried={tried} disabled={busy} issues={[]} prefix="">
        <BehaviorField label={label('samples')} hint={label('samplesHelp')} value={samples} area checks={[safeJsonArray(1000)]}
          change={text => { setSamples(text); clear(); setAck(false) }} />
      </DraftForm>
      <Row><Button disabled={busy} onClick={() => {
        setTried(true)
        const invalid = reference.current?.querySelector<HTMLElement>('[data-behavior-invalid]')
        if (invalid) {
          invalid.focus()
          return
        }
        setAck(false)
        run(samples.trim() ? JSON.parse(samples) as unknown[] : undefined)
      }}>{label('check')}</Button></Row>
      {result && <>
        <Alert tone={result.ok && result.proven ? 'success' : result.ok ? 'warning' : 'danger'}>
          {label(!result.ok ? 'notReady' : result.proven ? 'ready' : 'notProven')}
        </Alert>
        {!!result.problems.length && <ul className="behavior-list">{result.problems.map((problem, index) => <li key={index}>
          <Badge tone={problem.severity === 'warning' ? 'warning' : 'danger'}>{label(problem.severity === 'warning' ? 'warning' : 'error')}</Badge>
          {' '}{t('behavior.issue', { code: problem.code, message: problem.message })}
          {problem.sample_index != null && <> {t('behavior.custom.sample', { count: problem.sample_index + 1 })}</>}
        </li>)}</ul>}
        {result.warnings?.filter(warning => !result.problems.some(problem => problem.message === warning)).map(warning =>
          <p key={warning}>{t('behavior.backendText', { message: warning })}</p>)}
        {!!result.plan_sql.length && <Stack gap={1}><h3>{label('sql')}</h3><CodeBlock code={result.plan_sql.join('\n')} /></Stack>}
        {result.ok && !result.proven && <BehaviorCheck label={label('ack')} value={ack} disabled={busy} change={setAck} />}
        {result.ok && <Row><ConfirmDestructive
          trigger={<Button variant="danger" disabled={busy || (!result.proven && !ack)}>{label('promote')}</Button>}
          title={t('behavior.custom.promoteTitle', { name })} description={label('promoteHelp')} action={label('promote')} onConfirm={promote} /></Row>}
      </>}
    </Stack>
  </SettingsSection>
}

type Write =
  | { action: 'define'; value: CustomFieldDef }
  | { action: 'update'; name: string; value: CustomFieldDef }
  | { action: 'remove' | 'promote'; name: string }

function CustomEntity({ entity, projectId, writable, selection, page, move, setPage }: {
  entity: string; projectId: string; writable: boolean; selection?: string; page: number;
  move: (value?: string) => void; setPage: (value: number) => void
}) {
  const t = useT()
  const label = (key: string) => t('behavior.custom.' + key)
  const query = useQuery(fieldsOptions(projectId, entity))
  const client = useQueryClient()
  const editing = selection?.startsWith('edit:') ? selection.slice(5) : undefined
  const checking = selection?.startsWith('check:') ? selection.slice(6) : undefined
  const creating = selection === 'new'
  const check = useMutation({
    mutationKey: [...behaviorKeys.root(projectId), 'customfields', 'check', entity],
    mutationFn: ({ name, samples }: { name: string; samples?: unknown[] }) =>
      samples ? checkCustomFieldSamples(projectId, entity, name, samples) : customFieldsApi.check(projectId, entity, name),
  })
  const write = useMutation({
    mutationKey: [...behaviorKeys.root(projectId), 'customfields', 'write', entity],
    scope: { id: [projectId, entity, 'custom-fields'].join(':') },
    mutationFn: async (operation: Write): Promise<Promotion | undefined> => {
      switch (operation.action) {
        case 'define': await customFieldsApi.define(projectId, entity, operation.value); return
        case 'update': await updateCustomField(projectId, entity, operation.name, operation.value); return
        case 'remove': await customFieldsApi.remove(projectId, entity, operation.name); return
        case 'promote': return customFieldsApi.promote(projectId, entity, operation.name)
      }
    },
    onSuccess: async () => {
      check.reset()
      move()
      await client.invalidateQueries({ queryKey: ['projects', projectId] })
    },
  })
  const commit = (operation: Write) => {
    check.reset()
    write.mutate(operation)
  }
  const select = (value?: string) => {
    check.reset()
    write.reset()
    move(value)
  }
  const beginCheck = (name: string) => {
    select('check:' + name)
    check.mutate({ name })
  }
  const error = write.error ?? check.error
  const conflict = errorStatus(error) === 409
  const forbidden = errorStatus(error) === 403
  const busy = write.isPending || check.isPending || conflict || forbidden
  const result = write.data
  const detectedCheck = check.variables?.name === checking ? check.data : undefined

  if (query.isError && !query.data) return <LoadError retry={() => void query.refetch()} status={errorStatus(query.error)} />
  if (!query.data) return <Card><Skeleton lines={5} /></Card>
  const { items, enabled, max_keys, max_bytes } = query.data
  const definition = items.find(item => item.name === editing)
  const promotionField = checking && items.find(item => item.name === checking)
  const pages = Math.max(1, Math.ceil(items.length / listSize))
  const currentPage = Math.min(page, pages)
  const columns = ['fieldName', 'type', 'required', 'constraints', 'actions'].map(id => ({ id, label: id === 'required' ? t('behavior.required') : label(id) }))
  const add = <Button variant="primary" disabled={!writable || busy || items.length >= Math.min(max_keys, 100)}
    onClick={() => select('new')}>{label('addTitle')}</Button>
  return <Stack gap={4}>
    {query.isError && <LoadError retry={() => void query.refetch()} status={errorStatus(query.error)} />}
    {conflict && <ConflictBanner onReload={() => void query.refetch().then(result => {
      if (!result.isError) select()
    })} />}
    {forbidden && <ReadOnlyNote>{t('behavior.forbidden')}</ReadOnlyNote>}
    {error && !conflict && !forbidden && <Alert tone="danger">{label(check.isError ? 'checkError' : 'writeError')}</Alert>}
    <IssueList issues={errorIssues(error)} />
    <Row>
      <Badge tone={enabled ? 'success' : 'neutral'}>{t(enabled ? 'behavior.enabled' : 'behavior.disabled')}</Badge>
      <span>{t('behavior.custom.limits', { count: items.length, max: max_keys, bytes: max_bytes })}</span>
    </Row>
    {items.length ? <Stack>
      <Table label={t('nav.customfields')} columns={columns} rows={items.slice((currentPage - 1) * listSize, currentPage * listSize).map(item => ({
        id: item.name, cells: [
          <strong>{item.name}</strong>, item.type, t(item.required ? 'behavior.yes' : 'behavior.no'),
          [item.max_length ? t('behavior.custom.displayLength', { count: item.max_length }) : '', item.enum_values?.join(', ')].filter(Boolean).join(' · ') || t('behavior.none'),
          writable ? <Row>
            <Button disabled={busy} aria-label={t('behavior.custom.editNamed', { name: item.name })} onClick={() => select('edit:' + item.name)}>{t('behavior.edit')}</Button>
            <Button disabled={busy} onClick={() => beginCheck(item.name)}>{t('behavior.custom.checkNamed', { name: item.name })}</Button>
            <ConfirmDestructive trigger={<Button variant="danger" disabled={busy} aria-label={t('behavior.custom.removeNamed', { name: item.name })}>{t('behavior.remove')}</Button>}
              title={t('behavior.custom.removeNamed', { name: item.name })} description={label('removeHelp')}
              action={t('behavior.remove')} onConfirm={() => write.mutateAsync({ action: 'remove', name: item.name }).then(() => undefined)} />
          </Row> : t('behavior.none'),
        ],
      }))} />
      {pages > 1 && <Pagination label={t('nav.customfields')} page={currentPage} pages={pages} onChange={setPage} />}
      <Row>{add}</Row>
    </Stack> : <EmptyState title={label('empty')} description={label('emptyHelp')} action={add} />}
    {writable && !conflict && !forbidden && (creating || definition) &&
      <Definition key={selection} initial={definition} pending={busy} error={write.error} cancel={() => select()}
        save={value => commit(definition ? { action: 'update', name: definition.name, value } : { action: 'define', value })} />}
    {writable && !conflict && !forbidden && promotionField && <Promote name={promotionField.name} key={promotionField.name} busy={busy}
      result={detectedCheck} clear={check.reset} run={samples => check.mutate({ name: promotionField.name, samples })}
      promote={() => write.mutateAsync({ action: 'promote', name: promotionField.name }).then(() => undefined)} />}
    {write.isSuccess && <Alert tone="success">{result ? t('behavior.custom.promoted', { name: result.name, seq: result.op_seq }) : label('saved')}</Alert>}
    {result && <SettingsSection title={label('migration')}>
      {result.migration_steps?.map((step, index) => <Stack key={index} gap={1}>
        <Row><Badge>{step.kind}</Badge><Badge>{step.safety}</Badge></Row>
        <p>{t('behavior.backendText', { message: step.reason })}</p>
        {step.sql_hint && <CodeBlock code={step.sql_hint} />}
      </Stack>)}
      {!!result.plan_sql.length && <CodeBlock code={result.plan_sql.join('\n')} />}
      <Row><Button asChild><Link to={route} params={{ projectId, section: 'timeline' }}>{label('history')}</Link></Button></Row>
    </SettingsSection>}
  </Stack>
}

export default function CustomFieldsScreen(props: BehaviorProps) {
  const t = useT()
  const { entity: selected, view, page } = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const { projectId } = props
  const spec = useQuery(specOptions(projectId))
  const names = entityNames(spec.data)
  const activeWrites = useIsMutating({ mutationKey: [...behaviorKeys.root(projectId), 'customfields'] })
  const entity = selected && names.includes(selected) ? selected : names[0]
  const search = (changes: { entity?: string; view?: string; page?: number }) =>
    void navigate({ params: { projectId, section: 'customfields' }, search: previous => ({ ...previous, ...changes }) })
  return <BehaviorPage title={t('nav.customfields')} description={t('behavior.custom.intro')} access={props}>
    {spec.isError && <LoadError retry={() => void spec.refetch()} status={errorStatus(spec.error)} />}
    {spec.isPending && <Card><Skeleton lines={5} /></Card>}
    {spec.data && (!entity ? <EmptyState title={t('behavior.custom.noEntities')} description={t('behavior.custom.noEntitiesHelp')}
      action={<Button asChild><Link to={route} params={{ projectId, section: 'model' }}>{t('nav.model')}</Link></Button>} />
      : <>
        <BehaviorSelect label={t('behavior.custom.entity')} options={names} value={entity} disabled={activeWrites > 0}
          change={next => search({ entity: next, view: undefined, page: undefined })} />
        <CustomEntity key={entity} {...{ entity, projectId }} writable={canEdit(props.role)} selection={view} page={page ?? 1}
          move={value => search({ view: value })} setPage={value => search({ page: value })} />
      </>)}
  </BehaviorPage>
}
