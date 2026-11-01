import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { api } from '../../api/client'
import type { ExpressionCheckRead, ExpressionField, StateMachineBody } from '../../api/types'
import { link } from '../../components/Sidebar'
import { applyCompletion, errorSegments, guardsOf, mapLimit, moveActive, prefixAt, suggest, typeLabel, type Guard } from './rulesLogic'

const DEBOUNCE_MS = 300

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; entities: string[]; machines: StateMachineBody[] }

type GuardResult = { status: 'checking' } | { status: 'ok'; type: string | null | undefined } | { status: 'broken'; message: string } | { status: 'unknown'; message: string }

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

export function RulesPage({ projectId }: { projectId: string }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    Promise.all([api.listEntities(projectId, 200, 0), api.getStateMachines(projectId)])
      .then(([entities, machines]) => {
        if (!cancelled) setLoad({ status: 'ready', entities: entities.items.map((e) => e.name), machines: machines.state_machines })
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: 'error', message: err instanceof Error ? err.message : 'Could not load the project' })
      })
    return () => {
      cancelled = true
    }
  }, [projectId, attempt])

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Rules</h1>
          <p>Try a true/false expression against an entity and see at once whether the platform accepts it. This is a scratchpad: nothing you type here is saved.</p>
        </div>
      </div>

      {load.status === 'loading' && <p className="empty-state">Loading rules…</p>}

      {load.status === 'error' && (
        <div className="card empty-hero" role="alert">
          <h2>We could not load the rules page</h2>
          <p>{load.message}</p>
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </div>
      )}

      {load.status === 'ready' && load.entities.length === 0 && (
        <div className="card empty-hero" data-testid="rules-empty">
          <h2>No entities yet</h2>
          <p>Expressions read the fields of an entity. Add one first, then come back to try expressions on it.</p>
          <a className="button" href={link(`/p/${projectId}/model`)}>
            Open the data model
          </a>
        </div>
      )}

      {load.status === 'ready' && load.entities.length > 0 && <Workbench projectId={projectId} entities={load.entities} machines={load.machines} />}
    </>
  )
}

