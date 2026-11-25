import { useQuery } from '@tanstack/react-query'
import { Link, useSearch } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import type { HookBody, HookFieldBody } from '../../../api/types'
import { useT } from '../../i18n'
import { SettingsSection } from '../../patterns'
import { openInEditor } from '../../patterns/editorLink'
import { Badge, Button, Card, CodeBlock, EmptyState, Row, Stack, useToast } from '../../ui'
import { behaviorIdentifier, booleanValue, hookDate, hookDateTime, hookFieldName, hookModelName, hookUuid, validators } from '../../validators'
import { catalogOptions, effectsSection, hooksSection, issuesOptions } from './api/behavior'
import type { Catalog } from './api/behavior'
import {
  BehaviorCheck, BehaviorField, BehaviorPage, BehaviorSelect, Choices, FormGrid, IssueList, RemoveAction,
  SectionForm, queryStates, Summary, WholeNumber, canEdit, removeAt, replaceAt,
} from './BehaviorForm'
import type { BehaviorProps } from './BehaviorForm'
import { effectBudget, effectKinds, provenance } from './blocks'
import { blankHook, fixedOutput, hookFields, hookTypes, legalPolicies, ownerLocked, pointStage, pointsFor, rename, retarget, stubFor } from './hooks'

const route = '/projects/$projectId/$section'
function fieldList(fields: HookFieldBody[] = []) {
  return fields.map(field => field.name + ': ' + (field.type ?? 'string') + (field.required === false ? '?' : '')).join(', ')
}

