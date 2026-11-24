import { expect, it } from 'vitest'
import { draftReducer } from './drafts'

it('holds the original content and SHA across background changes and clears only the named file', () => {
  const first = draftReducer({}, { type: 'edit', key: 'one', content: 'edited', original: 'before', sha: 'original' })
  const second = draftReducer(first, { type: 'edit', key: 'two', content: 'draft', original: '', sha: 'second' })
  const third = draftReducer(second, { type: 'edit', key: 'one', content: 'next', original: 'remote', sha: 'remote' })
  expect(third.one).toEqual({ original: 'before', content: 'next', sha: 'original' })
  expect(draftReducer(third, { type: 'clear', key: 'one' })).toEqual({ two: second.two })
  expect(draftReducer(third, { type: 'edit', key: 'one', content: 'before', original: 'remote', sha: 'remote' })).toEqual({ two: second.two })
})
