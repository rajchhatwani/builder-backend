import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { ConfirmDestructive, SettingsSection } from '../../patterns'
import { Badge, Button, EmptyState, Grid, Row, Stack } from '../../ui'
import { effectHost, validators } from '../../validators'
import { effectsSection, hooksSection, issuesOptions, specOptions } from './api/behavior'
import type { Effects } from './api/behavior'
import { BehaviorCheck, BehaviorField, BehaviorPage, IssueList, RemoveAction, SectionForm, queryStates, removeAt, replaceAt } from './BehaviorForm'
import type { BehaviorProps } from './BehaviorForm'
import { objectValue, provenance } from './blocks'

const defaults: Effects = { enabled: false, trusted_authors_only: false, webhook_hosts: [] }
const integrations = [
  { key: 'providers', page: 'providers' }, { key: 'webhooks', page: 'webhooks' },
  { key: 'notifications', page: 'notiftypes' },
] as const
const scopedCodes = new Set(['untrusted_author', 'effects_not_enabled', 'needs_providers', 'needs_webhooks', 'needs_notifications'])

export default function EffectsScreen(props: BehaviorProps) {
  const t = useT()
  const { projectId } = props
  const hooks = useQuery(hooksSection.query(projectId))
  const spec = useQuery(specOptions(projectId))
  const issues = useQuery(issuesOptions(projectId))
  const scopedIssues = (issues.data?.issues ?? []).filter(issue => issue.path.startsWith('hooks[') && scopedCodes.has(issue.code))
  const effectful = (hooks.data?.value ?? []).filter(hook => hook.effects?.length)
  return <BehaviorPage title={t('nav.hookeffects')} description={t('behavior.effects.intro')} desktop access={props} ownerOnly>
    <SectionForm projectId={projectId} config={effectsSection} writable={props.role === 'owner'} supporting={queryStates(hooks, spec)}
      render={({ value, edit, saved, disabled }) => <>
        {!value ? <EmptyState title={t('behavior.effects.empty')} description={t('behavior.effects.emptyHelp')}
          action={<Button variant="primary" disabled={disabled} onClick={() => edit(defaults)}>{t('behavior.effects.setup')}</Button>} />
          : <SettingsSection title={t('behavior.effects.config')}>
            <Row>
              <Badge tone={value.enabled ? 'success' : 'neutral'}>{t(value.enabled ? 'behavior.enabled' : 'behavior.disabled')}</Badge>
              {value.enabled && saved?.enabled ? <ConfirmDestructive
                trigger={<Button variant="danger" disabled={disabled}>{t('behavior.effects.disable')}</Button>}
                title={t('behavior.effects.disable')} description={t('behavior.effects.disableHelp')}
                action={t('behavior.effects.disable')} onConfirm={() => edit({ ...value, enabled: false })} />
                : <BehaviorCheck label={t('behavior.enabled')} path="enabled" value={value.enabled}
                  change={enabled => edit({ ...value, enabled })} />}
              <BehaviorCheck label={t('behavior.effects.trusted')} value={value.trusted_authors_only} path="trusted_authors_only"
                requirement={value.enabled ? t('behavior.effects.trustedRequired') : undefined}
                change={trusted_authors_only => edit({ ...value, trusted_authors_only })} />
            </Row>
            <h3>{t('behavior.effects.hosts')}</h3>
            <p className="v2-muted">{t('validation.effectHost')}</p>
            {value.webhook_hosts.map((host, index) => {
              const move = (delta: number) => {
                const hosts = [...value.webhook_hosts]
                const target = index + delta
                hosts[target] = value.webhook_hosts[index]
                hosts[index] = value.webhook_hosts[target]
                edit({ ...value, webhook_hosts: hosts })
              }
              return <Grid key={index}>
                <BehaviorField label={t('behavior.effects.host', { count: index + 1 })} value={host} path={'webhook_hosts.' + index}
                  maxLength={253} checks={[validators.required, effectHost]} change={next => edit({ ...value, webhook_hosts: replaceAt(value.webhook_hosts, index, next) })} />
                <Row>
                  <Button disabled={disabled || index === 0} onClick={() => move(-1)}>{t('behavior.up')}</Button>
                  <Button disabled={disabled || index === value.webhook_hosts.length - 1} onClick={() => move(1)}>{t('behavior.down')}</Button>
                  <RemoveAction onConfirm={() => edit({ ...value, webhook_hosts: removeAt(value.webhook_hosts, index) })} />
                </Row>
              </Grid>
            })}
            <Row>
              <Button disabled={disabled} onClick={() => edit({ ...value, webhook_hosts: [...value.webhook_hosts, ''] })}>{t('behavior.effects.hostAdd')}</Button>
              <RemoveAction label={t('behavior.effects.remove')} onConfirm={() => edit(null)} />
            </Row>
          </SettingsSection>}
        <SettingsSection title={t('behavior.effects.before')} description={t('behavior.effects.prerequisites')}>
          <Stack gap={2}>
            <Badge tone={hooks.data?.value.length ? 'success' : 'warning'}>{t(hooks.data?.value.length ? 'behavior.effects.hookPresent' : 'behavior.effects.hookNeeded')}</Badge>
            {integrations.map(integration => {
              const active = objectValue(spec.data?.[integration.key]).enabled === true
              return <Row className="v2-spread" key={integration.key}>
                <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: integration.page }}>
                  {t('nav.' + integration.page)}
                </Link></Button>
                <Badge tone={active ? 'success' : 'neutral'}>{t(active ? 'behavior.enabled' : 'behavior.disabled')}</Badge>
              </Row>
            })}
          </Stack>
        </SettingsSection>
        <SettingsSection title={t('behavior.effects.hooks')}>
          {effectful.length ? effectful.map(hook => <Row key={hook.name} className="v2-spread">
            <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'hooks' }} search={{ hook: hook.name }}>{hook.name}</Link></Button>
            <span>{hook.effects?.join(', ')}</span><Badge>{t('behavior.hooks.author.' + provenance(hook.author))}</Badge>
          </Row>) : <p>{t('behavior.effects.noHooks')}</p>}
          <IssueList issues={scopedIssues} />
        </SettingsSection>
      </>} />
  </BehaviorPage>
}
