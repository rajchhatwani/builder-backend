import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConflictBanner, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, EmptyState, Grid, Pagination, Row, Stack, Table } from '../../ui'
import { canEdit, pageSize, scoreOptions, shipError, shipKeys, upgradesOptions, useUpgradeCreate } from './api/ship'
import type { ScorecardCheck, ShipProps } from './api/ship'
import { ShipLink, ShipLoading, ShipProblem, ShipRole, ShipScreen, useShipFormat, useShipSearch } from './components/Common'
import { ProposalDetail } from './components/ProposalDetail'

export default function UpgradesScreen(props: ShipProps) {
  return <ShipScreen name="upgrades"><Upgrades {...props} /></ShipScreen>
}

function Upgrades(props: ShipProps) {
  const t = useT()
  const client = useQueryClient()
  const { projectId: id } = props
  const { search, change } = useShipSearch()
  const page = search.page ?? 1
  const write = canEdit(props.role) && !props.roleError
  const list = useQuery(upgradesOptions(id, page))
  const create = useUpgradeCreate(id)
  const { columns, date } = useShipFormat()
  const start = () => create.mutate(undefined, { onSuccess: proposal => void change({ page: undefined, proposal: proposal.id }) })
  const failure = shipError(create.error)
  const conflict = failure?.status === 409
  const openConflict = failure?.code === 'proposal_open'
  const proposal = (failure?.details?.[0] as { proposal_id?: string } | undefined)?.proposal_id
  const baselineConflict = failure?.code === 'no_baseline' || failure?.code === 'baseline_unavailable' || failure?.code === 'baseline_unreadable'
  const createLabel = t(create.isPending ? 'ship.working' : 'ship.checkUpgrade')
  const open = (proposal: string) => void change({ proposal })
  const creationButton = <Button variant="primary" disabled={!write || create.isPending} onClick={start} data-testid="create-proposal">{createLabel}</Button>

  return <Stack gap={4}>
    <ShipRole props={props} />
    {create.isSuccess && <Alert tone="success">{t('ship.proposalCreated')}</Alert>}
    {create.isError && <div data-testid="create-error">
      {failure?.code === 'up_to_date' ? <Alert tone="success">{t('ship.up_to_date')}</Alert> :
        conflict ? <Stack>
          <ConflictBanner>{t(openConflict || baselineConflict ? 'ship.' + failure.code : 'ship.upgradeConflict')}</ConflictBanner>
          {baselineConflict && <Row><ShipLink id={id} section="generate" label={t('ship.openGenerate')} /></Row>}
          {openConflict && <Row>{proposal ? <Button onClick={() => open(proposal)}>{t('ship.openProposal')}</Button> :
            <Button onClick={() => {
              void change({ page: undefined })
              void client.invalidateQueries({ queryKey: shipKeys.read(id, 'upgrades', 'list') })
            }}>{t('ship.refreshProposals')}</Button>}</Row>}
        </Stack> : <ShipProblem error={create.error} message={t('ship.createError')} retry={write ? start : undefined} />}
    </div>}
    <Scorecard id={id} create={start} disabled={!write || create.isPending} />
    <SettingsSection title={t('ship.proposals')}>
      <Row>{creationButton}</Row>
      {list.isPending && <ShipLoading label={t('ship.proposalsLoading')} />}
      {list.isError && <ShipProblem error={list.error} message={t('ship.proposalsError')} retry={list.refetch} testId="list-error" />}
      {list.data && <>
            {list.data.items.length ? <Table label={t('ship.proposals')} columns={columns('generator', 'status', 'files', 'created')}
              rows={list.data.items.map(row => ({ id: row.id, testId: 'proposal', status: row.status, cells: [
                <Button onClick={() => open(row.id)} aria-pressed={search.proposal === row.id}>{t('ship.generatorVersions', {
                  from: row.from_generator_version ?? t('ship.unknown'), to: row.to_generator_version,
                })}</Button>,
                <span data-testid="proposal-status"><ProposalStatus status={row.status} /></span>,
                t('ship.value', { value: row.file_count }), date(row.created_at),
              ] }))} /> : <div data-testid="list-empty"><EmptyState title={t(page === 1 ? 'ship.proposalsEmpty' : 'ship.pageEmpty')}
                action={page > 1 ? <Button onClick={() => void change({ page: undefined })}>{t('ship.firstPage')}</Button> : undefined} /></div>}
            {(page > 1 || list.data.total > pageSize) && <Pagination label={t('ship.proposals')} page={page}
              pages={Math.ceil(list.data.total / pageSize)} onChange={value => void change({ page: value > 1 ? value : undefined, proposal: undefined })} />}
          </>}
    </SettingsSection>
    {search.proposal && <ProposalDetail key={search.proposal} id={id} proposal={search.proposal} write={write}
      close={() => void change({ proposal: undefined })} />}
  </Stack>
}

