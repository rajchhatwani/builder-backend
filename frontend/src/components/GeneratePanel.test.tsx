import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { click, flush, mount, q } from '../shell/ai/testUtils'
import { GeneratePanel } from './GeneratePanel'

const m = vi.hoisted(() => ({ gens: vi.fn(), kit: vi.fn(), save: vi.fn() }))
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: { listGenerations: m.gens, downloadSelfHostKit: m.kit },
  saveBlob: m.save,
}))

const project = { id: 'p1', slug: 'shop', name: 'Shop' } as never
beforeEach(() => { m.gens.mockReset(); m.kit.mockReset(); m.save.mockReset(); m.gens.mockResolvedValue({ items: [] }) })

describe('GeneratePanel self-host kit', () => {
  it('downloads the kit with the server filename', async () => {
    const blob = new Blob(['zip'])
    m.kit.mockResolvedValue({ blob, filename: 'shop-kit.zip' })
    await mount(createElement(GeneratePanel, { project, modelVersion: 1 }))
    await click(q('self-host-kit'))
    expect(m.kit).toHaveBeenCalledWith('p1', 'shop-self-host-kit.zip')
    expect(m.save).toHaveBeenCalledWith(blob, 'shop-kit.zip')
  })

  it('shows the refusal message when the kit cannot be built', async () => {
    m.kit.mockRejectedValueOnce(new Error('verify your e-mail first'))
    await mount(createElement(GeneratePanel, { project, modelVersion: 1 }))
    await click(q('self-host-kit'))
    await flush()
    expect(document.body.textContent).toContain('verify your e-mail first')
    expect(m.save).not.toHaveBeenCalled()
  })
})
