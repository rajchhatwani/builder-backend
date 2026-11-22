import { useId, useState } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { State, useCall, type Page } from '../money/moneyShared'
import { AiPageFrame, Pager, hasArray, isObj, useGet } from './aiShared'
import { pageInfo, shortId, usd } from './aiLogic'

interface Usage {
  period: string; period_start: string; limit_micro_usd: number; spent_micro_usd: number; reserved_micro_usd: number; remaining_micro_usd: number
  calls_ok: number; calls_error: number; input_tokens: number; output_tokens: number; zero_retention: boolean; region: string
}
interface Call {
  id: string; caller_id: string | null; stage: string; provider: string; model: string; status: string; input_tokens: number; output_tokens: number
  cost_micro_usd: number; reserved_micro_usd: number; error_code: string | null; fallback_used: boolean; created_at: string; finished_at: string | null
}
const LIMIT = 50
const WHAT = 'AI gateway'
const STATUSES = ['', 'reserved', 'ok', 'error']

function Body({ session }: { session: PreviewSession }) {
  const call = useCall(session)
  const [refresh, setRefresh] = useState(0)
  const [stage, setStage] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const stageId = useId(), statusId = useId()
  const usage = useGet<Usage>(call, '/ai/usage', isObj, WHAT, refresh)
  const qs = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) })
  if (stage.trim()) qs.set('stage', stage.trim().slice(0, 40))
  if (status) qs.set('status', status)
  const calls = useGet<Page<Call>>(call, `/ai/calls?${qs}`, hasArray('items'), WHAT, refresh)

  return (
    <>
      <div className="hstack">
        <button type="button" className="outline" onClick={() => setRefresh((n) => n + 1)} data-testid="usage-refresh">Refresh</button>
        <span className="muted" data-testid="usage-estimate-note">Costs are estimates in micro-USD (1 USD = 1,000,000). The price table is not verified against real provider invoices.</span>
      </div>

      <div>
        <h2>Usage and budget</h2>
        <State l={usage} id="usage" empty={() => false} emptyText="">
          {(u) => {
            const used = Number(u.limit_micro_usd) > 0 ? Math.min(100, Math.floor(((Number(u.spent_micro_usd) + Number(u.reserved_micro_usd)) * 100) / Number(u.limit_micro_usd))) : 0
            return (
              <div className="stack" data-testid="usage-totals">
                <p>Period: {u.period} (from {u.period_start}). Region: {u.region}. {u.zero_retention ? 'Zero retention: prompts and outputs are not stored.' : 'Prompts and outputs are retained by the gateway.'}</p>
                <dl className="stack">
                  <div><dt>Budget (estimate)</dt><dd data-testid="usage-limit">USD {usd(u.limit_micro_usd)}</dd></div>
                  <div><dt>Spent (estimate)</dt><dd data-testid="usage-spent">USD {usd(u.spent_micro_usd)}</dd></div>
                  <div><dt>Reserved for calls in flight (estimate)</dt><dd data-testid="usage-reserved">USD {usd(u.reserved_micro_usd)}</dd></div>
                  <div><dt>Remaining (estimate)</dt><dd data-testid="usage-remaining">USD {usd(u.remaining_micro_usd)}</dd></div>
                  <div><dt>Calls succeeded / failed</dt><dd data-testid="usage-calls">{u.calls_ok} / {u.calls_error}</dd></div>
                  <div><dt>Tokens in / out</dt><dd data-testid="usage-tokens">{u.input_tokens} / {u.output_tokens}</dd></div>
                </dl>
                <progress value={used} max={100} aria-label="Budget used" data-testid="usage-bar" />
                <span className="muted">{used}% of the budget reserved or spent (estimate).</span>
              </div>
            )
          }}
        </State>
      </div>

      <div className="stack">
        <h2>Calls</h2>
        <div className="hstack">
          <label htmlFor={stageId}>Stage</label>
          <input id={stageId} value={stage} maxLength={40} onChange={(e) => { setStage(e.target.value); setOffset(0) }} data-testid="calls-stage" />
          <label htmlFor={statusId}>Status</label>
          <select id={statusId} value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }} data-testid="calls-status">
            {STATUSES.map((s) => <option key={s} value={s}>{s || 'Any'}</option>)}
          </select>
        </div>
        <State l={calls} id="calls" empty={(v) => v.items.length === 0} emptyText="No calls match.">
          {(v) => (
            <>
              <div className="stage-table-wrap" tabIndex={0} role="region" aria-label="AI calls">
                <table className="stage-table" data-testid="calls-table">
                  <caption className="sr-only">AI gateway calls, newest first. Costs are estimates.</caption>
                  <thead><tr><th scope="col">When</th><th scope="col">Stage</th><th scope="col">Provider / model</th><th scope="col">Status</th><th scope="col">Tokens in / out</th><th scope="col">Cost (estimate, USD)</th><th scope="col">Caller</th><th scope="col">Error</th></tr></thead>
                  <tbody>{v.items.map((c) => (
                    <tr key={c.id} data-testid="calls-row">
                      <td>{c.created_at}</td><th scope="row">{c.stage}</th><td>{c.provider} / {c.model}{c.fallback_used ? ' (fallback)' : ''}</td><td>{c.status}</td>
                      <td className="num">{c.input_tokens} / {c.output_tokens}</td><td className="num">{usd(c.cost_micro_usd)}</td><td>{shortId(c.caller_id)}</td><td>{c.error_code ?? ''}</td>
                    </tr>))}</tbody>
                </table>
              </div>
              <Pager id="calls" info={pageInfo(Number(v.total), LIMIT, offset)} onPrev={() => setOffset(Math.max(0, offset - LIMIT))} onNext={() => setOffset(offset + LIMIT)} />
            </>
          )}
        </State>
      </div>
    </>
  )
}

export function AiUsagePage({ projectId, session }: { projectId: string; session?: PreviewSession }) {
  return (
    <AiPageFrame projectId={projectId} session={session} testid="ai-usage-page" title="AI usage"
      intro="What this project's AI gateway has spent against its budget, and every model call. Prompt text is never shown here.">
      {(s) => <Body session={s} />}
    </AiPageFrame>
  )
}
