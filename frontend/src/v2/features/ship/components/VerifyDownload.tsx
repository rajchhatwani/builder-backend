import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { SettingsSection } from '../../../patterns'
import { Alert, Button, Row } from '../../../ui'
import { generationApi, refreshDownloadAccount, shipError } from '../api/ship'

export function VerifyDownload() {
  const t = useT()
  const client = useQueryClient()
  const [until, setUntil] = useState(0)
  const [now, setNow] = useState(Date.now)
  const seconds = Math.max(0, Math.ceil((until - now) / 1000))
  const resend = useMutation({
    mutationFn: async () => {
      const account = await refreshDownloadAccount(client)
      if (!account?.email) throw new Error('missing_email')
      await generationApi.resend(account.email)
    },
    onSettled: (_, error) => {
      if (error && shipError(error)?.status !== 429) return
      const time = Date.now()
      setNow(time)
      setUntil(time + 60_000)
    },
  })
  useEffect(() => {
    if (until <= Date.now()) return
    const timer = window.setInterval(() => {
      const time = Date.now()
      setNow(time)
      if (time >= until) window.clearInterval(timer)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [until])
  return <SettingsSection title={t('ship.verifyTitle')}>
    <p>{t('ship.verifyNote')}</p>
    <Row><Button data-testid="resend" disabled={resend.isPending || seconds > 0} onClick={() => resend.mutate()}>
      {t(seconds ? 'ship.resendWait' : 'ship.resend', { seconds })}</Button></Row>
    {resend.isSuccess && <p role="status" data-testid="resend-note">{t('ship.resendSuccess')}</p>}
    {resend.isError && <Alert tone="danger">{t(shipError(resend.error)?.status === 429 ? 'ship.resendRate' : 'ship.resendError')}</Alert>}
  </SettingsSection>
}
