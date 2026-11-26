import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { SettingsSection } from '../../../patterns'
import { Alert, CodeBlock, Stack, Table } from '../../../ui'
import { setupOptions } from '../api/ship'
import type { AuthConfig, KeycloakConfig, PaymentsConfig, StorageConfig } from '../api/ship'
import { ShipLoading, ShipProblem, useShipFormat } from './Common'

export function FirstRun({ id, slug, generation, hash }: { id: string; slug: string; generation: string | null; hash: string | null }) {
  const t = useT()
  const setup = useQuery(setupOptions(id, generation ?? hash ?? 'latest'))
  return <Stack>
    <Alert tone="success">{generation && hash ? t('ship.generationSaved', { id: generation, hash: hash.slice(0, 12) }) : t('ship.downloadSaved')}</Alert>
    {setup.isPending ? <ShipLoading label={t('ship.setupLoading')} /> :
      setup.isError ? <ShipProblem error={setup.error} message={t('ship.setupError')} retry={setup.refetch} /> :
        <>
          <AuthSetup slug={slug} auth={setup.data.auth} keycloak={setup.data.keycloak} />
          {setup.data.payments?.enabled && <PaymentsSetup slug={slug} payments={setup.data.payments} />}
          {setup.data.storage?.enabled && <StorageSetup slug={slug} storage={setup.data.storage} />}
        </>}
  </Stack>
}

type Variable = { name: string; key: string; values?: Record<string, string | number> }

function Variables({ vars }: { vars: Variable[] }) {
  const t = useT()
  const { columns } = useShipFormat()
  return vars.length > 0 && <Table label={t('ship.envVars')} columns={columns('variable', 'setupValue')}
    rows={vars.map(({ name, key, values }) => ({
      id: name, cells: [<code>{t('ship.value', { value: name })}</code>, t('ship.setup.' + key, values)],
    }))} />
}

function emailVariables(auth: AuthConfig): Variable[] {
  return auth.smtp_config ? [
    { name: 'SMTP_USERNAME', key: 'smtpUser', values: { host: auth.smtp_config.host, port: auth.smtp_config.port } },
    { name: 'SMTP_PASSWORD', key: 'smtpPassword' },
  ] : []
}

function authVariables(auth: AuthConfig | null, keycloak: KeycloakConfig | null): Variable[] {
  if (!auth?.enabled) return []
  if (auth.provider === 'keycloak') {
    if (!keycloak) return []
    const own = keycloak.mode === 'own'
    return [
      { name: 'KEYCLOAK_PUBLIC_URL', key: own ? 'keycloakUrlOwn' : 'keycloakUrlExternal' },
      { name: 'API_PUBLIC_URL', key: 'apiUrl' },
      ...(own ? [
        { name: 'KEYCLOAK_DB_PASSWORD', key: 'keycloakDb' },
        { name: 'KC_BOOTSTRAP_ADMIN_USERNAME / KC_BOOTSTRAP_ADMIN_PASSWORD', key: 'keycloakAdmin' },
        ...emailVariables(auth),
        ...keycloak.identity_providers.map(idp => ({
          name: 'KC_IDP_' + idp.alias.toUpperCase().replace(/-/g, '_') + '_CLIENT_SECRET',
          key: 'keycloakIdp', values: { name: idp.display_name || idp.alias },
        })),
      ] : [{ name: 'KEYCLOAK_ADMIN_USERNAME / KEYCLOAK_ADMIN_PASSWORD', key: 'keycloakExistingAdmin' }]),
    ]
  }
  const sms: Record<string, Variable[]> = {
    twilio: [{ name: 'TWILIO_ACCOUNT_SID', key: 'twilio' }, { name: 'TWILIO_AUTH_TOKEN', key: 'twilio' }],
    vonage: [{ name: 'VONAGE_API_KEY', key: 'vonage' }, { name: 'VONAGE_API_SECRET', key: 'vonage' }],
    aws_sns: [{ name: 'AWS_REGION', key: 'snsRegion' }, { name: 'AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY', key: 'snsAccess' }],
  }
  return [
    auth.jwt_algorithm === 'RS256' ? { name: 'AUTH_JWT_PRIVATE_KEY', key: 'rsaKey' } : { name: 'AUTH_JWT_SECRET', key: 'jwtSecret' },
    ...emailVariables(auth),
    ...(auth.sms_provider && auth.sms_config ? sms[auth.sms_provider] ?? [] : []),
    ...(auth.token_store === 'redis' ? [{ name: 'REDIS_URL', key: 'redis' }] : []),
  ]
}

