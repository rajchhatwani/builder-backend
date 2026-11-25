import { useEffect, useReducer, useRef } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, SettingsSection, type FormField } from '../../patterns'
import { Button, Grid, Row, Stack } from '../../ui'
import { complianceChecks, validators } from '../../validators'
import { complianceBlockOptions, complianceChoicesOptions, complianceIssuesOptions, controlsApi, type BlockRead,
  type Compliance, type ComplianceBlocks, type ProjectSpec, type Regulated } from './api/controls'
import { fieldErrors, useSecureMutation } from './api/security'
import { blockDraftReducer, defaultCompliance, defaultRegulated, type BlockAction } from './state/compliance'
import { canEdit, checkField, Findings, groups, LoadFailure, pickField, SecureLink, SecureLoading,
  textField, WriteNotice, type SecureProps } from './SecureForm'

const blank = '_none'
const split = (value: string) => value.split(',').map(part => part.trim()).filter(Boolean)
const retentionActions = ['purge', 'anonymise'] as const
const treatments = ['drop', 'hash', 'generalise', 'keep'] as const
const keyProviders = ['file', 'env', 'command'] as const
const modes = ['encrypt', 'tokenise'] as const
function listChoices(values: string[], current = '') {
  return [...new Set([...values, ...current ? [current] : []])].map(value => ({ value, label: value }))
}
function keepChoice(value: string, choices: string[]) { return choices.includes(value) ? value : '' }
function isType(value: string, choices: readonly string[]) { return choices.includes(value) }
function updateItem<T>(items: T[], index: number, patch: Partial<T>) {
  return items.map((item, i) => i === index ? { ...item, ...patch } : item)
}

type EditorProps<K extends keyof ComplianceBlocks> = SecureProps & {
  saved: BlockRead<K>; block: K; defaults: ComplianceBlocks[K]; reload: () => Promise<BlockRead<K> | undefined>
  render: (value: ComplianceBlocks[K], edit: (apply: (value: ComplianceBlocks[K]) => ComplianceBlocks[K]) => void, disabled: boolean) => ReturnType<typeof groups>
}
function BlockEditor<K extends keyof ComplianceBlocks>({ saved, block, defaults, reload, render, ...props }: EditorProps<K>) {
  const t = useT()
  const heading = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const title = heading.current?.querySelector('h2')
    if (title) {
      title.tabIndex = -1
      title.focus()
    }
  }, [])
  const id = props.projectId
  const initial = saved[block] ?? defaults
  const [state, dispatch] = useReducer(blockDraftReducer<ComplianceBlocks[K]>,
    { base: initial, draft: initial, version: saved.version, revision: 0 })
  const disabled = !canEdit(props)
  const write = useSecureMutation(id, ({ body, version }: { body: ComplianceBlocks[K]; version: number }) =>
    controlsApi.putBlock(id, block, body, version))
  const issueQuery = useQuery(complianceIssuesOptions(id))
  const issues = issueQuery.data?.issues.filter(issue => issue.path === block || issue.path.startsWith(block + '.')) ?? []
  const dirty = JSON.stringify(state.draft) !== JSON.stringify(state.base)
  const form = render(state.draft, (apply: Extract<BlockAction<ComplianceBlocks[K]>, { type: 'edit' }>['apply']) =>
    dispatch({ type: 'edit', apply }), disabled || write.isPending)
  function reset(value: ComplianceBlocks[K], version: number) {
    dispatch({ type: 'reset', value, version })
    write.reset()
  }
  return <Stack gap={4} ref={heading}>
    {(write.error || write.isSuccess) && <div data-testid={block === 'compliance' && write.isSuccess ? 'settings-note' : undefined}>
      <WriteNotice error={write.error} message={t('compliance.saveError')}
        saved={write.isSuccess ? t('compliance.saved', { version: state.version }) : undefined}
        reload={() => void reload().then(next => { if (next) reset(next[block] ?? defaults, next.version) })} />
    </div>}
    <Findings issues={issues} />
    {issueQuery.isError && <LoadFailure error={issueQuery.error} message={t('compliance.issuesError')} retry={() => void issueQuery.refetch()} />}
    <Form key={state.revision} {...form} serverErrors={fieldErrors(write.error, Object.fromEntries(form.fields.map(field =>
        [block + '.' + field.name, field.name])))} readOnly={disabled}
      pending={write.isPending} submitLabel={t('common.save')} submitProps={{ hidden: disabled, disabled: !dirty, 'data-testid': block === 'compliance' ? 'settings-save' : undefined }}
      actions={<Button disabled={!dirty || write.isPending} onClick={() => reset(initial, saved.version)}>{t('common.discard')}</Button>}
      onSubmit={() => write.mutate({ body: state.draft, version: state.version }, { onSuccess: result => {
        const value = result[block] as ComplianceBlocks[K] | null
        dispatch({ type: 'reset', value: value ?? defaults, version: Number(result.version) })
      } })} />
    <details><summary>{t('compliance.versionDetails')}</summary><Stack gap={1}>
      <p>{t('compliance.version', { version: state.version })}</p>
      {saved.row_version != null && <p>{t('compliance.rowVersion', { version: saved.row_version })}</p>}
      {saved.updated_at && <p>{t('compliance.updated', { date: new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(saved.updated_at)) })}</p>}
    </Stack></details>
  </Stack>
}

