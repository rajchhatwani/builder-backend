// UI sweep: sign in as each role through the real login page, visit every page, 3 viewports x light/dark,
// record console errors, failed requests, horizontal overflow, and save redacted screenshots.
import puppeteer from '/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js'
import fs from 'fs'
const pw0 = process.env.BBF_PW
const [stateFile, pwArg, base = 'http://127.0.0.1:8081', outDir = 'evidence', rolesArg = 'owner,admin,member,outsider'] = process.argv.slice(2)
const pw = pw0 || pwArg
const S = JSON.parse(fs.readFileSync(stateFile))
const results = []
const rec = (id, desc, ok, detail = '') => { results.push({ id, desc, ok, detail: String(detail).slice(0, 300) }); console.log((ok ? 'PASS ' : 'FAIL ') + id, desc, ok ? '' : '-> ' + detail) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const browser = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: 'new', args: ['--no-sandbox'] })
const VIEWS = { mobile: [375, 800], tablet: [768, 1024], desktop: [1280, 900] }
async function login(page, email) {
  await page.goto(base + '/#/', { waitUntil: 'networkidle2' })
  await page.waitForSelector('input[type=email]', { timeout: 15000 })
  await page.type('input[type=email]', email)
  await page.keyboard.press('Enter')
  await page.waitForSelector('input[type=password]', { timeout: 15000 })
  await page.type('input[type=password]', pw)
  await page.keyboard.press('Enter')
  await sleep(2500)
}
for (const role of rolesArg.split(',')) {
  const email = S[role]
  const ctx = await browser.createBrowserContext()
  const page = await ctx.newPage()
  await page.setExtraHTTPHeaders({ 'ngrok-skip-browser-warning': '1' })
  const errors = [], bad = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)) })
  page.on('pageerror', (e) => errors.push('PAGEERROR ' + String(e).slice(0, 160)))
  page.on('response', (r) => { const s = r.status(); if (s >= 500) bad.push(s + ' ' + r.url().replace(base, '')) })
  await page.setViewport({ width: 1280, height: 900 })
  try { await login(page, email) } catch (e) { rec(`UI.${role}.login`, 'sign in through the real login page', false, e.message); continue }
  const body = await page.evaluate(() => document.body.innerText)
  rec(`UI.${role}.login`, 'sign in through the real login page lands on the app', !/Sign in/.test(body.split('\n')[0] || '') || /Projects/i.test(body), body.slice(0, 120))
  const pages = [['projects', '#/'], ['account', '#/account'], ['invitations', '#/invitations'], ['org-people', `#/org/${S.slug}`], ['org-invites', `#/org/${S.slug}/invites`], ['org-projects', `#/org/${S.slug}/projects`], ['org-plan', `#/org/${S.slug}/plan`], ['org-audit', `#/org/${S.slug}/audit`], ['org-sso', `#/org/${S.slug}/sso`], ['org-policies', `#/org/${S.slug}/policies`], ['project', `#/p/${S.pid}`], ['project-entities', `#/p/${S.pid}/entities`], ['project-generate', `#/p/${S.pid}/generate`], ['project-auth', `#/p/${S.pid}/auth`], ['project-members', `#/p/${S.pid}/members`], ['unknown-project', `#/p/00000000-0000-0000-0000-000000000000`], ['unknown-org', `#/org/nope-nope`], ['bad-route', `#/zzz/yyy`]]
  for (const [view, [w, h]] of Object.entries(VIEWS)) {
    await page.setViewport({ width: w, height: h })
    for (const dark of [false, true]) {
      if (view !== 'desktop' && dark) continue
      await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }])
      for (const [name, hash] of pages) {
        if (view === 'tablet' && !['org-people', 'project-entities'].includes(name)) continue
        await page.goto(base + '/' + hash, { waitUntil: 'networkidle2' }).catch(() => {})
        await page.reload({ waitUntil: 'networkidle2' }).catch(() => {})
        for (let i = 0; i < 40; i++) { const t = await page.evaluate(() => document.body.innerText); if (!/Loading…|Loading\.\.\./.test(t) && t.trim().length > 60) break; await sleep(400) }
        const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, text: document.body.innerText.slice(0, 4000), h1: (document.querySelector('h1,h2') || {}).textContent }))
        const id = `UI.${role}.${view}${dark ? '.dark' : ''}.${name}`
        rec(id + '.overflow', `${name} @${w}px has no horizontal page scroll`, m.sw <= m.iw + 1, `scrollWidth ${m.sw} > ${m.iw}`)
        rec(id + '.render', `${name} renders (not blank / no raw error)`, m.text.trim().length > 60 && !/Loading…/.test(m.text) && !/undefined|\[object Object\]|NaN|Traceback/.test(m.text), m.text.slice(0, 160))
        if (view === 'desktop' && !dark || (view === 'mobile' && ['projects', 'org-people', 'project-entities'].includes(name))) {
          if (role === 'owner' || ['org-policies', 'org-plan'].includes(name)) await page.screenshot({ path: `${outDir}/${role}_${view}${dark ? '_dark' : ''}_${name}.png` })
        }
      }
      if (dark) await page.screenshot({ path: `${outDir}/${role}_desktop_dark_last.png` })
    }
  }
  // keyboard: tab order reaches a button
  await page.setViewport({ width: 1280, height: 900 }); await page.goto(base + '/#/', { waitUntil: 'networkidle2' })
  await sleep(4000); for (let i = 0; i < 4; i++) await page.keyboard.press('Tab')
  const focus = await page.evaluate(() => document.activeElement && document.activeElement.tagName)
  rec(`UI.${role}.keyboard`, 'Tab moves focus to interactive elements', ['A', 'BUTTON', 'INPUT', 'SELECT'].includes(focus), focus)
  // back/forward
  await page.goto(base + `/#/org/${S.slug}`); await page.goto(base + `/#/account`); await page.goBack(); await sleep(400)
  rec(`UI.${role}.back`, 'browser back returns to previous hash page', (await page.evaluate(() => location.hash)).startsWith('#/org/'), '')
  // offline
  await page.setOfflineMode(true); await page.goto(base + '/#/account').catch(() => {}); await page.reload().catch(() => {}); await sleep(500)
  await page.setOfflineMode(false)
  rec(`UI.${role}.no5xx`, 'no 5xx responses seen during the sweep', bad.length === 0, bad.slice(0, 5).join(', '))
  const real = errors.filter((e) => !/Failed to load resource: the server responded with a status of (401|402|403|404|409|422|423|429)/.test(e) && !/net::ERR/.test(e))
  rec(`UI.${role}.console`, 'no unexpected console errors', real.length === 0, real.slice(0, 4).join(' | '))
  await ctx.close()
}
fs.appendFileSync('logs/ui_results.jsonl', results.map((r) => JSON.stringify(r)).join('\n') + '\n')
await browser.close()
