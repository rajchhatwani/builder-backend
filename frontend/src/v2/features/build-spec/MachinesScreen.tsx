import { useMutation, useQuery } from '@tanstack/react-query'
import { useReducer, useState } from 'react'
import type { StateMachineBody, TransitionBody } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, SaveBar, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Checkbox, Dialog, EmptyState, Field, Input, Row, Stack, Textarea } from '../../ui'
import { buildLimits, snakeName, validators } from '../../validators'
import { buildQueries, catalog, checkGuard, saveMachines, useBuildWrite } from './api/build'
import type { CatalogEntity } from './api/build'
import { DiagramAdapter } from './components/DiagramAdapter'
import { BuildFailure, BuildLoad, BuildPage, ChoiceGroup, choices, IssueList, Pick, SectionLink, useBuildDate, WriteAccess } from './components/shared'
import type { BuildScreenProps } from './components/shared'
import { useBuildRoute } from './routes'
import { sectionDraft } from './state/sectionDraft'
import { transitionDraft } from './state/transitionDraft'

type MachineDialog = { kind: 'machine'; edit: boolean } | { kind: 'transition'; edit: boolean }

export default function MachinesScreen({ access }: BuildScreenProps) {
  const { projectId } = useBuildRoute()
  return <BuildPage screen="machines" desktop><Machines key={projectId} access={access} /></BuildPage>
}