function RowEditor({ sections, add, onAdd, onRemove, limit, disabled, controls }: {
  controls: Record<string, ReactNode>
  sections: FormField[][]; add: string; onAdd: () => void; onRemove: (index: number) => void; limit: number; disabled: boolean
}) {
  const t = useT()
  return <Stack gap={4}>
    {sections.map((fields, index) => <Stack key={index} gap={2}>
      <Grid>{fields.map(field => controls[field.name])}</Grid>
      {!disabled && <Row><ConfirmDestructive trigger={<Button variant="danger">{t('compliance.remove')}</Button>}
        title={t('compliance.removeTitle')} description={t('compliance.removeHelp')} action={t('compliance.remove')} onConfirm={() => onRemove(index)} /></Row>}
    </Stack>)}
    {!disabled && <Row><Button disabled={sections.length >= limit} onClick={onAdd}>{add}</Button></Row>}
  </Stack>
}

function useBlock<K extends keyof ComplianceBlocks>(id: string, block: K) {
  const t = useT()
  const saved = useQuery(complianceBlockOptions(id, block))
  const choices = useQuery(complianceChoicesOptions(id))
  const failed = saved.error ?? choices.error
  const pending = saved.isPending || choices.isPending
  const fallback = failed ? <LoadFailure error={failed} message={t('compliance.settingsError')}
    retry={() => { void saved.refetch(); void choices.refetch() }} /> :
    pending ? <SecureLoading label={t('compliance.loadingSettings')} /> : null
  return { saved: saved.data, choices: choices.data, fallback, reload: async () => {
    const result = await saved.refetch()
    return result.isSuccess ? result.data : undefined
  } }
}

function editorFields(t: ReturnType<typeof useT>, spec: ProjectSpec) {
  const entities = spec.entities.map(item => item.name)
  const entityFields = (entity: string) => spec.entities.find(item => item.name === entity)?.fields ?? []
  const fields = (entity: string, types?: readonly string[]) =>
    entityFields(entity).filter(item => !types || isType(item.type, types)).map(item => item.name)
  const pick = (name: string, label: string, value: string, choices: string[], change: (value: string) => void, optional = false) => ({
    ...pickField(name, label, value || (optional ? blank : ''), [
      ...optional ? [{ value: blank, label: t('compliance.none') }] : [], ...listChoices(choices, value),
    ], { change: next => change(next === blank ? '' : next), required: !optional, placeholder: t('compliance.choose') }),
    validate: [...optional ? [] : [validators.required], complianceChecks.selection(choices, value ? [value] : [])],
  })
  const enumeration = <T extends string>(name: string, label: string, value: T, choices: readonly T[], change: (value: T) => void) =>
    pickField(name, label, value, choices.map(option => ({ value: option, label: t(`compliance.option_${option}`) })),
      { change: next => change(next as T) })
  return { entities, entityFields, fields, pick, enumeration }
}

