import { expect, it } from 'vitest'
import { createAppRouter } from './router'

it('the prepared router uses hash history and can be created without mounting', () => {
  window.location.hash = '#/org/acme'
  const router = createAppRouter()
  expect(router.history.location.pathname).toBe('/org/acme')
})
