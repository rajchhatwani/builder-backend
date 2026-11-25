import { Link, useSearch } from '@tanstack/react-router'
import { useReducer, useState } from 'react'
import { useT } from '../../i18n'
import { Form } from '../../patterns'
import { Alert, Button, Row, Stack } from '../../ui'
import { entryApi, entryError, useEntryAction, useSetCustomer } from './api/entry'
import { EntryCard, EntryFrame, EntryLoading, EntryProblem } from './components/EntryFrame'
import { ResendVerification } from './components/ResendVerification'
import { RecoveryCodes, SecondFactor } from './components/SecondFactor'
import { emailField, passwordField, valueOf } from './components/fields'
import { authProblem, authProblemValues } from './components/messages'
import { startSso } from './entryLinks'
import { initialSignIn, signInReducer } from './state/signIn'

const ssoReasons = new Set([
  'sso_unavailable', 'email_domain_not_verified', 'not_provisioned', 'seat_limit',
  'account_suspended', 'staff_account', 'invalid_request_state', 'bad_signature', 'idp_error',
  'malformed', 'discovery_failed', 'jwks_failed', 'insecure_url', 'invalid_test_ticket',
])

export default function SignInScreen() {
  const t = useT()
  const { next, sso_error: ssoError } = useSearch({ strict: false })
  const [email, setEmail] = useState('')
  const [resend, showResend] = useState(false)
  const [dismissedSso, dismissSso] = useState(false)
  const [state, dispatch] = useReducer(signInReducer, initialSignIn)
  const action = useEntryAction()
  const setCustomer = useSetCustomer()
  const { code, status } = entryError(action.error)
  const emailError = code === 'invalid_email' ? { email: { key: 'entry.invalidEmail' } } : undefined
  const failure = action.isError && !emailError && status !== 401 &&
    <EntryProblem error={action.error} message={t(authProblem(action.error), authProblemValues(action.error))} />

  function reset() {
    action.reset()
    dispatch({ type: 'reset' })
    showResend(false)
    dismissSso(true)
  }

  function discover() {
    const address = email.trim()
    dismissSso(true)
    action.run(async () => {
      const result = await entryApi.discoverLogin(address)
      dispatch({ type: 'discovered', email: address, result })
    })
  }

  function signIn(values: FormData) {
    const password = valueOf(values, 'password')
    action.run(async () => {
      const result = await entryApi.login(state.email, password)
      if (result.challenge) dispatch({ type: 'challenge', challenge: result.challenge })
      else if (result.user) setCustomer(result.user)
    })
  }

  if (state.step === 'recovery') {
    const { user, codes } = state
    return <EntryFrame title={t('entry.mfaOn')}><RecoveryCodes codes={codes} onSaved={() => setCustomer(user)} /></EntryFrame>
  }

  return <EntryFrame title={t('shell.signIn')}>
    {state.step === 'mfa' ? <SecondFactor challenge={state.challenge} onComplete={setCustomer}
        onRecovery={(user, codes) => dispatch({ type: 'recovery', user, codes })} onCancel={reset} /> : <>
      {action.isPending && state.step === 'email' ? <EntryLoading label={t('entry.pleaseWait')} /> :
        <EntryCard title={t('shell.product')}>
          {!dismissedSso && ssoError && <Alert tone="danger">{t(ssoReasons.has(ssoError) ? `entry.sso.${ssoError}` : 'entry.ssoFailed', { reason: /^[a-z_]{1,64}$/.test(ssoError) ? ssoError : t('entry.ssoUnknown') })}</Alert>}
          {failure}
          {state.step === 'email' ? <Form fields={[emailField(t('entry.email'), email, setEmail)]}
            submitLabel={t('entry.continue')} onSubmit={discover} serverErrors={emailError} /> :
            <Stack>
              <p className="v2-muted">{state.email}</p>
              <Row><Button onClick={reset} disabled={action.isPending}>{t('entry.differentEmail')}</Button></Row>
              {state.step === 'sso' ? <>
                <p>{t('entry.ssoDescription', { org: state.organization ?? t('entry.yourOrg') })}</p>
                <Row>
                  <Button variant="primary" onClick={() => startSso(state.url, next)}>
                    {state.organization ? t('entry.continueSsoOrg', { org: state.organization }) : t('entry.continueSso')}
                  </Button>
                  <Button onClick={() => dispatch({ type: 'password' })}>{t('entry.usePassword')}</Button>
                </Row>
              </> : <>
                <Form fields={[passwordField(t('entry.password'))]} pending={action.isPending}
                  submitLabel={t(action.isPending ? 'entry.pleaseWait' : 'shell.signIn')} onSubmit={signIn}
                  serverErrors={status === 401 ? { password: { key: 'entry.invalidCredentials' } } : undefined} />
                <Row><Button variant="ghost" aria-expanded={resend} onClick={() => showResend(!resend)}>{t('entry.resendConfirmation')}</Button></Row>
                {resend && <ResendVerification initialEmail={state.email} />}
              </>}
            </Stack>}
        </EntryCard>}
      <Row><p>{t('entry.newHere')}</p><Button asChild variant="ghost">
        <Link to="/signup" search={{ next }}>{t('entry.createAnAccount')}</Link>
      </Button></Row>
    </>}
  </EntryFrame>
}