function Contract({ hook, projectId }: { hook: HookBody; projectId: string }) {
  const t = useT()
  const toast = useToast()
  const stub = stubFor(hook)
  const [preview, setPreview] = useState(false)
  const copy = () => {
    if (!stub) return
    void navigator.clipboard.writeText(stub.code).then(
      () => toast({ title: t('behavior.copied'), tone: 'success' }),
      () => toast({ title: t('behavior.copyError'), tone: 'danger' }),
    )
  }
  const download = () => {
    if (!stub) return
    const url = URL.createObjectURL(new Blob([stub.code], { type: 'text/plain' }))
    const link = document.createElement('a')
    link.href = url
    link.download = hook.name + '.py'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  return <SettingsSection title={t('behavior.hooks.gate')} description={t('behavior.hooks.gateHelp')}>
    <code>{t('behavior.hooks.gateCommand')}</code>
    {stub ? <>
      <p>{t('behavior.hooks.stubPath')} <code>{stub.path}</code></p>
      <CodeBlock code={stub.signature} />
      <Row>
        <Button aria-expanded={preview} onClick={() => setPreview(!preview)}>{t(preview ? 'behavior.hooks.hideStub' : 'behavior.hooks.previewStub')}</Button>
        <Button asChild><Link {...openInEditor({ projectId, path: stub.path })}>{t('behavior.hooks.editor')}</Link></Button>
        <Button onClick={download}>{t('behavior.hooks.download')}</Button>
        <Button onClick={copy}>{t('behavior.copy')}</Button>
      </Row>
      {preview && <CodeBlock code={stub.code} label={t('behavior.hooks.previewStub')} />}
    </> : <p>{t('behavior.hooks.stubMissing')}</p>}
  </SettingsSection>
}

const limitOf = { calls_per_effect: 20, payload_bytes: 262144, outbound_per_minute: 600 }
const fallbackChecks = {
  int: validators.number({ integer: true }), float: validators.number(), decimal: validators.number({ digits: 18 }),
  bool: booleanValue, date: hookDate, datetime: hookDateTime, uuid: hookUuid,
}
function fallbackValue(type: string, value: string) {
  if (type === 'bool' && /^(true|false)$/i.test(value)) return value.toLowerCase() === 'true'
  if (['int', 'float'].includes(type) && value.trim() && Number.isFinite(Number(value))) return Number(value)
  return value
}

function HookEditor({ hook, index, catalog, change, owner, disabled, effectsEnabled }: {
  hook: HookBody; index: number; catalog: Catalog; change: (value: HookBody) => void; owner: boolean; disabled: boolean; effectsEnabled: boolean
}) {
  const t = useT()
  const label = (name: string) => t('behavior.hooks.' + name)
  const path = (name: string) => index + '.' + name
  const stage = pointStage(hook.point)
  const kind = hook.kind ?? 'pure'
  const entity = catalog.entities.find(item => item.name === hook.point.split('.')[0])
  const fields = hookFields(entity)
  const points = pointsFor(catalog).map(point => ({
    value: point.value, group: point.entity, label: t('behavior.hooks.pointOption', {
      stage: label('stage.' + point.stage), transition: point.transition ? ' (' + point.transition + ')' : '',
    }),
  }))
  const effects = hook.effects ?? []
  const output = hook.output.fields ?? []
  const outputChoices = fields.filter(field => field.name !== 'id' && field.name !== entity?.machine?.field)
  const setModelFields = (which: 'input' | 'output', names: string[]) => change({
    ...hook, [which]: { ...hook[which], fields: names.slice(0, 30).map(name =>
      hook[which].fields?.find(field => field.name === name) ?? fields.find(field => field.name === name) ?? { name }) },
  })
  const setOutput = (value: HookFieldBody[], oldName?: string, newName?: string) => {
    const fallback = { ...hook.fallback }
    if (oldName && oldName !== newName && Object.hasOwn(fallback, oldName)) {
      if (newName) fallback[newName] = fallback[oldName]
      delete fallback[oldName]
    }
    for (const field of value) {
      if (field.name && field.required !== false && (field.type ?? 'string') === 'string' && !Object.hasOwn(fallback, field.name)) {
        fallback[field.name] = ''
      }
    }
    change({ ...hook, output: { ...hook.output, fields: value }, fallback: hook.failure_policy === 'fallback' ? fallback : null })
  }
  const retargetTo = (point: string, nextKind: string) => change(retarget(hook, point, nextKind,
    catalog.entities.find(item => item.name === point.split('.')[0])))
  return <Stack data-testid="hook-form">
    <FormGrid>
      <BehaviorField label={label('name')} path={path('name')} value={hook.name} maxLength={40}
        checks={[validators.required, behaviorIdentifier(40)]} hint={label('nameHelp')} change={name => change(rename(hook, name))} />
      <BehaviorSelect label={label('point')} path={path('point')} value={hook.point} options={points} change={point => retargetTo(point, kind)} />
      <BehaviorSelect label={label('kind')} path={path('kind')} value={kind} options={stage === 'after_commit' ? ['pure', 'effect'] : ['pure']}
        hint={label(stage === 'after_commit' ? 'effectHelp' : 'pureHelp')} change={next => retargetTo(hook.point, next)} />
      <BehaviorSelect label={label('policy')} path={path('failure_policy')} value={hook.failure_policy ?? 'default'}
        options={[{ value: 'default', label: t('behavior.hooks.defaultPolicy', { value: legalPolicies(stage)[0] }) }, ...legalPolicies(stage)]}
        change={policy => change({ ...hook, failure_policy: policy === 'default' ? null : policy, fallback: policy === 'fallback' ? hook.fallback ??
          Object.fromEntries(output.filter(field => field.required !== false && (field.type ?? 'string') === 'string')
            .map(field => [field.name, ''])) : null })} />
      {(Object.keys({ cpu_ms: 0, rows: 0, outbound_calls: 0 }) as Array<'cpu_ms' | 'rows' | 'outbound_calls'>).map(key =>
        <WholeNumber key={key} label={label(key)} path={path('budget.' + key)} min={key === 'cpu_ms' || (key === 'rows' && hook.reads?.length) ? 1 : 0}
          max={key === 'cpu_ms' ? kind === 'effect' ? 4000 : 1000 : key === 'rows' && kind === 'effect' ? 1000 : 0}
          value={hook.budget?.[key] ?? (key === 'cpu_ms' ? 200 : 0)}
          change={value => change({ ...hook, budget: { ...hook.budget, [key]: value ?? 0 } })} />)}
      {(['input', 'output'] as const).map(which => <BehaviorField key={which} label={label(which + 'Model')}
        path={path(which + '.name')} value={hook[which].name} maxLength={40} checks={[validators.required, hookModelName]}
        change={name => change({ ...hook, [which]: { ...hook[which], name } })} />)}
    </FormGrid>
    {kind === 'effect' && <Choices label={label('readChoices')} path={path('reads')} options={catalog.entities.map(item => item.name)}
      values={hook.reads ?? []} change={reads => change({ ...hook, reads, budget: { ...hook.budget, rows: reads.length ? Math.max(hook.budget?.rows || 0, 1) : 0 } })} />}
    <Choices label={label('inputChoices')} path={path('input.fields')} required max={30} options={fields.map(field => ({ value: field.name, label: fieldList([field]) }))}
      values={hook.input.fields?.map(field => field.name) ?? []} change={names => setModelFields('input', names)} />
    {fixedOutput[stage] ? <p>{label('fixed')} <code>{fieldList(fixedOutput[stage])}</code></p>
      : stage === 'before_save' ? <Choices label={label('outputChoices')} path={path('output.fields')} required max={30}
        options={outputChoices.map(field => field.name)} values={output.map(field => field.name)} change={names => setModelFields('output', names)} />
      : <Stack>
        {output.map((field, position) => {
          const update = (next: HookFieldBody) => setOutput(replaceAt(output, position, next), field.name, next.name)
          const prefix = 'output.fields.' + position + '.'
          return <FormGrid key={position}>
            <BehaviorField label={t('behavior.hooks.outputName', { count: position + 1 })} path={path(prefix + 'name')}
              value={field.name} maxLength={40} checks={[validators.required, hookFieldName]} change={name => update({ ...field, name })} />
            <BehaviorSelect label={t('behavior.hooks.outputType', { count: position + 1 })} path={path(prefix + 'type')}
              value={field.type ?? 'string'} options={hookTypes} change={type => update({ ...field, type })} />
            <Row>
              <BehaviorCheck label={t('behavior.required')} value={field.required !== false} change={required => update({ ...field, required })} />
              <RemoveAction label={label('removeOutput')} onConfirm={() => setOutput(removeAt(output, position), field.name)} />
            </Row>
          </FormGrid>
        })}
        <Row><Button disabled={disabled || output.length >= 30} onClick={() => setOutput([...output, { name: '', type: 'string', required: true }])}>
          {label('addOutput')}
        </Button></Row>
      </Stack>}
    {hook.failure_policy === 'fallback' && <FormGrid>
      {output.filter(field => field.name).map((field, position) => {
        const type = field.type ?? 'string'
        const check = fallbackChecks[type as keyof typeof fallbackChecks]
        return <BehaviorField key={position} label={t('behavior.hooks.fallbackFor', { name: field.name })}
          path={path('fallback.' + field.name)} value={hook.fallback?.[field.name]} hint={type}
          maxLength={type === 'string' ? 500 : undefined}
          checks={[...(field.required === false || type === 'string' ? [] : [validators.required]), ...(check ? [check] : [])]}
          change={value => change({ ...hook, fallback: { ...hook.fallback, [field.name]: fallbackValue(type, value) } })} />
      })}
    </FormGrid>}
    {kind === 'effect' && owner && <SettingsSection title={label('effects')} description={label(effectsEnabled ? 'effectsOn' : 'effectsOff')}>
      <Choices label={label('effectChoices')} path={path('effects')} options={effectKinds} values={effects}
        change={next => change({ ...hook, effects: next, effect_budget: next.length ? hook.effect_budget : null })} />
      {!!effects.length && <>
        <BehaviorCheck label={label('customBudget')} value={Boolean(hook.effect_budget)}
          change={on => change({ ...hook, effect_budget: on ? effectBudget : null })} />
        {hook.effect_budget && <FormGrid>
          {Object.entries(limitOf).map(([key, max]) => <WholeNumber key={key} label={label(key)} path={path('effect_budget.' + key)}
            value={hook.effect_budget?.[key]} min={1} max={max}
            change={value => change({ ...hook, effect_budget: { ...hook.effect_budget, [key]: value ?? 1 } })} />)}
        </FormGrid>}
      </>}
    </SettingsSection>}
  </Stack>
}

function HookCard({ hook, catalog, index, edit, remove, locked, disabled, owner, effectsEnabled, projectId, linked, newRow, edited }: {
  hook: HookBody; catalog: Catalog; index: number; edit: (hook: HookBody) => void; remove: () => void; locked: boolean; disabled: boolean;
  owner: boolean; effectsEnabled: boolean; projectId: string; linked: boolean; newRow: boolean; edited: boolean
}) {
  const t = useT()
  const label = (key: string) => t('behavior.hooks.' + key)
  const [open, setOpen] = useState(newRow)
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    if (linked) {
      ref.current?.scrollIntoView?.({ block: 'center' })
      ref.current?.focus()
    }
  }, [linked])
  const data = [
    { label: label('point'), value: <code>{hook.point}</code> },
    { label: label('kind'), value: hook.kind ?? 'pure' },
    { label: label('policy'), value: hook.failure_policy ?? t('behavior.hooks.defaultPolicy', { value: legalPolicies(pointStage(hook.point))[0] }) },
    { label: label('budget'), value: t('behavior.hooks.budgetValue', { cpu: hook.budget?.cpu_ms ?? 200, rows: hook.budget?.rows ?? 0, calls: hook.budget?.outbound_calls ?? 0 }) },
    { label: label('input'), value: <code>{hook.input.name}({fieldList(hook.input.fields)})</code> },
    { label: label('output'), value: <code>{hook.output.name}({fieldList(hook.output.fields)})</code> },
  ]
  if (hook.reads?.length) data.push({ label: label('reads'), value: hook.reads.join(', ') })
  if (hook.failure_policy === 'fallback') data.push({ label: label('fallback'), value: JSON.stringify(hook.fallback ?? {}) })
  if (hook.effects?.length) data.push({ label: label('effects'), value: hook.effects.join(', ') })
  if (hook.effect_budget) data.push({ label: label('effectBudget'), value: t('behavior.hooks.effectsValue', {
    calls: hook.effect_budget.calls_per_effect, bytes: hook.effect_budget.payload_bytes, rate: hook.effect_budget.outbound_per_minute,
  }) })
  return <Card className="behavior-card" data-testid="hook-row" ref={ref} tabIndex={-1} aria-current={linked || undefined}>
    <Stack gap={4}>
      <Row className="v2-spread">
        <h2>{hook.name || label('new')}</h2>
        <Row>
          {!locked && <Button data-behavior-edit-toggle aria-expanded={open} disabled={disabled} onClick={() => setOpen(!open)}>{t(open ? 'behavior.doneEditing' : 'behavior.edit')}</Button>}
          {!locked && <RemoveAction label={t('behavior.hooks.remove', { name: hook.name || label('new') })} disabled={disabled} onConfirm={remove} />}
        </Row>
      </Row>
      <Row><Badge>{label('author.' + provenance(hook.author))}</Badge>{ownerLocked(hook) && <Badge>{label('effectOwner')}</Badge>}</Row>
      <Summary entries={data} testId="hook-summary" />
      {hook.effects?.length ? <Row><Button asChild><Link to={route} params={{ projectId, section: 'hookeffects' }}>{t('nav.hookeffects')}</Link></Button></Row> : null}
      {!locked && (open || edited) && <div hidden={!open} data-behavior-editor>
        <HookEditor {...{ hook, index, catalog, owner, disabled, effectsEnabled }} change={edit} />
      </div>}
      <Contract hook={hook} projectId={projectId} />
    </Stack>
  </Card>
}