function complianceFields(t: ReturnType<typeof useT>, { spec, roles, draft, edit }: {
  spec: ProjectSpec; roles: string[]; draft: Compliance; edit: (apply: (value: Compliance) => Compliance) => void
}) {
  const { entities, entityFields, fields, pick, enumeration } = editorFields(t, spec)
  const patch = (value: Partial<Compliance>) => edit(model => ({ ...model, ...value }))
  const breakGlass = (value: Partial<Compliance['break_glass']>) => patch({ break_glass: { ...draft.break_glass, ...value } })
  const patchRow = <K extends 'retention' | 'export_entities' | 'export_fields'>(
    key: K, index: number, change: Partial<Compliance[K][number]>,
  ) => patch({ [key]: updateItem<Compliance[K][number]>(draft[key], index, change) })
  const selection = (name: string, title: string, known: string[], current: string[], change: (values: string[]) => void) =>
    [...new Set([...known, ...current])].map((item, index) => checkField(`${name}.${index}`, item, current.includes(item),
      checked => change(checked ? [...current, item] : current.filter(value => value !== item)))).map((control, index) => index ? control :
        { ...control, hint: title, validate: [complianceChecks.selection(known, current)] })
  const number = (name: string, label: string, value: number, min: number, max: number, change: (value: number) => void) =>
    textField(name, label, Number.isNaN(value) ? '' : value, { type: 'number', required: true, controlled: true,
      checks: [validators.number({ min, max, integer: true })], change: text => change(text === '' ? NaN : Number(text)) })

  const retention = draft.retention.map((row, i) => {
    const name = `retention.${i}`
    const update = (value: Partial<Compliance['retention'][number]>) => patchRow('retention', i, value)
    const entity = pick(name + '.entity', t('compliance.entity'), row.entity, entities, entity =>
      update({ entity, date_field: 'created_at', anonymise_fields: [] }))
    const duplicate = draft.retention.some((other, index) => index !== i && other.entity === row.entity && other.action === row.action)
    const dateFields = ['created_at', 'updated_at', ...fields(row.entity, ['date', 'datetime'])]
    const canAnonymise = entityFields(row.entity).filter(field => !field.required || ['string', 'text'].includes(field.type)).map(field => field.name)
    const entityChecks = [...entity.validate,
      () => duplicate ? { key: 'validation.complianceRetentionDuplicate' } : undefined,
      () => row.action === 'anonymise' && !row.anonymise_fields.length ? { key: 'validation.complianceAnonymise' } : undefined,
    ]
    return [{ ...entity, validate: entityChecks },
      number(name + '.days', t('compliance.days'), row.days, 1, 36500, days => update({ days })),
      pick(name + '.date_field', t('compliance.dateField'), row.date_field, dateFields, date_field => update({ date_field })),
      enumeration(name + '.action', t('compliance.action'), row.action, retentionActions,
        action => update({ action, anonymise_fields: action === 'purge' ? [] : row.anonymise_fields })),
      ...row.action === 'anonymise' ? selection(name + '.anonymise_fields', t('compliance.anonymiseFields'),
        canAnonymise, row.anonymise_fields, anonymise_fields => update({ anonymise_fields })) : [],
    ]
  })
  const exports = draft.export_entities.map((row, i) => {
    const name = `export_entities.${i}`
    const update = (value: Partial<Compliance['export_entities'][number]>) => patchRow('export_entities', i, value)
    const references = (spec.relations ?? []).filter(item => item.to_entity === row.entity &&
      (item.kind === 'one_to_one' || item.kind === 'one_to_many')).map(item => item.to_name + '_id')
    const subject = pick(name + '.subject_field', t('compliance.subject'), row.subject_field ?? '',
      ['id', ...fields(row.entity), ...references], subject => update({ subject_field: subject || null }), true)
    return [pick(name + '.entity', t('compliance.entity'), row.entity, entities, entity => update({ entity, subject_field: null })),
      { ...subject, validate: [...subject.validate, () => draft.export_consent_purpose && !row.subject_field ? { key: 'validation.complianceSubject' } : undefined] }]
  })
  const fieldExports = draft.export_fields.map((row, i) => {
    const name = `export_fields.${i}`
    const update = (value: Partial<Compliance['export_fields'][number]>) => patchRow('export_fields', i, value)
    const fieldType = entityFields(row.entity).find(field => field.name === row.field)?.type
    const protectedField = spec.regulated?.enabled && spec.regulated.fields.some(field => field.entity === row.entity && field.field === row.field)
    const treatment = enumeration(name + '.treatment', t('compliance.treatment'), row.treatment, treatments, treatment => update({ treatment }))
    return [pick(name + '.entity', t('compliance.entity'), row.entity, draft.export_entities.map(entry => entry.entity).filter(Boolean), entity => update({ entity, field: '' })),
      pick(name + '.field', t('compliance.field'), row.field, ['created_at', 'updated_at', ...fields(row.entity)], field => update({ field })),
      { ...treatment, validate: [complianceChecks.exportTreatment(row.field, fieldType, row.treatment, Boolean(protectedField))] }]
  })
  return {
    runtime: [
      { ...checkField('enabled', t('compliance.enabled'), draft.enabled, enabled => patch({ enabled })), validate: [
        () => draft.enabled && !spec.auth ? { key: 'validation.complianceAuth' } : undefined,
        () => draft.enabled && !draft.roles.length ? { key: 'validation.complianceRoles' } : undefined,
      ] },
      ...selection('roles', t('compliance.roles'), roles, draft.roles, roles => patch({ roles })),
    ],
    retention, exports, fieldExports,
    consent: [textField('consent_purposes', t('compliance.purposes'), draft.consent_purposes.join(','), {
      max: 1350, checks: [complianceChecks.purposes], change: value => patch({ consent_purposes: split(value) }),
    })],
    emergency: [
      { ...checkField('break_glass.enabled', t('compliance.breakEnabled'), draft.break_glass.enabled, enabled => breakGlass({ enabled })),
        validate: [() => draft.break_glass.enabled && !spec.auth ? { key: 'validation.complianceAuth' } : undefined,
          () => draft.break_glass.enabled && !draft.break_glass.roles.length ? { key: 'validation.complianceBreakRoles' } : undefined] },
      ...selection('breakRoles', t('compliance.breakRoles'), roles, draft.break_glass.roles, roles => breakGlass({ roles })),
      number('break_glass.max_minutes', t('compliance.minutes'), draft.break_glass.max_minutes, 5, 240, max_minutes => breakGlass({ max_minutes })),
    ],
    exportConsent: pick('export_consent_purpose', t('compliance.exportPurpose'), draft.export_consent_purpose ?? '',
      draft.consent_purposes, value => patch({ export_consent_purpose: value || null }), true),
    patch,
  }
}

