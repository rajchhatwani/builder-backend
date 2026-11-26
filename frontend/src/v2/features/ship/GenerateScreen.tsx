import { useLayoutEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, SettingsSection } from '../../patterns'
import { openInEditor } from '../../patterns/editorLink'
import { Alert, Button, Disclosure, Row, Stack, Table } from '../../ui'
import { canEdit, generationApi, shipError, shipKeys } from './api/ship'
import type { DownloadOptions, MigrationPlanResponse, ShipPreview, ShipProps, ValidationIssue } from './api/ship'
import { ShipLink, ShipProblem, ShipRole, ShipScreen, useIssueRows, useShipFormat } from './components/Common'
import { GenerationHistory } from './components/GenerationHistory'
import { MigrationReview } from './components/MigrationReview'
import { FirstRun } from './components/FirstRun'
import { VerifyDownload } from './components/VerifyDownload'

type Action = { kind: 'check' | 'preview' | 'kit' } | { kind: 'zip'; approval?: DownloadOptions }
const actions = ['check', 'preview', 'zip', 'kit'] as const

export default function GenerateScreen(props: ShipProps) {
  const { revision, version } = props
  const [operationEpoch, setOperationEpoch] = useState(0)
  const last = useRef({ revision, version })
  useLayoutEffect(() => {
    const previous = last.current
    if (previous.revision !== revision || (previous.version !== undefined && version !== undefined && previous.version !== version)) {
      setOperationEpoch(value => value + 1)
    }
    // The initial project metadata response can arrive after the Ship route mounts.
    last.current = { revision, version: version ?? previous.version }
  }, [revision, version])
  return <ShipScreen name="generate"><Generate key={operationEpoch} {...props} /></ShipScreen>
}

function Generate(props: ShipProps) {
  const t = useT()
  const client = useQueryClient()
  const { projectId: id, slug, role } = props
  const fallback = slug || id
  const alive = useRef(true)
  useLayoutEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const operation = useMutation({
    mutationFn: async (action: Action) => {
      if (action.kind === 'check') return { kind: 'check' as const, report: await generationApi.check(id) }
      if (action.kind === 'preview') return { kind: 'preview' as const, preview: await generationApi.preview(id) }
      if (action.kind === 'kit') {
        const { blob, filename } = await generationApi.kit(id, fallback + '-self-host.zip')
        if (alive.current) generationApi.save(blob, filename)
        return { kind: 'kit' as const }
      }
      const { blob, filename, id: generation, hash } = await generationApi.download(id, fallback + '.zip', 'approval' in action ? action.approval : undefined)
      if (alive.current) generationApi.save(blob, filename)
      void client.invalidateQueries({ queryKey: shipKeys.read(id, 'generate', 'history') })
      void client.invalidateQueries({ queryKey: shipKeys.section(id, 'upgrades') })
      return { kind: 'zip' as const, generation, hash }
    },
  })
  const write = canEdit(role) && !props.roleError
  const run = (action: Action) => operation.mutate(action)
  const apiError = shipError(operation.error)
  const detail = apiError?.details?.[0]
  const verification = apiError?.code === 'email_not_verified'
  const conflict = apiError?.status === 409 && (apiError.code === 'migration_baseline_unreadable' || apiError.code === 'destructive_migration')
  const issues = apiError?.code === 'spec_invalid' ? (apiError.details ?? []) as ValidationIssue[]
    : operation.data?.kind === 'check' ? operation.data.report.issues : []
  const issueRows = useIssueRows(issues)
  const { columns } = useShipFormat()
  const checking = operation.data?.kind === 'check' && operation.data.report.valid
  const retry = operation.variables && (write || operation.variables.kind === 'zip' || operation.variables.kind === 'kit')
    ? () => operation.variables && run({ kind: operation.variables.kind }) : undefined
  return <Stack gap={4}>
    <SettingsSection title={t('ship.yourBackend')}>
      <Row>{actions.map(kind => <Button key={kind} variant={kind === 'zip' ? 'primary' : 'default'}
        data-testid={kind === 'kit' ? 'self-host-kit' : undefined} title={kind === 'kit' ? t('ship.kitTitle') : undefined}
        disabled={operation.isPending || (!write && (kind === 'check' || kind === 'preview'))}
        onClick={() => run({ kind })}>{t('ship.' + (operation.isPending && operation.variables.kind === kind ? kind + 'Busy' : kind))}</Button>)}</Row>
      <ShipRole props={props}>{t('ship.generateReadOnly')}</ShipRole>
      <p className="v2-muted">{t('ship.kitNote')}</p>
      <Row><ShipLink id={id} section="deployment" label={t('ship.deploySettings')} />
        <ShipLink id={id} section="specdiff" label={t('ship.specDiff')} /></Row>
    </SettingsSection>
    {verification && <VerifyDownload />}
    {operation.isError && !verification && !conflict && !issueRows.length && <ShipProblem error={operation.error} retry={retry}
      message={apiError?.code === 'migration_plan_invalid' ? t('ship.value', { value: apiError.message }) : t('ship.generationError')} />}
    {checking && <Alert tone="success">{t('ship.checkSuccess')}</Alert>}
    {operation.data?.kind === 'kit' && <Alert tone="success">{t('ship.kitSuccess')}</Alert>}
    {issueRows.length > 0 && <SettingsSection title={t('ship.validation')}>
      <Alert tone="danger">{t('ship.generationIssues', { count: issueRows.length })}</Alert>
      <Table label={t('ship.validation')} columns={columns('path', 'code', 'problem')} rows={issueRows} />
    </SettingsSection>}
    {conflict && <SettingsSection title={t('ship.reviewMigration')}>
      <ConflictBanner>{t('ship.value', { value: apiError.message })}</ConflictBanner>
      {apiError.code === 'migration_baseline_unreadable'
        ? <p>{t('ship.baselineId', { id: (detail as { generation_id?: string } | undefined)?.generation_id ?? t('ship.unknown') })}</p>
        : <MigrationReview migration={detail as MigrationPlanResponse | undefined} />}
      {write ? <Row><ConfirmDestructive
        title={t(apiError.code === 'migration_baseline_unreadable' ? 'ship.confirmBaselineTitle' : 'ship.confirmDestructiveTitle')}
        description={t(apiError.code === 'migration_baseline_unreadable' ? 'ship.confirmBaselineNote' : 'ship.confirmDestructiveNote')}
        action={t(apiError.code === 'migration_baseline_unreadable' ? 'ship.acceptBaseline' : 'ship.allowDestructive')}
        trigger={<Button variant="danger">{t(apiError.code === 'migration_baseline_unreadable' ? 'ship.reviewBaseline' : 'ship.reviewDestructive')}</Button>}
        onConfirm={() => {
          const previous = operation.variables?.kind === 'zip' ? operation.variables.approval : undefined
          run({ kind: 'zip', approval: apiError.code === 'migration_baseline_unreadable'
            ? { ...previous, acceptBaseline: true } : { ...previous, destructive: true } })
        }} /></Row> : <Alert>{t(apiError.code === 'migration_baseline_unreadable' ? 'ship.baselineForbidden' : 'ship.destructiveForbidden')}</Alert>}
    </SettingsSection>}
    {operation.data?.kind === 'preview' && <FilePreview id={id} preview={operation.data.preview} />}
    {operation.data?.kind === 'zip' && <FirstRun id={id} slug={fallback} generation={operation.data.generation} hash={operation.data.hash} />}
    <GenerationHistory id={id} busy={operation.isPending} onDownload={() => run({ kind: 'zip' })} />
  </Stack>
}

