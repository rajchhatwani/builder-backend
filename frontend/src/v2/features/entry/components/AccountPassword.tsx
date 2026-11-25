import { useMemo, useState } from 'react'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import { useToast } from '../../../ui'
import { checkPasswordConfirmation, checkPresentPassword, newPasswordChecks } from '../../../validators'
import type { ValidationIssue } from '../../../validators'
import { entryApi, entryError, useEntryAction, useSetCustomer } from '../api/entry'
import type { UserAccount } from '../api/entry'
import { EntryProblem } from './EntryFrame'
import { passwordField, valueOf } from './fields'
import { authProblem, passwordProblemKey } from './messages'

export function AccountPassword({ user, forced }: { user: UserAccount; forced?: boolean }) {
  const t = useT()
  const toast = useToast()
  const setCustomer = useSetCustomer()
  const action = useEntryAction()
  const [revision, setRevision] = useState(0)
  const { code, message } = entryError(action.error)
  const errors = useMemo((): Record<string, ValidationIssue> | undefined => {
    if (code === 'weak_password') return { newPassword: { key: passwordProblemKey(message) } }
    if (code === 'invalid_credentials') return { currentPassword: { key: 'entry.wrongCurrentPassword' } }
  }, [code, message])
  const passwordChecks = newPasswordChecks(user.email)

  return <>
    {action.isError && !errors && <EntryProblem error={action.error} message={t(authProblem(action.error))} />}
    <Form key={revision} fields={[
      passwordField(t('entry.currentPassword'), 'currentPassword'),
      { ...passwordField(t('entry.newPassword'), 'newPassword', passwordChecks, t('entry.passwordHint')),
        validateWith: (next, values) => next === valueOf(values, 'currentPassword') ? { key: 'entry.samePassword' } : undefined },
      { ...passwordField(t('account.repeatPassword'), 'repeatPassword', [checkPresentPassword]),
        validateWith: (repeat, values) => checkPasswordConfirmation(repeat, valueOf(values, 'newPassword')) },
    ]} pending={action.isPending} serverErrors={errors} submitLabel={t(forced ? 'entry.updatePassword' : 'account.changePassword')}
      onSubmit={values => action.run(async () => {
        const result = await entryApi.changePassword(valueOf(values, 'currentPassword'), valueOf(values, 'newPassword'))
        setCustomer(result.user)
        setRevision(value => value + 1)
        toast({ title: t('account.passwordChanged'), tone: 'success' })
      })} />
  </>
}
