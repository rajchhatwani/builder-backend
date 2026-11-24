import { getRouteApi, Link } from '@tanstack/react-router'
import { useState } from 'react'
import { useT } from '../i18n'
import { ConflictBanner, ConfirmDestructive, DataTable, Form, ListRow, PageHeader, RoleGate, SaveBar, SettingsSection, StatusPill } from '../patterns'
import type { DataTableState } from '../patterns'
import {
  Alert, Badge, Breadcrumb, Button, Card, Checkbox, Chip, CodeBlock, DesktopOnlyCard, Dialog, Dropdown, EmptyState,
  ErrorBoundary, Grid, IconButton, Input, Pagination, Popover, Radio, Row, Select, Sheet, Skeleton, Spinner,
  Stack, Switch, Table, Tabs, Textarea, Tooltip, useToast,
} from '../ui'
import { validators } from '../validators'
import { ScreenSkeleton } from './lazy'

const route = getRouteApi('/v2-kit')
const fixtures = [
  { id: 'alpha', state: 'active' },
  { id: 'bravo', state: 'paused' },
  { id: 'charlie', state: 'active' },
] as const

export default function KitScreen() {
  const t = useT()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const toast = useToast()
  const [dirty, setDirty] = useState(true)
  const [saved, setSaved] = useState(false)
  const notify = () => toast({ title: t('kit.toast'), tone: 'success' })
  const reset = () => void navigate({ search: { state: undefined, tab: undefined, page: 1, filter: '', sort: undefined } })
  const state: DataTableState = { filter: search.filter, page: search.page, sort: search.sort ? { id: 'name', direction: search.sort } : undefined }
  const filtered = fixtures.filter(item => t(`kit.rows.${item.id}`).toLowerCase().includes(state.filter.toLowerCase()))
  if (state.sort) {
    const sign = state.sort.direction === 'ascending' ? 1 : -1
    filtered.sort((a, b) => sign * t(`kit.rows.${a.id}`).localeCompare(t(`kit.rows.${b.id}`)))
  }
  const columns = [{ id: 'name', label: t('kit.name'), sortable: true }, { id: 'state', label: t('kit.state') }]
  const rows = filtered.map(item => ({
    id: item.id,
    cells: [t(`kit.rows.${item.id}`), <StatusPill tone={item.state === 'active' ? 'success' : 'warning'}>{t(`kit.${item.state}`)}</StatusPill>],
  }))

  return (
    <Stack gap={5}>
      <PageHeader title={t('kit.title')} description={t('kit.description')} />
      {search.state === 'loading' && <ScreenSkeleton />}
      {search.state === 'empty' && <EmptyState title={t('kit.empty')} description={t('kit.emptyDescription')}
        action={<Button onClick={reset}>{t('kit.showKit')}</Button>} />}
      {search.state === 'error' && <Alert tone="danger" action={<Button onClick={reset}>{t('common.retry')}</Button>}>{t('kit.error')}</Alert>}
      {!search.state && (
        <ErrorBoundary>
          <Stack gap={5}>
            <Breadcrumb items={[
              { id: 'projects', content: <Link to="/projects">{t('shell.projects')}</Link> },
              { id: 'kit', content: t('kit.title') },
            ]} />
            <Grid gap={4}>
              <SettingsSection title={t('kit.actions')}>
                <Stack>
                  <Row>
                    <Button variant="primary" onClick={notify}>{t('kit.showToast')}</Button>
                    <Button onClick={() => setDirty(true)}>{t('kit.edit')}</Button>
                    <Tooltip trigger={<IconButton label={t('kit.help')}><span aria-hidden>{'?'}</span></IconButton>}>{t('kit.tooltip')}</Tooltip>
                  </Row>
                  <Row>
                    <Dialog title={t('kit.dialog')} description={t('kit.overlayDescription')} trigger={<Button>{t('kit.dialog')}</Button>}>
                      <p>{t('kit.dialogBody')}</p>
                    </Dialog>
                    <Sheet title={t('kit.sheet')} description={t('kit.overlayDescription')} trigger={<Button>{t('kit.sheet')}</Button>}>
                      <p>{t('kit.dialogBody')}</p>
                    </Sheet>
                    <Dropdown trigger={<Button>{t('kit.menu')}</Button>} items={[{ id: 'notify', label: t('kit.showToast'), onSelect: notify }]} />
                    <Popover trigger={<Button>{t('kit.popover')}</Button>} label={t('kit.popover')}><p>{t('kit.tooltip')}</p></Popover>
                  </Row>
                  <Row>
                    <ConfirmDestructive trigger={<Button variant="danger">{t('kit.remove')}</Button>}
                      title={t('kit.confirm')} description={t('kit.confirmDescription')} action={t('kit.remove')} onConfirm={notify} />
                  </Row>
                </Stack>
              </SettingsSection>
              <SettingsSection title={t('kit.form')}>
                <Form submitLabel={t('common.save')} onSubmit={notify} fields={[
                  { name: 'email', label: t('kit.email'), hint: t('kit.hint'), validate: [validators.required, validators.email],
                    control: props => <Input {...props} type="email" placeholder={t('kit.emailPlaceholder')} /> },
                  { name: 'notes', label: t('kit.notes'), validate: [validators.length()], control: props => <Textarea {...props} /> },
                  { name: 'option', label: t('kit.option'), control: ({ name, disabled, ...triggerProps }) => (
                    <Select name={name} disabled={disabled} triggerProps={triggerProps} placeholder={t('kit.choose')}
                      options={[{ value: 'one', label: t('kit.first') }, { value: 'two', label: t('kit.second') }]} />
                  ) },
                ]} />
              </SettingsSection>
            </Grid>
            <Grid gap={4}>
              <SettingsSection title={t('kit.choices')}>
                <Stack>
                  <Checkbox label={t('kit.checkbox')} />
                  <Row role="group" aria-label={t('kit.radio')}>
                    <Radio label={t('kit.first')} name="kit-radio" defaultChecked />
                    <Radio label={t('kit.second')} name="kit-radio" />
                  </Row>
                  <Switch label={t('kit.switch')} defaultChecked />
                  <Row><Badge tone="info">{t('kit.badge')}</Badge><Chip>{t('kit.chip')}</Chip><Spinner /></Row>
                </Stack>
              </SettingsSection>
              <SettingsSection title={t('kit.feedback')}>
                <Stack>
                  <Alert tone="success">{t('kit.success')}</Alert>
                  <ConflictBanner onReload={notify} />
                  <RoleGate allowed={false}><p>{t('kit.roleContent')}</p></RoleGate>
                  <DesktopOnlyCard />
                  <Skeleton />
                </Stack>
              </SettingsSection>
            </Grid>
            <SettingsSection title={t('kit.navigation')}>
              <Stack gap={4}>
                <Tabs label={t('kit.tabs')} value={search.tab ?? 'first'}
                  onChange={tab => void navigate({ search: previous => ({ ...previous, tab: tab === 'second' ? 'second' : undefined }) })}
                  items={[
                    { id: 'first', label: t('kit.first'), content: <ListRow title={t('kit.listRow')} detail={t('kit.tooltip')} /> },
                    { id: 'second', label: t('kit.second'), content: <CodeBlock code={t('kit.code')} label={t('kit.codeLabel')} /> },
                  ]} />
                <CodeBlock code={t('kit.code')} label={t('kit.codeLabel')} />
                <Pagination label={t('kit.paginationExample')} page={Math.min(search.page, 2)} pages={2}
                  onChange={page => void navigate({ search: previous => ({ ...previous, page }) })} />
              </Stack>
            </SettingsSection>
            <SettingsSection title={t('kit.data')}>
              <Stack gap={5}>
                <Table label={t('kit.table')} columns={columns} rows={rows} />
                <DataTable label={t('kit.dataTable')} columns={columns} rows={rows.slice((search.page - 1) * 2, search.page * 2)}
                  state={state} pages={Math.ceil(rows.length / 2)}
                  onChange={next => void navigate({ search: previous => ({ ...previous, page: next.page, filter: next.filter, sort: next.sort?.direction }), replace: true })} />
              </Stack>
            </SettingsSection>
            <Card>
              <SaveBar dirty={dirty} saved={saved} onDiscard={() => { setDirty(false); setSaved(false) }}
                onSave={() => { setDirty(false); setSaved(true); notify() }} />
            </Card>
          </Stack>
        </ErrorBoundary>
      )}
    </Stack>
  )
}
