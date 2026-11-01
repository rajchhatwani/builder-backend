// F2-2/F2-3: derive the Payments and Deployment form schemas from the committed OpenAPI snapshot (e2e/openapi.json),
// without running the backend. Rewrites #/components/schemas/X refs to #/$defs/X. The `x-ui` hints are hand-written.
// Run from frontend/:  node scripts/dump_openapi_form_schemas.mjs
import { readFileSync, writeFileSync } from 'node:fs'

const doc = JSON.parse(readFileSync('e2e/openapi.json', 'utf8'))
const comps = doc.components.schemas

function build(name, title) {
  const defs = {}
  const rewrite = (node) => {
    if (Array.isArray(node)) return node.map(rewrite)
    if (node && typeof node === 'object') {
      const out = {}
      for (const [k, v] of Object.entries(node)) {
        if (k === '$ref' && typeof v === 'string') {
          const n = v.replace('#/components/schemas/', '')
          if (!defs[n]) { defs[n] = null; defs[n] = rewrite(comps[n]) }
          out[k] = `#/$defs/${n}`
        } else out[k] = rewrite(v)
      }
      return out
    }
    return node
  }
  const root = rewrite(comps[name])
  root.title = title
  if (Object.keys(defs).length) root.$defs = defs
  delete root.properties.expected_version
  return root
}

const csv = { widget: 'csv' }
const pay = build('PaymentsConfigWrite', 'Payments')
pay['x-ui'] = { order: ['provider', 'payable', 'currencies', 'max_amount_minor', 'success_urls', 'cancel_urls', 'roles', 'refund_approval_threshold_minor', 'scale', 'security'] }
for (const k of ['currencies', 'success_urls', 'cancel_urls']) pay.properties[k]['x-ui'] = csv
for (const p of Object.values(pay.$defs.PaymentsRoles.properties)) p['x-ui'] = csv

const dep = build('DeploymentWrite', 'Deployment')
dep['x-ui'] = { order: ['enabled', 'cloud', 'region', 'github_repo', 'environments'] }
dep.properties.environments['x-ui'] = { itemLabel: 'Environment' }

writeFileSync('src/forms/schemas/payments.json', JSON.stringify(pay, null, 2) + '\n')
writeFileSync('src/forms/schemas/deployment.json', JSON.stringify(dep, null, 2) + '\n')
console.log('wrote payments, deployment')