function Workbench({ projectId, entities, machines }: { projectId: string; entities: string[]; machines: StateMachineBody[] }) {
  const [entity, setEntity] = useState(entities[0])
  const [text, setText] = useState('')
  const [caret, setCaret] = useState(0)
  const [fields, setFields] = useState<ExpressionField[]>([])
  const [result, setResult] = useState<{ forText: string; forEntity: string; read: ExpressionCheckRead } | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [dismissedAt, setDismissedAt] = useState<string | null>(null)
  const [forced, setForced] = useState(false)
  const [active, setActive] = useState(0)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const mirrorRef = useRef<HTMLDivElement>(null)
  const pendingCaret = useRef<number | null>(null)
  const listId = useId()

  // Field names for the entity, before anything is typed ("true" always compiles; only `fields` is used).
  useEffect(() => {
    const ctrl = new AbortController()
    setFields([])
    api
      .checkExpression(projectId, entity, 'true', ctrl.signal)
      .then((r) => setFields(r.fields))
      .catch(() => undefined)
    return () => ctrl.abort()
  }, [projectId, entity])

  // Live check: debounced, the previous request is cancelled when the text changes again.
  useEffect(() => {
    if (!text.trim()) {
      setResult(null)
      setFailure(null)
      return
    }
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => {
      api
        .checkExpression(projectId, entity, text, ctrl.signal)
        .then((read) => {
          if (ctrl.signal.aborted) return
          setResult({ forText: text, forEntity: entity, read })
          setFailure(null)
          if (read.fields.length) setFields(read.fields)
        })
        .catch((err: unknown) => {
          if (isAbort(err) || ctrl.signal.aborted) return
          setFailure(err instanceof Error ? err.message : 'The check failed')
        })
    }, DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      ctrl.abort()
    }
  }, [projectId, entity, text])

  useLayoutEffect(() => {
    if (pendingCaret.current !== null && taRef.current) {
      taRef.current.setSelectionRange(pendingCaret.current, pendingCaret.current)
      pendingCaret.current = null
    }
  })

  const { start, prefix } = prefixAt(text, caret)
  const options = useMemo(() => suggest(fields, prefix, forced), [fields, prefix, forced])
  const open = options.length > 0 && dismissedAt !== `${text}|${caret}`
  const activeIndex = open ? Math.min(active, options.length - 1) : -1

  const settled = result !== null && result.forText === text && result.forEntity === entity
  const read = settled ? result.read : null
  const segs = read?.error ? errorSegments(text, read.error.pos) : null

  const accept = useCallback(
    (name: string) => {
      const next = applyCompletion(text, start, caret, name)
      setText(next.text)
      setCaret(next.caret)
      pendingCaret.current = next.caret
      setForced(false)
      setActive(0)
      taRef.current?.focus()
    },
    [text, start, caret],
  )

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === ' ') {
      e.preventDefault()
      setForced(true)
      setDismissedAt(null)
      return
    }
    if (!open) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setActive(moveActive(activeIndex, e.key === 'ArrowDown' ? 1 : -1, options.length))
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      accept(options[activeIndex].name)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setDismissedAt(`${text}|${caret}`)
      setForced(false)
    }
  }

  const track = (el: HTMLTextAreaElement) => setCaret(el.selectionStart)

  return (
    <>
      <div className="rules-controls">
        <label className="rules-entity">
          <span>Entity</span>
          <select
            value={entity}
            onChange={(e) => {
              setEntity(e.target.value)
              setResult(null)
            }}
          >
            {entities.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="rules-field">
        <label htmlFor="rules-expression" id="rules-expression-label">Expression</label>
        <div className="rules-editor" role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-owns={listId} aria-controls={listId} aria-labelledby="rules-expression-label">
          <div className="rules-mirror" ref={mirrorRef} aria-hidden="true" data-testid="rules-mirror">
            {segs ? (
              <>
                {segs.before}
                {segs.atEnd ? <mark className="rules-mark rules-mark-end" data-testid="rules-mark">{'​'}</mark> : <mark className="rules-mark" data-testid="rules-mark">{segs.mark}</mark>}
                {segs.after}
              </>
            ) : (
              text
            )}
            {'\n'}
          </div>
          <textarea
            id="rules-expression"
            ref={taRef}
            className="rules-input"
            rows={4}
            spellCheck={false}
            autoCapitalize="off"
            autoComplete="off"
            maxLength={1000}
            value={text}
            placeholder="for example: amount <= 10000 and status == &quot;draft&quot;"
            aria-autocomplete="list"
            aria-controls={listId}
            aria-activedescendant={open ? `${listId}-${activeIndex}` : undefined}
            aria-describedby="rules-result"
            aria-invalid={read?.error ? true : undefined}
            onChange={(e) => {
              setText(e.target.value)
              track(e.target)
              setActive(0)
              setForced(false)
              setDismissedAt(null)
            }}
            onKeyDown={onKeyDown}
            onKeyUp={(e) => {
              if (!['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(e.key)) track(e.currentTarget)
            }}
            onClick={(e) => track(e.currentTarget)}
            onSelect={(e) => track(e.currentTarget)}
            onScroll={(e) => {
              if (mirrorRef.current) mirrorRef.current.scrollTop = e.currentTarget.scrollTop
            }}
            onBlur={() => setForced(false)}
          />
          <ul id={listId} role="listbox" aria-label="Fields" className="rules-listbox" hidden={!open}>
            {options.map((f, i) => (
              <li
                key={f.name}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === activeIndex}
                className={i === activeIndex ? 'active' : undefined}
                onMouseDown={(e) => {
                  e.preventDefault()
                  accept(f.name)
                }}
              >
                <span>{f.name}</span>
                <span className="small-text">
                  {f.type}
                  {f.nullable ? ', may be empty' : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="muted small-text">Type a field name to get suggestions; arrows to move, Enter to insert, Esc to close, Ctrl+Space to list all.</p>
      </div>

      <div id="rules-result" className="rules-result" role="status" aria-live="polite" data-testid="rules-result">
        {failure && <span className="rules-error">The check could not run: {failure}</span>}
        {!failure && !text.trim() && <span className="muted">Type an expression to check it.</span>}
        {!failure && text.trim() && !settled && <span className="muted">Checking…</span>}
        {!failure && read?.ok && (
          <span className="rules-chip" data-testid="rules-type">
            {typeLabel(read.type)}
          </span>
        )}
        {!failure && read && !read.ok && read.error && (
          <span className="rules-error" data-testid="rules-error">
            {read.error.message}
          </span>
        )}
      </div>

      <section aria-labelledby="rules-fields" className="rules-fields">
        <h2 id="rules-fields">Fields of {entity}</h2>
        {fields.length === 0 ? (
          <p className="muted">Loading fields…</p>
        ) : (
          <ul className="rules-field-list" data-testid="rules-fields">
            {fields.map((f) => (
              <li key={f.name}>
                <code>{f.name}</code> <span className="muted small-text">{f.type}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Guards
        projectId={projectId}
        machines={machines}
        onTry={(g) => {
          setEntity(g.entity)
          setText(g.when)
          setCaret(g.when.length)
          taRef.current?.focus()
        }}
      />
    </>
  )
}

function Guards({ projectId, machines, onTry }: { projectId: string; machines: StateMachineBody[]; onTry: (g: Guard) => void }) {
  const guards = useMemo(() => guardsOf(machines), [machines])
  const [results, setResults] = useState<Record<string, GuardResult>>({})

  useEffect(() => {
    const ctrl = new AbortController()
    setResults(Object.fromEntries(guards.map((g) => [g.key, { status: 'checking' } as GuardResult])))
    void mapLimit(guards, 4, async (g) => {
      let r: GuardResult
      try {
        const read = await api.checkExpression(projectId, g.entity, g.when, ctrl.signal)
        r = read.ok ? { status: 'ok', type: read.type } : { status: 'broken', message: read.error?.message ?? 'Not accepted' }
      } catch (err) {
        if (isAbort(err)) return
        r = { status: 'unknown', message: err instanceof Error ? err.message : 'The check failed' }
      }
      if (!ctrl.signal.aborted) setResults((cur) => ({ ...cur, [g.key]: r }))
    })
    return () => ctrl.abort()
  }, [projectId, guards])

  const broken = Object.values(results).filter((r) => r.status === 'broken').length

  return (
    <section aria-labelledby="rules-guards" className="rules-guards">
      <h2 id="rules-guards">Guards in your state machines</h2>
      <p className="muted">
        Each guard decides when a transition may run.{' '}
        <a href={link(`/p/${projectId}/machines`)}>Open the state machines page</a> to see or change them.
      </p>
      {guards.length === 0 ? (
        <p className="muted" data-testid="rules-no-guards">
          None of your transitions has a guard yet.
        </p>
      ) : (
        <>
          <p role="status" data-testid="rules-guard-summary">
            {broken > 0 ? `${broken} of ${guards.length} ${guards.length === 1 ? 'guard is' : 'guards are'} broken.` : 'Every guard checked so far is accepted.'}
          </p>
          <ul className="rules-guard-list" data-testid="rules-guards">
            {guards.map((g) => {
              const r = results[g.key] ?? { status: 'checking' }
              return (
                <li key={g.key} data-guard={g.key} data-state={r.status}>
                  <div className="rules-guard-text">
                    <strong>
                      {g.entity}: {g.transition}
                    </strong>
                    <code>{g.when}</code>
                    {(r.status === 'broken' || r.status === 'unknown') && <span className="rules-error small-text">{r.message}</span>}
                  </div>
                  <span className={`rules-badge rules-badge-${r.status}`}>
                    {r.status === 'checking' ? 'Checking…' : r.status === 'ok' ? 'Accepted' : r.status === 'broken' ? 'Broken' : 'Could not check'}
                  </span>
                  <button className="outline small" onClick={() => onTry(g)} aria-label={`Try it: ${g.entity} ${g.transition}`}>
                    Try it
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}
