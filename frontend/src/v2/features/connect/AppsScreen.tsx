import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useSearch } from '@tanstack/react-router'
import { useReducer, useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, PageHeader } from '../../patterns'
import { Alert, Badge, Button, Card, Checkbox, CodeBlock, Disclosure, EmptyState, Row, Stack } from '../../ui'
import { blockOptions } from './api/blocks'
import { statusOf } from './api/connect'
import type { ConnectProps } from './api/connect'
import type { LiveSession } from './api/liveWebhooks'
import { catalogueOptions, installPlatformApp, platformAppsOptions, platformKeysOptions, uninstallPlatformApp } from './api/platform'
import type { Catalogue, PlatformApp, PlatformKey } from './api/platform'
import { BlockRole } from './components/BlockStatus'
import { PlatformPreview } from './components/PlatformPreview'
import type { PlatformPreviewProps } from './components/PlatformPreview'
import { PlatformProblem, PlatformSecret, usePlatformAction, usePlatformDate } from './components/PlatformState'
import { initialGrant, scopeGrantReducer } from './state/scopeGrant'

function KeysLink({ id, tab }: { id: string; tab: 'settings' | 'audit' }) {
  const t = useT()
  const search = useSearch({ strict: false })
  return <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId: id, section: 'apikeys' }}
    search={{ tab, preview: search.preview, workspace: search.workspace }}>{t('connectB.apps.' + tab)}</Link></Button>
}

export default function AppsScreen(props: ConnectProps & PlatformPreviewProps) {
  const t = useT()
  const { projectId: id, role, rolePending, credentials, renderIdentity } = props
  const settings = useQuery(blockOptions(id, 'api_platform'))
  return <Stack data-testid="apps-page">
    <PageHeader title={t('connectB.apps.title')} description={t('connectB.apps.intro')}
      actions={<Row><KeysLink id={id} tab="settings" /><KeysLink id={id} tab="audit" /></Row>} />
    <BlockRole {...props} />
    <PlatformPreview id={id} credentials={credentials} renderIdentity={renderIdentity} updatedAt={settings.data?.updated_at}>
      {session => <AppCatalogue id={id} session={session} readOnly={!role || role === 'viewer' || Boolean(rolePending)} />}
    </PlatformPreview>
    <Card><Disclosure label={t('connectB.apps.signing')}><Stack>
      <p>{t('connectB.apps.signingHelp')}</p>
      <CodeBlock code={t('connectB.apps.headers')} />
    </Stack></Disclosure></Card>
  </Stack>
}

function AppCatalogue({ id, session, readOnly }: { id: string; session: LiveSession; readOnly: boolean }) {
  const t = useT()
  const apps = useQuery(platformAppsOptions(id, session))
  const catalogue = useQuery(catalogueOptions(id, session))
  const keys = useQuery(platformKeysOptions(id, session))
  const date = usePlatformDate()
  const { secret, reveal, dismiss, refresh } = usePlatformAction(id, session)
  const write = useMutation({
    mutationFn: async (action: { app: PlatformApp; scopes?: string[] }) => {
      const name = action.app.title || action.app.name
      if (!action.scopes) {
        await uninstallPlatformApp(session, action.app.name)
        return name
      }
      const installed = await installPlatformApp(session, action.app.name, action.scopes)
      if (!installed.token || !installed.signing_secret) throw new Error('install_reply')
      reveal({
        title: t('connectB.apps.installed', { name }),
        summary: t('connectB.apps.installation', { id: installed.installation_id }),
        fields: [
          { label: t('connectB.apps.token'), value: installed.token },
          { label: t('connectB.apps.signingSecret'), value: installed.signing_secret },
        ],
      })
      return null
    },
    onSuccess: refresh,
  })
  const retry = () => { write.reset(); void refresh() }
  const label = t('connectB.apps.available')
  return <Card><Stack>
    <h2>{label}</h2>
    {secret && <PlatformSecret secret={secret} dismiss={dismiss} />}
    {!apps.data || apps.isError ? <div data-testid="apps-error"><PlatformProblem error={apps.error} retry={retry} errorKey="connectB.apps.error" /></div> :
      <>
        {!!(catalogue.error || keys.error) && <Alert tone="warning" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t('connectB.apps.metadataError')}</Alert>}
        {catalogue.data && <p>{t('connectB.apps.tenant', { limit: catalogue.data.rate_limit, days: catalogue.data.key_ttl_days })}</p>}
        {write.isError && <div data-testid="apps-action-error"><PlatformProblem error={write.error} retry={retry} /></div>}
        {write.data && <div data-testid="apps-note"><Alert tone="success">{t('connectB.apps.uninstalled', { name: write.data })}</Alert></div>}
        {apps.data.length ? apps.data.map(app => <AppCard key={app.name + ':' + app.installation_id} app={app} catalogue={catalogue.data}
          token={keys.data?.find(key => key.id === app.installation_id)} date={date}
          readOnly={readOnly} pending={write.isPending || statusOf(write.error) === 409} install={scopes => write.mutate({ app, scopes })}
          uninstall={async () => { await write.mutateAsync({ app }) }} />) :
          <div data-testid="apps-empty"><EmptyState title={t('connectB.apps.empty')} action={<KeysLink id={id} tab="settings" />} /></div>}
      </>}
  </Stack></Card>
}