function FilePreview({ id, preview }: { id: string; preview: ShipPreview }) {
  const t = useT()
  const { bytes, columns } = useShipFormat()
  const link = (path: string) => <Button asChild variant="ghost">
    <Link {...openInEditor({ projectId: id, path, source: 'manifest' })}
      aria-label={t('ship.openFile', { path })}><code>{t('ship.value', { value: path })}</code></Link></Button>
  const grouped = new Map<string, ShipPreview['files']>()
  for (const file of preview.files) {
    const folder = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/')) : t('ship.projectRoot')
    const files = grouped.get(folder) ?? []
    files.push(file)
    grouped.set(folder, files)
  }
  return <Stack>
    <SettingsSection title={t('ship.files')}>
      <p>{t('ship.previewSummary', { count: preview.total_files, size: bytes(preview.total_size), hash: preview.spec_hash.slice(0, 12) })}</p>
      {preview.files.length > 0 && <>
        <div className="v2-ship-data" tabIndex={0} role="region" aria-label={t('ship.filePreview')}>
          <Table label={t('ship.files')} columns={columns('path', 'size')} rows={preview.files.map(file => ({
            id: file.path, cells: [link(file.path), bytes(file.size)],
          }))} />
        </div>
        <Disclosure label={t('ship.folders')}><Stack>{[...grouped].map(([folder, files]) =>
          <Disclosure key={folder} label={t('ship.value', { value: folder })}><ul className="v2-stack">
            {files.map(file => <li key={file.path}><code>{t('ship.value', { value: file.path.split('/').at(-1) ?? file.path })}</code> {bytes(file.size)}</li>)}
          </ul></Disclosure>)}</Stack></Disclosure>
      </>}
    </SettingsSection>
    {preview.migration && <SettingsSection title={t('ship.migrationPlan')}>
      <MigrationReview migration={preview.migration} />
      <Row><ShipLink id={id} section="specdiff" label={t('ship.compareSpec')} /></Row>
    </SettingsSection>}
  </Stack>
}
