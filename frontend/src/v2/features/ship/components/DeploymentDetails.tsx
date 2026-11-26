import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { ConfirmDestructive, SettingsSection } from '../../../patterns'
import type { ProjectSection } from '../../../projectNavigation'
import { Badge, Button, Card, CodeBlock, Disclosure, Field, Grid, Input, Row, Select, Stack, Table } from '../../../ui'
import { deployFlags, deployLimits, deployNumberKeys, deployProfiles } from '../../../validators/deployment'
import { sizingOptions } from '../api/ship'
import type { DeploymentPlan, DeploymentWrite, ValidationIssue } from '../api/ship'
import type { DeployDraft, EnvDraft } from '../state/deployment'
import { ShipLink, ShipLoading, ShipProblem, useIssueRows, useShipFormat } from './Common'

export function DeployEnvironment({ env, index, count, disabled, canRemove, error, touch, update, move, remove }: {
  env: EnvDraft; index: number; count: number; disabled: boolean; canRemove: boolean
  error: (field: string) => string | undefined; touch: (field: string) => void
  update: (patch: Partial<EnvDraft>) => void; move: (delta: -1 | 1) => void; remove: () => void
}) {
  const t = useT()
  const path = (key: string) => 'env-' + index + '-' + key
  const name = env.name || t('ship.environmentNumber', { number: index + 1 })
  return <Card><Stack>
    <Stack gap={1}><h3>{t('ship.value', { value: name })}</h3>
      <p className="v2-muted">{index === 0 ? t('ship.deployTarget') : t('ship.environmentNumber', { number: index + 1 })}</p></Stack>
    <Grid>
      <Field id={'cf-deployment-' + path('name')} label={t('ship.envName')} error={error(path('name'))}>{attr =>
        <Input {...attr} value={env.name} disabled={disabled} onBlur={() => touch(path('name'))} maxLength={deployLimits.name}
          onChange={event => update({ name: event.target.value })} />}</Field>
      <Field id={'cf-deployment-' + path('profile')} label={t('ship.profile')} error={error(path('profile'))}>{attr =>
        <Select value={env.profile} disabled={disabled} onValueChange={profile => update({ profile })}
          triggerProps={{ ...attr, onBlur: () => touch(path('profile')) }} placeholder={t('ship.profileInvalid')}
          options={deployProfiles.map(profile => ({ value: profile, label: t('ship.' + profile) }))} />}</Field>
    </Grid>
    <Disclosure label={t('ship.fineTune')}>
      <Grid>{deployNumberKeys.map(key => <Field key={key} id={'cf-deployment-' + path(key)} label={t('ship.' + key)} error={error(path(key))}>{attr =>
        <Input {...attr} inputMode="numeric" value={env[key]} disabled={disabled} onBlur={() => touch(path(key))}
          onChange={event => update({ [key]: event.target.value })} />}</Field>)}
        {deployFlags.map(key => <Field key={key} label={t('ship.' + key)} error={error(path(key))}>{attr =>
          <Select value={env[key] === null ? 'inherit' : String(env[key])} disabled={disabled} triggerProps={attr}
            options={['inherit', 'true', 'false'].map(value => ({ value, label: t('ship.' + value) }))}
            onValueChange={value => update({ [key]: value === 'inherit' ? null : value === 'true' })} />}</Field>)}
      </Grid>
    </Disclosure>
    {!disabled && <Row>
      <Button disabled={index === 0} onClick={() => move(-1)} aria-label={t('ship.moveUp', { name })}>{t('ship.up')}</Button>
      <Button disabled={index === count - 1} onClick={() => move(1)} aria-label={t('ship.moveDown', { name })}>{t('ship.down')}</Button>
      <ConfirmDestructive title={t('ship.removeEnvironment', { name })} description={t('ship.removeEnvironmentNote')}
        action={t('ship.remove')} trigger={<Button variant="danger" disabled={!canRemove} aria-label={t('ship.removeEnvironment', { name })}>{t('ship.remove')}</Button>}
        onConfirm={remove} />
    </Row>}
  </Stack></Card>
}

