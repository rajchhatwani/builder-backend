import { useReducer, useState } from 'react'
import type { ReactNode } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, SettingsSection, type FormField } from '../../patterns'
import { Button, Dialog, EmptyState, Grid, Pagination, Row, Stack, Table } from '../../ui'
import { accessChecks, checkPolicyCondition } from '../../validators'
import { editableError, type Policy } from './api/controls'
import { fieldErrors } from './api/security'
import type { AccessEditorProps } from './AccessModel'
import { operations } from './state/access'
import { conditionBody, conditionDraft, conditionSize, emptyLeaf, emptyOperand, policyReducer, unary,
  type DraftCondition, type DraftOperand, type OperandKind } from './state/policy'
import { checkField, duplicateValue, pickField, textField, useSecureSearch } from './SecureForm'

const comparisons = ['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'in', 'not_in', 'contains', 'is_null', 'not_null', 'ip_in']
const kinds = ['subject', 'resource', 'env', 'literal'] as const
const templates = ['owner', 'hours', 'network', 'finished'] as const
const getOptions = (values: string[]) => values.map(value => ({ value, label: value }))
type Attributes = Record<Exclude<OperandKind, 'literal'>, string[]>
type ConditionForm = { fields: FormField[]; layout: (controls: Record<string, ReactNode>) => ReactNode }

function conditionForm(t: ReturnType<typeof useT>, node: DraftCondition, attributes: Attributes,
  onChange: (node: DraftCondition) => void, onRemove: () => void, depth: number, size: number, prefix: string): ConditionForm {
  const row = [pickField(prefix + '.kind', t('authorization.condition'), node.kind,
    ['comparison', 'all', 'any'].map(value => ({ value, label: t(`authorization.condition_${value}`) })), {
      change: kind => {
        if (kind === 'comparison') onChange(emptyLeaf())
        else if (kind === 'all' || kind === 'any') onChange({ kind, children: node.kind === 'comparison' ? [node] : node.children })
      },
    })]
  const shape = { ...row[0], validate: [() => checkPolicyCondition(node, depth, size)] }
  const remove = <Button variant="danger" onClick={onRemove}>{t('authorization.removeCondition')}</Button>

  if (node.kind !== 'comparison') {
    const children = node.children.map((item, index) => conditionForm(t, item, attributes,
      value => onChange({ ...node, children: node.children.map((child, i) => i === index ? value : child) }),
      () => onChange({ ...node, children: node.children.filter((_, i) => i !== index) }), depth + 1, size, prefix + '.' + index))
    return { fields: [shape, ...children.flatMap(item => item.fields)], layout: controls => <Stack className="v2-card" gap={3}>
      {controls[shape.name]}{children.map((item, index) => <div key={index}>{item.layout(controls)}</div>)}
      <Row><Button disabled={depth >= 4 || size >= 24} onClick={() => onChange({ ...node, children: [...node.children, emptyLeaf()] })}>
        {t('authorization.addCondition')}</Button>{remove}</Row>
    </Stack> }
  }
  function operand(side: 'left' | 'right', value: DraftOperand, update: (value: DraftOperand) => void) {
    const available = value.kind === 'literal' ? [] : attributes[value.kind]
    return [
      pickField(prefix + '.' + side + '.kind', t(`authorization.operand_${side}`), value.kind,
        kinds.map(kind => ({ value: kind, label: t(`authorization.kind_${kind}`) })), { change: next => update(emptyOperand(next as OperandKind)) }),
      value.kind === 'literal' ? textField(prefix + '.' + side + '.value', t('authorization.literal'), value.value,
        { required: true, controlled: true, checks: [accessChecks.literal], change: next => update({ ...value, value: next }) }) :
        pickField(prefix + '.' + side + '.value', t('authorization.attribute'), value.value,
          getOptions([...new Set([...available, ...value.value ? [value.value] : []])]), {
            required: true, placeholder: t('authorization.choose'), change: next => update({ ...value, value: next }),
          }),
    ]
  }
  const fields = [shape,
    ...operand('left', node.left, left => onChange({ ...node, left })),
    pickField(prefix + '.op', t('authorization.operator'), node.op,
      comparisons.map(value => ({ value, label: t(`authorization.compare_${value}`) })), { change: op => onChange({ ...node, op }) }),
    ...unary(node.op) ? [] : operand('right', node.right, right => onChange({ ...node, right })),
  ]
  return { fields, layout: controls => <Stack className="v2-card" gap={2}>
    <Grid>{fields.map(field => controls[field.name])}</Grid><Row>{remove}</Row>
  </Stack> }
}

function templatePolicy(template: typeof templates[number], entity: string, enabled: readonly string[]): Partial<Policy> {
  const actions = (names: string[]) => names.filter(name => enabled.includes(name)).map(name => entity + '.' + name)
  switch (template) {
    case 'owner': return { effect: 'allow', actions: [entity + '.*'],
      when: { left: { resource: 'created_by_id' }, op: 'eq', right: { subject: 'id' } } }
    case 'hours': return { effect: 'allow', actions: actions(['create', 'update', 'delete']), when: { all: [
      { left: { env: 'hour_utc' }, op: 'gte', right: { literal: 8 } },
      { left: { env: 'hour_utc' }, op: 'lt', right: { literal: 18 } },
    ] } }
    case 'network': return { effect: 'allow', actions: [entity + '.*'],
      when: { left: { env: 'client_ip' }, op: 'ip_in', right: { literal: ['10.0.0.0/8'] } } }
    case 'finished': return { effect: 'deny', actions: actions(['update', 'replace', 'delete']),
      when: { left: { resource: 'status' }, op: 'eq', right: { literal: 'done' } } }
  }
}

function describe(condition: DraftCondition | null, t: ReturnType<typeof useT>): string {
  if (!condition) return t('authorization.always')
  if (condition.kind !== 'comparison') return '(' + condition.children.map(child => describe(child, t))
    .join(t(condition.kind === 'all' ? 'authorization.joinAll' : 'authorization.joinAny')) + ')'
  const operand = (item: DraftOperand) => item.kind === 'literal' ? item.value :
    t('authorization.attributeName', { kind: t(`authorization.kind_${item.kind}`), name: item.value })
  return t('authorization.comparisonText', { left: operand(condition.left), op: t(`authorization.compare_${condition.op}`),
    right: unary(condition.op) ? '' : operand(condition.right) })
}

export function AccessPolicies({ settings, spec, roles, editable, busy, submit, error }: AccessEditorProps & { error: unknown }) {
  const t = useT()
  const { search, page: setPage } = useSecureSearch()
  const [draft, dispatch] = useReducer(policyReducer, null)
  const [templateEntity, setTemplateEntity] = useState<string>()
  const first = spec.entities.find(item => item.name === templateEntity) ?? spec.entities[0]
  const policy = draft?.policy
  const policies = settings.policies
  const detail = editableError(error)
  const pages = Math.ceil(policies.length / 10)
  const page = Math.min(search.page ?? 1, Math.max(1, pages))
  const visible = policies.slice((page - 1) * 10, page * 10)
  const roleChoices = [{ name: '*', label: t('authorization.everyone') }, ...roles]
  const possibleActions = ['*', ...spec.entities.flatMap(entity => [entity.name + '.*',
    ...(entity.options?.operations ?? operations).map(op => entity.name + '.' + op)])]
  const options = [...new Set([...possibleActions, ...(policy?.actions ?? [])])]
  const attributes = {
    subject: ['id', 'email', 'roles', ...spec.auth?.multi_tenant ? ['tenant_id'] : [],
      ...(spec.auth?.registration?.custom_fields ?? []).map(item => item.name)],
    resource: [...new Set(['id', 'created_at', 'updated_at', 'created_by_id', ...spec.entities.flatMap(item => item.fields.map(field => field.name))])],
    env: ['hour_utc', 'weekday_utc', 'client_ip'],
  }
  const change = (value: Partial<NonNullable<typeof policy>>) => dispatch({ type: 'change', value })
  const condition = policy?.when ? conditionForm(t, policy.when, attributes, when => change({ when }), () => change({ when: null }),
    1, conditionSize(policy.when), 'when') : null
  function open(existing?: Policy, template?: typeof templates[number]) {
    let index = policies.length + 1
    while (policies.some(item => item.id === 'policy_' + index)) index++
    const initial: Policy = existing ?? { id: 'policy_' + index, description: '', effect: 'allow', actions: [], when: null,
      ...(template && first ? { ...templatePolicy(template, first.name, first.options?.operations ?? operations),
        description: t(`authorization.template_${template}`) } : {}) }
    dispatch({ type: 'open', draft: { original: existing, base: settings, policy: { ...initial, when: conditionDraft(initial.when) } } })
  }
  function store(next: Policy) {
    if (!draft) return
    const base = draft.base
    const originalId = draft.original?.id
    const renamed = originalId && originalId !== next.id
    const attachments = Object.fromEntries(Object.entries(base.attachments).map(([role, ids]) =>
      [role, renamed ? ids.map(id => id === originalId ? next.id : id) : ids]))
    void submit({ kind: 'settings', settings: { ...base, attachments,
      policies: originalId ? base.policies.map(item => item.id === originalId ? next : item) : [...base.policies, next] } }).then(accepted => { if (accepted) dispatch({ type: 'close' }) })
  }
  function attach(role: string, policy: string, checked: boolean) {
    const selected = settings.attachments[role] ?? []
    void submit({ kind: 'settings', settings: { ...settings, attachments: { ...settings.attachments,
      [role]: checked ? [...selected, policy] : selected.filter(value => value !== policy),
    } } })
  }
  const fields = policy ? [
    textField('id', t('authorization.name'), policy.id, { required: true, max: 40, controlled: true, change: id => change({ id }),
      checks: [accessChecks.policyName, value => duplicateValue(value.trim(), policies.filter(item => item.id !== draft?.original?.id).map(item => item.id))] }),
    pickField('effect', t('authorization.effect'), policy.effect, ['allow', 'deny'].map(value => ({
      value, label: t(`authorization.effect_${value}`),
    })), { change: value => change({ effect: value === 'deny' ? 'deny' : 'allow' }) }),
    textField('description', t('authorization.description'), policy.description, { max: 600, area: true, controlled: true,
      change: description => change({ description }) }),
  ] : []
  const selectedActions = policy?.actions ?? []
  const actionFields = options.map((value, i) => {
    const control = checkField('action.' + i, value === '*' ? t('authorization.allActions') : value, selectedActions.includes(value),
      checked => change({ actions: checked ? [...selectedActions, value] : selectedActions.filter(item => item !== value) }))
    return i ? control : { ...control, validate: [() => !selectedActions.length || selectedActions.length > 200 ?
      { key: 'validation.accessActions' } : undefined] }
  })

  return <Stack gap={4}>
    <SettingsSection title={t('authorization.tab_policies')}>
      {editable && <Stack gap={2}>
        {policies.length < 200 && <Row><Button variant="primary" disabled={busy} onClick={() => open()}>{t('authorization.newPolicy')}</Button></Row>}
        {first && policies.length < 200 && <details><summary>{t('authorization.templates')}</summary>
          <Form fields={[pickField('template_entity', t('authorization.entity'), first.name, getOptions(spec.entities.map(item => item.name)),
            { change: setTemplateEntity })]} submitLabel={t('common.save')} submitProps={{ hidden: true }} onSubmit={() => undefined}>
            <Row>{templates.map(template => <Button key={template} disabled={busy} onClick={() => open(undefined, template)}>
              {t(`authorization.template_${template}`)}</Button>)}</Row>
          </Form>
        </details>}
      </Stack>}
      {policies.length ? visible.map(item => <Stack key={item.id} className="v2-card" gap={2}>
        <Row className="v2-spread"><h3>{item.id}</h3><strong>{t(`authorization.effect_${item.effect}`)}</strong></Row>
        {item.description && <p>{item.description}</p>}
        <p>{t('authorization.actionsText', { actions: item.actions.join(', ') })}</p>
        <p>{t('authorization.whenText', { condition: describe(conditionDraft(item.when), t) })}</p>
        <p>{t('authorization.appliesTo', { roles: settings.model === 'abac' ? t('authorization.everyone') :
          roleChoices.filter(role => settings.attachments[role.name]?.includes(item.id)).map(role => role.label).join(', ') || t('authorization.nobody'),
        })}</p>
        {editable && <Row>
          <Button disabled={busy} onClick={() => open(item)}>{t('authorization.edit')}</Button>
          <ConfirmDestructive trigger={<Button disabled={busy} variant="danger">{t('authorization.delete')}</Button>}
            title={t('authorization.deletePolicy', { name: item.id })} description={t('authorization.deletePolicyHelp')} action={t('authorization.delete')}
            onConfirm={async () => { await submit({ kind: 'settings', settings: { ...settings, policies: policies.filter(policy => policy.id !== item.id),
              attachments: Object.fromEntries(Object.entries(settings.attachments).map(([role, ids]) => [role, ids.filter(id => id !== item.id)])),
            } }) }} />
        </Row>}
      </Stack>) : <EmptyState title={t('authorization.noPolicies')} action={editable ?
        <Button onClick={() => open()}>{t('authorization.newPolicy')}</Button> :
        <Button onClick={() => setPage(1)}>{t('authorization.tab_policies')}</Button>} />}
      {pages > 1 && <Pagination page={page} pages={pages} onChange={setPage} label={t('authorization.tab_policies')} />}
    </SettingsSection>
    {settings.model === 'pbac' && Boolean(visible.length) && <SettingsSection title={t('authorization.attachments')}>
      <Table label={t('authorization.attachments')} columns={[{ id: 'policy', label: t('authorization.policy') },
        ...roleChoices.map(role => ({ id: role.name, label: role.label }))]} rows={visible.map(policy => ({
          id: policy.id, cells: [policy.id, ...roleChoices.map(role => {
            const active = settings.attachments[role.name]?.includes(policy.id) ?? false
            return editable ? <Button aria-pressed={active} disabled={busy} aria-label={t('authorization.attachmentLabel', { role: role.label, policy: policy.id })}
              onClick={() => attach(role.name, policy.id, !active)}>{t(active ? 'authorization.yes' : 'authorization.no')}</Button> :
              t(active ? 'authorization.yes' : 'authorization.no')
          })],
        }))} />
    </SettingsSection>}
    {policy && <Dialog open title={t(draft.original ? 'authorization.editPolicy' : 'authorization.newPolicy')}
      onOpenChange={open => { if (!open) dispatch({ type: 'close' }) }}>
      <Form fields={[...fields, ...actionFields, ...(condition?.fields ?? [])]} pending={busy} submitLabel={t('common.save')}
        serverErrors={fieldErrors(error)} formError={error && !Object.keys(fieldErrors(error)).length
          ? detail ? t('secure.fieldError', { message: detail }) : t('authorization.policySaveError') : undefined} layout={controls => <Stack>
          {fields.map(field => controls[field.name])}
          <fieldset><legend>{t('authorization.actions')}</legend><Grid>{actionFields.map(field => controls[field.name])}</Grid></fieldset>
          <Stack gap={1}><h3>{t('authorization.onlyWhen')}</h3>
            <p className="v2-muted">{t('authorization.conditionLimit')}</p></Stack>
          {condition ? condition.layout(controls) : <Row><Button onClick={() => change({ when: emptyLeaf() })}>{t('authorization.addCondition')}</Button></Row>}
        </Stack>}
        onSubmit={() => store({ ...policy, id: policy.id.trim(), when: conditionBody(policy.when) })} />
    </Dialog>}
  </Stack>
}