export function ComplianceSettings(props: SecureProps) {
  const t = useT()
  const { fallback, saved, choices, reload } = useBlock(props.projectId, 'compliance')
  if (fallback || !saved || !choices) return fallback
  const original = saved.compliance ?? defaultCompliance
  return <Stack gap={4}>
    <BlockEditor {...props} block="compliance" saved={saved} defaults={defaultCompliance} reload={reload} render={(draft, edit, disabled) => {
      const form = complianceFields(t, { spec: choices.spec, roles: choices.roles.map(role => role.name), draft, edit })
      const rows = [
        { key: 'retention', title: 'retention', add: 'addRetention', sections: form.retention, limit: 64,
          append: () => form.patch({ retention: [...draft.retention, { entity: '', days: 30, date_field: 'created_at', action: 'purge', anonymise_fields: [] }] }) },
        { key: 'export_entities', title: 'exportEntities', add: 'addExportEntity', sections: form.exports, limit: 64,
          append: () => form.patch({ export_entities: [...draft.export_entities, { entity: '', subject_field: null }] }) },
        { key: 'export_fields', title: 'exportFields', add: 'addExportField', sections: form.fieldExports, limit: 256,
          append: () => form.patch({ export_fields: [...draft.export_fields, { entity: '', field: '', treatment: 'drop' }] }) },
      ] as const
      const base = groups([
        { title: t('compliance.settings'), fields: form.runtime, extra: <SecureLink id={props.projectId} section="access" label={t('compliance.authorization')} /> },
        { title: t('compliance.consent'), fields: form.consent },
        { title: t('compliance.emergency'), fields: form.emergency },
      ])
      return { fields: [...base.fields, ...rows.flatMap(item => item.sections.flat()), form.exportConsent], layout: controls => <Stack gap={4}>
        {base.layout(controls)}
        {rows.map(row => <SettingsSection key={row.key} title={t(`compliance.${row.title}`)}>
          {!row.sections.length && <p>{t('compliance.none')}</p>}
          <RowEditor sections={row.sections} add={t(`compliance.${row.add}`)} onAdd={row.append}
            onRemove={index => form.patch({ [row.key]: draft[row.key].filter((_, position) => index !== position) })}
            limit={row.limit} disabled={disabled} controls={controls} />
        </SettingsSection>)}
        <SettingsSection title={t('compliance.exportPurpose')} description={t('compliance.exportHint')}>{controls[form.exportConsent.name]}</SettingsSection>
      </Stack> }
    }} />
    <SettingsSection title={t('compliance.runtimeFlows')} description={t('compliance.runtimeHint')}>
      <details><summary>{t('compliance.retention')}</summary><ul>{original.retention.map((row, index) =>
        <li key={index}>{t('compliance.retentionFlow', { entity: row.entity, field: row.date_field, days: row.days, action: t(`compliance.option_${row.action}`) })}</li>)}</ul></details>
      <details><summary>{t('compliance.emergency')}</summary><p>{t('compliance.breakFlow', { minutes: original.break_glass.max_minutes })}</p></details>
      <details><summary>{t('compliance.exportEntities')}</summary><p>{t('compliance.exportHint')}</p></details>
    </SettingsSection>
  </Stack>
}

