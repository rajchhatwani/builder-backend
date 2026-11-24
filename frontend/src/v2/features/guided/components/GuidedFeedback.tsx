import { useT } from '../../../i18n'
import { Alert, Button } from '../../../ui'
import { errorCode, errorStatus, retrySeconds, serverMessage } from '../api/guided'

export function useGuidedError() {
  const t = useT()
  return (error: unknown) => {
    const code = errorCode(error)
    const seconds = retrySeconds(error)
    if (errorStatus(error) === 429 && seconds !== undefined) return t('guided.retryAfter', { count: seconds })
    if (code === 'email_not_verified') return t('guided.verify')
    if (code === 'bad_response' || !code) return t('guided.connection')
    if (code === 'validation_error') return t('guided.checkFields')
    return t('common.serverText', { text: serverMessage(error) })
  }
}

export function GuidedLoadError({ error, retry, label }: { error: unknown; retry: () => void; label: string }) {
  const t = useT()
  return <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>
    {errorStatus(error) === 403 ? t('guided.forbidden') : label}
  </Alert>
}
