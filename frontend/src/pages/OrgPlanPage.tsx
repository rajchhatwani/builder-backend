import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { OrgPlan, PlanInfo } from '../api/types'
import { useUi } from '../components/Ui'

function money(cents: number): string {
  return cents ? `$${(cents / 100).toFixed(cents % 100 ? 2 : 0)}/mo` : 'Free'
}

function limit(cap: number | null): string {
  return cap === null ? 'unlimited' : String(cap)
}

/** One usage counter: "3 of 5", amber at 80 %, red when full. */
function UsageCard({ label, used, cap, note }: { label: string; used: number; cap: number | null; note?: string }) {
  const ratio = cap === null ? 0 : cap === 0 ? 1 : used / cap
  const tone = cap !== null && used >= cap ? 'status-error' : ratio >= 0.8 ? 'status-warn' : ''
  return (
    <div className={`card stat-card ${tone}`}>
      <div className="stat-value">
        {used}
        <span className="muted"> / {limit(cap)}</span>
      </div>
      <div className="stat-label">{label}</div>
      {cap !== null && cap > 0 && (
        <progress value={Math.min(used, cap)} max={cap} aria-label={`${label}: ${used} of ${cap}`} />
      )}
      {note && <div className="muted small-text">{note}</div>}
    </div>
  )
}

function UpgradeOption({ plan, busy, onChoose }: { plan: PlanInfo; busy: boolean; onChoose: () => void }) {
  return (
    <div className="card">
      <h3>{plan.display_name}</h3>
      <p className="stat-value">{money(plan.monthly_price_usd)}</p>
      <ul className="small-text">
        <li>{limit(plan.max_seats)} seats</li>
        <li>{limit(plan.max_projects)} projects</li>
        <li>{limit(plan.max_api_tokens)} API tokens per member</li>
        <li>{plan.allow_mcp ? `${limit(plan.max_mcp_tokens)} MCP tokens` : 'No MCP access'}</li>
        {plan.allow_sso && <li>Single sign-on</li>}
      </ul>
      <button disabled={busy} onClick={onChoose}>
        {busy ? 'Opening checkout…' : `Upgrade to ${plan.display_name}`}
      </button>
    </div>
  )
}

/**
 * `#/org/<slug>/plan` — current plan, usage counters and upgrade options. `embedded`: shown as
 * a tab inside the org console, so the title is a section heading rather than the page title.
 */
export function OrgPlanPage({ slug, embedded = false }: { slug: string; embedded?: boolean }) {
  const { toast } = useUi()
  const [data, setData] = useState<OrgPlan | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyPlan, setBusyPlan] = useState<string | null>(null)
  const [canManage, setCanManage] = useState(false)
  const [portalBusy, setPortalBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [plan, orgs] = await Promise.all([api.orgPlan(slug), api.listOrgs()])
      setData(plan)
      const me = orgs.items.find((o) => o.slug === slug)
      setCanManage(me?.my_role === 'owner' || me?.my_role === 'admin')
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server.")
    }
  }, [slug])

  useEffect(() => {
    load()
  }, [load])

  // Coming back from Stripe Checkout. The plan itself changes once Stripe confirms payment.
  useEffect(() => {
    const result = new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('checkout')
    if (result === 'success') toast('Payment received. Your plan updates as soon as Stripe confirms it.')
    if (result === 'cancel') toast('Checkout cancelled. Nothing was charged.', 'danger')
  }, [toast])

  async function upgrade(planId: string) {
    setBusyPlan(planId)
    try {
      const session = await api.startCheckout(slug, planId)
      window.location.assign(session.url) // Stripe-hosted; card details never touch us
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
      setBusyPlan(null)
    }
  }

  async function manageBilling() {
    setPortalBusy(true)
    try {
      const { url } = await api.openBillingPortal(slug)
      window.location.assign(url) // Stripe-hosted Billing Portal
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Can't reach the server.", 'danger')
      setPortalBusy(false)
    }
  }

  if (error) return <div role="alert" data-variant="danger">{error}</div>
  if (!data) return <p className="empty-state">Loading…</p>

  const { plan, subscription, usage } = data
  const seatNote = usage.pending_invites ? `includes ${usage.pending_invites} pending invite(s)` : undefined
  // A live Stripe subscription changes plan in the Billing Portal, never via a second Checkout.
  const paying = data.portal_available && subscription.status !== 'canceled'
  const manageButton =
    data.portal_available && canManage ? (
      <button className="outline" disabled={portalBusy} onClick={manageBilling}>
        {portalBusy ? 'Opening billing…' : 'Manage billing'}
      </button>
    ) : null

  return (
    <>
      <div className="page-header">
        <div>
          {embedded ? <h2>Plan & usage</h2> : <h1>Plan & usage</h1>}
          <p>
            <strong>{plan.display_name}</strong> · {money(plan.monthly_price_usd)} ·{' '}
            <span className={subscription.status === 'active' ? 'status-ok' : 'status-warn'}>{subscription.status}</span>
          </p>
        </div>
        {manageButton}
      </div>

      {subscription.status === 'past_due' && (
        <div role="alert" data-variant="danger">
          The last payment failed. New members and projects are paused until billing is fixed.
          {canManage && data.portal_available
            ? ' Update the payment method under Manage billing.'
            : ' Ask an owner or admin to update the payment method.'}
        </div>
      )}

      <div className="stat-grid">
        <UsageCard label="Seats" used={usage.seats_used + usage.pending_invites} cap={usage.seats_cap} note={seatNote} />
        <UsageCard label="Projects" used={usage.projects_used} cap={usage.projects_cap} />
        <UsageCard label="Your API tokens" used={usage.api_tokens_used} cap={usage.api_tokens_cap} note="per member" />
        <UsageCard label="MCP tokens" used={usage.mcp_tokens_used} cap={usage.mcp_tokens_cap} note="whole organization" />
      </div>
      {(subscription.seat_override !== null || subscription.project_override !== null) && (
        <p className="muted small-text">Your limits include an extra allowance granted by support.</p>
      )}

      <h2>Upgrade</h2>
      {!data.checkout_available ? (
        <p className="muted">Online upgrades aren't available on this platform. Contact support to change plans.</p>
      ) : !canManage ? (
        <p className="muted">Only owners and admins of this organization can change its plan. Ask one of them.</p>
      ) : paying ? (
        <p className="muted">Change or cancel your plan, or update the card, under Manage billing.</p>
      ) : data.upgrades.length === 0 ? (
        <p className="muted">You're on the largest plan sold online. Contact sales for Enterprise.</p>
      ) : (
        <div className="stat-grid">
          {data.upgrades.map((p) => (
            <UpgradeOption key={p.id} plan={p} busy={busyPlan === p.id} onChoose={() => upgrade(p.id)} />
          ))}
        </div>
      )}
    </>
  )
}
