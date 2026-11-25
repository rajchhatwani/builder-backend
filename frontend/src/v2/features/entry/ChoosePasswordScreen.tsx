import { useMemo } from 'react'
import { useT } from '../../i18n'
import { Form } from '../../patterns'
import type { ValidationIssue } from '../../validators'
import { newPasswordChecks } from '../../validators'
import { entryApi, entryError, useEntryAction, useSetCustomer } from './api/entry'
import type { UserAccount } from './api/entry'
import { EntryCard, EntryFrame, EntryProblem } from './components/EntryFrame'
import { passwordField, valueOf } from './components/fields'
import { authProblem, passwordProblemKey } from './components/messages'

export default function ChoosePasswordScreen({ user }: { user: UserAccount }) {
  const t = useT()
  const setCustomer = useSetCustomer()
  const action = useEntryAction()
  const { code, message } = entryError(action.error)
  const errors = useMemo((): Record<string, ValidationIssue> | undefined => {
    if (code === 'weak_password') return { newPassword: { key: passwordProblemKey(message) } }
    if (code === 'invalid_credentials') return { currentPassword: { key: 'entry.wrongCurrentPassword' } }
  }, [code, message])

  function change(values: FormData) {
    const current = valueOf(values, 'currentPassword')
    const next = valueOf(values, 'newPassword')
    action.run(async () => {
      const result = await entryApi.changePassword(current, next)
      setCustomer(result.user)
    })
  }

  return <EntryFrame title={t('entry.choosePassword')}><EntryCard title={t('entry.password')}>
    <p>{t('entry.forcedHint')}</p>
    {action.isError && !errors && <EntryProblem error={action.error} message={t(authProblem(action.error))} />}
    <Form fields={[
      passwordField(t('entry.currentPassword'), 'currentPassword'),
      passwordField(t('entry.newPassword'), 'newPassword', newPasswordChecks(user.email), t('entry.passwordHint')),
    ]} pending={action.isPending} serverErrors={errors} submitLabel={t('entry.updatePassword')} onSubmit={change} />
  </EntryCard></EntryFrame>
}
