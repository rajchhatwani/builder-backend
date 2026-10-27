import { useEffect, useState } from 'react'
import { onOrgMfaRequired } from '../api/client'
import type { OrgMfaDetail } from '../api/types'
import { useAuth } from './AuthProvider'
import { Modal } from './Modal'

/**
 * Listens for 403 `org_mfa_required` from any API call: the org requires two-factor and this
 * session was started without it (§4.4). Without TOTP the way out is turning it on; with TOTP
 * on, it's signing in again with the code. Mounted once, next to the 402 and 423 prompts.
 */
export function OrgMfaPrompt() {
  const { signOut } = useAuth()
  const [hit, setHit] = useState<{ message: string; detail: OrgMfaDetail | null } | null>(null)

  useEffect(() => onOrgMfaRequired((error, detail) => setHit({ message: error.message, detail })), [])

  if (!hit) return null
  const close = () => setHit(null)
  const org = hit.detail?.organization_name ?? 'This organization'
  const hasTotp = hit.detail?.mfa_enabled ?? false

  return (
    <Modal open onClose={close}>
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <header>
          <h3>{org} requires two-factor authentication</h3>
          <p>
            {hasTotp
              ? 'You have two-factor turned on, but this session was started with only a password. Sign in again and enter your code.'
              : 'Turn on two-factor authentication in your account, then sign in again with your code to open its projects.'}
          </p>
        </header>
        <div>
          <p className="muted small-text">
            Your other organizations and projects keep working. An organization admin set this policy.
          </p>
        </div>
        <footer>
          <button type="button" className="outline" onClick={close}>
            Not now
          </button>
          {hasTotp ? (
            <button
              type="button"
              onClick={() => {
                close()
                signOut()
              }}
            >
              Sign out and sign in again
            </button>
          ) : (
            <a className="button" href="#/account" onClick={close}>
              Turn on two-factor
            </a>
          )}
        </footer>
      </form>
    </Modal>
  )
}
