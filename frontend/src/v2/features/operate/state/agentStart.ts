import type { RunMode } from '../api/ai'

export type AgentAttempt = { agent: string; goal: string; mode: RunMode; key: string }
export type AgentStart = { agent: string; mode: RunMode | ''; attempt?: AgentAttempt; confirm: boolean; revision: number }
type Action =
  | { type: 'agent'; agent: string }
  | { type: 'mode'; mode: RunMode | '' }
  | { type: 'prepare'; attempt: AgentAttempt }
  | { type: 'close' | 'newKey' | 'complete' }

export const initialAgentStart: AgentStart = { agent: '', mode: '', confirm: false, revision: 0 }

export function agentStart(state: AgentStart, action: Action): AgentStart {
  switch (action.type) {
    case 'agent': return { ...state, agent: action.agent, mode: '', confirm: false }
    case 'mode': return { ...state, mode: action.mode, confirm: false }
    case 'prepare': return { ...state, attempt: action.attempt, confirm: action.attempt.mode !== 'suggest' }
    case 'close': return { ...state, confirm: false }
    case 'newKey': return { ...state, attempt: undefined, confirm: false }
    case 'complete': return { ...state, attempt: undefined, confirm: false, revision: state.revision + 1 }
  }
}

export function prepareAttempt(previous: AgentAttempt | undefined, agent: string, goal: string, mode: RunMode, newKey: () => string): AgentAttempt {
  const key = previous?.agent === agent && previous.goal === goal && previous.mode === mode ? previous.key : newKey()
  return { agent, goal, mode, key }
}
