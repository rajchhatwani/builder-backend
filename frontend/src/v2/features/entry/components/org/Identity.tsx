import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../../i18n'
import { ConfirmDestructive, Form, SettingsSection } from '../../../../patterns'
import { Alert, Badge, Button, Checkbox, Row, Select, Stack, Textarea } from '../../../../ui'
import { orgLimits, orgSsoDomain, orgSsoUrl, validators } from '../../../../validators'
import { orgApi, orgQueries } from '../../api/org'
import type { SsoCheck, SsoConfig, SsoConfigWrite, SsoProtocol } from '../../api/org'
import { CopyValue, Scim } from './Scim'
import { orgDate, OrgData, orgFieldError, OrgProblem, OrgTabButton, OrgTable, textValue, useOrgAction, useOrgFields } from './shared'
import type { OrgProps } from './shared'

type IdentityProps = OrgProps & { config: SsoConfig }

function SsoSettings({ config, ...props }: IdentityProps) {
  const t = useT()
  const [protocol, setProtocol] = useState<SsoProtocol>(config.protocol ?? 'saml')
  const action = useOrgAction(props)
  const fields = useOrgFields()
  const saml = protocol === 'saml'
  const matches = config.protocol === protocol
  const urlChecks = [validators.required, validators.length(orgLimits.ssoUrl), orgSsoUrl]
  const serverErrors = orgFieldError(action.error, {
    idp_cert_pem: 'cert', idp_entity_id: 'idpEntity', idp_sso_url: 'idpUrl', oidc_client_secret: 'clientSecret',
    oidc_client_id: 'clientId', oidc_discovery_url: 'discovery',
  })
  return <SettingsSection title={t('org.idp')}>
    {action.isError && !serverErrors && <OrgProblem error={action.error} />}
    <Form serverErrors={serverErrors} fields={[
      { name: 'protocol', label: t('org.field.protocol'), control: ({ name, disabled, ...triggerProps }) =>
        <Select name={name} disabled={disabled} triggerProps={triggerProps} value={protocol} onValueChange={value => setProtocol(value as SsoProtocol)}
          options={(['saml', 'oidc'] as const).map(value => ({ value, label: t('org.protocol.' + value) }))} /> },
      ...(saml ? [
        fields.input('idpEntity', { defaultValue: config.idp_entity_id ?? '', maxLength: orgLimits.entityId }, [validators.required, validators.length(orgLimits.entityId)]),
        fields.input('idpUrl', { defaultValue: config.idp_sso_url ?? '', type: 'url', maxLength: orgLimits.ssoUrl }, urlChecks),
        { name: 'cert', label: t('org.field.cert'), hint: config.idp_certificate ? t('org.certCurrent', {
          subject: config.idp_certificate.subject, fingerprint: config.idp_certificate.sha256_fingerprint,
          date: orgDate(config.idp_certificate.not_after) ?? config.idp_certificate.not_after,
        }) : undefined, validate: [validators.required, validators.length(orgLimits.cert)],
        control: attributes => <Textarea {...attributes} maxLength={orgLimits.cert} /> } satisfies ReturnType<typeof fields.input>,
      ] : [
        fields.input('discovery', { defaultValue: config.oidc_discovery_url ?? '', type: 'url', maxLength: orgLimits.ssoUrl }, urlChecks),
        fields.input('clientId', { defaultValue: config.oidc_client_id ?? '', maxLength: orgLimits.clientId }, [validators.required, validators.length(orgLimits.clientId)]),
        { ...fields.input('clientSecret', { type: 'password', autoComplete: 'new-password', maxLength: orgLimits.clientSecret }, [
          ...(!matches || !config.oidc_client_secret_set ? [validators.required] : []), validators.length(orgLimits.clientSecret),
        ]), hint: matches && config.oidc_client_secret_set ? t('org.keepSecret') : undefined },
      ]),
      fields.select('jitRole', ['member', 'admin'], config.jit_role ?? 'member', 'role'),
    ]} pending={action.isPending} submitLabel={t('org.saveSso')} onSubmit={data => {
      const body: SsoConfigWrite = {
        protocol, jit_enabled: data.has('jit'), jit_role: textValue(data, 'jitRole') as 'member' | 'admin',
        trust_unverified_email: data.has('trustEmail'),
        ...(saml ? { idp_entity_id: textValue(data, 'idpEntity'), idp_sso_url: textValue(data, 'idpUrl'), idp_cert_pem: textValue(data, 'cert') } :
          { oidc_discovery_url: textValue(data, 'discovery'), oidc_client_id: textValue(data, 'clientId'),
            oidc_client_secret: String(data.get('clientSecret') ?? '') || undefined }),
      }
      action.submit(() => orgApi.saveSso(props.org.slug, body), 'org.ssoSaved')
    }}>
      <Checkbox name="jit" label={t('org.jit')} defaultChecked={config.jit_enabled ?? true} disabled={action.isPending} />
      <Checkbox name="trustEmail" label={t('org.trustEmail')} defaultChecked={config.trust_unverified_email ?? false} disabled={action.isPending} />
    </Form>
  </SettingsSection>
}

