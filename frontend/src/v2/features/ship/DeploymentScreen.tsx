import { useReducer, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, SaveBar, SettingsSection } from '../../patterns'
import { Alert, Button, Card, Disclosure, EmptyState, Field, Grid, Input, Radio, Row, Select, Stack, Switch, Tabs } from '../../ui'
import { deployLimits, deploymentClouds, deploymentErrors, suggestedDeployRegion } from '../../validators/deployment'
import { canEdit, deployOptions, issuesOptions, shipError, useDeploySave } from './api/ship'
import type { DeploymentSettings, ShipProps } from './api/ship'
import { ShipLink, ShipLoading, ShipProblem, ShipRole, ShipScreen, useShipSearch } from './components/Common'
import { DeployEnvironment, DeploySizing, SavedDeployIssues, useDeployPlan } from './components/DeploymentDetails'
import { deploymentBody, deploymentDraft, initialDeployment } from './state/deployment'

export default function DeploymentScreen(props: ShipProps) {
  return <ShipScreen name="deployment"><Deployment {...props} /></ShipScreen>
}

function Deployment(props: ShipProps) {
  const t = useT()
  const query = useQuery(deployOptions(props.projectId))
  const { search } = useShipSearch()
  const [showDefaults, setShowDefaults] = useState(false)
  const tab = search.tab === 'form' ? 'form' : 'guided'
  const ready = query.data && (query.data.version > 0 || showDefaults)
  return <Stack><ShipRole props={props} />
    {ready && query.data ? <DeploymentForm props={props} settings={query.data} guided={tab === 'guided'} reload={query.refetch} />
      : <DeployTabs tab={tab}>{query.data ?
        <EmptyState title={t('ship.deployEmpty')} description={t('ship.deployUntouched')}
          action={<Button onClick={() => setShowDefaults(true)}>{t('ship.viewDefaults')}</Button>} />
        : query.isError ?
          <ShipProblem error={query.error} message={t(tab === 'guided' ? 'ship.deployLoadError' : 'ship.deployFormError')} retry={query.refetch} />
          : <ShipLoading label={t('ship.deployLoading')} lines={10} />}</DeployTabs>}
  </Stack>
}

function DeployTabs({ tab, children }: { tab: string; children: ReactNode }) {
  const t = useT()
  const { change } = useShipSearch()
  return <Tabs label={t('ship.deployViews')} value={tab} onChange={tab => void change({ tab })}
    items={[{ id: 'guided', label: t('ship.guided'), content: tab === 'guided' ? children : null },
      { id: 'form', label: t('ship.settingsForm'), content: tab === 'form' ? children : null }]} />
}

