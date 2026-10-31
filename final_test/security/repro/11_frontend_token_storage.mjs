import puppeteer from '/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js'
const EMAIL = process.argv[2]
const PASSWORD = process.argv[3]
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage()
await p.setExtraHTTPHeaders({ 'ngrok-skip-browser-warning': '1' })
const netLeaks = []
p.on('request', req => { const u = req.url(); if (/access_token|refresh_token|password=/.test(u)) netLeaks.push(u.slice(0,200)) })
const consoleMsgs = []
p.on('console', msg => consoleMsgs.push(msg.text().slice(0,200)))

await p.goto('https://cinderous-overfamiliar-sanford.ngrok-free.dev/#/login', { waitUntil: 'networkidle2', timeout: 45000 })
await new Promise(r => setTimeout(r, 1500))
await p.type('input[type=email]', EMAIL)
let buttons = await p.$$('button')
for (const btn of buttons) { if ((await p.evaluate(e=>e.textContent.trim(), btn)) === 'Continue') { await btn.click(); break } }
await new Promise(r => setTimeout(r, 2000))
// click "Sign in with a password instead" if offered (SSO-domain fallback)
let links = await p.$$('a,button')
for (const el of links) {
  const t = await p.evaluate(e=>e.textContent.trim(), el)
  if (t === 'Sign in with a password instead') { await el.click(); break }
}
await new Promise(r => setTimeout(r, 1500))
const pwField = await p.$('input[type=password]')
if (pwField) {
  await p.type('input[type=password]', PASSWORD)
  buttons = await p.$$('button')
  for (const btn of buttons) { if ((await p.evaluate(e=>e.textContent.trim(), btn)) === 'Sign in') { await btn.click(); break } }
}
await new Promise(r => setTimeout(r, 3000))

const storage = await p.evaluate(() => {
  const ls = {}; for (let i=0;i<localStorage.length;i++){ const k=localStorage.key(i); ls[k]=localStorage.getItem(k) }
  const ss = {}; for (let i=0;i<sessionStorage.length;i++){ const k=sessionStorage.key(i); ss[k]=sessionStorage.getItem(k) }
  return { localStorage: ls, sessionStorage: ss, url: location.href, bodyStart: document.body.innerText.slice(0,150) }
})
const cookies = await b.cookies ? await b.cookies() : await p.cookies("https://cinderous-overfamiliar-sanford.ngrok-free.dev")
console.log(JSON.stringify({
  storage,
  cookies: cookies.map(c => ({ name: c.name, httpOnly: c.httpOnly, secure: c.secure, sameSite: c.sameSite, path: c.path })),
  netLeaksCount: netLeaks.length, netLeaksSample: netLeaks.slice(0,3),
  consoleSample: consoleMsgs.filter(m => /token|password|secret/i.test(m)).slice(0,5),
}, null, 1))
await b.close()
