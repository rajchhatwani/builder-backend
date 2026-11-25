import { useId } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { PageHeader, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, EmptyState, Field, Grid, Row, Select, Stack, Table, Tabs } from '../../ui'
import { complianceControlsOptions, controlsApi, controlStatuses, frameworks, type Control, type Framework } from './api/controls'
import { ComplianceSettings, RegulatedSettings } from './ComplianceSettings'
import { LoadFailure, SecureLoading, SecureRole, useSecureSearch, type SecureProps } from './SecureForm'

const contents = ['controls.json', 'mapping.md', 'spec-excerpt.json', 'tests.txt', 'README.md', 'MANIFEST.json']
const tabs = ['controls', 'settings', 'regulated'] as const

function controlTarget(control: Control) {
  if (control.evidence.some(item => item.fact.startsWith('compliance.'))) return 'settings'
  if (control.evidence.some(item => item.fact.startsWith('regulated.'))) return 'regulated'
}

function Controls({ id }: { id: string }) {
  const t = useT()
  const pickId = useId()
  const { search, tab, filter } = useSecureSearch()
  const framework = frameworks.find(option => option === search.kind)
  const status = controlStatuses.find(option => option === search.view)
  const query = useQuery(complianceControlsOptions(id, framework))
  const download = useMutation({ mutationFn: (frame: Framework) => controlsApi.downloadComplianceEvidence(id, frame) })
  const frameLabel = (choice?: Framework) => t(`compliance.frame_${choice ?? 'all'}`)
  const choose = (kind?: Framework) => { download.reset(); filter({ kind }) }
  const controls = query.data?.controls ?? []
  const visible = controls.filter(row => !status || row.status === status)
  const renderControl = (row: Control) => {
    const target = controlTarget(row)
    return {
      id: row.id, testId: 'control-row', status: row.status, cells: [
        <Stack gap={1}><strong>{row.title}</strong><span className="v2-muted">{t('compliance.controlId', { id: row.id, framework: frameLabel(row.framework) })}</span>
          <p>{row.description}</p></Stack>,
        <Badge tone={row.status === 'met' ? 'success' : row.status === 'unmet' ? 'danger' : 'neutral'}>{t(`compliance.${row.status}`)}</Badge>,
        <Stack gap={2}><p>{row.reason}</p>{row.status === 'unmet' && target && <Row><Button onClick={() => tab(target)}
          aria-label={t('compliance.fixNamed', { id: row.id })}>{t('compliance.fix')}</Button></Row>}</Stack>,
        row.evidence.length ? <details><summary>{t('compliance.facts', { count: row.evidence.length })}</summary>
          <ul>{row.evidence.map((item, index) => <li key={index}><code>{item.fact}</code>{t('compliance.factValue', { value: JSON.stringify(item.value) ?? '' })}</li>)}</ul>
        </details> : t('compliance.none'),
        row.tests.length ? <details><summary>{t('compliance.testsCount', { count: row.tests.length })}</summary>
          <ul>{row.tests.map(item => <li key={item.name}><Stack gap={1}><Badge>{t(item.where === 'generated' ? 'compliance.generated' : 'compliance.platform')}</Badge>
            <code>{t('compliance.testName', { file: item.file, name: item.name })}</code></Stack></li>)}</ul>
        </details> : t('compliance.none'),
      ],
    }
  }
  return <SettingsSection title={t('compliance.controls')}>
    <Row role="group" aria-label={t('compliance.framework')}>
      {[undefined, ...frameworks].map(choice => <Button key={choice ?? 'all'} data-testid={'fw-' + (choice ?? 'all')} variant={framework === choice ? 'primary' : 'default'}
        aria-pressed={framework === choice} onClick={() => choose(choice)}>{frameLabel(choice)}</Button>)}
    </Row>
    {query.isPending ? <SecureLoading label={t('compliance.loading')} /> : query.isError ?
      <LoadFailure error={query.error} message={t('compliance.loadError')} retry={() => void query.refetch()} /> : <>
        <p role="status" data-testid="controls-summary">{t('compliance.summary', { met: query.data.met, unmet: query.data.unmet, na: query.data.not_applicable })}</p>
        <Grid>{controlStatuses.map(key => <Stack key={key} gap={1}><strong>{t('compliance.count', { count: query.data[key] })}</strong>
          <Badge tone={key === 'met' ? 'success' : key === 'unmet' ? 'danger' : 'neutral'}>{t(`compliance.${key}`)}</Badge></Stack>)}</Grid>
        <Row className="v2-spread">
          <Field id={pickId} label={t('compliance.show')}>{attrs => <Select value={status ?? 'all'}
            onValueChange={value => filter({ view: value === 'all' ? undefined : value })}
            triggerProps={attrs} options={[{ value: 'all', label: t('compliance.allStatuses') },
              ...controlStatuses.map(value => ({ value, label: t(`compliance.${value}`) }))]} />}</Field>
          <Button data-testid="evidence-download" disabled={!framework || download.isPending || !controls.length} onClick={() => { if (framework) download.mutate(framework) }}>
            {download.isPending ? t('compliance.preparing') : t('compliance.download', { framework: frameLabel(framework) })}
          </Button>
        </Row>
        {framework ? <details><summary>{t('compliance.bundle')}</summary>
          <ul>{contents.map(file => <li key={file}><code>{file}</code></li>)}</ul></details> : <p className="v2-muted" data-testid="evidence-hint">{t('compliance.downloadHint')}</p>}
        {download.isError && <LoadFailure error={download.error} message={t('compliance.downloadError')}
          retry={framework ? () => download.mutate(framework) : undefined} />}
        {download.isSuccess && <Alert tone="success"><span data-testid="evidence-note">{t('compliance.downloaded', { file: download.data })}</span></Alert>}
        {visible.length ? <Table label={t('compliance.controlsTable')} columns={['control', 'status', 'reason', 'evidence', 'tests'].map(key =>
          ({ id: key, label: t(`compliance.${key}`) }))} rows={visible.map(renderControl)} /> :
          <EmptyState title={t(controls.length ? 'compliance.filteredEmpty' : 'compliance.empty')}
            action={<Button onClick={status ? () => filter({ view: undefined }) : framework ? () => choose() : () => tab('settings')}>
              {t(status ? 'compliance.allStatuses' : framework ? 'compliance.frame_all' : 'compliance.settings')}
            </Button>} />}
      </>}
  </SettingsSection>
}

export default function ComplianceScreen(props: SecureProps) {
  const t = useT()
  const { search, tab } = useSecureSearch()
  const selected = tabs.find(item => item === search.tab) ?? 'controls'
  return <Stack gap={4}>
    <PageHeader title={t('compliance.title')} description={t('compliance.lead')} />
    <SecureRole {...props} />
    <Tabs label={t('compliance.title')} value={selected} onChange={tab}
      items={tabs.map(id => ({ id, label: t(`compliance.${id}`), content: id === selected ?
        id === 'controls' ? <Controls id={props.projectId} /> : id === 'settings' ? <ComplianceSettings {...props} /> : <RegulatedSettings {...props} /> : null }))} />
  </Stack>
}
