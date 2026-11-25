import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import { Alert, Button, Checkbox, ErrorBoundary, Input, Row, Skeleton, Stack, useToast } from '../../../ui'
import { checkTotp, entryLimits, validators } from '../../../validators'
import { entryApi, entryError, useEntryAction } from '../api/entry'
import type { MfaChallenge, TotpSetup, UserAccount } from '../api/entry'
import { EntryCard, EntryProblem } from './EntryFrame'
import { valueOf } from './fields'
import { authProblem } from './messages'

const QrImage = lazy(() => import('./QrImage'))
const invalidCode = { key: 'entry.invalidCode' }

function useCopy() {
  const t = useT()
  const toast = useToast()
  return async (value: string, key: string) => {
    try {
      await navigator.clipboard.writeText(value)
      toast({ title: t(key), tone: 'success' })
    } catch {
      toast({ title: t('entry.copyFailed'), tone: 'danger' })
    }
  }
}

function Authenticator({ setup }: { setup: TotpSetup }) {
  const t = useT()
  const copy = useCopy()
  const help = <Alert>{t('entry.qrFallback')}</Alert>
  return <Stack>
    <p>{t('entry.scanQr')}</p>
    <ErrorBoundary fallback={() => help}>
      <Suspense fallback={<div className="v2-entry-qr"><Skeleton label={t('entry.qrLoading')} /></div>}>
        <QrImage value={setup.otpauth_uri} />
      </Suspense>
    </ErrorBoundary>
    <p>{t('entry.enterKey')}</p>
    <code>{setup.secret.match(/.{1,4}/g)?.join(' ')}</code>
    <Row>
      <Button onClick={() => void copy(setup.secret, 'entry.keyCopied')}>{t('entry.copyKey')}</Button>
      {setup.otpauth_uri.startsWith('otpauth:') && <Button asChild><a href={setup.otpauth_uri}>{t('entry.openAuthenticator')}</a></Button>}
    </Row>
    <p className="v2-muted">{t('entry.otpHint')}</p>
  </Stack>
}

export function SecondFactor({ challenge, onComplete, onRecovery, onCancel }: {
  challenge: MfaChallenge; onComplete: (user: UserAccount) => void; onRecovery: (user: UserAccount, codes: string[]) => void; onCancel: () => void
}) {
  const t = useT()
  const started = useRef(false)
  const checked = useEntryAction()
  const setupAction = useEntryAction()
  const [setup, setSetup] = useState<TotpSetup>()
  const enrolling = challenge.enrollment_required
  const codeError = entryError(checked.error).code === 'invalid_mfa_code'
  const expired = [setupAction.error, checked.error].some(error => entryError(error).code === 'invalid_mfa_token')

  const runSetup = setupAction.run
  useEffect(() => {
    if (!enrolling || started.current) return
    started.current = true
    runSetup(async () => setSetup(await entryApi.loginMfa.setup(challenge.mfa_token)))
  }, [enrolling, runSetup, challenge.mfa_token])

  function submit(code: string) {
    checked.run(async () => {
      if (enrolling) {
        const { user, recovery_codes } = await entryApi.loginMfa.enable(challenge.mfa_token, code)
        onRecovery(user, recovery_codes)
      } else {
        const { user } = await entryApi.loginMfa.verify(challenge.mfa_token, code)
        onComplete(user)
      }
    })
  }

  return <>
    <EntryCard title={t(enrolling ? 'entry.mfaSetup' : 'entry.mfa')}>
    {enrolling && <p>{t('entry.staffMfa')}</p>}
    {enrolling && !setup && (setupAction.isError
      ? <EntryProblem error={setupAction.error} message={t(authProblem(setupAction.error))}
          retry={expired ? undefined : () => runSetup(async () => setSetup(await entryApi.loginMfa.setup(challenge.mfa_token)))} />
      : <Skeleton lines={5} label={t('entry.loadingSetup')} />)}
    {setup && <Authenticator setup={setup} />}
    {checked.isError && !codeError && <EntryProblem error={checked.error} message={t(authProblem(checked.error))} />}
    {!expired && (!enrolling || setup) && <Form fields={[{
      name: 'code', label: t(enrolling ? 'entry.totpCode' : 'entry.mfaCode'),
      validate: enrolling ? [checkTotp] : [validators.required, validators.length(entryLimits.code)],
      control: attributes => <Input {...attributes} required autoComplete="one-time-code" maxLength={entryLimits.code}
        inputMode={enrolling ? 'numeric' : undefined} />,
    }]} pending={checked.isPending} serverErrors={codeError ? { code: invalidCode } : undefined}
      submitLabel={t(enrolling ? 'entry.enableMfa' : 'entry.verifyCode')}
      onSubmit={values => submit(valueOf(values, 'code').trim())} />}
    </EntryCard>
    <Row><Button onClick={onCancel} disabled={checked.isPending}>{t('entry.differentAccount')}</Button></Row>
  </>
}

export function RecoveryCodes({ codes, onSaved }: { codes: string[]; onSaved: () => void }) {
  const t = useT()
  const [saved, setSaved] = useState(false)
  const copy = useCopy()
  const text = codes.join('\n')

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    const link = document.createElement('a')
    link.href = url
    link.download = t('entry.codesFileName')
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  return <EntryCard title={t('entry.recoveryCodes')}>
    <p>{t('entry.saveCodes')}</p>
    <ul className="v2-entry-codes">{codes.map(code => <li key={code}><code>{code}</code></li>)}</ul>
    <Row>
      <Button onClick={() => void copy(text, 'entry.codesCopied')}>{t('entry.copy')}</Button>
      <Button onClick={download}>{t('entry.download')}</Button>
    </Row>
    <Checkbox label={t('entry.savedCodes')} checked={saved} onChange={event => setSaved(event.target.checked)} />
    <Row><Button variant="primary" onClick={onSaved} disabled={!saved}>{t('entry.continue')}</Button></Row>
  </EntryCard>
}
