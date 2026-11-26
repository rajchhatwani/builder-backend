import type { ComponentProps, ReactNode } from 'react'
import { RouteTranslations, useLanguage, useT } from '../../../i18n'
import { ConflictBanner } from '../../../patterns'
import { Alert, Button, Row } from '../../../ui'
import { runtimeError, runtimeStatus } from '../api/live'
import { RuntimeContents, key, RuntimeState, runtimeEnglish } from './Runtime'
import { SectionLink } from './Common'
import copy from '../aiCopy.json'
import '../ai.css'

export function AiRuntime(props: ComponentProps<typeof RuntimeContents>) {
  return <RouteTranslations english={{ ...runtimeEnglish, runtime: { ...runtimeEnglish.runtime, ...copy } }}>
    <RuntimeContents {...props} />
  </RouteTranslations>
}

export function AiActions({ id, settings, refresh, testId, children }: {
  id: string; settings: string; refresh: () => unknown; testId: string; children?: ReactNode
}) {
  const t = useT()
  return <Row><SectionLink id={id} section={settings} label={t(key(settings))} />
    {children}
    <Button data-testid={testId} onClick={() => void refresh()}>{t(key('refresh'))}</Button>
  </Row>
}

export function AiFeedback({ error, retry, write = false, conflictLabel }: {
  error?: unknown; retry: () => unknown; write?: boolean; conflictLabel?: string
}) {
  const t = useT()
  if (!error) return write ? null : <RuntimeState retry={retry} />
  const info = runtimeError(error)
  const status = runtimeStatus(error)
  const label = status === 403 ? 'forbidden' : status === 401 ? 'signInAgain' : status === 404 && !write ? 'missing' : write ? 'writeError' : 'loadError'
  const message = status === 409 ? t(key('conflict')) : t(key(label))
  const detail = info?.message && status && status < 500 && (write || status === 409) ? info.message : message
  const body = status ? t(key(info?.code ? 'responseCode' : 'responseStatus'), { message: detail, status, code: info?.code ?? '' }) : detail
  if (status === 409) return <ConflictBanner action={conflictLabel ? <Button onClick={() => void retry()}>{conflictLabel}</Button> : undefined} onReload={() => void retry()}>{body}</ConflictBanner>
  return <Alert tone={status === 403 ? 'warning' : 'danger'} action={(!write || status === 401) &&
    <Button onClick={() => void retry()}>{t('common.retry')}</Button>}>{body}</Alert>
}

export function useAiFormat() {
  const { language, t } = useLanguage()
  const integer = new Intl.NumberFormat(language)
  const percent = new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 2 })
  return {
    count: (value: number) => integer.format(value),
    bp: (value: number) => percent.format(value / 10_000),
    pair: (left: number, right: number) => t(key('pair'), { left: integer.format(left), right: integer.format(right) }),
  }
}

export function AiPermission({ access, children }: {
  access: { pending: boolean; error: unknown; retry: () => unknown }; children: ReactNode
}) {
  return access.pending || access.error
    ? <AiFeedback error={access.error} retry={access.retry} />
    : children
}
