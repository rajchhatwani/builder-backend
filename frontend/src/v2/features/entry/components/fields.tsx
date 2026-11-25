import type { FormField } from '../../../patterns/Form'
import { Input } from '../../../ui'
import { checkPresentPassword, entryEmailChecks, entryLimits, validators } from '../../../validators'
import type { Validator } from '../../../validators'

export const valueOf = (values: FormData, name: string) => String(values.get(name) ?? '')

export function emailField(label: string, value: string, onChange: (value: string) => void): FormField {
  return {
    name: 'email', label, validate: entryEmailChecks,
    control: attributes => <Input {...attributes} type="email" autoComplete="email" required maxLength={entryLimits.email}
      value={value} onChange={event => onChange(event.target.value)} />,
  }
}

export function passwordField(label: string, name = 'password', checks?: Validator[], hint?: string): FormField {
  const maxLength = checks ? entryLimits.passwordMax : entryLimits.loginPassword
  return {
    name, label, hint, validate: checks ?? [checkPresentPassword, validators.length(maxLength)],
    control: attributes => <Input {...attributes} type="password" autoComplete={checks ? 'new-password' : 'current-password'}
      required maxLength={maxLength} />,
  }
}
