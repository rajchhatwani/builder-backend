import { afterEach, describe, expect, it } from 'vitest'
import { anotherModalOpen, isPaletteKey } from './ShellV2'

describe('Ctrl+K guard', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })
  it('recognises Ctrl+K and Cmd+K only', () => {
    expect(isPaletteKey({ ctrlKey: true, metaKey: false, key: 'k' })).toBe(true)
    expect(isPaletteKey({ ctrlKey: false, metaKey: true, key: 'K' })).toBe(true)
    expect(isPaletteKey({ ctrlKey: false, metaKey: false, key: 'k' })).toBe(false)
  })
  it('sees no modal on a plain page', () => {
    document.body.innerHTML = '<main><p>hi</p></main>'
    expect(anotherModalOpen(document)).toBe(false)
    document.body.innerHTML = '<dialog></dialog>'
    expect(anotherModalOpen(document)).toBe(false)
  })
  it.each([
    '<dialog open></dialog>',
    '<div role="dialog"></div>',
    '<div aria-modal="true"></div>',
  ])('sees an open modal: %s', (html) => {
    document.body.innerHTML = html
    expect(anotherModalOpen(document)).toBe(true)
  })
})
