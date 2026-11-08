import puppeteer from '/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js'
import fs from 'fs'
const S = JSON.parse(fs.readFileSync('logs/ui_state.json')); const base = process.argv[2]
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage(); await p.setExtraHTTPHeaders({ 'ngrok-skip-browser-warning': '1' })
p.on('response', r => console.log(r.status(), r.request().method(), r.url().replace(base,'').slice(0,80)))
p.on('console', m => m.type()==='error' && console.log('CONSOLE', m.text().slice(0,200)))
await p.goto(base + '/#/', { waitUntil: 'networkidle2' })
await p.type('input[type=email]', S.owner); await p.keyboard.press('Enter')
await p.waitForSelector('input[type=password]'); await p.type('input[type=password]', process.env.BBF_PW); await p.keyboard.press('Enter')
await new Promise(r=>setTimeout(r,6000))
console.log('TEXT', (await p.evaluate(()=>document.body.innerText)).slice(0,300).replace(/\n/g,' | '))
await p.goto(base + '/#/account'); await p.reload({waitUntil:'networkidle2'}); await new Promise(r=>setTimeout(r,6000))
console.log('TEXT2', (await p.evaluate(()=>document.body.innerText)).slice(0,300).replace(/\n/g,' | '))
await b.close()
