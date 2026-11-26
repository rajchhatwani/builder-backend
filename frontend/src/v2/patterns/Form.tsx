import { useId, useState } from 'react'
import type { ComponentProps, FormEvent, ReactNode } from 'react'
import { useT } from '../i18n'
import { Alert, Button, Field, Row, Spinner, Stack } from '../ui'
import type { FieldAttributes } from '../ui'
import type { ValidationIssue, Validator } from '../validators'

export type FormField = {
  name: string
  label: string
  hint?: string
  ownLabel?: boolean
  errorTestId?: string
  validate?: Validator[]
  validateWith?: (value: string, data: FormData) => ValidationIssue | undefined
  control: (attributes: FieldAttributes & { name: string; disabled?: boolean }) => ReactNode
}
type Errors = Record<string, ValidationIssue>

function firstIssue(field: FormField, data: FormData) {
  const value = String(data.get(field.name) ?? '')
  return field.validate?.map(validate => validate(value)).find(Boolean) ?? field.validateWith?.(value, data)
}

export function Form({ fields, onSubmit, submitLabel, pending, readOnly, serverErrors, formError, submitProps, preserveFocusOnSubmit, actions, children, layout }: {
  fields: FormField[]
  actions?: ReactNode
  children?: ReactNode
  layout?: (fields: Record<string, ReactNode>) => ReactNode
  onSubmit: (values: FormData) => void
  submitLabel: string
  pending?: boolean
  readOnly?: boolean
  serverErrors?: Errors
  formError?: string
  submitProps?: ComponentProps<typeof Button> & { 'data-testid'?: string }
  preserveFocusOnSubmit?: boolean
}) {
  const t = useT()
  const id = useId()
  const [errors, setErrors] = useState<Errors>({})
  const [edited, setEdited] = useState<Record<string, ValidationIssue | undefined>>({})

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending || readOnly || submitProps?.disabled) return
    const data = new FormData(event.currentTarget)
    const next: Errors = {}
    for (const field of fields) {
      const issue = firstIssue(field, data)
      if (issue) next[field.name] = issue
    }
    setErrors(next)
    const first = Object.keys(next)[0]
    if (first) {
      const control = document.getElementById(`${id}-${first}`)
      const disclosure = control?.closest('details')
      if (disclosure) disclosure.open = true
      control?.focus()
      return
    }
    setEdited({})
    onSubmit(data)
  }

  const controls = fields.map(field => {
    const fieldId = `${id}-${field.name}`
    const error = errors[field.name] ?? (Object.hasOwn(edited, field.name) && edited[field.name] === serverErrors?.[field.name] ? undefined : serverErrors?.[field.name])
    const message = error && t(error.key, { ...error.values, field: field.label })
    return [field.name, (
      <div key={field.name} onChange={() => setEdited(current => ({ ...current, [field.name]: serverErrors?.[field.name] }))}
        onBlur={event => {
          const form = event.currentTarget.closest('form')
          // Disabling a focused control can blur it after FormData has stopped including its value.
          if (pending || readOnly || !form || event.currentTarget.contains(event.relatedTarget)) return
          const issue = firstIssue(field, new FormData(form))
          setErrors(previous => {
            const next = { ...previous }
            if (issue) next[field.name] = issue
            else delete next[field.name]
            return next
          })
        }}>
        <Field id={fieldId} label={field.ownLabel ? undefined : field.label} hint={field.hint} error={message && (field.errorTestId ? <span data-testid={field.errorTestId}>{message}</span> : message)}>
          {attributes => field.control({ ...attributes, name: field.name, disabled: readOnly || pending })}
        </Field>
      </div>
    )] as const
  })

  return (
    <form noValidate onSubmit={submit} aria-busy={pending}>
      <Stack>
        {layout ? layout(Object.fromEntries(controls)) : controls.map(([, control]) => control)}
        {children}
        {formError && <Alert tone="danger">{formError}</Alert>}
        {!submitProps?.hidden && <Row>
          <Button {...submitProps} type="submit" variant={submitProps?.variant ?? 'primary'}
            disabled={readOnly || pending || submitProps?.disabled}
            onMouseDown={preserveFocusOnSubmit ? event => {
              submitProps?.onMouseDown?.(event)
              // Submit validates the whole form. Keep a focused field from moving the button on blur before the click.
              if (event.button === 0 && event.currentTarget.form?.contains(document.activeElement)) event.preventDefault()
            } : submitProps?.onMouseDown}>
            {pending && <Spinner />}{submitLabel}
          </Button>
          {actions}
        </Row>}
      </Stack>
    </form>
  )
}
