import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { Alert, Button, Row, Skeleton, Stack } from '../../../ui'
import { projectPlanOptions } from '../api/projects'
import { EntryProblem } from './EntryFrame'

export function ProjectPlan({ slug, name, expandable = false }: { slug: string; name: string; expandable?: boolean }) {
  const t = useT()
  const plan = useQuery(projectPlanOptions(slug))
  if (plan.isPending) return <Skeleton lines={1} />
  if (plan.isError) return <EntryProblem error={plan.error} message={t('projectList.planFailed')} retry={() => void plan.refetch()} />
  const { plan: current, usage, subscription } = plan.data
  const full = usage.projects_cap !== null && usage.projects_used >= usage.projects_cap
  const usageText = t(usage.projects_cap === null ? 'projectList.usageUncapped' : 'projectList.usage', {
    count: usage.projects_used, cap: usage.projects_cap ?? 0, name,
  })
  return <Stack gap={2}>
    {expandable && <h2>{current.display_name}</h2>}
    <p className="v2-muted">{usageText}</p>
    {subscription.status === 'past_due' && <Alert tone="warning">{t('projectCreate.pastDue')}</Alert>}
    {full && !expandable && <Row><Button asChild><Link to="/org/$slug" params={{ slug }} search={{ tab: 'plan' }}>
      {t('projectCreate.seePlans')}
    </Link></Button></Row>}
    {expandable && plan.data.upgrades.length > 0 && <Stack gap={1}>
      <h3>{t('projectCreate.availablePlans')}</h3>
      <ul>{plan.data.upgrades.map(item => <li key={item.id}>{item.display_name}</li>)}</ul>
    </Stack>}
  </Stack>
}
