import { Link, useBlocker, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useReducer, useRef, useState } from 'react'
import { useLanguage, useT } from '../../../i18n'
import { ConfirmDestructive, Form, ReadOnlyNote, SettingsSection } from '../../../patterns'
import { Alert, Badge, Button, Input, Row, Skeleton, Stack, useToast } from '../../../ui'
import { checkTotp, checkTotpOrRecovery, entryLimits } from '../../../validators'
import type { ValidationIssue } from '../../../validators'
import { accountApi, accountKeys, mfaOptions } from '../api/account'
import { clearCustomerQueries, entryApi, entryError, entryKeys, useEntryAction, useSetCustomer } from '../api/entry'
import { accountMfaReducer, idleMfa } from '../state/accountMfa'
import type { MfaStep } from '../state/accountMfa'
import { EntryProblem } from './EntryFrame'
import { Authenticator, RecoveryCodes } from './SecondFactor'
import { formatEntryDate } from './entryData'
import { passwordField, valueOf } from './fields'
import { authProblem } from './messages'

export function AccountMfa() {
  const t = useT()
  const { language } = useLanguage()
  const toast = useToast()
  const client = useQueryClient()
  const navigate = useNavigate()
  const setCustomer = useSetCustomer()
  const status = useQuery(mfaOptions)
  const [state, dispatch] = useReducer(accountMfaReducer, idleMfa)
  const [confirming, setConfirming] = useState(false)
  const [codeRevision, setCodeRevision] = useState(0)
  const confirmation = useRef<FormData | null>(null)
  const action = useEntryAction()
  const signOut = useEntryAction()
  const { code } = entryError(action.error)
  const errors: Record<string, ValidationIssue> | undefined = code === 'invalid_password' ? { password: { key: 'account.mfaPasswordWrong' } }
    : code === 'invalid_mfa_code' ? { code: { key: 'entry.invalidCode' } } : undefined
  const destructive = state.step === 'disable' || state.step === 'regenerate'
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => state.step === 'codes' && current.pathname !== next.pathname,
    enableBeforeUnload: state.step === 'codes',
    withResolver: true,
  })

  useEffect(() => {
    if (blocker.status === 'blocked') blocker.reset()
  }, [blocker])

  function refresh() {
    void client.invalidateQueries({ queryKey: accountKeys.mfa() })
  }
  function start(step: MfaStep) {
    action.reset()
    dispatch({ type: 'start', step })
  }
  function finish() {
    action.reset()
    dispatch({ type: 'complete' })
  }
  async function apply(values: FormData) {
    const password = valueOf(values, 'password')
    const codeValue = valueOf(values, 'code').trim()
    switch (state.step) {
      case 'setup': {
        const setup = await accountApi.setup(password)
        dispatch({ type: 'scan', setup })
        break
      }
      case 'scan': {
        const result = await accountApi.enable(codeValue)
        setCustomer(result.user)
        dispatch({ type: 'recovery', codes: result.recovery_codes })
        refresh()
        break
      }
      case 'disable':
        await accountApi.disable(password, codeValue)
        void client.invalidateQueries({ queryKey: entryKeys.session() })
        refresh()
        dispatch({ type: 'complete' })
        toast({ title: t('account.mfaDisabled'), tone: 'success' })
        break
      case 'regenerate': {
        const result = await accountApi.regenerate(codeValue)
        dispatch({ type: 'recovery', codes: result.recovery_codes })
        refresh()
        break
      }
    }
  }
  function run(values: FormData) {
    action.run(async () => {
      try {
        await apply(values)
      } catch (error) {
        if (entryError(error).code === 'invalid_mfa_code') setCodeRevision(revision => revision + 1)
        throw error
      }
    })
  }
  function signInAgain() {
    signOut.run(async () => {
      try {
        await entryApi.logout()
      } finally {
        clearCustomerQueries(client)
        void navigate({ to: '/login', search: { next: '/account' }, replace: true })
      }
    })
  }

  const setup = state.step === 'setup'
  const hasPassword = setup || state.step === 'disable'
  const disabling = state.step === 'disable'
  const actionLabel = t(disabling ? 'account.disableMfa' : 'account.makeCodes')
  const codeLabel = state.step === 'scan' ? 'account.codeFromApp' : disabling ? 'entry.mfaCode' : 'account.currentCode'
  const statusErrorKeys: Record<string, string> = {
    mfa_already_enabled: 'account.mfaAlreadyEnabled', mfa_not_enabled: 'account.mfaNotEnabled',
    mfa_setup_required: 'account.mfaSetupRequired',
    mfa_required_for_staff: 'account.staffMfa', mfa_required_by_org: 'account.orgKeepMfa',
  }
  const mfaConflict = Object.hasOwn(statusErrorKeys, code)

  return <SettingsSection title={t('entry.mfa')}>
    {state.step === 'codes' ? <RecoveryCodes codes={state.codes} onSaved={finish} /> : <>
      {status.isPending ? <Skeleton lines={4} label={t('account.loadingMfa')} /> : status.isError
        ? <EntryProblem error={status.error} message={t('account.mfaFailed')} retry={() => void status.refetch()} /> : status.data.sso_only
          ? <ReadOnlyNote>{t('account.ssoMfa')}</ReadOnlyNote> : <>
            <Row><Badge tone={status.data.totp_enabled ? 'success' : 'neutral'}>{t(status.data.totp_enabled ? 'account.on' : 'account.off')}</Badge></Row>
            {state.step === 'idle' ? <Stack>
              {status.data.totp_enabled ? <>
                <p>{t('account.mfaEnabled', {
                  date: formatEntryDate(status.data.enabled_at, language, t('account.recently')), count: status.data.recovery_codes_left,
                })}</p>
                <Row>
                  <Button onClick={() => start('regenerate')}>{t('account.newCodes')}</Button>
                  {!status.data.required_by.length && !status.data.required_for_staff && <Button onClick={() => start('disable')}>{t('account.turnOff')}</Button>}
                </Row>
                {!status.data.session_mfa && <Alert tone="warning"
                  action={<Button onClick={signInAgain} disabled={signOut.isPending}>{t('account.signInAgain')}</Button>}>{t('account.mfaSession')}</Alert>}
              </> : <>
                <p>{t('account.mfaIntro')}</p>
                <Row><Button variant="primary" onClick={() => start('setup')}>{t('account.turnOn')}</Button></Row>
              </>}
              {status.data.required_for_staff && <ReadOnlyNote>{t('account.staffMfa')}</ReadOnlyNote>}
              {status.data.required_by.length > 0 && <Stack gap={2}>
                <ReadOnlyNote>{t(status.data.totp_enabled ? 'account.orgKeepMfa' : 'account.orgNeedsMfa')}</ReadOnlyNote>
                <Row>{status.data.required_by.map(org => <Button key={org.organization_id} asChild>
                  <Link to="/org/$slug" params={{ slug: org.slug }}>{org.name}</Link>
                </Button>)}</Row>
              </Stack>}
            </Stack> : <Stack>
              {state.step === 'scan' && <Authenticator setup={state.setup} />}
              {action.isError && !errors && <EntryProblem error={action.error}
                message={t(mfaConflict ? statusErrorKeys[code] : authProblem(action.error))}
                retry={mfaConflict ? () => { finish(); refresh() } : undefined} />}
              <Form fields={[
                ...(hasPassword ? [passwordField(t('account.mfaPassword'))] : []),
                ...(!setup ? [{
                  name: 'code', label: t(codeLabel), validate: [disabling ? checkTotpOrRecovery : checkTotp],
                  control: (attributes: Parameters<ReturnType<typeof passwordField>['control']>[0]) =>
                    <Input key={codeRevision} {...attributes} inputMode={disabling ? undefined : 'numeric'} autoComplete="one-time-code" maxLength={entryLimits.code} required />,
                }] : []),
              ]} pending={action.isPending} serverErrors={errors} submitLabel={t(destructive || setup ? 'entry.continue' : 'account.turnOn')}
                actions={<Button onClick={finish} disabled={action.isPending}>{t('projectCreate.cancel')}</Button>}
                onSubmit={values => {
                  if (!destructive) { run(values); return }
                  confirmation.current = values
                  setConfirming(true)
                }} />
              {destructive && <ConfirmDestructive open={confirming} onOpenChange={open => {
                setConfirming(open)
                if (!open) confirmation.current = null
              }} title={actionLabel} description={t(disabling ? 'account.disableHelp' : 'account.replaceCodesHelp')}
                action={actionLabel} onConfirm={() => {
                  const data = confirmation.current
                  if (data) run(data)
                }} />}
            </Stack>}
          </>}
    </>}
  </SettingsSection>
}
