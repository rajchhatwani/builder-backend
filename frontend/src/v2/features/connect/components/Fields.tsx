import type { ReactNode } from 'react'
import { useT } from '../../../i18n'
import { SettingsSection } from '../../../patterns'
import type { FormField } from '../../../patterns'
import { Button, Checkbox, Disclosure, Grid, Input, Radio, Row, Select, Stack, Textarea } from '../../../ui'
import { connectList, validators } from '../../../validators'
import type { ValidationIssue, Validator } from '../../../validators'
import { checked, list, text } from '../state/draft'
import type { DraftValue, SettingsDraft } from '../state/draft'

type Choice = { value: string; label: string; description?: string }
export type EditorProps = {
  draft: SettingsDraft
  change: (name: string, value: DraftValue) => void
  guided: boolean
}
export type Group = { title: string; description?: string; fields: FormField[]; extra?: ReactNode; disclosure?: string }

export function SettingsGroups({ groups, controls }: { groups: Group[]; controls: Record<string, ReactNode> }) {
  return <Stack>{groups.map(({ title, description, fields, extra, disclosure }) => {
    const content = <Stack><Grid>{fields.map(field => controls[field.name])}</Grid>{extra}</Stack>
    return <SettingsSection key={title} title={title} description={description}>
      {disclosure ? <Disclosure label={disclosure}>{content}</Disclosure> : content}
    </SettingsSection>
  })}</Stack>
}

export function useFields({ draft, change, guided }: EditorProps, kind: string) {
  const t = useT()
  const label = (name: string) => t('connect.' + kind + '.fields.' + name)
  const field = (name: string, control: FormField['control'], options?: Partial<FormField>): FormField =>
    ({ name, label: label(name), control, ...options })

  function input(name: string, validate: Validator[] = [], options: { hint?: string; placeholder?: string; maxLength?: number } = {}) {
    const { hint, ...attributes } = options
    return field(name, props => <Input {...props} {...attributes} value={text(draft, name)}
      onChange={event => change(name, event.target.value)} />, { validate, hint })
  }
  function numeric(name: string, min: number, max: number, optional = false, extra?: Validator) {
    const validate = [validators.number({ min, max, integer: true })]
    if (!optional) validate.unshift(validators.required)
    if (extra) validate.push(extra)
    return field(name, props => <Input {...props} inputMode="numeric" value={text(draft, name)}
      onChange={event => change(name, event.target.value)} />, {
      validate, hint: t('connect.range', { min, max }),
    })
  }
  function toggle(name: string) {
    return field(name, props => <Checkbox {...props} checked={checked(draft, name)}
      onChange={event => change(name, event.target.checked)} label={label(name)} />, { ownLabel: true })
  }
  function choice(name: string, choices: Choice[], options: {
    cards?: boolean; required?: boolean; validate?: Validator[]; allowEmpty?: boolean; hint?: string; onPick?: (value: string) => void
  } = {}) {
    const { cards, required, allowEmpty, hint, onPick } = options
    const value = text(draft, name)
    const empty = 'connect-none'
    const all = value && !choices.some(item => item.value === value)
      ? [...choices, { value, label: value }] : choices
    const validate = [...(required ? [validators.required] : []), ...(options.validate ?? [])]
    const pick = (next: string) => {
      change(name, next === empty ? '' : next)
      onPick?.(next)
    }
    return field(name, ({ disabled, ...props }) => guided && cards ? (
      <Stack gap={1} role="radiogroup" aria-label={label(name)} aria-describedby={props['aria-describedby']}>
        {all.map((item, index) => <Radio key={item.value} {...props} id={index === 0 ? props.id : undefined}
          disabled={disabled} value={item.value} checked={value === item.value}
          onChange={() => pick(item.value)} label={<Stack gap={1}><strong>{item.label}</strong>
            {item.description && <span className="v2-muted">{item.description}</span>}</Stack>} />)}
      </Stack>
    ) : (
      <Select name={props.name} disabled={disabled} triggerProps={props} value={value || empty}
        onValueChange={pick} placeholder={t('connect.choose')}
        options={[...(allowEmpty || !value ? [{ value: empty, label: t('connect.choose'), disabled: !allowEmpty }] : []), ...all]} />
    ), {
      ownLabel: guided && cards, hint,
      validateWith: () => validate.map(check => check(text(draft, name))).find(Boolean),
    })
  }
  function values(name: string, check: (list: string[]) => ValidationIssue | undefined, options: {
    choices?: Choice[]; hint?: string; placeholder?: string; quickAdd?: { label: string; values: string[] }[]
  } = {}) {
    const selected = list(draft, name)
    const { choices, hint, placeholder, quickAdd } = options
    const all = choices && [...choices, ...selected.filter(value => !choices.some(item => item.value === value)).map(value => ({ value, label: value }))]
    return field(name, ({ disabled, ...props }) => all ? (
      <Stack gap={1} role="group" aria-label={label(name)} aria-describedby={props['aria-describedby']}>
        {all.length ? <Row gap={2}>{all.map((option, index) => <Checkbox key={option.value} {...props}
          id={index === 0 ? props.id : undefined} disabled={disabled} value={option.value} checked={selected.includes(option.value)}
          aria-label={t('connect.choiceLabel', { field: label(name), option: option.label })}
          onChange={event => change(name, event.target.checked ? [...selected, option.value] : selected.filter(value => value !== option.value))}
          label={option.label} />)}</Row> : <p className="v2-muted">{t('connect.noRoles')}</p>}
      </Stack>
    ) : <Stack gap={1}>
      <Textarea {...props} disabled={disabled} placeholder={placeholder}
        value={Array.isArray(draft[name]) ? selected.join('\n') : text(draft, name)}
        onChange={event => change(name, event.target.value)} />
      {quickAdd && !disabled && <QuickAdd groups={quickAdd} onAdd={entries => change(name, [...new Set([...selected, ...entries])])} />}
    </Stack>, { ownLabel: Boolean(all), hint, validateWith: () => check(selected) })
  }

  function permissions(actions: readonly string[], roles?: Choice[]): Group {
    return {
      title: t('connect.permissions'), description: t('connect.' + kind + '.permissionsHelp'),
      fields: actions.map(action => values('roles.' + action, connectList(50), { choices: guided ? roles : undefined })),
    }
  }
  return { input, numeric, toggle, choice, values, permissions }
}

function QuickAdd({ groups, onAdd }: { groups: { label: string; values: string[] }[]; onAdd: (values: string[]) => void }) {
  return <Row gap={2}>{groups.map(group =>
    <Button key={group.label} onClick={() => onAdd(group.values)}>{group.label}</Button>)}</Row>
}