function regulatedForm(t: ReturnType<typeof useT>, draft: Regulated, edit: (apply: (value: Regulated) => Regulated) => void,
  disabled: boolean, choices: ProjectSpec) {
  const { entities, entityFields, pick, enumeration } = editorFields(t, choices)
  const protectable = (entity: string) => entityFields(entity).filter(field =>
    ['string', 'text'].includes(field.type) && !field.unique && !field.indexed).map(field => field.name)
  const patch = (value: Partial<Regulated>) => edit(model => ({ ...model, ...value }))
  const rows = draft.fields.map((row, index) => {
    const update = (value: Partial<Regulated['fields'][number]>) => patch({ fields: updateItem(draft.fields, index, value) })
    const field = pick(`fields.${index}.field`, t('compliance.field'), row.field, protectable(row.entity), field => update({ field }))
    return [
      pick(`fields.${index}.entity`, t('compliance.entity'), row.entity, entities, entity =>
        update({ entity, field: keepChoice(row.field, protectable(entity)) })),
      { ...field, validate: [...field.validate, () => draft.fields.some((item, position) =>
        position !== index && item.entity === row.entity && item.field === row.field) ? { key: 'validation.accessDuplicateField' } : undefined] },
      enumeration(`fields.${index}.mode`, t('compliance.mode'), row.mode, modes,
        mode => update({ mode, searchable: mode === 'encrypt' && row.searchable })),
      ...row.mode === 'encrypt' ? [checkField(`fields.${index}.searchable`, t('compliance.searchable'), row.searchable,
        searchable => update({ searchable }))] : [],
    ]
  })
  const base = groups([{ title: t('compliance.regulated'), hint: t('compliance.keyHint'), fields: [
    { ...checkField('enabled', t('compliance.regulatedEnabled'), draft.enabled, enabled => patch({ enabled })),
      validate: [() => draft.enabled && !choices.auth ? { key: 'validation.complianceAuth' } : undefined] },
    { ...enumeration('key_provider', t('compliance.provider'), draft.key_provider, keyProviders, key_provider => patch({ key_provider })),
      validate: [() => draft.enabled && draft.key_provider === 'env' ? { key: 'validation.complianceManagedKey' } : undefined] },
  ] }])
  return { fields: [...base.fields, ...rows.flat()], layout: (controls: Record<string, ReactNode>) => <Stack gap={4}>
    {base.layout(controls)}
    <SettingsSection title={t('compliance.protectedFields')} description={t('compliance.protectedCount', { count: draft.fields.length })}>
      <RowEditor sections={rows} add={t('compliance.addProtected')} onAdd={() =>
        patch({ fields: [...draft.fields, { entity: '', field: '', mode: 'encrypt', searchable: false }] })}
        onRemove={index => patch({ fields: draft.fields.filter((_, position) => index !== position) })}
        limit={64} disabled={disabled} controls={controls} />
    </SettingsSection>
  </Stack> }
}

export function RegulatedSettings(props: SecureProps) {
  const t = useT()
  const { fallback, saved, choices, reload } = useBlock(props.projectId, 'regulated')
  if (fallback || !saved || !choices) return fallback
  return <Stack gap={4}>
    <div data-testid="regulated-summary">
      <SettingsSection title={t('compliance.regulatedSummary')}>
        <p>{t(saved.regulated === null ? 'compliance.notConfigured' : saved.regulated.enabled ? 'compliance.on' : 'compliance.off')}</p>
        {saved.regulated && <p>{t('compliance.protectedCount', { count: saved.regulated.fields.length })}</p>}
      </SettingsSection>
    </div>
    <BlockEditor {...props} block="regulated" saved={saved} defaults={defaultRegulated} reload={reload}
      render={(draft, edit, disabled) => regulatedForm(t, draft, edit, disabled, choices.spec)} />
  </Stack>
}
