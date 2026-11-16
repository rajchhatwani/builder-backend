import { describe, expect, it } from 'vitest'
import { slugify, slugifyLive } from './DocumentsPanel'

describe('DocumentsPanel template name', () => {
  it('can type an underscore character by character', () => {
    let v = ''
    for (const ch of 'my_invoice') v = slugifyLive(v + ch)
    expect(v).toBe('my_invoice')
  })
  it('strips the trailing underscore when finished', () => {
    expect(slugify(slugifyLive('my_'))).toBe('my')
  })
})
