import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useT } from '../../../../i18n'
import { ConfirmDestructive, Form, ReadOnlyNote, SettingsSection } from '../../../../patterns'
import { Button, Checkbox, Row, Select, Stack } from '../../../../ui'
import { orgSessionHours, validators } from '../../../../validators'
import { orgApi, orgQueries } from '../../api/org'
import type { OrgPolicies, OrgPoliciesUpdate } from '../../api/org'
import { canAdmin, OrgData, OrgProblem, textValue, useOrgAction, useOrgFields } from './shared'
import type { OrgProps } from './shared'

export function Export(props: Pick<OrgProps, 'org' | 'user'>) {
  const { org } = props
  const t = useT()
  const action = useOrgAction(props)
  return <SettingsSection title={t('org.export')} description={t('org.exportBody', { org: org.name })}>
    {action.isError && <OrgProblem error={action.error} />}
    <Row><Button disabled={action.isPending} onClick={() => action.submit(() => orgApi.export(org.slug), 'org.exported', 'none')}>{t(action.isPending ? 'org.preparing' : 'org.downloadExport')}</Button></Row>
  </SettingsSection>
}

function PoliciesForm(props: OrgProps & { policy: OrgPolicies }) {
  const { org, policy } = props
  const t = useT()
  const fields = useOrgFields()
  const action = useOrgAction(props)
  const [mfa, setMfa] = useState(policy.require_mfa)
  const [support, setSupport] = useState(policy.allow_impersonation)
  const [mode, setMode] = useState(policy.session_ttl_hours == null ? 'default' : 'custom')
  const [hours, setHours] = useState(String(policy.session_ttl_hours ?? policy.default_session_hours))
  const [confirm, setConfirm] = useState<OrgPoliciesUpdate>()
  const ttl = mode === 'custom' ? Number(hours) : null
  const changes: OrgPoliciesUpdate = {}
  if (mfa !== policy.require_mfa) changes.require_mfa = mfa
  if (support !== policy.allow_impersonation) changes.allow_impersonation = support
  if (ttl !== policy.session_ttl_hours) changes.session_ttl_hours = ttl
  const warnMfa = confirm?.require_mfa === true
  const warnSupport = confirm?.allow_impersonation === false

  return <SettingsSection title={t('org.securityPolicies')}>
    {action.isError && <OrgProblem error={action.error} />}
    <p>{t('org.mfaImpact', { count: policy.members_without_mfa })}</p>
    <Form fields={[
      { name: 'mfa', label: t('org.field.mfa'), hint: t('org.mfaPolicyHint'),
        control: ({ name, id, disabled, 'aria-describedby': describedBy }) => <Checkbox name={name} id={id} disabled={disabled}
          aria-describedby={describedBy} label={t('org.requireMfa')} checked={mfa} onChange={event => setMfa(event.target.checked)} /> },
      { name: 'hoursMode', label: t('org.field.hoursMode'), control: ({ name, disabled, ...triggerProps }) =>
        <Select name={name} disabled={disabled} triggerProps={triggerProps} value={mode} onValueChange={setMode}
          options={[{ value: 'default', label: t('org.platformHours', { count: policy.default_session_hours }) },
            { value: 'custom', label: t('org.hoursMode.custom') }]} /> },
      ...(mode === 'custom' ? [fields.input('hours', { value: hours, inputMode: 'numeric', onChange: event => setHours(event.target.value) },
        [value => value.trim() ? orgSessionHours(value) : validators.required(value)])] : []),
      { name: 'support', label: t('org.field.support'), control: ({ name, id, disabled }) =>
        <Checkbox name={name} id={id} disabled={disabled} label={t('org.allowSupport')} checked={support} onChange={event => setSupport(event.target.checked)} /> },
    ]} pending={action.isPending} submitProps={{ disabled: !Object.keys(changes).length }} submitLabel={t('org.savePolicies')} onSubmit={data => {
      const next = { ...changes }
      if (next.session_ttl_hours !== undefined && mode === 'custom') next.session_ttl_hours = Number(textValue(data, 'hours'))
      if (next.require_mfa === true || next.allow_impersonation === false) setConfirm(next)
      else action.submit(() => orgApi.policies(org.slug, next), 'org.policiesSaved')
    }} />
    <Row><Button asChild><Link to="/account">{t('org.openAccount')}</Link></Button></Row>
    <ConfirmDestructive open={Boolean(confirm)} onOpenChange={open => { if (!open) setConfirm(undefined) }}
      title={t(warnMfa ? 'org.mfaTitle' : 'org.supportTitle')}
      description={[warnMfa && t('org.mfaBody', { count: policy.members_without_mfa, org: org.name }), warnSupport && t('org.supportBody')].filter(Boolean).join(' ')}
      action={t('org.savePolicies')} onConfirm={async () => {
        if (confirm) await action.perform(() => orgApi.policies(org.slug, confirm), 'org.policiesSaved')
      }} />
  </SettingsSection>
}

export function Security(props: OrgProps) {
  const { org, owners } = props
  const t = useT()
  const admin = canAdmin(org)
  const query = useQuery({ ...orgQueries.policies(org.slug), enabled: admin })
  return <Stack gap={4}>
    {admin ? <OrgData query={query}>{policy => <PoliciesForm
      key={JSON.stringify([policy.require_mfa, policy.session_ttl_hours, policy.allow_impersonation])} {...props} policy={policy} />}</OrgData> :
      <SettingsSection title={t('org.securityPolicies')}>
        <p>{t('org.securitySummary', { mfa: t(org.require_mfa ? 'org.yes' : 'org.no'),
          hours: org.session_ttl_hours == null ? t('org.hoursMode.default') : t('org.hours', { count: org.session_ttl_hours }) })}</p>
        <ReadOnlyNote>{t('org.adminOnly', { owners })}</ReadOnlyNote>
      </SettingsSection>}
    {org.my_role === 'owner' && <Export {...props} />}
  </Stack>
}