function Machines({ access }: BuildScreenProps) {
  const t = useT()
  const date = useBuildDate()
  const { projectId, search, update } = useBuildRoute()
  const section = useQuery(buildQueries.machines(projectId))
  const spec = useQuery(buildQueries.spec(projectId))
  const issues = useQuery(buildQueries.issues(projectId))
  const roles = useQuery(buildQueries.roles(projectId))
  const save = useBuildWrite(projectId, saveMachines)
  const [draft, dispatch] = useReducer(sectionDraft<StateMachineBody>, null)
  const [dialog, setDialog] = useState<MachineDialog>()
  const rows = draft?.rows ?? section.data?.state_machines ?? []
  const entities = catalog(spec.data ?? {})
  const available = entities.filter(entity => !rows.some(row => row.entity === entity.name) && entity.fields.some(field => field.type === 'enum' && field.required))
  const machine = rows.find(row => row.entity === search.entity) ?? rows[0]
  const transitions = machine?.transitions ?? []
  const transition = transitions.find(item => item.name === search.target)
  const entityField = entities.find(entity => entity.name === machine?.entity)?.fields.find(field => field.name === machine?.field)
  const states = machine ? [...new Set([...(entityField?.enum_values ?? []), machine.initial,
    ...transitions.flatMap(item => [...item.from_states ?? [], item.to_state])])].filter(Boolean) : []
  const rolesList = roles.data?.roles.map(role => ({ value: role.name, label: role.label || role.name })) ?? []
  const disabled = !access.writable || save.isPending
  const problems = issues.data?.issues ?? []
  const setRows = (next: StateMachineBody[]) => {
    if (section.data) dispatch({ type: 'set', rows: next, version: section.data.version })
  }
  const setTransitions = (items: TransitionBody[]) => setRows(rows.map(row => row.entity === machine?.entity ? { ...row, transitions: items } : row))
  const reload = async () => {
    if ((await section.refetch()).isSuccess) { dispatch({ type: 'reset' }); save.reset() }
    void issues.refetch()
  }

  async function submit() {
    if (!draft || disabled) return
    try {
      await save.mutateAsync(draft)
      dispatch({ type: 'reset' })
    } catch { /* Displayed in the section. */ }
  }
  const add = <Button variant="primary" disabled={disabled || !available.length} onClick={() => setDialog({ kind: 'machine', edit: false })}>{t('buildSpec.machines.add')}</Button>
  return <BuildLoad reads={[section, spec, issues, roles]}>
    <WriteAccess access={access} />
    <BuildFailure error={save.error} reload={() => void reload()} />
    {problems.length > 0 && <Alert tone="warning"><IssueList issues={problems} /></Alert>}
    {!machine ? <EmptyState title={t('buildSpec.machines.empty')} description={t('buildSpec.machines.emptyDetail')}
      action={available.length ? add : <SectionLink projectId={projectId} section="model">{t('buildSpec.openModel')}</SectionLink>} /> : <>
      <Row>{add}
        <Button disabled={disabled} onClick={() => setDialog({ kind: 'machine', edit: true })}>{t('buildSpec.machines.edit')}</Button>
        <Button disabled={disabled || transitions.length >= 100} onClick={() => setDialog({ kind: 'transition', edit: false })}>{t('buildSpec.machines.addTransition')}</Button>
        <ConfirmDestructive title={t('buildSpec.machines.remove')} description={t('buildSpec.machines.removeDetail', { entity: machine.entity })}
          action={t('buildSpec.remove')} trigger={<Button variant="danger" disabled={disabled}>{t('buildSpec.machines.remove')}</Button>}
          onConfirm={() => { setRows(rows.filter(row => row.entity !== machine.entity)); update({ entity: undefined, target: undefined }) }} />
      </Row>
      <Pick label={t('buildSpec.machines.pick')} options={rows.map(row => ({
        value: row.entity, label: t('buildSpec.machines.machineChoice', { entity: row.entity, field: row.field, count: row.transitions?.length ?? 0 }),
      }))} value={machine.entity} onChange={entity => update({ entity, target: undefined })} />
      <Row><strong>{t('buildSpec.machines.entityField', { entity: machine.entity, field: machine.field })}</strong>
        <Badge tone="info">{t('buildSpec.machines.initialBadge', { state: machine.initial })}</Badge>
        <Badge>{t('buildSpec.machines.stateCount', { count: states.length })}</Badge>
      </Row>
      <DiagramAdapter label={t('buildSpec.machines.diagram', { entity: machine.entity })}
        nodes={states.map(state => ({ id: state, label: state, initial: state === machine.initial }))}
        edges={transitions.flatMap((item, index) => (item.from_states ?? []).filter(source => states.includes(source) && states.includes(item.to_state))
          .map((source, edge) => ({ id: index + '-' + edge, source, target: item.to_state, label: item.name,
            selection: item.name, active: transition?.name === item.name })))}
        onSelect={target => update({ target })} />
      <Row>{transitions.map(item => <Button key={item.name} aria-pressed={item === transition} onClick={() => update({ target: item.name })}>{item.name}</Button>)}</Row>
      <SettingsSection title={transition ? t('buildSpec.machines.transitionTitle', { name: transition.name }) : t('buildSpec.machines.transition')}>
        {transition ? <>
          <dl className="v2-stack">
            <dt>{t('buildSpec.machines.moves')}</dt><dd>{t('buildSpec.arrow', { from: transition.from_states?.join(', ') ?? '', to: transition.to_state })}</dd>
            <dt>{t('buildSpec.machines.guard')}</dt><dd><code>{transition.when || t('buildSpec.none')}</code></dd>
            <dt>{t('buildSpec.machines.roles')}</dt><dd>{transition.auto ? t('buildSpec.machines.autoRoles') : transition.roles?.join(', ') || t('buildSpec.machines.anyEditor')}</dd>
            <dt>{t('buildSpec.machines.runs')}</dt><dd>{t(transition.auto ? 'buildSpec.machines.autoRuns' : 'buildSpec.machines.manualRuns')}</dd>
          </dl>
          <Row><Button disabled={disabled} onClick={() => setDialog({ kind: 'transition', edit: true })}>{t('buildSpec.edit')}</Button>
            <ConfirmDestructive title={t('buildSpec.machines.removeTransition')} description={t('buildSpec.machines.removeTransitionDetail', { name: transition.name })}
              action={t('buildSpec.remove')} trigger={<Button variant="danger" disabled={disabled}>{t('buildSpec.remove')}</Button>}
              onConfirm={() => { setTransitions(transitions.filter(item => item !== transition)); update({ target: undefined }) }} /></Row>
        </> : <p>{t('buildSpec.machines.pickTransition')}</p>}
      </SettingsSection>
    </>}
    {entities.length > 0 && <GuardChecker projectId={projectId} entities={entities} preferred={machine?.entity} writable={access.writable} />}
    {section.data?.updated_at && <p className="v2-muted">{t('buildSpec.versionUpdated', { version: section.data.version, date: date(section.data.updated_at) })}</p>}
    <SaveBar dirty={Boolean(draft)} pending={save.isPending} saved={save.isSuccess} readOnly={disabled} onSave={() => void submit()} onDiscard={() => void reload()} />
    {dialog?.kind === 'machine' && <MachineEditor machine={dialog.edit ? machine : undefined} entities={dialog.edit ? entities.filter(item => item.name === machine?.entity) : available}
      close={() => setDialog(undefined)} onSave={next => {
        setRows(dialog.edit ? rows.map(row => row.entity === machine?.entity ? next : row) : [...rows, next])
        update({ entity: next.entity, target: undefined })
        setDialog(undefined)
      }} />}
    {dialog?.kind === 'transition' && machine && <TransitionEditor projectId={projectId} entity={machine.entity} states={states} roles={rolesList}
      transition={dialog.edit ? transition : undefined} existing={transitions.map(item => item.name)}
      close={() => setDialog(undefined)} onSave={next => {
        setTransitions(dialog.edit ? transitions.map(item => item === transition ? next : item) : [...transitions, next])
        update({ target: next.name })
        setDialog(undefined)
      }} />}
  </BuildLoad>
}

