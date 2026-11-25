import { useReducer, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../../i18n'
import { ConfirmDestructive, Form, ReadOnlyNote, SettingsSection } from '../../../../patterns'
import { Alert, Badge, Button, Row } from '../../../../ui'
import { orgGroupName, orgLimits, validators } from '../../../../validators'
import { orgApi, orgQueries } from '../../api/org'
import type { ScimConfig, ScimRole } from '../../api/org'
import { scimDraft, scimMappings } from '../../state/scimMappings'
import { useCopy } from '../SecondFactor'
import { orgDate, OrgData, OrgProblem, OrgTabButton, OrgTable, roles, textValue, useOrgAction, useOrgFields } from './shared'
import type { OrgProps } from './shared'

export function CopyValue({ label, value }: { label: string; value: string }) {
  const t = useT()
  const copy = useCopy()
  return <Row><strong>{label}</strong><code>{value}</code>
    <Button aria-label={t('org.copyValue', { label })} onClick={() => void copy(value, 'org.copied')}>{t('org.copy')}</Button></Row>
}

function Mappings({ config, ...props }: OrgProps & { config: ScimConfig }) {
  const t = useT()
  const action = useOrgAction(props)
  const fields = useOrgFields()
  const [state, dispatch] = useReducer(scimMappings, config.group_roles, scimDraft)
  const [revision, reset] = useState(0)
  const owner = props.org.my_role === 'owner'
  const blocked = !owner && Object.values(config.group_roles).includes('owner')
  const choices = owner ? roles : roles.filter(role => role !== 'owner')
  const draft = state.rows.map(row => {
    const name = 'group-' + row.id
    return [
      { ...fields.input(name, { defaultValue: row.name, maxLength: orgLimits.groupName }, [validators.length(orgLimits.groupName)]),
        label: t('org.field.group'), validateWith: (value: string, data: FormData) =>
          orgGroupName(value, state.rows.map(item => textValue(data, 'group-' + item.id))) },
      { ...fields.select('role-' + row.id, choices, row.role, 'role'), label: t('org.groupRole', { number: state.rows.indexOf(row) + 1 }) },
    ]
  }).flat()

  return <SettingsSection title={t('org.groupMappings')}>
    {action.isError && <OrgProblem error={action.error} />}
    {blocked ? <ReadOnlyNote>{t('org.ownerMappings')}</ReadOnlyNote> : <Form key={revision} pending={action.isPending} fields={draft}
      submitLabel={t('org.saveMappings')} onSubmit={data => {
        const group_roles = Object.fromEntries(state.rows.map(row => [
          textValue(data, 'group-' + row.id).toLowerCase(), textValue(data, 'role-' + row.id) as ScimRole,
        ]))
        action.submit(() => orgApi.scim(props.org.slug, { group_roles }), 'org.mappingsSaved')
      }}>
      {!state.rows.length && <p>{t('org.noMappings')}</p>}
      <Row>{state.rows.map((row, index) => <Button key={row.id} disabled={action.isPending}
        onClick={() => dispatch({ type: 'remove', id: row.id })}>{t('org.removeMapping', { number: index + 1 })}</Button>)}</Row>
      <Row>
        <Button disabled={state.rows.length >= orgLimits.groups || action.isPending} onClick={() => dispatch({ type: 'add' })}>{t('org.addMapping')}</Button>
        <Button disabled={action.isPending} onClick={() => { dispatch({ type: 'reset', mappings: config.group_roles }); reset(value => value + 1) }}>{t('common.discard')}</Button>
      </Row>
    </Form>}
    {blocked && <OrgTable label={t('org.groupMappings')} fields={['group', 'role']}
      rows={Object.entries(config.group_roles).map(([id, role]) => ({ id, cells: [id, t('org.role.' + role)] }))} />}
  </SettingsSection>
}

function Directory({ config, ...props }: OrgProps & { config: ScimConfig }) {
  const t = useT()
  const copy = useCopy()
  const action = useOrgAction(props)
  const [token, setToken] = useState('')
  const { slug } = props.org
  const issue = async () => { setToken((await orgApi.scimToken(slug)).token) }
  return <>
    <SettingsSection title={t('org.scimProvisioning')}>
      {!config.allowed_by_plan ? <Alert action={<OrgTabButton slug={slug} tab="plan">{t('org.seePlans')}</OrgTabButton>}>{t('org.noScim')}</Alert> : <>
        {action.isError && <OrgProblem error={action.error} />}
        <Row><Badge tone={config.active ? 'success' : 'neutral'}>{t(config.configured ? config.active ? 'org.on' : 'org.off' : 'org.notConfigured')}</Badge>
          <span>{t('org.lastSync', { date: orgDate(config.last_sync_at) ?? t('org.never') })}</span></Row>
        <p>{t('org.scimCounts', { active: config.active_users, deactivated: config.deactivated_users })}</p>
        <CopyValue label={t('org.scimBase')} value={config.base_url} />
        <CopyValue label={t('org.scimUsers')} value={config.users_url} />
        {config.token_hint && <p>{t('org.scimHint', { hint: config.token_hint })}</p>}
        {config.configured && !config.active && !config.token_hint && <Alert tone="warning">{t('org.scimRotated')}</Alert>}
        {token && <Alert tone="warning">{t('org.scimTokenOnce')}</Alert>}
        {token ? <>
          <code>{token}</code>
          <Row><Button onClick={() => void copy(token, 'org.copied')}>{t('org.copyToken')}</Button>
            <Button onClick={() => setToken('')}>{t('org.scimTokenSaved')}</Button></Row>
        </> : <Row>
          {config.configured ? <>
            <ConfirmDestructive trigger={<Button disabled={action.isPending}>{t('org.rotateToken')}</Button>}
              title={t('org.rotateTitle')} description={t('org.rotateBody')} action={t('org.rotateToken')} onConfirm={() => action.perform(issue, '')} />
            {config.active ? <ConfirmDestructive trigger={<Button disabled={action.isPending}>{t('org.turnScimOff')}</Button>}
              title={t('org.turnScimOff')} description={t('org.turnScimOffBody')} action={t('org.turnScimOff')}
              onConfirm={() => action.perform(() => orgApi.scim(slug, { active: false }), 'org.scimOff')} /> :
              <Button disabled={!config.token_hint || action.isPending} onClick={() => action.submit(() => orgApi.scim(slug, { active: true }), 'org.scimOn')}>{t('org.turnScimOn')}</Button>}
            <ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending}>{t('org.removeScim')}</Button>}
              title={t('org.removeScim')} description={t('org.removeScimBody')} action={t('org.removeScim')}
              onConfirm={() => action.perform(() => orgApi.deleteScim(slug), 'org.scimRemoved')} />
          </> : <Button variant="primary" disabled={action.isPending} onClick={() => action.submit(issue, '')}>{t('org.generateToken')}</Button>}
        </Row>}
        {config.groups.length > 0 && <OrgTable label={t('org.syncedGroups')} fields={['group', 'members', 'role']}
          rows={config.groups.map(group => ({ id: group.display_name, cells: [
            group.display_name, t('org.number', { number: group.members }), group.mapped_role ? t('org.role.' + group.mapped_role) : t('org.na'),
          ] }))} />}
      </>}
    </SettingsSection>
    {config.allowed_by_plan && config.configured && <Mappings key={JSON.stringify(config.group_roles)} {...props} config={config} />}
  </>
}

export function Scim(props: OrgProps) {
  const query = useQuery(orgQueries.scim(props.org.slug))
  return <OrgData query={query}>{config => <Directory {...props} config={config} />}</OrgData>
}
