import { useId, useState } from 'react'
import { api } from '../../api/client'
import type { AdminOrg } from '../../api/types'
import { ConfirmPrompt } from '../../components/ConfirmPrompt'

/** Platform admins free an SSO domain claim (verified or pending) so another organization can verify it. */
export function SsoDomainsPage({ readOnly }: { readOnly: boolean }) {
  const [domain, setDomain] = useState('')
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [released, setReleased] = useState<{ domain: string; org: AdminOrg } | null>(null)
  const domainId = useId()
  const reasonId = useId()
  const clean = domain.trim().toLowerCase()
  const ready = clean.length > 0 && reason.trim().length > 0

  const release = async () => {
    setBusy(true); setError(null)
    try {
      const org = await api.adminReleaseSsoDomain(clean, reason.trim())
      setReleased({ domain: clean, org }); setConfirming(false); setDomain(''); setReason('')
    } catch (e) { setError(e instanceof Error ? e.message : 'The domain could not be released') } finally { setBusy(false) }
  }

  if (readOnly) return <p className="empty-state" role="alert" data-testid="sso-readonly">Releasing a domain is for platform admins.</p>
  return (
    <>
      <div className="page-header">
        <div>
          <h1>SSO domains</h1>
          <p>Free a domain claim so another organization can verify it. If it was the holder's last verified domain, their single sign-on is switched off. This is recorded in the audit log.</p>
        </div>
      </div>
      <form className="card" aria-label="Release an SSO domain" onSubmit={(e) => { e.preventDefault(); if (ready) setConfirming(true) }}>
        <div className="field"><label htmlFor={domainId}>Domain</label><input id={domainId} value={domain} placeholder="example.com" maxLength={253} onChange={(e) => setDomain(e.target.value)} data-testid="sso-domain" /></div>
        <div className="field"><label htmlFor={reasonId}>Reason</label><input id={reasonId} value={reason} maxLength={255} onChange={(e) => setReason(e.target.value)} data-testid="sso-reason" /></div>
        <button type="submit" data-variant="danger" disabled={!ready || busy || confirming} data-testid="sso-release">Release domain</button>
      </form>
      {confirming && (
        <ConfirmPrompt testId="sso-confirm" title={`Release ${clean}?`} confirmLabel="Release domain" busy={busy} onConfirm={() => void release()} onCancel={() => setConfirming(false)}>
          <p>The organization holding this claim loses it, and its sign-in with this domain stops working.</p>
        </ConfirmPrompt>
      )}
      {error && <p role="alert" data-testid="sso-error">{error}</p>}
      {released && <p role="status" data-testid="sso-done">Released {released.domain}. It was held by {released.org.name}.</p>}
    </>
  )
}