export function useDeployPlan(id: string, body: DeploymentWrite | null) {
  const serialized = body === null ? null : JSON.stringify(body)
  const [debounced, setDebounced] = useState(serialized)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(serialized), 300)
    return () => window.clearTimeout(timer)
  }, [serialized])
  const query = useQuery(sizingOptions(id, debounced === null ? null : JSON.parse(debounced) as DeploymentWrite))
  return { query, waiting: serialized !== debounced, data: serialized === debounced ? query.data : undefined }
}

export function DeploySizing({ plan, draft, schemaValid }: { plan: ReturnType<typeof useDeployPlan>; draft: DeployDraft; schemaValid: boolean }) {
  const t = useT()
  const { query, data, waiting } = plan
  return <SettingsSection title={t('ship.draftSizing')}>
    {!schemaValid ? <p>{t('ship.sizingFix')}</p> : waiting || query.isPending ? <ShipLoading label={t('ship.sizingLoading')} /> :
      query.isError ? <ShipProblem error={query.error} message={t('ship.sizingError')} retry={query.refetch} /> :
      data && <Stack>
        {data.notes.map(note => <p key={note}>{t('ship.value', { value: note })}</p>)}
        {data.valid_sizes.length > 0 && <p>{t('ship.validSizes', {
          cloud: t('ship.' + data.cloud), pairs: data.valid_sizes.map(([cpu, memory]) => t('ship.pair', { cpu, memory })).join(', '),
        })}</p>}
        {data.environments.length === 0 && <p>{t('ship.noSizing')}</p>}
        {data.environments.map((env, i) => <Resolved key={i} env={env}
          draft={draft.environments.filter(row => deployProfiles.some(profile => row.profile === profile))[i]} />)}
      </Stack>}
  </SettingsSection>
}

function Resolved({ env, draft }: { env: DeploymentPlan['environments'][number]; draft?: EnvDraft }) {
  const t = useT()
  return <Card><Stack><h3>{t('ship.value', { value: env.name || t('ship.unnamed') })}</h3>
    <Grid gap={3} role="list">
      {[...deployNumberKeys, ...deployFlags, 'db_class'].map(key => {
        const field = key as keyof typeof env
        const value = env[field]
        const override = draft?.[key as keyof EnvDraft]
        return <Stack key={key} gap={1} role="listitem"><span className="v2-muted">{t('ship.' + key)}</span>
          <Row><strong>{typeof value === 'boolean' ? t('ship.' + value) : t('ship.value', { value })}</strong>
            <Badge>{t(override == null || override === '' ? 'ship.inherited' : 'ship.override')}</Badge></Row>
        </Stack>
      })}
    </Grid>
    <Disclosure label={t('ship.tfvars', { name: env.name })}><CodeBlock code={env.tfvars} /></Disclosure>
  </Stack></Card>
}


const owningSettings: Record<string, ProjectSection> = {
  payments: 'payments', storage: 'storage', providers: 'providers', jobs: 'jobs', workflows: 'workflows',
  'auth.keycloak': 'keycloak', 'auth.token_store': 'auth',
}

export function SavedDeployIssues({ query, projectId }: { query: UseQueryResult<{ issues: ValidationIssue[] }>; projectId: string }) {
  const t = useT()
  const { columns } = useShipFormat()
  const issues = query.data?.issues ?? []
  const rows = useIssueRows(issues)
  const links = [...new Set(issues.map(issue => owningSettings[issue.path.replace(/^deployment\./, '')]).filter(Boolean))]
  return <SettingsSection title={t('ship.savedIssues')}>
    {query.isPending ? <ShipLoading label={t('ship.issuesLoading')} /> : query.isError ?
      <ShipProblem error={query.error} message={t('ship.issuesError')} retry={query.refetch} /> : rows.length === 0 ?
        <p>{t('ship.noSavedIssues')}</p> : <Stack>
          <p>{t('ship.issuesCount', { count: rows.length })}</p>
          <Table label={t('ship.savedIssues')} columns={columns('path', 'code', 'problem')} rows={rows} />
          {links.length > 0 && <Row>{links.map(section => <ShipLink key={section} id={projectId} section={section}
            label={t('ship.openSettings', { section: t('nav.' + section) })} />)}</Row>}
        </Stack>}
  </SettingsSection>
}
