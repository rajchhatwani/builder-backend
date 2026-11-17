import puppeteer from '/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js'
const EMAIL = process.argv[2]
const PASSWORD = process.argv[3]
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage()
await p.setExtraHTTPHeaders({ 'ngrok-skip-browser-warning': '1' })
await p.goto('https://cinderous-overfamiliar-sanford.ngrok-free.dev/#/login', { waitUntil: 'networkidle2', timeout: 45000 })
await new Promise(r => setTimeout(r, 1500))
await p.type('input[type=email]', EMAIL)
let buttons = await p.$$('button')
for (const btn of buttons) { if ((await p.evaluate(e=>e.textContent.trim(), btn)) === 'Continue') { await btn.click(); break } }
await new Promise(r => setTimeout(r, 2000))
let links = await p.$$('a,button')
for (const el of links) { if ((await p.evaluate(e=>e.textContent.trim(), el)) === 'Sign in with a password instead') { await el.click(); break } }
await new Promise(r => setTimeout(r, 1500))
const pwField = await p.$('input[type=password]')
if (pwField) {
  await p.type('input[type=password]', PASSWORD)
  buttons = await p.$$('button')
  for (const btn of buttons) { if ((await p.evaluate(e=>e.textContent.trim(), btn)) === 'Sign in') { await btn.click(); break } }
}
await new Promise(r => setTimeout(r, 2500))

// navigate to the bb-sso org page and look for admin-only controls (SSO/SCIM/Policies tabs, invite button, etc.)
await p.goto('https://cinderous-overfamiliar-sanford.ngrok-free.dev/#/org/bb-sso', { waitUntil: 'networkidle2', timeout: 45000 })
await new Promise(r => setTimeout(r, 1500))
const orgPage = await p.evaluate(() => ({
  bodyText: document.body.innerText.slice(0, 1500),
  buttons: [...document.querySelectorAll('button,a')].map(e => e.textContent.trim()).filter(Boolean),
}))
console.log(JSON.stringify(orgPage, null, 1))

// also directly try the SSO settings route as a member (should the UI even render it, and does the API 403/404 it)
await p.goto('https://cinderous-overfamiliar-sanford.ngrok-free.dev/#/org/bb-sso/sso', { waitUntil: 'networkidle2', timeout: 45000 })
await new Promise(r => setTimeout(r, 1500))
const ssoPage = await p.evaluate(() => document.body.innerText.slice(0, 500))
console.log("SSO PAGE AS MEMBER:", JSON.stringify(ssoPage))

// check viewport at 375px width for horizontal overflow
await p.setViewport({ width: 375, height: 700 })
await p.goto('https://cinderous-overfamiliar-sanford.ngrok-free.dev/#/org/bb-sso', { waitUntil: 'networkidle2', timeout: 45000 })
await new Promise(r => setTimeout(r, 1500))
const overflow = await p.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  clientWidth: document.documentElement.clientWidth,
  hasHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
}))
console.log("375px layout:", JSON.stringify(overflow))

await b.close()
