import { useNavigate, useSearch } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { PageHeader } from '../../patterns'
import { Alert, Button, Card, EmptyState, Field, Grid, Row, Select, Stack } from '../../ui'
import { connectRolesOptions } from './api/blocks'
import { specOptions } from './api/connect'
import type { ConnectProps } from './api/connect'
import { BlockRole, SectionLink } from './components/BlockStatus'
import { BlockSettings } from './components/BlockSettings'
import { eventFields, notificationDefaults, notificationSchema, specEvents } from './state/blockSchemas'

export default function NotificationTypesScreen(props: ConnectProps) {
  const t = useT()
  const { projectId, role, rolePending } = props
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const row = search.notificationRow
  const selectRow = (notificationRow?: number) => void navigate({ search: previous => ({ ...previous, notificationRow }) })
  const spec = useQuery(specOptions(projectId))
  const roles = useQuery(connectRolesOptions(projectId))
  const value = spec.data
  const selectOptions = (names: string[]) => names.map(name => ({ value: name, label: t('schema.option', { value: name }) }))
  const retry = () => { if (spec.isError) void spec.refetch(); if (roles.isError) void roles.refetch() }
  return <Stack>
    <PageHeader title={t('connectA2.types.title')} description={t('connectA2.types.intro')}
      actions={<><SectionLink projectId={projectId} section="notifications" label={t('connectA2.notifications.title')} />
        <SectionLink projectId={projectId} section="history" label={t('connectA2.history')} /></>} />
    <BlockRole {...props} />
    {(spec.isError || roles.isError) && <Alert tone="warning" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t('connectA2.dependenciesError')}</Alert>}
    <BlockSettings projectId={projectId} name="notifications" schema={notificationSchema} defaults={notificationDefaults}
      selectedRow={path => path.length === 1 && path[0] === 'types' ? { index: row, select: selectRow } : undefined}
      fieldOverride={({ path, id, onChange, readOnly, error }, draft) => {
        if (!value || path[0] !== 'types' || typeof path[1] !== 'number' || path[2] !== 'address_fields') return
        const type = draft.types[path[1]]
        if (!type.on_event) return
        const fields = eventFields(value, type.on_event)
        const current = type.address_fields ?? {}
        const channels = [...new Set([...type.channels, ...Object.keys(current)])]
        return <Stack>
          <p>{t('connectA2.types.addresses')}</p>
          {error && <Alert tone="danger">{t('schema.message', { message: error })}</Alert>}
          <Grid>{channels.map(channel => <Field key={channel} id={id + '-' + channel}
            label={t('connectA2.types.address', { channel })}>{attrs => <Select triggerProps={attrs} disabled={readOnly}
              options={[{ value: '__unset', label: t('schema.unset') }, ...selectOptions([...new Set([...fields, current[channel]].filter(Boolean))])]}
              value={current[channel] || '__unset'} onValueChange={field => {
                const next = { ...current }
                if (field === '__unset') delete next[channel]
                else next[channel] = field
                onChange(next)
              }} />}</Field>)}</Grid>
        </Stack>
      }}
      title={t('connectA2.types.settings')} errorKey="connectA2.types.error" readOnly={!role || role === 'viewer' || rolePending === true}
      options={(path, draft) => {
        if (path[0] === 'admin_role' && roles.data) return roles.data.roles.map(role => ({ value: role.name, label: role.label || role.name }))
        if (!value || path[0] !== 'types' || typeof path[1] !== 'number') return
        if (path[2] === 'on_event') return selectOptions(specEvents(value, false))
        if (path[2] === 'recipient_key_field') return selectOptions(eventFields(value, draft.types[path[1]].on_event))
        if (path[2] === 'templates' && path[4] === 'channel') return selectOptions(draft.types[path[1]].channels)
      }}
      empty={<EmptyState title={t('connectA2.types.empty')} description={t('connectA2.types.emptyHelp')} />}>
      {draft => <Card><Stack><h2>{t('connectA2.prerequisites')}</h2>
        <p>{t('connectA2.types.requirements')}</p>
        <Row>{(['auth', 'providers', 'events'] as const).map(section => <SectionLink key={section} projectId={projectId}
          section={section} label={t('connectA2.link.' + section)} />)}</Row>
        {value && <p className="v2-muted">{t('connectA2.readiness', { states: [
          value.auth?.enabled ? '' : t('connectA2.link.auth'), value.providers?.enabled ? '' : t('connectA2.link.providers'),
          draft.types.some(type => type.on_event) && !value.events?.enabled ? t('connectA2.link.events') : '',
        ].filter(Boolean).join(', ') || t('connectA2.ready') })}</p>}
      </Stack></Card>}
    </BlockSettings>
  </Stack>
}

