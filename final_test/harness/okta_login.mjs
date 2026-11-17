// Sign in through the Builder's SSO discovery and the real Okta page, headless. Usage:
//   node okta_login.mjs <app-url> <email> <okta-password> [new-password-if-okta-forces-a-change] [screenshot.png]
// Prints only: which step it reached and the final page headings/URL path (no tokens, no passwords).
import puppeteer from '/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js'
const [app, email, pw, newPw, shot] = process.argv.slice(2)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: 'new', args: ['--no-sandbox'] })
const ctx = await b.createBrowserContext() // clean cookies: no leftover Okta/app session
const p = await ctx.newPage()
await p.setUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36')
await p.setRequestInterception(true) // the ngrok bypass header must go to ngrok only: on other origins it breaks CORS
p.on('request', (r) => {
  if (/\.ngrok-free\.(dev|app)$/.test(new URL(r.url()).hostname)) r.continue({ headers: { ...r.headers(), 'ngrok-skip-browser-warning': '1' } })
  else r.continue()
})
const step = (s) => console.log('step:', s)
const fillFirst = async (sels, value) => {
  for (const s of sels) { const h = await p.$(s); if (h) { await h.click({ clickCount: 3 }); await h.type(value, { delay: 15 }); return true } }
  return false
}
const clickText = async (re) => p.evaluate((src) => {
  const r = new RegExp(src, 'i'); const el = [...document.querySelectorAll('button,input[type=submit],a')].find((e) => r.test((e.textContent || e.value || '').trim()))
  if (el) { el.click(); return true } return false }, re.source)
try {
  await p.goto(app, { waitUntil: 'networkidle2', timeout: 45000 }); step('app login page')
  await p.type('input[type=email]', email, { delay: 15 }); await clickText(/^continue$/); await sleep(1500); await clickText(/^continue with/)
  await p.waitForFunction(() => /okta\.com/.test(location.host), { timeout: 30000 }); step('redirected to Okta')
  await p.waitForSelector('input[name="identifier"], input[name="username"], #okta-signin-username', { timeout: 30000 })
  await fillFirst(['input[name="identifier"]', 'input[name="username"]', '#okta-signin-username'], email)
  await p.evaluate(() => document.querySelector('input[type=submit],button[type=submit]')?.click()); await sleep(4000)
  if (!(await p.$('input[type=password]'))) { // authenticator list ("Verify it's you"): choose Password, never Passkey
    await p.evaluate(() => { const el = document.querySelector('[data-se="okta_password"] a,[data-se="okta_password"] button'); if (el) el.click() })
    step('chose the Password method')
  }
  await p.waitForSelector('input[type=password]', { timeout: 30000 })
  await fillFirst(['input[type=password]'], pw); await p.evaluate(() => document.querySelector('input[type=submit],button[type=submit]')?.click()); step('Okta credentials submitted')
  await sleep(4000)
  if (await p.evaluate(() => /unable to sign in/i.test(document.body.innerText))) throw new Error('Okta rejected the password for this user (stale FINAL_TEST_IDP_USER_PASSWORD?)')
  if (await p.evaluate(() => /new password|change your password|password expired|reset your password/i.test(document.body.innerText))) {
    step('Okta asks for a new password')
    if (!newPw) throw new Error('Okta wants a password change but no new password was given')
    const pws = await p.$$('input[type=password]'); for (const h of pws) { await h.click({ clickCount: 3 }); await h.type(newPw, { delay: 15 }) }
    await clickText(/^(reset password|change password|next|verify|submit)$/); step('new password submitted'); await sleep(4000)
  }
  await p.waitForFunction((h) => location.host === h, { timeout: 45000 }, new URL(app).host); await sleep(3000); step('back on the Builder')
  const info = await p.evaluate(() => ({ path: location.pathname + location.hash.split('?')[0], headings: [...document.querySelectorAll('h1,h2')].map((e) => e.textContent.trim()).slice(0, 3), err: (location.hash.match(/sso_error=([a-z_]+)/) || [])[1] || null }))
  console.log(JSON.stringify(info)); if (shot) await p.screenshot({ path: shot })
} catch (e) {
  console.log('FAILED at:', e.message.split('\n')[0]); try { console.log(JSON.stringify(await p.evaluate(() => ({ host: location.host, headings: [...document.querySelectorAll('h1,h2,[role=alert],.o-form-error-container')].map((x) => x.textContent.trim().slice(0, 120)).slice(0, 4) })))) } catch {}
  if (shot) await p.screenshot({ path: shot }).catch(() => {})
  process.exitCode = 1
} finally { await b.close() }