function DeploymentForm({ props, settings, guided, reload }: {
  props: ShipProps; settings: DeploymentSettings; guided: boolean; reload: () => Promise<{ isSuccess: boolean }>
}) {
  const t = useT()
  const { projectId, role } = props
  const issues = useQuery(issuesOptions(projectId))
  const save = useDeploySave(projectId)
  const [edit, dispatch] = useReducer(deploymentDraft, null)
  const [touched, setTouched] = useState<string[]>([])
  const [submitted, setSubmitted] = useState(false)
  const [confirmOff, setConfirmOff] = useState(false)
  const toggle = useRef<HTMLInputElement>(null)
  const base = initialDeployment(settings)
  const draft = edit ?? base
  const effective = { ...draft, region: draft.region || (guided ? suggestedDeployRegion(draft.cloud) : '') }
  const schemaValid = !Object.keys(deploymentErrors(effective, undefined, true)).length
  const plan = useDeployPlan(projectId, schemaValid ? deploymentBody(draft, guided) : null)
  const knownSizes = plan.query.data?.cloud === draft.cloud ? plan.query.data.valid_sizes : undefined
  const waitingForSizes = draft.enabled && schemaValid && !knownSizes &&
    draft.environments.some(env => env.cpu !== '' && env.memory !== '')
  const errors = deploymentErrors(effective, knownSizes)
  const server = shipError(save.error)
  const conflict = server?.status === 409 || (edit !== null && draft.version !== settings.version)
  const readonly = !canEdit(role) || props.roleError
  const disabled = Boolean(readonly || save.isPending)
  const dirty = edit !== null && JSON.stringify(edit) !== JSON.stringify(base)
  const saved = save.isSuccess && !dirty

  function reset(resetSave = true) {
    dispatch({ type: 'reset' })
    setTouched([])
    setSubmitted(false)
    if (resetSave) save.reset()
  }
  const touch = (name: string) => setTouched(list => list.includes(name) ? list : [...list, name])
  const fieldError = (name: string) => {
    const issue = errors[name]
    if ((submitted || touched.includes(name)) && issue) return t(issue.key, issue.values)
    const field = name.match(/^env-(\d+)-(.+)$/)
    const path = field ? ['environments', field[1], field[2]] : [name]
    const detail = server?.status === 422 ? server.details.find((item): item is { loc: string[]; msg: string } => {
      if (!item || typeof item !== 'object' || !('loc' in item) || !('msg' in item)) return false
      return Array.isArray(item.loc) && item.loc.map(String).slice(-path.length).join('.') === path.join('.') && typeof item.msg === 'string'
    }) : undefined
    return detail && t('ship.value', { value: detail.msg })
  }
  const settingsField = (name: 'region' | 'github_repo') =>
    <Field id={'cf-deployment-' + name} label={t('ship.' + name)} error={fieldError(name)}>
      {attr => <Input {...attr} disabled={disabled} value={draft[name]} placeholder={name === 'region' && guided ? t('ship.value', { value: effective.region }) : undefined} maxLength={deployLimits[name]} onBlur={() => touch(name)}
        onChange={event => dispatch({ type: 'settings', base, patch: { [name]: event.target.value } })} />}
    </Field>
  const chooseCloud = (cloud: string) => {
    const suggest = guided && (!draft.region || Object.values(deploymentClouds).some(entry => entry.region === draft.region))
    dispatch({ type: 'settings', base, patch: { cloud, ...(suggest ? { region: suggestedDeployRegion(cloud) } : {}) } })
  }
  const setEnabled = (enabled: boolean) => dispatch({ type: 'settings', base, patch: { enabled } })
  function submit() {
    setSubmitted(true)
    const first = document.getElementById('cf-deployment-' + Object.keys(errors)[0])
    if (first) {
      const details = first.closest('details')
      if (details) details.open = true
      first.focus()
    }
    if (Object.keys(errors).length || disabled || conflict || waitingForSizes) return
    save.mutate(deploymentBody(draft, guided, true), { onSuccess: () => reset(false) })
  }
  const toggleLabel = t('ship.deployToggle')
  return <DeployTabs tab={guided ? 'guided' : 'form'}><Stack gap={4}>
    {settings.version === 0 && <Alert>{t('ship.deployUntouched')}</Alert>}
    {saved && <Alert tone="success">{t('ship.deploySaved', { version: settings.version })}</Alert>}
    {conflict && <div data-testid="conflict"><ConflictBanner onReload={async () => {
      const result = await reload()
      if (result.isSuccess) reset()
    }} /></div>}
    {save.isError && !conflict && <ShipProblem error={save.error} message={t(server?.status === 422 ? 'ship.deployFix' : 'ship.deploySaveError')} retry={server?.status === 422 ? undefined : submit} />}
    <SettingsSection title={t('ship.deployFiles')}>
      <Switch ref={toggle} label={toggleLabel} disabled={disabled} checked={draft.enabled} onChange={event => {
        if (!event.target.checked && settings.enabled) setConfirmOff(true)
        else setEnabled(event.target.checked)
      }} />
      <ConfirmDestructive title={t('ship.turnOffTitle')} description={t('ship.turnOffNote')} action={t('ship.turnOff')}
        open={confirmOff} onOpenChange={setConfirmOff} returnFocus={toggle} onConfirm={() => setEnabled(false)} />
      <p>{t(settings.version === 0 ? 'ship.deployOff' : 'ship.turnOffNote')}</p>
    </SettingsSection>
    <SettingsSection title={t('ship.where')}>
      <Grid>
        {guided ? <fieldset className="v2-ship-group"><legend>{t('ship.cloud')}</legend><Stack gap={1}>
          {Object.keys(deploymentClouds).map(cloud => <Radio key={cloud} name="deploy-cloud" id={cloud === 'aws' ? 'cf-deployment-cloud' : undefined} label={t('ship.' + cloud)} checked={draft.cloud === cloud}
            disabled={disabled} onChange={() => chooseCloud(cloud)} />)}
          {fieldError('cloud') && <p role="alert">{fieldError('cloud')}</p>}
        </Stack></fieldset> :
          <Field id="cf-deployment-cloud" label={t('ship.cloud')} error={fieldError('cloud')}>{attr =>
            <Select value={draft.cloud} disabled={disabled} onValueChange={chooseCloud} triggerProps={{ ...attr, onBlur: () => touch('cloud') }}
              options={Object.keys(deploymentClouds).map(cloud => ({ value: cloud, label: t('ship.' + cloud) }))} />}
          </Field>}
        {settingsField('region')}{settingsField('github_repo')}
      </Grid>
      {guided && <p className="v2-muted">{t('ship.repoTrust')}</p>}
    </SettingsSection>
    <Stack gap={3}>
      <Row className="v2-spread"><h2>{t('ship.environments')}</h2>
        <Button disabled={disabled || draft.environments.length >= deployLimits.environments} id="cf-deployment-environments"
          onClick={() => dispatch({ type: 'add', base })}>{t('ship.addEnvironment')}</Button></Row>
      {fieldError('environments') && <p role="alert">{fieldError('environments')}</p>}
      <p className="v2-muted">{t('ship.environmentHelp')}</p>
      {draft.environments.map((env, index) => <DeployEnvironment key={env.row} env={env} index={index} disabled={disabled}
        canRemove={draft.environments.length > (guided ? 1 : 0)} count={draft.environments.length} error={fieldError} touch={touch}
        update={patch => dispatch({ type: 'environment', base, index, patch })}
        move={delta => { dispatch({ type: 'move', base, index, delta }); setTouched([]) }}
        remove={() => { dispatch({ type: 'remove', base, index }); setTouched([]) }} />)}
    </Stack>
    <DeploySizing plan={plan} draft={draft} schemaValid={schemaValid} />
    <SavedDeployIssues query={issues} projectId={projectId} />
    {guided && Object.hasOwn(deploymentClouds, draft.cloud) && <SettingsSection title={t('ship.deploySetup')}>
      <ol className="v2-stack"><li>{t('ship.bootstrap.' + draft.cloud)}</li>
        {['githubSetup', 'cloudSecrets', 'pushMain'].map(key => <li key={key}>{t('ship.' + key)}</li>)}
      </ol>
      <Disclosure label={t('ship.deployDocs')}><p>{t('ship.deployRehearsal')}</p></Disclosure>
    </SettingsSection>}
    {!readonly && <Card><SaveBar preserveFocusOnSave dirty={dirty || settings.version === 0} pending={save.isPending} saved={saved}
      readOnly={conflict || waitingForSizes} onSave={submit} onDiscard={() => reset()} /></Card>}
    <Row><ShipLink id={projectId} section="generate" label={t('ship.fullValidation')} /></Row>
  </Stack></DeployTabs>
}
