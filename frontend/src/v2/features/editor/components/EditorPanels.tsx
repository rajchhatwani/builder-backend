import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useT } from '../../../i18n'
import { Alert, Badge, Button, Row, Skeleton, Stack, Tabs } from '../../../ui'
import { runChecksOptions, runOptions } from '../api/editor'

type Problem = { line: number; message: string }

export function EditorPanels({ projectId, run, workspace, panel, problems, onPanel, onLine }: {
  projectId: string; run?: string; workspace?: string; panel?: string; problems: Problem[]
  onPanel: (panel: string) => void; onLine: (line: number) => void
}) {
  const t = useT()
  const selected = panel === 'tests' || panel === 'logs' ? panel : 'problems'
  const logs = useQuery({ ...runOptions(projectId, run ?? ''), enabled: Boolean(run && selected === 'logs') })
  const checks = useQuery({ ...runChecksOptions(projectId, run ?? ''), enabled: Boolean(run && selected === 'tests') })
  const steps = logs.data?.steps ?? []
  const gate = checks.data?.find(approval => approval.kind === 'C' && approval.payload.final === true && approval.payload.gate_report_hash)
  const query = selected === 'logs' ? logs : checks
  const report = selected !== 'problems' && run && (query.isPending ? <Skeleton lines={2} />
    : query.isError ? <Alert tone="danger" action={<Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>}>{t('editor.loadRunFailed')}</Alert> : null)

  return <section className="v2-editor-panel" aria-label={t('editor.panels')}>
    <Tabs label={t('editor.panels')} value={selected} onChange={onPanel} items={[
      { id: 'problems', label: t('editor.problemCount', { count: problems.length }), content: problems.length
        ? <Stack gap={1}>{problems.map((problem, index) => <Button key={index} variant="ghost" className="v2-editor-result" onClick={() => onLine(problem.line)}>
          {t('editor.problem', { line: problem.line, message: problem.message })}
        </Button>)}</Stack> : <p>{t('editor.noProblems')}</p> },
      { id: 'tests', label: t('editor.tests'), content: report || <p>{t(gate ? 'editor.gatesPassed' : 'editor.noTests')}</p> },
      { id: 'logs', label: t('editor.logs'), content: report || <Stack gap={2}>
        {steps.length ? steps.map(step => <Row key={step.id} gap={2}>
          <Badge tone={step.ok ? 'success' : 'danger'}>{t(step.ok ? 'build.ok' : 'build.failed')}</Badge>
          <span>{t('build.step', { number: step.seq, name: step.tool_name ?? step.kind })}</span>
        </Row>) : <p>{t('editor.noRunLogs')}</p>}
        <Row>
          {run && <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'build' }} search={{ run }}>{t('nav.build')}</Link></Button>}
          <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'see' }} search={{ workspace, view: 'logs' }}>{t('editor.liveLogs')}</Link></Button>
        </Row>
      </Stack> },
    ]} />
  </section>
}
