import { useT } from '../../i18n'
import { Row, Stack } from '../../ui'
import type { OperateProps } from './api/operate'
import { OperateScreen, RoleNotice, SectionLink } from './components/Common'
import { JobSettings } from './components/JobSettings'

export default function JobsScreen(props: OperateProps) {
  return <OperateScreen title={'operate.jobs.title'} lead="operate.jobs.lead"><Jobs {...props} /></OperateScreen>
}

function Jobs(props: OperateProps) {
  const t = useT()
  return <Stack>
    <RoleNotice {...props} />
    <JobSettings {...props} kind="jobs" />
    <Row><SectionLink id={props.projectId} section="workers" label={t('operate.workers.title')} />
      <SectionLink id={props.projectId} section="workflows" label={t('operate.flows.title')} /></Row>
  </Stack>
}
