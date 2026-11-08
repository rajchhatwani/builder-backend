import { useEffect, useState } from 'react'
import { api, onOrgLocked } from '../api/client'
import { formatDeletionDate } from '../api/dates'
import type { Organization } from '../api/types'
import { Modal } from './Modal'

/**
 * Listens for 423 `org_deletion_pending` from any API call (org and project routes of an org
 * that is waiting for deletion) and explains it. The 423 doesn't say which org, so the
 * prompt looks up the signed-in user's locked orgs and links to them. Mounted once, next to
 * the 402 QuotaPrompt.
 */
export function OrgLockedPrompt() {
  const [hit, setHit] = useState<{ scheduledFor: string | null } | null>(null)
  const [locked, setLocked] = useState<Organization[]>([])

  useEffect(
    () =>
      onOrgLocked((_error, detail) => {
        setHit({ scheduledFor: detail?.deletion_scheduled_for ?? null })
        // The 423 names the org; fall back to looking it up for older backends.
        if (detail?.organization_slug) {
          setLocked([
            {
              id: detail.organization_id ?? detail.organization_slug,
              slug: detail.organization_slug,
              name: detail.organization_name ?? detail.organization_slug,
              deletion_scheduled_for: detail.deletion_scheduled_for,
            } as Organization,
          ])
          return
        }
        api
          .listOrgs()
          .then((page) => setLocked(page.items.filter((o) => o.deletion_scheduled_for)))
          .catch(() => setLocked([]))
      }),
    [],
  )

  if (!hit) return null
  const close = () => setHit(null)
  const onlyOne = locked.length === 1 ? locked[0] : null

  return (
    <Modal open onClose={close}>
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <header>
          <h3>This organization is scheduled for deletion</h3>
          <p>
            It will be deleted, with all its projects, on {formatDeletionDate(hit.scheduledFor)}. Until then it's
            locked: nothing in it can be opened or changed.
          </p>
        </header>
        <div>
          <p className="muted small-text">An owner can cancel the deletion from the organization's page to unlock it.</p>
          {locked.length > 1 && (
            <ul className="small-text">
              {locked.map((o) => (
                <li key={o.id}>
                  <a href={`#/org/${encodeURIComponent(o.slug)}`} onClick={close}>
                    {o.name}
                  </a>{' '}
                  — {formatDeletionDate(o.deletion_scheduled_for)}
                </li>
              ))}
            </ul>
          )}
        </div>
        <footer>
          <button type="button" className="outline" onClick={close}>
            Close
          </button>
          {onlyOne ? (
            <a className="button" href={`#/org/${encodeURIComponent(onlyOne.slug)}`} onClick={close}>
              Open {onlyOne.name}
            </a>
          ) : (
            <a className="button" href="#/" onClick={close}>
              Back to projects
            </a>
          )}
        </footer>
      </form>
    </Modal>
  )
}
