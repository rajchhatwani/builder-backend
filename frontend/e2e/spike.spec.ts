import { expect, test } from '@playwright/test'

/** C0-F4 spike: Tailwind v4 utilities (no preflight) coexist with Oat on one hidden route. */
test('tailwind spike route renders utilities next to Oat components', async ({ page }) => {
  await page.goto('/#/__spike')
  const pill = page.getByTestId('tw-pill')
  await expect(pill).toBeVisible()
  expect(await pill.evaluate((el) => getComputedStyle(el).backgroundColor)).toMatch(/^(rgb|oklch|color)/)
  expect(await pill.evaluate((el) => getComputedStyle(el).borderRadius)).not.toBe('0px')
  // Oat keeps styling its own elements: the button is not reset to browser defaults.
  const button = page.getByRole('button', { name: 'Oat button' })
  expect(await button.evaluate((el) => getComputedStyle(el).borderRadius)).not.toBe('0px')
})