function MachineEditor({ machine, entities, close, onSave }: {
  machine?: StateMachineBody; entities: CatalogEntity[]; close: () => void; onSave: (row: StateMachineBody) => void
}) {
  const t = useT()
  const [entity, selectEntity] = useState(machine?.entity ?? entities[0]?.name)
  const [field, selectField] = useState(machine?.field)
  const options = entities.find(item => item.name === entity)?.fields.filter(item => item.type === 'enum' && item.required) ?? []
  const selected = options.find(item => item.name === field) ?? options[0]
  const initial = typeof selected?.default === 'string' && selected.enum_values?.includes(selected.default) ? selected.default : undefined
  const incompatible = Boolean(machine?.transitions?.some(item =>
    !selected?.enum_values?.includes(item.to_state) || item.from_states?.some(state => !selected.enum_values?.includes(state))))
  return <Dialog open onOpenChange={open => { if (!open) close() }} title={t(machine ? 'buildSpec.machines.edit' : 'buildSpec.machines.add')}
    actions={<Button variant="primary" disabled={!initial || !entity || !selected || incompatible} onClick={() => {
      if (initial && entity && selected) onSave({ entity, field: selected.name, initial, transitions: machine?.transitions ?? [] })
    }}>{t('common.save')}</Button>}>
    <Stack>
      <Pick label={t('buildSpec.entity')} options={choices(entities.map(item => item.name))} value={entity} onChange={value => { selectEntity(value); selectField(undefined) }} disabled={Boolean(machine)} />
      <Pick label={t('buildSpec.machines.stateField')} options={choices(options.map(item => item.name))} value={selected?.name} onChange={selectField} />
      {initial ? <p>{t('buildSpec.machines.initialBadge', { state: initial })}</p> : <Alert tone="warning">{t('buildSpec.machines.initialRequired')}</Alert>}
      {incompatible && <Alert tone="warning">{t('buildSpec.machines.incompatible')}</Alert>}
    </Stack>
  </Dialog>
}

