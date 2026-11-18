import { createElement } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { byText, click, mount } from '../shell/ai/testUtils'
import { UiProvider, useUi } from './Ui'

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})

function Asker({ out }: { out: boolean[] }) {
  const { confirm } = useUi()
  return createElement('button', { id: 'ask', onClick: () => confirm({ title: 'Sure?', message: 'x', confirmLabel: 'Yes do it' } as never).then((v) => out.push(v)) }, 'ask')
}

describe('Ui confirm', () => {
  it('resolves true on confirm and false on cancel', async () => {
    const out: boolean[] = []
    const host = await mount(createElement(UiProvider, null, createElement(Asker, { out })))
    await click(host.querySelector('#ask'))
    await click(byText(host, 'dialog button', /Yes do it/)!)
    await click(host.querySelector('#ask'))
    await click(byText(host, 'dialog button', /Cancel/)!)
    expect(out).toEqual([true, false])
  })
})
