import { useSearch } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { Row } from '../../ui'
import { useCustomerSession } from './api/entry'
import { BackToSignIn, EntryCard, EntryFrame, EntryLoading, EntryProblem } from './components/EntryFrame'

export default function SsoCompleteScreen() {
  const t = useT()
  const { next } = useSearch({ strict: false })
  const session = useCustomerSession()
  return <EntryFrame title={t('shell.signIn')}>
    {session.isPending || session.isFetching ? <EntryLoading label={t('entry.ssoWorking')} /> : <EntryCard>
      <EntryProblem error={session.error} message={t(session.isError ? 'entry.network' : 'entry.ssoIncomplete')}
        retry={session.isError ? () => void session.refetch() : undefined} />
      <Row><BackToSignIn next={next} /></Row>
    </EntryCard>}
  </EntryFrame>
}
