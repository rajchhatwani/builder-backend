import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { ConfirmDestructive, SettingsSection } from '../../patterns'
import { Badge, Button, EmptyState, Pagination, Row, Stack, Table } from '../../ui'
import { eventsSection, specOptions } from './api/behavior'
import type { Events } from './api/behavior'
import { BehaviorCheck, BehaviorPage, BehaviorSelect, FormGrid, RemoveAction, SectionForm, queryStates, WholeNumber, canEdit } from './BehaviorForm'
import type { BehaviorProps } from './BehaviorForm'
import { entityNames, eventDataFields, eventPrefix, recordList } from './blocks'

const defaults: Events = { enabled: true, adapter: 'in_process', retention_days: 14 }
const route = '/projects/$projectId/$section'
const pageSize = 25
const changes = ['created', 'updated', 'deleted'] as const

export default function EventsScreen(props: BehaviorProps) {
  const t = useT()
  const { page } = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const spec = useQuery(specOptions(props.projectId))
  const entities = entityNames(spec.data)
  const machines = new Set(recordList(spec.data?.state_machines).map(machine => machine.entity))
  const columns = ['name', 'payload'].map(id => ({ id, label: t('behavior.events.' + id) }))
  const eventRows = entities.flatMap(entity => (machines.has(entity) ? [...changes, 'transitioned'] : changes).map(kind => ({
    kind, entity, id: eventPrefix(entity) + '.' + kind,
  })))
  const pages = Math.max(1, Math.ceil(eventRows.length / pageSize))
  const current = Math.min(page ?? 1, pages)
  return <BehaviorPage title={t('nav.events')} description={t('behavior.events.intro')} access={props}>
    <SectionForm projectId={props.projectId} config={eventsSection} writable={canEdit(props.role)} supporting={queryStates(spec)}
      render={({ value, edit, disabled, saved }) => <>
        {!value ? <EmptyState title={t('behavior.events.empty')} description={t('behavior.events.emptyHelp')}
          action={entities.length ? <Button variant="primary" disabled={disabled} onClick={() => edit(defaults)}>{t('behavior.events.on')}</Button>
            : <Button asChild><Link to={route} params={{ projectId: props.projectId, section: 'model' }}>{t('nav.model')}</Link></Button>} />
          : <>
            <SettingsSection title={t('behavior.events.delivery')} description={t('behavior.events.dependencies')}>
              <FormGrid>
                <BehaviorSelect label={t('behavior.events.adapter')} path="adapter" value={value.adapter}
                  options={['in_process']} hint={t('behavior.events.adapterHelp')}
                  requirement={value.enabled && value.adapter !== 'in_process' ? t('behavior.events.adapterHelp') : undefined} change={adapter => edit({ ...value, adapter })} />
                <WholeNumber label={t('behavior.events.retention')} path="retention_days" value={value.retention_days} min={1} max={3650}
                  hint={t('behavior.events.retentionHelp')} change={retention => edit({ ...value, retention_days: retention ?? 14 })} />
              </FormGrid>
              <Row>
                <Badge tone={value.enabled ? 'success' : 'neutral'}>{t(value.enabled ? 'behavior.enabled' : 'behavior.disabled')}</Badge>
                {value.enabled && saved?.enabled ? <ConfirmDestructive
                  trigger={<Button variant="danger" disabled={disabled}>{t('behavior.events.off')}</Button>}
                  title={t('behavior.events.off')} description={t('behavior.events.dependencies')} action={t('behavior.events.off')}
                  onConfirm={() => edit({ ...value, enabled: false })} />
                  : <BehaviorCheck label={t('behavior.enabled')} value={value.enabled} path="enabled"
                    disabled={!value.enabled && !entities.length} change={enabled => edit({ ...value, enabled })} />}
                <RemoveAction label={t('behavior.events.remove')} onConfirm={() => edit(null)} />
              </Row>
            </SettingsSection>
            {value.enabled && <SettingsSection title={t('behavior.events.catalog')} description={t('behavior.events.exclusions')}>
              <Table label={t('behavior.events.catalog')} columns={columns} rows={eventRows.slice((current - 1) * pageSize, current * pageSize).map(({ entity, kind, id }) => ({
                id, cells: [<code>{id}</code>, <Stack gap={1}>
                  <code>{t('behavior.events.shape.' + kind)}</code>
                  {kind !== 'transitioned' && spec.data && <span className="v2-small">
                    {t('behavior.events.dataFields', { fields: eventDataFields(spec.data, entity).join(', ') })}
                  </span>}
                </Stack>],
              }))} />
              {pages > 1 && <Pagination label={t('behavior.events.catalog')} page={current} pages={pages}
                onChange={page => void navigate({ search: previous => ({ ...previous, page }) })} />}
            </SettingsSection>}
          </>}
        <SettingsSection title={t('behavior.events.how')} description={t('behavior.events.howHelp')}>{null}</SettingsSection>
      </>} />
  </BehaviorPage>
}
