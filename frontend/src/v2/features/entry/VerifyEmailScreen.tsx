import { useLocation, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { useT } from '../../i18n'
import { Alert, Row } from '../../ui'
import { entryLimits } from '../../validators'
import { entryApi, entryError, entryKeys, useEntryAction } from './api/entry'
import { BackToSignIn, EntryCard, EntryFrame, EntryLoading, EntryProblem } from './components/EntryFrame'
import { ResendVerification } from './components/ResendVerification'
import { consumeEntryVerification } from './entryLinks'

export default function VerifyEmailScreen() {
  const t = useT()
  const navigate = useNavigate()
  const search = useLocation({ select: location => location.searchStr })
  const incoming = new URLSearchParams(search).get('token')
  const [token, setToken] = useState(incoming ?? undefined)
  const started = useRef(false)
  const verification = useEntryAction()
  const client = useQueryClient()
  const valid = token && token.length >= entryLimits.verifyMin && token.length <= entryLimits.verifyMax
  const run = verification.run
  const verify = useCallback(async (code: string) => {
    await entryApi.verifyEmail(code)
    setToken(undefined)
    if (client.getQueryData(entryKeys.session())) void client.invalidateQueries({ queryKey: entryKeys.session() })
  }, [client])

  useLayoutEffect(() => {
    if (started.current) return
    started.current = true
    const addressToken = consumeEntryVerification() ?? incoming
    if (incoming !== null) void navigate({ to: '/verify-email', search: { token: undefined }, replace: true })
    if (addressToken) setToken(addressToken)
    if (addressToken && addressToken.length >= entryLimits.verifyMin && addressToken.length <= entryLimits.verifyMax) {
      run(() => verify(addressToken))
    }
  }, [incoming, navigate, run, verify])

  const status = entryError(verification.error).status
  const retryable = verification.isError && (!status || status === 429 || status >= 500)
  const error = !token ? 'entry.verifyMissing'
    : !retryable ? 'entry.verifyBad' : status === 429 ? 'entry.rateLimit' : status ? 'entry.requestFailed' : 'entry.network'
  function retry() {
    if (!valid) return
    run(() => verify(token))
  }

  return <EntryFrame title={t('entry.confirmEmail')}>
    {verification.isSuccess ? <>
      <div data-testid="verify-ok"><Alert tone="success">{t('entry.verifyDone')}</Alert></div>
      <Row data-testid="verify-signin"><BackToSignIn label={t('shell.signIn')} /></Row>
    </> : valid && !verification.isError ? <EntryLoading label={t('entry.confirming')} /> :
      <EntryCard title={t('entry.confirmationLink')}>
        <div data-testid="verify-bad"><EntryProblem error={verification.error} message={t(error)} retry={retryable ? retry : undefined} /></div>
        <ResendVerification showHint />
        <Row><BackToSignIn /></Row>
      </EntryCard>}
  </EntryFrame>
}