function AppCard({ app, catalogue, token, date, readOnly, pending, install, uninstall }: {
  app: PlatformApp; catalogue?: Catalogue; token?: PlatformKey; date: (value: string | null) => string
  readOnly: boolean; pending: boolean; install: (scopes: string[]) => void; uninstall: () => Promise<void>
}) {
  const t = useT()
  const name = app.title || app.name
  const [draft, dispatch] = useReducer(scopeGrantReducer, { ...initialGrant, picked: app.scopes })
  const [error, setError] = useState(false)
  const scopes = app.scopes.filter(scope => draft.picked.includes(scope))
  const toggle = (scope: string, checked: boolean) => dispatch({ type: 'scope', scope, checked })
  return <Card data-testid="app-item" data-installed={String(app.installed)}><Stack>
    <Row><h3>{t('schema.option', { value: name })}</h3><Badge tone={app.installed ? 'success' : 'neutral'}>
      <span data-testid="app-status">{t(app.installed ? 'connectB.apps.active' : 'connectB.apps.inactive')}</span>
    </Badge></Row>
    <p>{t('connectB.apps.slug', { name: app.name })}</p>
    {app.events.length > 0 && <p>{t('connectB.apps.events', { events: app.events.join(', ') })}</p>}
    {app.installed ? <>
      <p>{t('connectB.apps.granted', { date: date(app.installed_at), scopes: app.granted_scopes.join(', ') })}</p>
      {app.installation_id && <p>{t('connectB.apps.installation', { id: app.installation_id })}</p>}
      {token && <p>{t('connectB.apps.tokenTimes', { expires: date(token.expires_at), lastUsed: date(token.last_used_at) })}</p>}
      {!readOnly && <Row><ConfirmDestructive
        trigger={<Button data-testid="uninstall" variant="danger" disabled={pending}
          aria-label={t('connectB.apps.uninstallName', { name })}>{t('connectB.apps.uninstall')}</Button>}
        title={t('connectB.apps.uninstallName', { name })} description={t('connectB.apps.uninstallHelp')} action={t('connectB.apps.uninstallYes')}
        onConfirm={uninstall}><div data-testid="uninstall-confirm" /></ConfirmDestructive></Row>}
    </> : <>
      <Stack role="group" aria-label={t('connectB.apps.scopes')}>
        <h4>{t('connectB.apps.scopes')}</h4>
        {app.scopes.map(scope => {
          const fields = catalogue?.entities.find(item => item.entity === scope)?.fields
          return <Checkbox key={scope} data-testid="app-scope" disabled={readOnly || pending} checked={scopes.includes(scope)}
            label={fields?.length ? t('connectB.keys.scopeFields', { entity: scope, fields: fields.join(', ') }) : t('schema.option', { value: scope })}
            onChange={event => toggle(scope, event.target.checked)} />
        })}
        {error && !scopes.length && <Alert tone="danger">{t('connectB.apps.scopeError')}</Alert>}
      </Stack>
      {!readOnly && <Row><Button data-testid="install" variant="primary" disabled={pending}
        aria-label={t('connectB.apps.installName', { name })} onClick={() => scopes.length ? install(scopes) : setError(true)}>
        {t('connectB.apps.install')}</Button></Row>}
    </>}
  </Stack></Card>
}
