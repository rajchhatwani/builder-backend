export type Credential = { token: string; bearer?: string; revision: number }
export type Credentials = Record<string, Credential>
export type CredentialAction =
  | { type: 'connect'; id: string; token: string }
  | { type: 'identity'; id: string; token: string; bearer?: string }
  | { type: 'stop'; id: string }

export function credentialsReducer(state: Credentials, action: CredentialAction): Credentials {
  const entry = state[action.id]
  if (action.type === 'stop') return Object.fromEntries(Object.entries(state).filter(([id]) => id !== action.id))
  if (action.type === 'connect') return { ...state, [action.id]: { token: action.token, revision: (entry?.revision ?? 0) + 1 } }
  if (!entry || entry.token !== action.token) return state
  return { ...state, [action.id]: { ...entry, bearer: action.bearer, revision: entry.revision + 1 } }
}

export type Check = 'list' | 'create' | 'read' | 'update'
export type CheckResult = { verdict: 'pass' | 'fail'; status?: number; request?: string; response?: string }
export type Checks = { record?: string; results: Partial<Record<Check, CheckResult>> }
export type CheckAction = { type: 'result'; check: Check; result: CheckResult; record?: string } | { type: 'removed' }
export const initialChecks: Checks = { results: {} }

export function checkReducer(state: Checks, action: CheckAction): Checks {
  if (action.type === 'removed') return { results: state.results }
  if (action.check === 'create') {
    return { record: action.record, results: { list: state.results.list, create: action.result } }
  }
  return { ...state, results: { ...state.results, [action.check]: action.result } }
}

export type LogState = { lines: string[]; frozen?: string[]; status: string }
type LogAction = { type: 'line'; text: string } | { type: 'status'; status: string } | { type: 'pause' } | { type: 'clear' }
export function logReducer(state: LogState, action: LogAction): LogState {
  switch (action.type) {
    case 'line': return { ...state, lines: [...state.lines.slice(-399), action.text] }
    case 'status': return { ...state, status: action.status }
    case 'pause': return { ...state, frozen: state.frozen ? undefined : state.lines }
    case 'clear': return { ...state, lines: [], frozen: state.frozen ? [] : undefined }
  }
}

export type ConsoleEntry = { request: string; response: string }
export function consoleReducer(previous: ConsoleEntry[], entry: ConsoleEntry): ConsoleEntry[] {
  return [entry, ...previous.slice(0, 19)]
}
