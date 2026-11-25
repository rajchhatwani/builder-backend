import { Link, useParams, useSearch } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { PageHeader } from '../../patterns'
import { Button, Row, Skeleton, Stack } from '../../ui'
import { organizationOptions, useCustomerSession } from './api/entry'
import { EntryProblem } from './components/EntryFrame'
import { ProjectPlan } from './components/ProjectPlan'
import { authProblem } from './components/messages'

export default function OrganizationLandingScreen() {
  const t = useT()
  const { slug } = useParams({ from: '/org/$slug' })
  const { tab } = useSearch({ from: '/org/$slug' })
  const { data: user } = useCustomerSession()
  const organization = useQuery(organizationOptions(user?.id ?? '', slug))

  return <Stack gap={5}>
    <PageHeader title={organization.data?.name ?? t('entry.organization')} />
    {organization.isPending ? <Skeleton /> : organization.isError
      ? <EntryProblem error={organization.error} message={t(authProblem(organization.error))} retry={() => void organization.refetch()} />
      : tab === 'plan' ? <ProjectPlan slug={slug} name={organization.data.name} expandable /> : null}
    <Row><Button asChild><Link to="/projects">{t('shell.projects')}</Link></Button></Row>
  </Stack>
}