export default function HooksScreen(props: BehaviorProps) {
  const t = useT()
  const { hook: selected } = useSearch({ from: route })
  const { projectId } = props
  const catalog = useQuery(catalogOptions(projectId))
  const effects = useQuery(effectsSection.query(projectId))
  const issues = useQuery(issuesOptions(projectId))
  const owner = props.role === 'owner'
  return <BehaviorPage title={t('nav.hooks')} description={t('behavior.hooks.intro')} desktop access={props}>
    <SectionForm projectId={projectId} config={hooksSection} writable={canEdit(props.role)} supporting={queryStates(catalog, effects)}
      render={({ value, edit, saved, disabled }) => {
        if (!catalog.data) return null
        const entities = catalog.data
        const start = pointsFor(entities).find(point => point.stage !== 'before_save' || hookFields(
          entities.entities.find(entity => entity.name === point.entity)).length > 1)
        const add = start ? <Button variant="primary" disabled={disabled || value.length >= 50}
          onClick={() => edit([...value, blankHook(start.value, entities.entities.find(entity => entity.name === start.entity))])}>
          {t('behavior.hooks.add')}
        </Button> : <Button asChild><Link to={route} params={{ projectId, section: 'model' }}>{t('nav.model')}</Link></Button>
        return <Stack gap={4}>
          <IssueList issues={(issues.data?.issues ?? []).filter(issue => issue.path.startsWith('hook_effects'))} />
          {selected && !value.some(item => item.name === selected) && <p role="status">{t('behavior.hooks.missing', { name: selected })}</p>}
          {!value.length && <EmptyState title={t('behavior.hooks.empty')} description={t(start ? 'behavior.hooks.emptyHelp' : 'behavior.hooks.noEntity')} action={add} />}
          {value.map((hook, index) => <HookCard key={index} hook={hook} index={index} catalog={entities} projectId={projectId} disabled={disabled}
            owner={owner} locked={!canEdit(props.role) || !owner && ownerLocked(hook)} effectsEnabled={effects.data?.value?.enabled === true}
            linked={Boolean(selected && hook.name === selected)} newRow={index >= saved.length} edited={!saved.includes(hook)}
            edit={next => edit(replaceAt(value, index, next))} remove={() => edit(removeAt(value, index))} />)}
          {!!value.length && <Row>{add}</Row>}
        </Stack>
      }} />
  </BehaviorPage>
}
