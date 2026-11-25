import { Slot } from '@radix-ui/react-slot'
import * as SelectBase from '@radix-ui/react-select'
import { useId } from 'react'
import type { ComponentPropsWithRef, ReactNode } from 'react'
import { Stack } from './layout'
import { useLanguage } from '../i18n'

type ButtonProps = ComponentPropsWithRef<'button'> & {
  variant?: 'default' | 'primary' | 'danger' | 'ghost'
  asChild?: boolean
}

export function Button({ asChild, variant = 'default', className = '', type = 'button', ...props }: ButtonProps) {
  const classes = `v2-button ${className}`
  if (asChild) return <Slot className={classes} data-variant={variant} {...props} />
  return <button type={type} className={classes} data-variant={variant} {...props} />
}

export function IconButton({ label, className = '', ...props }: ButtonProps & { label: string }) {
  return <Button aria-label={label} className={`v2-icon-button ${className}`} {...props} />
}

export function Input({ className = '', ...props }: ComponentPropsWithRef<'input'>) {
  return <input className={`v2-control ${className}`} {...props} />
}

export function Textarea({ className = '', ...props }: ComponentPropsWithRef<'textarea'>) {
  return <textarea className={`v2-control ${className}`} rows={3} {...props} />
}

type SelectOption = { value: string; label: string; disabled?: boolean; group?: string }

type SelectProps = ComponentPropsWithRef<typeof SelectBase.Root> & {
  triggerProps?: ComponentPropsWithRef<typeof SelectBase.Trigger>
  placeholder?: string
  options: SelectOption[]
}

export function Select({ triggerProps, placeholder, options, ...props }: SelectProps) {
  const { dir } = useLanguage()
  const groups = new Map<string | undefined, SelectOption[]>()
  for (const option of options) {
    const group = groups.get(option.group) ?? []
    group.push(option)
    groups.set(option.group, group)
  }
  const item = ({ value, label, disabled }: SelectOption) => (
    <SelectBase.Item key={value} value={value} disabled={disabled} className="v2-option">
      <SelectBase.ItemText>{label}</SelectBase.ItemText>
      <SelectBase.ItemIndicator aria-hidden>{'✓'}</SelectBase.ItemIndicator>
    </SelectBase.Item>
  )
  return (
    <SelectBase.Root dir={dir} {...props}>
      <SelectBase.Trigger {...triggerProps} className="v2-control v2-select">
        <SelectBase.Value placeholder={placeholder} />
        <SelectBase.Icon aria-hidden>{'▾'}</SelectBase.Icon>
      </SelectBase.Trigger>
      <SelectBase.Portal>
        <SelectBase.Content position="popper" className="v2-popup">
          <SelectBase.Viewport>
            {[...groups].map(([group, entries]) => group
              ? <SelectBase.Group key={group}>
                <SelectBase.Label className="v2-select-group">{group}</SelectBase.Label>
                {entries.map(item)}
              </SelectBase.Group>
              : entries.map(item))}
          </SelectBase.Viewport>
        </SelectBase.Content>
      </SelectBase.Portal>
    </SelectBase.Root>
  )
}

type ChoiceProps = Omit<ComponentPropsWithRef<'input'>, 'type'> & { label: ReactNode }

function Choice({ label, type, ...props }: ChoiceProps & { type: 'checkbox' | 'radio' | 'switch' }) {
  return (
    <label className="v2-choice">
      <input {...props} type={type === 'radio' ? 'radio' : 'checkbox'} role={type === 'switch' ? 'switch' : undefined} />
      <span>{label}</span>
    </label>
  )
}

export function Checkbox(props: ChoiceProps) { return <Choice type="checkbox" {...props} /> }
export function Radio(props: ChoiceProps) { return <Choice type="radio" {...props} /> }
export function Switch(props: ChoiceProps) { return <Choice type="switch" {...props} /> }

export type FieldAttributes = { id: string; 'aria-describedby'?: string; 'aria-invalid'?: true }

export function Field({ id, label, hint, error, children }: {
  id?: string
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  children: (attributes: FieldAttributes) => ReactNode
}) {
  const generatedId = useId()
  const fieldId = id ?? generatedId
  const hintId = hint ? `${fieldId}-hint` : undefined
  const errorId = error ? `${fieldId}-error` : undefined
  return (
    <Stack gap={1}>
      <label className="v2-label" htmlFor={fieldId}>{label}</label>
      {children({ id: fieldId, 'aria-invalid': error ? true : undefined, 'aria-describedby': [hintId, errorId].filter(Boolean).join(' ') || undefined })}
      {hint && <span id={hintId} className="v2-muted v2-small">{hint}</span>}
      {error && <span id={errorId} role="alert" className="v2-field-error v2-small">{error}</span>}
    </Stack>
  )
}
