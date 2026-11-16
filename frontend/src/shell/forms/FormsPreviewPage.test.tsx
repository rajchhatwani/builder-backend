import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { byText, click, mount, q } from '../ai/testUtils'
import { FormsPreviewPage } from './FormsPreviewPage'

describe('FormsPreviewPage (F-0656)', () => {
  it('switches blocks and resets the value and sample errors', async () => {
    const host = await mount(createElement(FormsPreviewPage))
    expect(host.textContent).toContain('Flat toggles and numbers')
    expect(byText(host, 'button', /Clear backend errors/)!.hasAttribute('disabled')).toBe(true)
    await click(byText(host, 'button', /Show sample backend errors/) ?? null)
    expect(byText(host, 'button', /Clear backend errors/)!.hasAttribute('disabled')).toBe(false)
    await click(byText(host, 'nav button', /^Lists$/) ?? null)
    expect(host.textContent).toContain('List of rows with a nested list')
    expect(byText(host, 'button', /Clear backend errors/)!.hasAttribute('disabled')).toBe(true)
    expect(q('form-value')).not.toBeNull()
  })
})
