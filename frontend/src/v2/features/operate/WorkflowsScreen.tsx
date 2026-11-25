import { useT } from '../../i18n'
import { EmptyState, Row, Stack, Tabs } from '../../ui'
import type { OperateProps } from './api/operate'
import { OperateScreen, RoleNotice, SectionLink, useOperateSearch } from './components/Common'
import { JobSettings } from './components/JobSettings'

export default function WorkflowsScreen(props: OperateProps) {
  return <OperateScreen title={'operate.flows.title'} lead="operate.flows.lead"><Workflows {...props} /></OperateScreen>
}

function Workflows(props: OperateProps) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const id = props.projectId
  return <Stack>
    <RoleNotice {...props} />
    <Tabs label={t('operate.flows.title')} value={search.tab === 'runs' ? 'runs' : 'form'}
      onChange={tab => change({ tab })} keepMounted items={[
        { id: 'form', label: t('operate.settings'), content: <JobSettings {...props} kind="workflows" /> },
        { id: 'runs', label: t('operate.flows.runs'), content: <EmptyState title={t('operate.flows.runtime')}
          description={t('operate.flows.unavailable')} action={<SectionLink id={id} section="see" label={t('operate.flows.preview')} />} /> },
      ]} />
    <Row>
      <SectionLink id={id} section="auth" label={t('operate.flows.auth')} />
      <SectionLink id={id} section="jobs" label={t('operate.jobs.title')} />
      <SectionLink id={id} section="workers" label={t('operate.workers.title')} />
    </Row>
  </Stack>
}