function TransitionEditor({ projectId, entity, states, roles, transition, existing, close, onSave }: {
  projectId: string; entity: string; states: string[]; roles: { value: string; label: string }[];
  transition?: TransitionBody; existing: string[]; close: () => void; onSave: (row: TransitionBody) => void
}) {
  const t = useT()
  const [{ from, to, auto, roles: viewRoles, guard }, dispatch] = useReducer(transitionDraft, {
    from: transition?.from_states ?? [], to: transition?.to_state ?? states[0], auto: transition?.auto ?? false,
    roles: transition?.roles ?? [], guard: transition?.when ?? '',
  })
  const roleChoices = [...roles, ...choices(viewRoles.filter(role => !roles.some(item => item.value === role)))]
  const [attempted, setAttempted] = useState(false)
  const check = useMutation({ mutationFn: (expression: string) => checkGuard(projectId, { entity, expression }) })
  const changeGuard = (value: string) => { dispatch({ field: 'guard', value }); check.reset() }
  const focusSource = () => document.getElementById('machine-from')?.querySelector<HTMLElement>('input')?.focus()
  return <Dialog open onOpenChange={open => { if (!open) close() }} title={t(transition ? 'buildSpec.machines.editTransition' : 'buildSpec.machines.addTransition')}>
    <Form fields={[{ name: 'name', label: t('buildSpec.name'),
      validate: [validators.required, validators.length(buildLimits.transition), snakeName, value => existing.includes(value.trim()) && value.trim() !== transition?.name
        ? { key: 'buildSpec.machines.duplicateTransition' } : undefined],
      control: attrs => <Input {...attrs} maxLength={buildLimits.transition} defaultValue={transition?.name} /> }]}
      submitLabel={t('common.save')} onSubmit={data => {
        setAttempted(true)
        if (!from.length) { focusSource(); return }
        if (!to || guard.length > buildLimits.guard) return
        onSave({ name: String(data.get('name')).trim(), from_states: from, to_state: to, when: guard.trim() || null, roles: auto ? [] : viewRoles, auto })
      }}>
      <div id="machine-from"><ChoiceGroup label={t('buildSpec.machines.from')} options={choices(states)} selected={from}
        onChange={value => dispatch({ field: 'from', value })} error={attempted && !from.length ? t('buildSpec.machines.fromRequired') : undefined} /></div>
      <Pick label={t('buildSpec.machines.to')} options={choices(states)} value={to} onChange={value => dispatch({ field: 'to', value })} />
      <Field label={t('buildSpec.machines.guard')}>{attrs => <Textarea {...attrs} value={guard} maxLength={buildLimits.guard} onChange={event => changeGuard(event.target.value)} />}</Field>
      <Row><Button disabled={!guard.trim() || check.isPending} onClick={() => check.mutate(guard.trim())}>{t('buildSpec.machines.check')}</Button></Row>
      <GuardResult result={check.data} error={check.error} />
      <Checkbox label={t('buildSpec.machines.automatic')} checked={auto} onChange={event => dispatch({ field: 'auto', value: event.target.checked })} />
      {!auto && <ChoiceGroup label={t('buildSpec.machines.roles')} options={roleChoices} selected={viewRoles} onChange={value => dispatch({ field: 'roles', value })} />}
    </Form>
  </Dialog>
}

function GuardResult({ result, error }: { result?: Awaited<ReturnType<typeof checkGuard>>; error: unknown }) {
  const t = useT()
  return <>
    <BuildFailure error={error} />
    {result && <Alert tone={result.ok ? 'success' : 'danger'}>{result.ok ? t('buildSpec.machines.guardOk')
      : result.error?.message ?? t('buildSpec.machines.guardFailed')}</Alert>}
  </>
}

function GuardChecker({ projectId, entities, preferred, writable }: { projectId: string; entities: CatalogEntity[]; preferred?: string; writable: boolean }) {
  const t = useT()
  const { search, update } = useBuildRoute()
  const selected = entities.find(entity => entity.name === search.view)?.name ?? preferred ?? entities[0]?.name
  const check = useMutation({ mutationFn: (expression: string) => checkGuard(projectId, { entity: selected, expression }) })
  return <details open={search.tab === 'guard' || undefined}>
    <summary className="v2-status-disclosure">{t('buildSpec.machines.check')}</summary>
    <Stack>
      <Pick label={t('buildSpec.entity')} options={choices(entities.map(item => item.name))} value={selected} onChange={value => { update({ view: value }); check.reset() }} />
      <Form fields={[{ name: 'guard', label: t('buildSpec.machines.guard'), validate: [validators.required, validators.length(buildLimits.guard)],
        control: attrs => <Textarea {...attrs} maxLength={buildLimits.guard} onChange={() => check.reset()} /> }]}
        readOnly={!writable} pending={check.isPending} submitLabel={t('buildSpec.machines.check')} onSubmit={data => check.mutate(String(data.get('guard')).trim())} />
      <GuardResult result={check.data} error={check.error} />
      {check.data?.fields.length ? <p className="v2-muted">{t('buildSpec.machines.guardFields', { names: check.data.fields.map(field => field.name).join(', ') })}</p> : null}
    </Stack>
  </details>
}
