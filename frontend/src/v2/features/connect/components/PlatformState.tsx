import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useLanguage, useT } from '../../../i18n'
import { ConflictBanner } from '../../../patterns'
import { Alert, Button, CodeBlock, Dialog, Stack } from '../../../ui'
import { errorText, statusOf } from '../api/connect'
import type { LiveSession } from '../api/liveWebhooks'
import { platformErrorCode, platformKey } from '../api/platform'
import { CopyButton } from './CopyButton'
import { BlockLoad } from './BlockStatus'

export function PlatformProblem({ error, retry, errorKey }: { error: unknown; retry: () => void; errorKey?: string }) {
  const t = useT()
  const status = statusOf(error)
  if (status === 409) return <ConflictBanner onReload={retry} />
  if (status === 401 || status === 403) return <Alert tone="warning" action={<Button onClick={retry}>{t('common.retry')}</Button>}>
    {t(status === 401 ? 'connectB.platform.signInAgain' : 'connectB.platform.denied')}
    {errorText(error) && <p>{t('common.serverText', { text: errorText(error) ?? '' })}</p>}
  </Alert>
  if (platformErrorCode(error) === 'signing_key_missing') return <Alert tone="danger">{t('connectB.apps.signingKeyRequired')}</Alert>
  if (error && !errorKey) return <Alert tone="danger">{t('common.serverText', { text: errorText(error) ?? t('common.actionFailed') })}</Alert>
  return <BlockLoad error={status === 404 ? new Error() : error} retry={retry} errorKey={errorKey ?? 'connectB.platform.error'} />
}

type Reveal = { title: string; summary?: string; fields: { label: string; value: string }[] }
export function usePlatformAction(id: string, session: LiveSession) {
  const client = useQueryClient()
  const alive = useRef(false)
  const [secret, setSecret] = useState<Reveal>()
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    if (!secret) return
    const timer = window.setTimeout(() => setSecret(undefined), 300_000)
    return () => window.clearTimeout(timer)
  }, [secret])
  return {
    secret, dismiss: () => setSecret(undefined),
    reveal: (value: Reveal) => { if (alive.current) setSecret(value) },
    refresh: () => client.invalidateQueries({ queryKey: platformKey(id, session) }),
  }
}

export function PlatformSecret({ secret, dismiss }: { secret: Reveal; dismiss: () => void }) {
  const t = useT()
  return <Dialog title={secret.title} description={t('connectB.platform.once')} open onOpenChange={open => { if (!open) dismiss() }}
    actions={<Button variant="primary" data-testid="secret-dismiss" onClick={dismiss}>{t('connectB.platform.dismiss')}</Button>}>
    <Stack data-testid="secret-panel">
      {secret.summary && <p>{secret.summary}</p>}
      {secret.fields.map(field => <Stack key={field.label}>
        <h3>{field.label}</h3>
        <div data-testid="secret-value"><CodeBlock code={field.value} /></div>
        <CopyButton value={field.value} label={t('connectB.platform.copy', { field: field.label })} />
      </Stack>)}
    </Stack>
  </Dialog>
}

export function usePlatformDate() {
  const { t, language } = useLanguage()
  return (value: string | null) => value ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) :
    t('connectB.platform.noDate')
}
