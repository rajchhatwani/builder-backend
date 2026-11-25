import { useSearch } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { useT } from '../../i18n'
import { Form } from '../../patterns'
import { Input, Row } from '../../ui'
import type { ValidationIssue } from '../../validators'
import { entryLimits, newPasswordChecks, validators } from '../../validators'
import { entryApi, entryError, useEntryAction } from './api/entry'
import { BackToSignIn, EntryCard, EntryFrame, EntryProblem } from './components/EntryFrame'
import { ResendVerification, startResendCooldown } from './components/ResendVerification'
import { emailField, passwordField, valueOf } from './components/fields'
import { authProblem, passwordProblemKey } from './components/messages'

export default function SignupScreen() {
  const t = useT()
  const { next } = useSearch({ strict: false })
  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState('')
  const action = useEntryAction()
  const { code, message } = entryError(action.error)
  const fields = useMemo((): Record<string, ValidationIssue> | undefined => {
    if (code === 'invalid_email') return { email: { key: 'entry.invalidEmail' } }
    if (code === 'weak_password') return { password: { key: passwordProblemKey(message) } }
  }, [code, message])

  function register(values: FormData) {
    const address = valueOf(values, 'email').trim()
    const name = valueOf(values, 'name').trim()
    const password = valueOf(values, 'password')
    action.run(async () => {
      await entryApi.register({ email: address, password, name })
      startResendCooldown(address)
      setSentTo(address)
    })
  }

  if (sentTo) return <EntryFrame testId="check-inbox" title={t('entry.checkInbox')}>
    <EntryCard title={t('entry.confirmEmail')}>
      <p role="status">{t('entry.inboxMessage')}</p>
      <p>{t('entry.inboxDetails', { email: sentTo })}</p>
      <ResendVerification initialEmail={sentTo} />
      <Row><BackToSignIn next={next} /></Row>
    </EntryCard>
  </EntryFrame>

  return <EntryFrame title={t('entry.createAccountTitle')}>
    <EntryCard title={t('shell.product')}>
      {action.isError && !fields && <EntryProblem error={action.error} message={t(authProblem(action.error))} />}
      <Form fields={[
        { name: 'name', label: t('entry.name'), validate: [validators.length(entryLimits.name)],
          control: attributes => <Input {...attributes} autoComplete="name" maxLength={entryLimits.name} /> },
        emailField(t('entry.email'), email, setEmail),
        passwordField(t('entry.password'), 'password', newPasswordChecks(email), t('entry.passwordHint')),
      ]} submitLabel={t(action.isPending ? 'entry.pleaseWait' : 'entry.createAccount')}
        pending={action.isPending} serverErrors={fields} onSubmit={register} />
    </EntryCard>
    <Row><p>{t('entry.haveAccount')}</p><BackToSignIn label={t('shell.signIn')} next={next} /></Row>
  </EntryFrame>
}
