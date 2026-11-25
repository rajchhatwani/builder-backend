import { useEffect, useState } from 'react'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import { Alert, Stack } from '../../../ui'
import { entryApi, entryError, useEntryAction } from '../api/entry'
import { EntryProblem } from './EntryFrame'
import { emailField, valueOf } from './fields'

const cooldown = 60_000
const deadlines = new Map<string, number>()
const addressKey = (email: string) => email.trim().toLowerCase()

export function startResendCooldown(email: string) {
  const now = Date.now()
  for (const [key, deadline] of deadlines) if (deadline <= now) deadlines.delete(key)
  deadlines.set(addressKey(email), now + cooldown)
}

export function ResendVerification({ initialEmail = '', showHint = false }: { initialEmail?: string; showHint?: boolean }) {
  const t = useT()
  const [email, setEmail] = useState(initialEmail)
  const [now, setNow] = useState(Date.now)
  const resend = useEntryAction()
  const remaining = Math.max(0, Math.ceil(((deadlines.get(addressKey(email)) ?? now) - now) / 1000))

  useEffect(() => {
    if (!remaining) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [remaining])

  function send(address: string) {
    resend.run(async () => {
      if ((deadlines.get(addressKey(address)) ?? 0) > Date.now()) return
      await entryApi.resendVerification(address)
      startResendCooldown(address)
      setNow(Date.now())
    })
  }

  return <Stack>
    {showHint && <p className="v2-muted">{t('entry.resendHint')}</p>}
    <Form fields={[emailField(t('entry.yourEmail'), email, text => { setEmail(text); resend.reset(); setNow(Date.now()) })]}
      submitProps={{ 'data-testid': 'resend', disabled: !!remaining, hidden: !email.trim() }}
      submitLabel={t(remaining ? 'entry.resendWait' : 'entry.resend', { seconds: remaining })}
      pending={resend.isPending} onSubmit={values => send(valueOf(values, 'email').trim())} />
    {resend.isSuccess && <div data-testid="resend-note"><Alert>{t('entry.inboxMessage')}</Alert></div>}
    {resend.isError && <EntryProblem error={resend.error}
      message={t(entryError(resend.error).status === 429 ? 'entry.resendRate' : 'entry.resendFailed')} retry={() => send(email.trim())} />}
  </Stack>
}
