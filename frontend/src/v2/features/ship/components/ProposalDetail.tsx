import { useQuery, useQueryClient } from '@tanstack/react-query'
import { readBlockChanges, readFiles, readMigrations, readSbom } from '../../../../shell/upgrades/upgradeLogic'
import { useT } from '../../../i18n'
import { ConfirmDestructive, ConflictBanner, SettingsSection } from '../../../patterns'
import { Badge, Button, CodeBlock, Disclosure, Grid, Row, Stack, Table } from '../../../ui'
import { downloadPatch, patchOptions, proposalOptions, shipError, shipKeys, useUpgradeDecision } from '../api/ship'
import type { UpgradeProposalDetail } from '../api/ship'
import { ShipLoading, ShipProblem, useShipFormat } from './Common'

export function ProposalDetail({ id, proposal, write, close }: { id: string; proposal: string; write: boolean; close: () => void }) {
  const t = useT()
  const client = useQueryClient()
  const detail = useQuery(proposalOptions(id, proposal))
  const patch = useQuery(patchOptions(id, proposal))
  const decision = useUpgradeDecision(id, proposal)
  const closed = shipError(decision.error)?.status === 409
  const data = detail.data
  const { date } = useShipFormat()
  return <SettingsSection title={t('ship.proposalDetail')}>
    <Row><Button onClick={close}>{t('common.close')}</Button></Row>
    {detail.isPending ? <ShipLoading label={t('ship.proposalLoading')} /> : detail.isError ?
      <ShipProblem error={detail.error} message={t('ship.proposalError')} retry={detail.refetch} testId="detail-error" /> :
      data && <Stack data-testid="detail">
        <p data-testid="detail-status">{t('ship.proposalStatus', {
          status: t('ship.' + data.status), from: data.from_generator_version ?? t('ship.unknown'),
          to: data.to_generator_version, count: data.file_count,
        })}</p>
        {closed && <div data-testid="decide-error"><ConflictBanner onReload={async () => {
          const result = await detail.refetch()
          if (result.isSuccess) decision.reset()
          void client.invalidateQueries({ queryKey: shipKeys.read(id, 'upgrades', 'list') })
        }}>{t('ship.proposal_closed')}</ConflictBanner></div>}
        {decision.isError && !closed && <ShipProblem error={decision.error} message={t('ship.decisionError')} testId="decide-error" />}
        <ProposalFacts data={data} />
        <ProposalChanges data={data} />
        <h3>{t('ship.patch')}</h3>
        {patch.isPending ? <ShipLoading label={t('ship.patchLoading')} /> : patch.isError ?
          <ShipProblem error={patch.error} message={t('ship.patchError')} retry={patch.refetch} testId="patch-error" /> : <>
            <Disclosure label={t('ship.readPatch')} open>
              <div className="v2-ship-data" role="region" aria-label={t('ship.patchName')} tabIndex={0} data-testid="patch">
                <CodeBlock code={patch.data} />
              </div>
            </Disclosure>
            <Row><Button data-testid="download-patch" onClick={() => downloadPatch(data.id, patch.data)}>{t('ship.downloadPatch')}</Button></Row>
          </>}
        {data.status === 'open' && write && <Row data-testid="decide">
          {(['applied', 'dismiss'] as const).map(kind => <ConfirmDestructive key={kind}
            trigger={<Button data-testid={kind === 'applied' ? 'mark-applied' : 'dismiss'} disabled={closed || decision.isPending}
              variant={kind === 'dismiss' ? 'danger' : 'default'}>{t('ship.decision.' + kind)}</Button>}
            title={t('ship.decision.' + kind + 'Title')} description={t('ship.decision.' + kind + 'Note')}
            action={t('ship.decision.' + kind + 'Confirm')} pending={decision.isPending} confirmTestId="confirm-decide"
            onConfirm={() => decision.mutateAsync(kind).then(() => undefined, error => {
              if (shipError(error)?.status !== 409) throw error
            })} />)}
        </Row>}
        {data.status !== 'open' && <p className="v2-muted" data-testid="closed-note">{data.decided_at
          ? t('ship.closedDated', { status: t('ship.' + data.status), date: date(data.decided_at) })
          : t('ship.closed', { status: t('ship.' + data.status) })}</p>}
      </Stack>}
  </SettingsSection>
}

