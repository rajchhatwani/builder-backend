// Dump visible inputs/buttons/headings of a page (for building UI scripts). Usage: node probe.mjs <url> [wait-ms]
import puppeteer from '/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js'
const [url, wait = '2500'] = process.argv.slice(2)
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage()
await p.setExtraHTTPHeaders({ 'ngrok-skip-browser-warning': '1' })
await p.goto(url, { waitUntil: 'networkidle2', timeout: 45000 })
await new Promise((r) => setTimeout(r, Number(wait)))
console.log(JSON.stringify(await p.evaluate(() => ({
  url: location.origin + location.pathname + location.hash.slice(0, 40),
  title: document.title,
  headings: [...document.querySelectorAll('h1,h2')].map((e) => e.textContent.trim()).slice(0, 5),
  inputs: [...document.querySelectorAll('input')].map((e) => ({ type: e.type, name: e.name, id: e.id, ph: e.placeholder, ac: e.autocomplete })),
  buttons: [...document.querySelectorAll('button,a[role=button],input[type=submit]')].map((e) => (e.textContent || e.value).trim()).slice(0, 12),
})), null, 1))
await b.close()