const groups = ['security', 'dependency_freshness', 'hook_coverage', 'block_version_lag', 'drift']

function Scorecard({ id, create, disabled }: { id: string; create: () => void; disabled: boolean }) {
  const t = useT()
  const query = useQuery(scoreOptions(id))
  const score = query.data
  const entries = score && [...groups, 'other'].map(group => ({
    group, checks: score.checks.filter(check => group === 'other' ? !groups.includes(check.group) : check.group === group),
  })).filter(entry => entry.checks.length)
  return <SettingsSection title={t('ship.scorecard')}>
    {query.isPending ? <ShipLoading label={t('ship.scoreLoading')} /> :
      query.isError ? <ShipProblem error={query.error} message={t('ship.scoreError')} retry={query.refetch} testId="scorecard-error" /> :
        score && <Stack data-testid="scorecard">
          <Row><strong data-testid="score">{t('ship.score', { score: score.score })}</strong>
            <span data-testid="passing"><Badge tone={score.passing ? 'success' : 'danger'}>{t(score.passing ? 'ship.passing' : 'ship.notPassing')}</Badge></span></Row>
          {entries?.length ? <Grid>{entries.map(({ group, checks }) =>
            <Stack key={group} data-testid="check-group" data-group={group} className="v2-ship-group">
              <h3>{t('ship.' + group)}</h3>
              {checks.map(check => <Stack key={check.id} className="v2-ship-check" data-testid="check" data-status={check.status}>
                <Row><span data-testid="check-status"><Badge tone={check.status === 'pass' ? 'success' : check.status === 'warn' ? 'warning' : 'danger'}>
                  {t('ship.' + check.status)}</Badge></span><code>{t('ship.value', { value: check.id })}</code></Row>
                {check.status !== 'pass' && <><p data-testid="check-detail">{t('ship.value', { value: check.detail })}</p>
                  <ScorecardFix check={check} id={id} create={create} disabled={disabled} /></>}
              </Stack>)}
            </Stack>)}</Grid> : <p>{t('ship.noChecks')}</p>}
        </Stack>}
  </SettingsSection>
}

function ScorecardFix({ check, id, create, disabled }: { check: ScorecardCheck; id: string; create: () => void; disabled: boolean }) {
  const t = useT()
  switch (check.fix.action) {
    case 'open_upgrade': return <Row><Button disabled={disabled} onClick={create} data-testid="fix-open-upgrade"
      aria-label={t('ship.fixUpgradeAria', { id: check.id })}>{t('ship.fixUpgrade')}</Button></Row>
    case 'regenerate': return <Row><ShipLink id={id} section="generate" label={t('ship.fixRegenerate')} testId="fix-regenerate" /></Row>
    case 'redeclare_hook': return <Row><ShipLink id={id} section="hooks" label={t('ship.fixHook')} testId="fix-hook" /></Row>
    default: return <p data-testid="fix-none" className="v2-muted">{t('ship.fixManual')}</p>
  }
}

function ProposalStatus({ status }: { status: string }) {
  const t = useT()
  return <Badge tone={status === 'applied' ? 'success' : status === 'open' ? 'warning' : 'neutral'}>{t('ship.' + status)}</Badge>
}
