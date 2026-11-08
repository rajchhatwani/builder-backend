import { useCallback, useEffect, useRef, useState } from 'react'
import { MAX_RECONNECTS, backoffDelay, createSseParser, pushLines, type LogLine } from './stageLogic'
import { TOKEN_HEADER, classifyStatus, previewUrl } from './previewAccess'

/** A connection must stay open this long before the reconnect budget resets (a server that opens, emits, and closes must not loop forever). */
export const STABLE_MS = 10_000
type Status = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'sleeping' | 'gone' | 'token' | 'ended' | 'error'
const LABEL: Record<Status, string> = {
  idle: 'Not connected', connecting: 'Connecting…', live: 'Live', reconnecting: 'Reconnecting…', sleeping: 'Preview is sleeping or starting; logs resume when it runs',
  gone: 'This preview has ended (expired or stopped). Start a new one.', token: 'The preview token was not accepted. Issue a new token.', ended: 'Log stream closed', error: 'Could not read the logs',
}

/** Live preview logs over fetch streaming (EventSource cannot send the X-Preview-Token header). The token stays in memory. */
export function RunLogs({ previewId, token, doFetch = fetch }: { previewId: string; token: string; doFetch?: typeof fetch }) {
  const [lines, setLines] = useState<LogLine[]>([])
  const [status, setStatus] = useState<Status>('idle')
  const [paused, setPaused] = useState(false)
  const [copied, setCopied] = useState(false)
  const buf = useRef<LogLine[]>([])
  const seq = useRef(0)
  const pausedRef = useRef(false)
  const box = useRef<HTMLDivElement>(null)

  const add = useCallback((kind: LogLine['kind'], text: string) => {
    buf.current = pushLines(buf.current, [{ id: ++seq.current, kind, text }])
    if (!pausedRef.current) setLines(buf.current)
  }, [])

  useEffect(() => {
    if (!token) { setStatus('idle'); return }
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    const run = async () => {
      setStatus(attempt ? 'reconnecting' : 'connecting')
      let stop = false
      let liveSince = 0
      try {
        const res = await doFetch(previewUrl(previewId, '/-/logs'), { headers: { [TOKEN_HEADER]: token, Accept: 'text/event-stream' }, credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: ctl.signal })
        if (!res.ok || !res.body) {
          const f = classifyStatus(res.status)
          if (f === 'gone') { setStatus('gone'); return }
          if (f === 'token') { setStatus('token'); return }
          throw new Error(`status ${res.status}`)
        }
        setStatus('live'); liveSince = Date.now()
        const parse = createSseParser()
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          for (const ev of parse(dec.decode(value, { stream: true }))) {
            if (ev.event === 'state') { setStatus('sleeping'); add('state', `preview state: ${ev.data}`) }
            else if (ev.event === 'end') { add('end', ev.data); if (/switched off/i.test(ev.data)) stop = true }
            else if (ev.event === 'info') add('info', ev.data)
            else { setStatus('live'); add('log', ev.data) }
          }
        }
        if (stop) { setStatus('ended'); return }
      } catch {
        if (ctl.signal.aborted) return
      }
      if (ctl.signal.aborted) return
      if (liveSince && Date.now() - liveSince >= STABLE_MS) attempt = 0
      if (attempt >= MAX_RECONNECTS) { setStatus('error'); return }
      timer = setTimeout(run, backoffDelay(attempt++))
      setStatus((s) => (s === 'sleeping' ? s : 'reconnecting'))
    }
    void run()
    return () => { ctl.abort(); if (timer) clearTimeout(timer) }
  }, [previewId, token, doFetch, add])

  useEffect(() => { const el = box.current; if (el && !paused) el.scrollTop = el.scrollHeight }, [lines, paused])

  const togglePause = () => { pausedRef.current = !paused; setPaused(!paused); if (paused) setLines(buf.current) }
  const clear = () => { buf.current = []; setLines([]) }
  const copy = async () => {
    try { await navigator.clipboard.writeText(buf.current.map((l) => l.text).join('\n')); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { setCopied(false) }
  }

  return (
    <div className="stage-logs" data-testid="run-logs">
      <div className="hstack stage-bar">
        <span className="badge" role="status" data-testid="log-status" data-status={status}>{LABEL[status]}</span>
        <button type="button" className="btn btn-sm" data-testid="log-pause" aria-pressed={paused} onClick={togglePause}>{paused ? 'Resume' : 'Pause'}</button>
        <button type="button" className="btn btn-sm" data-testid="log-copy" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy'}</button>
        <button type="button" className="btn btn-sm" data-testid="log-clear" onClick={clear}>Clear</button>
      </div>
      <div ref={box} className="stage-log-box" tabIndex={0} role="log" aria-label="Preview logs" data-testid="log-box">
        {lines.length === 0 ? <p className="muted small-text">{token ? 'No log lines yet.' : 'Add a preview token to see logs.'}</p>
          : lines.map((l) => <div key={l.id} className={`stage-log-line stage-log-${l.kind}`} data-testid="log-line">{l.text}</div>)}
      </div>
    </div>
  )
}
