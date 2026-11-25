import { Link } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { PageHeader } from '../../patterns'
import { openInEditor } from '../../patterns/editorLink'
import { Button, Card, EmptyState, Row, Stack } from '../../ui'
import { edgeDraftIssues } from '../../validators'
import type { ConnectProps } from './api/connect'
import { BlockSettings } from './components/BlockSettings'
import { BlockRole, SectionLink } from './components/BlockStatus'
import { edgeDefaults, edgeSchema } from './state/settingsSchemas'

export default function ApiEdgeScreen(props: ConnectProps) {
  const { projectId, role, rolePending } = props
  const t = useT()
  return <Stack>
    <PageHeader title={t('connectB.edge.title')} description={t('connectB.edge.intro')} />
    <BlockRole {...props} />
    <BlockSettings projectId={projectId} name="api_edge" schema={edgeSchema} defaults={edgeDefaults}
      title={t('connectB.edge.settings')} errorKey="connectB.edge.error" remove readOnly={!role || role === 'viewer' || Boolean(rolePending)}
      validate={value => edgeDraftIssues(value, t)}
      options={(path, value) => {
        if (path[0] !== 'versioning' || path[1] !== 'default' || !value.versioning) return
        const dates = [...new Set(value.versioning.versions.map(row => row.date).filter(Boolean))]
        if (dates.length) return dates.map(value => ({ value, label: t('schema.option', { value }) }))
      }}
      empty={<EmptyState title={t('connectB.edge.empty')} description={t('connectB.edge.emptyHelp')} />}>
      {draft => <Card><Stack>
        <h2>{t('connectB.edge.behavior')}</h2>
        <p>{t('connectB.edge.flow')}</p>
        <p>{t('connectB.edge.limits')}</p>
        {draft.idempotency && <p>{t('connectB.edge.idempotency')}</p>}
        {draft.versioning && <p>{t('connectB.edge.versioning')}</p>}
        {(draft.idempotency || draft.rate_limits || draft.quotas.length > 0) && <p>{t('connectB.edge.maintenance')}</p>}
        <Row>
          <SectionLink projectId={projectId} section="keycloak" label={t('nav.keycloak')} />
          <SectionLink projectId={projectId} section="events" label={t('nav.events')} />
          {draft.enabled && draft.versioning && <Button asChild><Link {...openInEditor({ projectId, path: 'app/hooks/api_versions.py', source: 'kit' })}>
            {t('connectB.edge.editor')}
          </Link></Button>}
        </Row>
      </Stack></Card>}
    </BlockSettings>
  </Stack>
}