function ProposalFacts({ data }: { data: UpgradeProposalDetail }) {
  const t = useT()
  const { date, bytes } = useShipFormat()
  const facts = [
    ['proposalId', data.id], ['baseGeneration', data.base_generation_id], ['creatorId', data.created_by ?? t('ship.unknown')],
    ['patchSize', bytes(data.patch_size)], ['created', date(data.created_at)],
    ['capturedScore', t(data.scorecard.passing === true ? 'ship.passing' : data.scorecard.passing === false ? 'ship.notPassing' : 'ship.unknown')],
  ]
  return <Grid role="list">{facts.map(([label, value]) => <Stack key={label} role="listitem" gap={1}>
    <span className="v2-muted">{t('ship.' + label)}</span><code>{t('ship.value', { value })}</code>
  </Stack>)}</Grid>
}

function ProposalChanges({ data }: { data: UpgradeProposalDetail }) {
  const t = useT()
  const { columns } = useShipFormat()
  const changes = readBlockChanges(data.block_changes)
  const files = readFiles(data.files)
  const migrations = readMigrations(data.migrations)
  const sbom = readSbom(data.sbom_diff)
  const sbomRows = (['added', 'removed', 'changed'] as const).flatMap(kind => sbom[kind].map(entry => ({ kind, entry })))
  const zones = [...new Set(files.map(file => file.zone))]
  const eligibility = data.auto_apply_eligible ? (changes.length ? 'eligibleBumps' : 'eligibleFiles') :
    migrations.length ? 'eligibilityMigration' : data.scorecard.passing === false ? 'eligibilityScore' :
      changes.some(change => change.bump === 'major') ? 'eligibilityMajor' :
        changes.some(change => change.bump !== 'patch') ? 'eligibilityBump' :
          files.some(file => file.zone !== 'generated') ? 'eligibilityZone' : 'eligibilityOther'
  return <Stack>
    <h3>{t('ship.blockVersions')}</h3>
    {changes.length === 0 ? <p>{t('ship.noBlocks')}</p> : <ul className="v2-stack" data-testid="block-changes">
      {changes.map(change => <li key={change.block}>
        <Row><code>{t('ship.value', { value: change.block })}</code>{t('ship.generatorVersions', {
          from: change.from ?? t('ship.none'), to: change.to ?? t('ship.none'),
        })}<span data-testid="bump" data-bump={change.bump}><Badge>{t('ship.value', { value: change.bump })}</Badge></span></Row>
      </li>)}
    </ul>}
    <h3>{t('ship.files')}</h3>
    {zones.length === 0 ? <p>{t('ship.noFilesChange')}</p> : zones.map(zone => <Stack key={zone}>
      <h4>{t('ship.zoneFiles', { zone })}</h4>
      <Table label={t('ship.zoneFiles', { zone })} columns={columns('path', 'zone', 'change')}
        rows={files.filter(file => file.zone === zone).map(file => ({
          id: file.path, testId: 'file-row',
          cells: [<code>{t('ship.value', { value: file.path })}</code>, t('ship.value', { value: file.zone }), t('ship.value', { value: file.change })],
        }))} />
    </Stack>)}
    {!!data.kept?.length && <p className="v2-muted" data-testid="kept">{t('ship.kept', { files: data.kept.join(', ') })}</p>}
    <h3>{t('ship.sbom')}</h3>
    {sbomRows.length === 0 ? <p>{t('ship.noDependencies')}</p> : <ul className="v2-stack" data-testid="sbom">
      {sbomRows.map(({ kind, entry }) => <li key={kind + entry.name}>
        {t('ship.dependencyChange', {
          change: t('ship.' + kind), name: entry.name, version: kind === 'changed'
            ? t('ship.generatorVersions', { from: entry.from ?? '', to: entry.to ?? '' }) : entry.spec ?? '',
        })}
      </li>)}
    </ul>}
    <h3>{t('ship.migrations')}</h3>
    {migrations.length === 0 ? <p>{t('ship.noMigrations')}</p> : <ul className="v2-stack" data-testid="migrations">
      {migrations.map(row => <li key={row.path}>{t('ship.fileChange', { path: row.path, change: row.change })}</li>)}
    </ul>}
    <h3>{t('ship.eligibility')}</h3>
    <p data-testid="eligibility">{t('ship.' + eligibility)} {t('ship.eligibilityNote')}</p>
  </Stack>
}
