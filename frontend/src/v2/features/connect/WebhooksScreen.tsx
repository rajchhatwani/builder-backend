import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { PageHeader } from '../../patterns'
import { openInEditor } from '../../patterns/editorLink'
import { Alert, Button, Card, CodeBlock, EmptyState, Row, Stack, Tabs, useToast } from '../../ui'
import { blockOptions, connectRolesOptions } from './api/blocks'
import { specOptions } from './api/connect'
import type { ConnectProps } from './api/connect'
import type { PreviewCredential } from './api/liveWebhooks'
import { BlockLoad, BlockRole, SectionLink } from './components/BlockStatus'
import { BlockSettings } from './components/BlockSettings'
import { WebhookLive } from './components/WebhookLive'
import { specEvents, webhookDefaults, webhookSchema } from './state/blockSchemas'

type Props = ConnectProps & { credentials?: Record<string, PreviewCredential> }

export default function WebhooksScreen(props: Props) {
  const { projectId, role, rolePending, credentials = {} } = props
  const t = useT()
  const notify = useToast()
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const tab = search.tab === 'subscriptions' ? 'subscriptions' : 'config'
  const query = useQuery(blockOptions(projectId, 'webhooks'))
  const roles = useQuery({ ...connectRolesOptions(projectId), enabled: tab === 'config' })
  const spec = useQuery(specOptions(projectId))
  const readOnly = !role || role === 'viewer' || Boolean(rolePending)
  const saved = query.data?.block
  const data = spec.data
  const change = (tab: string) => void navigate({ search: previous => ({ ...previous, tab }) })
  const retry = () => { if (spec.isError) void spec.refetch(); if (roles.isError) void roles.refetch() }
  async function copy(path: string) {
    try { await navigator.clipboard.writeText(path); notify({ title: t('connectA2.live.pathCopied'), tone: 'success' }) }
    catch { notify({ title: t('connectA2.live.copyError'), tone: 'danger' }) }
  }
  return <Stack>
    <PageHeader title={t('connectA2.webhooks.title')} description={t('connectA2.webhooks.intro')}
      actions={<SectionLink projectId={projectId} section="history" label={t('connectA2.history')} preview={search.preview} />} />
    <BlockRole {...props} />
    <Tabs label={t('connectA2.webhooks.tabs')} value={tab} onChange={change} keepMounted items={[
      { id: 'config', label: t('connectA2.webhooks.settings'), content: <Stack>
        {(spec.isError || roles.isError) && <Alert tone="warning" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t('connectA2.dependenciesError')}</Alert>}
        <BlockSettings projectId={projectId} name="webhooks" schema={webhookSchema} defaults={webhookDefaults}
          title={t('connectA2.webhooks.config')} errorKey="connectA2.webhooks.error" readOnly={readOnly}
          empty={<EmptyState title={t('connectA2.webhooks.empty')} description={t('connectA2.webhooks.emptyHelp')} />}
          options={path => {
            if (path[0] === 'admin_role' && roles.data) return roles.data.roles.map(role => ({ value: role.name, label: role.label || role.name }))
            if (path[0] === 'events' && typeof path[1] === 'number' && data) return specEvents(data, true)
              .map(value => ({ value, label: t('schema.option', { value }) }))
          }}>
          {draft => <Card><Stack>
            <h2>{t('connectA2.prerequisites')}</h2>
            <Row>{(['auth', 'events', 'jobs', 'providers'] as const).map(section => <SectionLink key={section}
              projectId={projectId} section={section} label={t('connectA2.link.' + section)} preview={search.preview} />)}</Row>
            {data && <p className="v2-muted">{t('connectA2.readiness', { states: [
              data.auth?.enabled ? '' : t('connectA2.link.auth'), data.events?.enabled ? '' : t('connectA2.link.events'),
              data.jobs?.enabled && data.jobs.jobs?.some(job => job.name === 'webhook_delivery') ? '' : t('connectA2.link.jobs'),
              data.providers?.enabled ? '' : t('connectA2.link.providers'),
            ].filter(Boolean).join(', ') || t('connectA2.ready') })}</p>}
            <p>{t(draft.allow_http ? 'connectA2.webhooks.httpPolicy' : 'connectA2.webhooks.httpsPolicy', {
              ports: (draft.allowed_ports.length ? draft.allowed_ports : draft.allow_http ? [80, 443] : [443]).join(', '),
            })}</p>
          </Stack></Card>}
        </BlockSettings>
        {query.data && <Card><Stack>
          <h2>{t('connectA2.webhooks.deliveryFlow')}</h2>
          <p>{t('connectA2.webhooks.outFlow')}</p>
          <p>{t('connectA2.webhooks.inFlow')}</p>
          <p>{t('connectA2.webhooks.signature')}</p>
          <p>{t('connectA2.webhooks.maintenance')}</p>
          {saved?.inbound.map(receiver => {
            const path = '/webhooks/in/' + encodeURIComponent(receiver.name) + (data?.auth?.multi_tenant ? '/{tenant_id}' : '')
            return <Stack key={receiver.name}><CodeBlock code={path} />
              <Row><Button onClick={() => void copy(path)}>{t('connectA2.live.copyPath')}</Button></Row>
            </Stack>
          })}
          {saved?.enabled && <Row><Button asChild><Link {...openInEditor({ projectId, path: 'app/hooks/webhooks.py', source: 'kit' })}>
            {t('connectA2.webhooks.editor')}
          </Link></Button></Row>}
        </Stack></Card>}
      </Stack> },
      { id: 'subscriptions', label: t('connectA2.live.tab'), content: tab === 'subscriptions' && (query.data ?
        <WebhookLive id={projectId} credentials={credentials} enabled={saved?.enabled === true} readOnly={readOnly}
          overlap={saved?.secret_overlap_hours ?? webhookDefaults.secret_overlap_hours} multiTenant={data?.auth?.multi_tenant === true} /> :
        <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectA2.webhooks.error" />) },
    ]} />
  </Stack>
}
