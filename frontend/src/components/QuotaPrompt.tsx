import { useEffect, useState } from 'react'
import { onQuotaExceeded } from '../api/client'
import type { QuotaDetail } from '../api/types'
import { Modal } from './Modal'

const RESOURCE_LABEL: Record<QuotaDetail['resource'], string> = {
  seats: 'seats',
  projects: 'projects',
  api_tokens: 'API tokens per member',
  mcp_tokens: 'MCP tokens',
  sso: 'single sign-on',
  scim: 'SCIM provisioning',
}

/**
 * Listens for 402 quota refusals from any API call and offers the way out: the
 * organization's Plan page. Mounted once in the customer app.
 */
export function QuotaPrompt() {
  const [hit, setHit] = useState<{ message: string; detail: QuotaDetail | null } | null>(null)

  useEffect(() => onQuotaExceeded((error, detail) => setHit({ message: error.message, detail })), [])

  if (!hit) return null
  const { detail } = hit
  const planHref = detail?.organization_slug ? `#/org/${detail.organization_slug}/plan` : null
  const pastDue = detail?.reason === 'past_due'
  const feature = detail?.reason === 'feature'

  return (
    <Modal open onClose={() => setHit(null)}>
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <header>
          <h3>{pastDue ? 'Payment needed' : feature ? 'Not in this plan' : 'Plan limit reached'}</h3>
          <p>
            {pastDue
              ? `The organization's last payment failed, so new ${RESOURCE_LABEL[detail.resource]} are paused. Everything you already have keeps working.`
              : feature
                ? `The ${detail.plan} plan doesn't include ${RESOURCE_LABEL[detail.resource]}.`
                : detail
                ? `The ${detail.plan} plan includes ${detail.cap} ${RESOURCE_LABEL[detail.resource]}, and all of them are in use.`
                : hit.message}
          </p>
        </header>
        <div>
          <p className="muted small-text">
            {pastDue
              ? 'Owners and admins can update the payment method from the Plan page.'
              : feature
                ? "Owners and admins can upgrade the organization's plan."
                : "Free one up, or upgrade the organization's plan. Owners and admins can upgrade."}
          </p>
        </div>
        <footer>
          <button type="button" className="outline" onClick={() => setHit(null)}>
            Not now
          </button>
          {planHref && (
            <a className="button" href={planHref} onClick={() => setHit(null)}>
              See plans
            </a>
          )}
        </footer>
      </form>
    </Modal>
  )
}
