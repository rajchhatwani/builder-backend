import { expect, it, vi } from 'vitest'
import { agentStart, initialAgentStart, prepareAttempt } from './agentStart'

it('keeps the same key for a retry until the payload changes or the user requests a new key', () => {
  const newKey = vi.fn().mockReturnValueOnce('first').mockReturnValueOnce('different').mockReturnValueOnce('rotated')
  const first = prepareAttempt(undefined, 'scribe', 'Summarize returns', 'suggest', newKey)
  const pending = agentStart(initialAgentStart, { type: 'prepare', attempt: first })
  expect(pending.confirm).toBe(false)
  expect(prepareAttempt(pending.attempt, 'scribe', 'Summarize returns', 'suggest', newKey).key).toBe('first')
  expect(prepareAttempt(pending.attempt, 'scribe', 'Summarize returns', 'draft', newKey).key).toBe('different')
  const reset = agentStart(pending, { type: 'newKey' })
  expect(prepareAttempt(reset.attempt, 'scribe', 'Summarize returns', 'suggest', newKey).key).toBe('rotated')
})

it('requires confirmation for draft and auto and clears an attempt on completion', () => {
  const agent = agentStart(initialAgentStart, { type: 'agent', agent: 'scribe' })
  for (const mode of ['draft', 'auto'] as const) {
    const attempt = prepareAttempt(undefined, 'scribe', 'Summarize returns', mode, () => 'key')
    const confirming = agentStart(agent, { type: 'prepare', attempt })
    expect(confirming.confirm).toBe(true)
    expect(agentStart(confirming, { type: 'close' })).toMatchObject({ confirm: false, attempt })
    expect(agentStart(confirming, { type: 'complete' })).toEqual({ agent: 'scribe', mode: '', attempt: undefined, confirm: false, revision: 1 })
  }
})