function AuthSetup({ slug, auth, keycloak }: { slug: string; auth: AuthConfig | null; keycloak: KeycloakConfig | null }) {
  const t = useT()
  const vars = authVariables(auth, keycloak)
  const useKeycloak = auth?.enabled && auth.provider === 'keycloak'
  return <SettingsSection title={t('ship.authSetup', { slug })}>
    <ol className="v2-stack">
      <li>{t('ship.setup.unzip')}</li>
      {vars.length > 0 && <li>{t('ship.setup.fillEnv')}</li>}
      {useKeycloak && keycloak && keycloak.mode !== 'own' && <li>{t('ship.setup.keycloakRegister')}</li>}
      <li>{t('ship.setup.start')}</li>
      {useKeycloak && keycloak && <li>{t('ship.setup.keycloakUsers', { realm: keycloak.realm, client: keycloak.api_client_id })}</li>}
      {useKeycloak && keycloak?.mode === 'own' && <li>{t('ship.setup.keycloakOwn')}</li>}
      {useKeycloak && auth?.multi_tenant && <li>{t('ship.setup.keycloakTenants')}</li>}
      <li>{t('ship.setup.test')}</li>
    </ol>
    <Variables vars={vars} />
    {auth?.enabled && !useKeycloak && <p>{t('ship.setup.authRate')}</p>}
  </SettingsSection>
}

const paymentsSetup = {
  stripe: {
    vars: [{ name: 'STRIPE_SECRET_KEY', key: 'stripeKey' }, { name: 'STRIPE_WEBHOOK_SECRETS', key: 'stripeWebhook' }],
    events: [
      'checkout.session.completed', 'checkout.session.async_payment_succeeded', 'checkout.session.async_payment_failed',
      'checkout.session.expired', 'charge.refunded', 'refund.created', 'refund.updated', 'charge.refund.updated',
      'charge.dispute.created', 'charge.dispute.updated', 'charge.dispute.closed',
    ],
  },
  razorpay: {
    vars: [{ name: 'RAZORPAY_KEY_ID', key: 'razorpayId' }, { name: 'RAZORPAY_KEY_SECRET', key: 'razorpayKey' },
      { name: 'RAZORPAY_WEBHOOK_SECRETS', key: 'razorpayWebhook' }],
    events: [
      'payment_link.paid', 'payment_link.expired', 'payment_link.cancelled', 'refund.created', 'refund.processed', 'refund.failed',
      'payment.dispute.created', 'payment.dispute.won', 'payment.dispute.lost', 'payment.dispute.closed',
      'payment.dispute.under_review', 'payment.dispute.action_required',
    ],
  },
}

function PaymentsSetup({ slug, payments }: { slug: string; payments: PaymentsConfig }) {
  const t = useT()
  const provider = paymentsSetup[payments.provider]
  if (!provider) return null
  return <SettingsSection title={t('ship.paymentsSetup', { slug })}>
    <p>{t('ship.setup.fillEnv')}</p>
    <Variables vars={provider.vars} />
    <p>{t('ship.setup.paymentsHook', { provider: payments.provider })}</p>
    <CodeBlock code={provider.events.join('\n')} label={t('ship.paymentEvents')} />
    <p>{t('ship.setup.paymentsWorker')}</p>
  </SettingsSection>
}

function StorageSetup({ slug, storage }: { slug: string; storage: StorageConfig }) {
  const t = useT()
  const minio = storage.backend === 'minio'
  const vars: Variable[] = minio ? [
    { name: 'STORAGE_ACCESS_KEY_ID', key: 'storageUser' },
    { name: 'STORAGE_SECRET_ACCESS_KEY', key: 'storagePassword' },
    { name: 'STORAGE_ENDPOINT_URL', key: 'storageEndpoint' },
  ] : [
    { name: 'STORAGE_ACCESS_KEY_ID / STORAGE_SECRET_ACCESS_KEY', key: 'storageIam' },
    { name: 'STORAGE_REGION', key: 'storageRegion', values: { region: storage.region ?? t('ship.setup.bucketRegion') } },
  ]
  return <SettingsSection title={t('ship.storageSetup', { slug })}>
    <p>{t('ship.setup.fillEnv')}</p>
    <Variables vars={[...vars, { name: 'APP_ENV', key: 'storageEnvironment' }]} />
    <ol className="v2-stack">
      <li>{t(minio ? 'ship.setup.storageLocal' : 'ship.setup.storageBucket', { bucket: storage.bucket ?? t('ship.unknown') })}</li>
      <li>{t('ship.setup.storageStart')}</li>
      <li>{t('ship.setup.storageMaintenance')}</li>
      <li>{t('ship.setup.storageDocs')}</li>
    </ol>
  </SettingsSection>
}
