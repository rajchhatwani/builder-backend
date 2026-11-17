import puppeteer from '/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js'
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage(); await p.setExtraHTTPHeaders({ 'ngrok-skip-browser-warning': '1' })
p.on('response', r => { if (r.status()>=400) console.log(r.status(), r.url().slice(0,100)) })
await p.goto('https://cinderous-overfamiliar-sanford.ngrok-free.dev/#/', { waitUntil: 'networkidle2' })
await p.type('input[type=email]', 'x@y.com')
await p.keyboard.press('Enter'); await new Promise(r=>setTimeout(r,3000))
console.log(await p.evaluate(()=>document.body.innerText.slice(0,300)))
await b.close()
