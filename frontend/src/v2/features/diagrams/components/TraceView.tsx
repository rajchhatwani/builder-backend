import { useRef, useState } from 'react'
import { useT } from '../../../i18n'
import { Button, Field, Input, Row, Stack, Table } from '../../../ui'
import { MAX_TRACE_BYTES, parseTrace } from '../../../../shell/traces/traceLogic'
import type { ParsedTrace } from '../../../../shell/traces/traceLogic'

const spansPerPage = 25

export default function TraceView({ page, onPage }: { page: number; onPage: (next: number) => void }) {
  const t = useT()
  const readId = useRef(0)
  const [trace, setTrace] = useState<ParsedTrace>()
  const [error, setError] = useState<string>()
  async function load(file?: File) {
    const request = ++readId.current
    if (!file) return
    if (file.size > MAX_TRACE_BYTES) {
      setError(t('diagrams.traceSize', { count: MAX_TRACE_BYTES / (1024 * 1024) }))
      return
    }
    const parsed = await file.text().then(text => parseTrace(text), () => undefined)
    if (request !== readId.current) return
    if (!parsed?.ok) {
      setError(t('diagrams.traceInvalid'))
      return
    }
    setError(undefined)
    onPage(1)
    setTrace(parsed.trace)
  }

  const total = trace ? Math.ceil(trace.rows.length / spansPerPage) : 1
  const current = Math.min(page, total)

  return <Stack gap={3}>
    <Field label={t('diagrams.upload')} error={error} hint={t('diagrams.traceLoad')}>
      {props => <Input {...props} type="file" accept=".json,application/json" onChange={event => {
        void load(event.currentTarget.files?.[0])
        event.currentTarget.value = ''
      }} />}
    </Field>
    {trace && <>
      <p>{t('diagrams.traceSummary', { id: trace.traceId, count: trace.rows.length, duration: trace.totalMs })}</p>
      <Table label={t('diagrams.words.traces')} columns={['span', 'service', 'startsMs', 'durationMs', 'status', 'waterfall']
        .map(id => ({ id, label: t('diagrams.words.' + id) }))}
        rows={trace.rows.slice((current - 1) * spansPerPage, current * spansPerPage).map(row => ({
          id: row.span.span_id, cells: [row.span.name, row.span.service || t('diagrams.blank'),
            t('diagrams.value', { value: row.offsetMs }), t('diagrams.value', { value: row.durationMs }),
            t('diagrams.words.' + (row.span.status === 'ok' ? 'traceOk' : 'traceError')),
            <svg key="bar" className="v2-diagrams-trace" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden>
              <rect width={100} height={10} className="v2-diagrams-trace-track" />
              <rect x={row.offsetPct} width={Math.min(100 - row.offsetPct, Math.max(1, row.widthPct))} height={10}
                className={row.onCriticalPath ? 'v2-diagrams-trace-critical' : 'v2-diagrams-trace-range'} />
            </svg>],
        }))} />
      {total > 1 && <Row>
        <Button disabled={current <= 1} onClick={() => onPage(current - 1)}>{t('diagrams.previous')}</Button>
        <span>{t('diagrams.tablePage', { page: current, total })}</span>
        <Button disabled={current >= total} onClick={() => onPage(current + 1)}>{t('diagrams.more')}</Button>
      </Row>}
    </>}
  </Stack>
}
