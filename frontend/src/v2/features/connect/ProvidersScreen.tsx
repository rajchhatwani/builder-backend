import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { PageHeader } from '../../patterns'
import { Alert, Button, Card, Disclosure, EmptyState, Row, Stack } from '../../ui'
import { credentialLikeValue, providerDraftIssues, providerSecretKey } from '../../validators'
import { blockOptions, connectRolesOptions } from './api/blocks'
import type { Providers } from './api/blocks'
import { specOptions } from './api/connect'
import type { ConnectProps } from './api/connect'
import { BlockSettings } from './components/BlockSettings'
import { BlockRole, SectionLink } from './components/BlockStatus'
import { providerKinds, providersDefaults, providersSchema } from './state/settingsSchemas'

function omitCredentials(value: Providers): Providers {
  return { ...value, adapters: value.adapters.map(adapter => ({
    ...adapter, name: credentialLikeValue(adapter.name) ? '' : adapter.name,
    settings: Object.fromEntries(Object.entries(adapter.settings ?? {}).filter(([name, setting]) =>
      !providerSecretKey(name) && !credentialLikeValue(setting))),
  })) }
}

export default function ProvidersScreen(props: ConnectProps) {
  const { projectId, role, rolePending } = props
  const t = useT()
  const raw = useQuery(blockOptions(projectId, 'providers'))
  const hidden = raw.data?.block?.adapters.some(adapter => credentialLikeValue(adapter.name) ||
    Object.entries(adapter.settings ?? {}).some(([key, value]) => providerSecretKey(key) || credentialLikeValue(value)))
  const roles = useQuery(connectRolesOptions(projectId))
  const spec = useQuery(specOptions(projectId))
  const readOnly = !role || role === 'viewer' || Boolean(rolePending)
  return <Stack>
    <PageHeader title={t('connectB.providers.title')} description={t('connectB.providers.intro')} />
    <BlockRole {...props} />
    {(roles.isError || spec.isError) && <Alert tone="warning" action={<Button onClick={() => {
      if (roles.isError) void roles.refetch()
      if (spec.isError) void spec.refetch()
    }}>{t('common.retry')}</Button>}>{t('connectA2.dependenciesError')}</Alert>}
    <BlockSettings projectId={projectId} name="providers" schema={providersSchema} defaults={providersDefaults}
      title={t('connectB.providers.settings')} errorKey="connectB.providers.error" readOnly={readOnly}
      prepare={omitCredentials} remove validate={value => providerDraftIssues(value, t)}
      options={path => path[0] === 'admin_role' && roles.data?.roles.length ? roles.data.roles.map(role => ({
        value: role.name, label: t('schema.option', { value: role.label || role.name }),
      })) : undefined}
      empty={<EmptyState title={t('connectB.providers.empty')} description={t('connectB.providers.emptyHelp')} />}>
      {draft => <Card><Stack>
        <h2>{t('connectB.providers.vault')}</h2>
        <p>{t('connectB.providers.vaultHelp')}</p>
        {hidden && <Alert tone="warning">{t('connectB.providers.legacy')}</Alert>}
        <p>{t('connectB.providers.rules')}</p>
        {draft.enabled && spec.data && (!spec.data.auth?.enabled || !spec.data.entities.length ||
          roles.data && !roles.data.roles.some(role => role.name === draft.admin_role)) &&
          <Alert tone="warning">{t('connectB.providers.prerequisites')}</Alert>}
        <Disclosure label={t('connectB.providers.topology')}><ul>{providerKinds.map(kind =>
          <li key={kind}>{t('connectB.providers.kind', { kind, adapters: ['emulator', ...draft.adapters.filter(item => item.kind === kind && item.name).map(item => item.name)].join(', ') })}</li>)}</ul></Disclosure>
        <p>{t('connectB.providers.resilience', { timeout: draft.timeout_seconds, attempts: draft.max_attempts, failures: draft.breaker_failures, reset: draft.breaker_reset_seconds })}</p>
        <Row>{['auth', 'model', 'notiftypes', 'webhooks', 'payments'].map(section =>
          <SectionLink key={section} projectId={projectId} section={section} label={t('nav.' + section)} />)}</Row>
      </Stack></Card>}
    </BlockSettings>
  </Stack>
}
