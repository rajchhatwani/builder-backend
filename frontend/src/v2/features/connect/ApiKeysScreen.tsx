import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { PageHeader } from '../../patterns'
import { Alert, Button, Card, EmptyState, Row, Stack, Tabs } from '../../ui'
import { blockOptions, connectRolesOptions } from './api/blocks'
import { specOptions } from './api/connect'
import type { ConnectProps } from './api/connect'
import { BlockSettings } from './components/BlockSettings'
import { BlockRole, SectionLink } from './components/BlockStatus'
import { KeyAudit, KeyManager } from './components/PlatformKeys'
import { PlatformPreview } from './components/PlatformPreview'
import type { PlatformPreviewProps } from './components/PlatformPreview'
import { platformDefaults, platformSchema } from './state/settingsSchemas'
import { platformDraftIssues } from '../../validators'

export default function ApiKeysScreen(props: ConnectProps & PlatformPreviewProps) {
  const t = useT()
  const { projectId: id, role, rolePending, credentials, renderIdentity } = props
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const tab = search.tab === 'keys' || search.tab === 'audit' ? search.tab : 'settings'
  const settings = useQuery(blockOptions(id, 'api_platform'))
  const spec = useQuery({ ...specOptions(id), enabled: tab === 'settings' })
  const roles = useQuery({ ...connectRolesOptions(id), enabled: tab === 'settings' })
  const readOnly = !role || role === 'viewer' || Boolean(rolePending)
  const pick = (values: string[]) => values.map(value => ({ value, label: t('schema.option', { value }) }))
  return <Stack data-testid="apikeys-page">
    <PageHeader title={t('connectB.keys.title')} description={t('connectB.keys.intro')}
      actions={<SectionLink projectId={id} section="apps" label={t('connectB.apps.title')} preview={search.preview} />} />
    <BlockRole {...props} />
    <Tabs label={t('connectB.keys.tabs')} value={tab} keepMounted
      onChange={tab => void navigate({ search: previous => ({ ...previous, tab, page: undefined, auditPage: undefined }) })}
      items={[
        { id: 'settings', label: t('connectB.keys.settings'), content: <Stack data-testid="apikeys-settings">
          {(spec.isError || roles.isError) && <Alert tone="warning" action={<Button onClick={() => {
            if (spec.isError) void spec.refetch()
            if (roles.isError) void roles.refetch()
          }}>{t('common.retry')}</Button>}>{t('connectA2.dependenciesError')}</Alert>}
          <BlockSettings projectId={id} name="api_platform" schema={platformSchema} defaults={platformDefaults}
            title={t('connectB.keys.settings')} errorKey="connectB.keys.settingsError" remove readOnly={readOnly}
            validate={value => platformDraftIssues(value, t)}
            empty={<EmptyState title={t('connectB.keys.settingsEmpty')} description={t('connectB.keys.settingsEmptyHelp')} />}
            options={(path, current) => {
              if (path[0] === 'roles' && typeof path[1] === 'number' && roles.data?.roles.length) return roles.data.roles.map(role =>
                ({ value: role.name, label: t('schema.option', { value: role.label || role.name }) }))
              if (path[0] === 'entities' && path[2] === 'entity' && spec.data) return pick(spec.data.entities.map(entity => entity.name))
              if (path[0] === 'entities' && path[2] === 'fields' && typeof path[3] === 'number' && spec.data) {
                const entity = spec.data.entities.find(entity => entity.name === current.entities[Number(path[1])]?.entity)
                if (entity) return pick([...new Set(['id', ...entity.fields.map(field => field.name), 'created_at', 'updated_at'])])
              }
              if (path[0] === 'apps' && path[2] === 'scopes' && typeof path[3] === 'number')
                return pick([...new Set(current.entities.filter(entity => entity.entity && entity.fields.length).map(entity => entity.entity))])
            }}>
            {value => <Card><Stack>
              <h2>{t('connectB.keys.exposure')}</h2>
              <p>{t('connectB.keys.exposureHelp')}</p>
              {value.enabled && spec.data && !spec.data.auth?.enabled && <Alert tone="warning">{t('connectB.keys.needsAuth')}</Alert>}
              <Row><SectionLink projectId={id} section="auth" label={t('nav.auth')} />
                <SectionLink projectId={id} section="model" label={t('nav.model')} /></Row>
            </Stack></Card>}
          </BlockSettings>
        </Stack> },
        { id: 'keys', label: t('connectB.keys.keys'), content: tab === 'keys' && <Stack data-testid="apikeys-keys">
          <PlatformPreview id={id} credentials={credentials} renderIdentity={renderIdentity} updatedAt={settings.data?.updated_at}>
            {session => <KeyManager id={id} session={session} readOnly={readOnly} />}
          </PlatformPreview>
        </Stack> },
        { id: 'audit', label: t('connectB.keys.audit'), content: tab === 'audit' && <Stack data-testid="apikeys-audit">
          <PlatformPreview id={id} credentials={credentials} renderIdentity={renderIdentity}>
            {session => <KeyAudit id={id} session={session} />}
          </PlatformPreview>
        </Stack> },
      ]} />
  </Stack>
}