function Domains({ config, ...props }: IdentityProps) {
  const t = useT()
  const action = useOrgAction(props)
  const fields = useOrgFields()
  const [revision, reset] = useState(0)
  const { slug } = props.org
  return <SettingsSection title={t('org.domains')} description={t('org.domainsHelp')}>
    {action.isError && <OrgProblem error={action.error} />}
    <Form key={revision} fields={[fields.input('domain', { placeholder: t('org.domainPlaceholder'), maxLength: orgLimits.domain },
      [validators.required, validators.length(orgLimits.domain), orgSsoDomain])]}
      pending={action.isPending} submitLabel={t('org.addDomain')} onSubmit={data => action.submit(async () => {
        await orgApi.domain(slug, textValue(data, 'domain'))
        reset(value => value + 1)
      })} />
    {config.domains.map(domain => <Stack key={domain.domain}>
      <Row><strong>{domain.domain}</strong><Badge tone={domain.verified_at ? 'success' : 'warning'}>{t(domain.verified_at ? 'org.verified' : 'org.waitingDns')}</Badge></Row>
      {!domain.verified_at && <p>{t('org.dnsHelp')}</p>}
      <CopyValue label={t('org.dnsName', { type: domain.dns_record_type ?? 'TXT' })} value={domain.dns_record_name} />
      <CopyValue label={t('org.dnsValue')} value={domain.dns_record_value} />
      <Row>
        {!domain.verified_at && <Button disabled={action.isPending} onClick={() => action.submit(() => orgApi.verifyDomain(slug, domain.domain), 'org.domainVerified')}>{t('org.verify')}</Button>}
        <ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending}>{t('org.remove')}</Button>}
          title={t('org.removeDomainTitle', { domain: domain.domain })} description={t('org.removeDomainBody')} action={t('org.remove')}
          onConfirm={() => action.perform(() => orgApi.removeDomain(slug, domain.domain), 'org.domainRemoved')} />
      </Row>
    </Stack>)}
  </SettingsSection>
}

function Status({ config, ...props }: IdentityProps) {
  const t = useT()
  const [check, setCheck] = useState<SsoCheck>()
  const action = useOrgAction(props)
  const { slug } = props.org
  const result = props.search.sso_test
  const testResult = (result: string) => t(result === 'ok' || result === 'email_mismatch' ? 'org.test.' + result : 'org.test.failed', { result })
  return <SettingsSection title={t('org.field.status')}>
    {action.isError && <OrgProblem error={action.error} />}
    {result && <Alert tone={result === 'ok' ? 'success' : 'danger'}>{testResult(result)}</Alert>}
    <Row><Badge tone={config.active ? 'success' : 'neutral'}>{config.configured && config.protocol ?
      t('org.ssoState', { protocol: t('org.protocol.' + config.protocol), state: t(config.active ? 'org.on' : 'org.off') }) : t('org.notConfigured')}</Badge>
      <span>{t('org.lastTest', { date: orgDate(config.last_test?.at) ?? t('org.never') })}</span></Row>
    {config.last_test && <p>{testResult(config.last_test.result)} {config.last_test.tested_by_email}</p>}
    <p>{t('org.testHelp')}</p>
    <Row>
      <Button disabled={action.isPending || !config.configured} onClick={() => action.submit(async () => {
        window.location.assign((await orgApi.testSso(slug)).login_url)
      }, '', 'none')}>{t('org.testSso')}</Button>
      <Button disabled={action.isPending} onClick={() => action.submit(async () => { setCheck(await orgApi.checkSso(slug)) }, '', 'none')}>{t('org.checkSso')}</Button>
      {config.active ? <ConfirmDestructive trigger={<Button disabled={action.isPending}>{t('org.turnSsoOff')}</Button>}
        title={t('org.turnSsoOff')} description={t('org.turnSsoOffBody')} action={t('org.turnSsoOff')}
        onConfirm={() => action.perform(() => orgApi.activateSso(slug, false), 'org.ssoOff')} /> :
        config.last_test?.result === 'ok' ?
          <Button disabled={action.isPending || !config.configured} onClick={() => action.submit(() => orgApi.activateSso(slug, true), 'org.ssoOn')}>{t('org.turnSsoOn')}</Button> :
          <ConfirmDestructive trigger={<Button disabled={action.isPending || !config.configured}>{t('org.turnSsoOn')}</Button>}
            title={t('org.turnSsoOnTitle')} description={t('org.turnSsoOnBody')} action={t('org.turnSsoOn')}
            onConfirm={() => action.perform(() => orgApi.activateSso(slug, true), 'org.ssoOn')} />}
      <ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending || !config.configured || config.active}>{t('org.removeSso')}</Button>}
        title={t('org.removeSso')} description={t('org.removeSsoBody')} action={t('org.removeSso')}
        onConfirm={() => action.perform(() => orgApi.deleteSso(slug), 'org.ssoRemoved')} />
    </Row>
    {check && <>
      <Alert tone={check.ok ? 'success' : 'warning'}>{t(check.ok ? 'org.checkOk' : 'org.checkWarning')}</Alert>
      <OrgTable label={t('org.checkSso')} fields={['check', 'result', 'details']} rows={check.checks.map(row => ({
        id: row.name, cells: [t('org.check.' + row.name), t('org.result.' + row.status), row.detail ?? t('org.na')],
      }))} />
    </>}
  </SettingsSection>
}

export function Identity(props: OrgProps) {
  const { org } = props
  const t = useT()
  const query = useQuery(orgQueries.sso(org.slug))
  return <Stack gap={4}>
    <OrgData query={query}>{config => config.allowed_by_plan ? <>
      <Status {...props} config={config} />
      <SettingsSection title={t('org.serviceProvider')}>
        {Object.entries(config.sp).map(([key, value]) => <CopyValue key={key} label={t('org.sp.' + key)} value={value} />)}
        <Row><Button asChild><a href={config.sp.metadata_url} target="_blank" rel="noreferrer" download>{t('org.downloadMetadata')}</a></Button></Row>
      </SettingsSection>
      <Domains {...props} config={config} />
      <SsoSettings key={config.updated_at ?? 'new'} {...props} config={config} />
    </> : <Alert action={<OrgTabButton slug={org.slug} tab="plan">{t('org.seePlans')}</OrgTabButton>}>{t('org.noSso')}</Alert>}</OrgData>
    <Scim {...props} />
  </Stack>
}
