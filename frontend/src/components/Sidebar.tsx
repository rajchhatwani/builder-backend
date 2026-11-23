import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { notifyOrgsChanged, onOrgsChanged } from '../api/orgEvents'
import type { Organization } from '../api/types'
import { NewOrgDialog } from './NewOrgDialog'
import { useUi } from './Ui'

export type Section =
  | 'overview'
  | 'model'
  | 'auth'
  | 'keycloak'
  | 'payments'
  | 'storage'
  | 'access'
  | 'observability'
  | 'deployment'
  | 'documents'
  | 'integrations'
  | 'generate'

/** Pages beyond the twelve classic sections. */
export type V2Section = 'machines' | 'rules' | 'permissions' | 'specdiff' | 'import' | 'customfields' | 'events' | 'apiedge' | 'hookeffects' | 'notiftypes' | 'settings' | 'history' | 'hooks' | 'seed' | 'forms' | 'timeline' | 'notifications' | 'webhooks' | 'providers' | 'jobs' | 'workers' | 'workflows' | 'traces' | 'metrics' | 'suite' | 'intake' | 'plan' | 'build' | 'approvals' | 'see' | 'search' | 'dependencies' | 'ledger' | 'map' | 'bookings' | 'agentactions' | 'compliance' | 'apikeys' | 'apps' | 'upgrades' | 'invoices' | 'payouts' | 'reconciliation' | 'bookingadmin' | 'ledgersettings' | 'currencysettings' | 'reconsettings' | 'invoicingsettings' | 'bookingsettings' | 'places' | 'matching' | 'prediction' | 'routing' | 'aiusage' | 'knowledge' | 'evals' | 'agentruns' | 'geosettings' | 'locationsettings' | 'matchingsettings' | 'predictionsettings' | 'aigatewaysettings' | 'aidocssettings' | 'knowledgesettings' | 'agentssettings' | 'evalssettings'

export const SECTIONS: { id: Section; label: string; icon: ReactNode }[] = [
  {
    id: 'overview',
    label: 'Overview',
    icon: <path d="M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z" />,
  },
  {
    id: 'model',
    label: 'Data model',
    icon: (
      <>
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
        <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
      </>
    ),
  },
  {
    id: 'auth',
    label: 'Authentication',
    icon: (
      <>
        <rect x="4" y="11" width="16" height="10" rx="2" />
        <path d="M8 11V7a4 4 0 0 1 8 0v4" />
      </>
    ),
  },
  {
    id: 'keycloak',
    label: 'Keycloak',
    icon: (
      <>
        <circle cx="8" cy="15" r="4" />
        <path d="M10.8 12.2L20 3" />
        <path d="M16 7l3 3" />
        <path d="M13.5 9.5l2 2" />
      </>
    ),
  },
  {
    id: 'payments',
    label: 'Payments',
    icon: (
      <>
        <rect x="2" y="5" width="20" height="14" rx="2" />
        <path d="M2 10h20" />
        <path d="M6 15h4" />
      </>
    ),
  },
  {
    id: 'storage',
    label: 'File uploads',
    icon: (
      <>
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
        <path d="M14 3v5h5" />
        <path d="M12 17v-5" />
        <path d="M9.5 14.5L12 12l2.5 2.5" />
      </>
    ),
  },
  {
    id: 'access',
    label: 'Authorization',
    icon: (
      <>
        <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />
        <path d="M9 12l2 2 4-4" />
      </>
    ),
  },
  {
    id: 'observability',
    label: 'Observability',
    icon: (
      <>
        <path d="M3 12h4l3-8 4 16 3-8h4" />
      </>
    ),
  },
  {
    id: 'documents',
    label: 'Documents',
    icon: (
      <>
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
        <path d="M14 3v5h5" />
        <path d="M9 13h6" />
        <path d="M9 17h4" />
      </>
    ),
  },
  {
    id: 'deployment',
    label: 'Deploy',
    icon: (
      <>
        <path d="M12 3l4 4-4 4" />
        <path d="M20 7H8a4 4 0 0 0 0 8h2" />
        <path d="M6 21h12" />
      </>
    ),
  },
  {
    id: 'integrations',
    label: 'Integrations',
    icon: (
      <>
        <circle cx="6" cy="6" r="3" />
        <circle cx="18" cy="6" r="3" />
        <circle cx="12" cy="18" r="3" />
        <path d="M6 9v2a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9" />
        <path d="M12 13v2" />
      </>
    ),
  },
  {
    id: 'generate',
    label: 'Generate',
    icon: (
      <>
        <path d="M12 3v12" />
        <path d="M7 10l5 5 5-5" />
        <path d="M4 21h16" />
      </>
    ),
  },
]

export function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export function link(path: string): string {
  return `#${path}`
}

/** The signed-in user's organizations, refreshed whenever one is created, joined or left. */
function useMyOrgs(): { orgs: Organization[]; invites: number } {
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [invites, setInvites] = useState(0)
  const [version, setVersion] = useState(0)
  useEffect(() => onOrgsChanged(() => setVersion((v) => v + 1)), [])
  useEffect(() => {
    let cancelled = false
    api
      .listOrgs()
      .then((page) => !cancelled && setOrgs(page.items))
      .catch(() => undefined)
    api
      .myPendingInvitations()
      .then((page) => !cancelled && setInvites(page.total))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [version])
  return { orgs, invites }
}

export function orgLabel(org: Organization): string {
  return org.kind === 'personal' ? 'Personal' : org.name
}

/** Sidebar on the projects list, the account page and the org console. */
export function ProjectsSidebar() {
  const { orgs, invites } = useMyOrgs()
  const { toast } = useUi()
  const [creating, setCreating] = useState(false)
  const current = window.location.hash
  const onProjects = current === '' || current === '#' || current === '#/'
  return (
    <nav>
      <ul>
        <li>
          <a href={link('/')} aria-current={onProjects ? 'page' : undefined}>
            <Icon>
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
            </Icon>
            Projects
          </a>
        </li>
        {invites > 0 && (
          <li>
            <a href={link('/invitations')} aria-current={current.startsWith('#/invit') ? 'page' : undefined}>
              <Icon>
                <rect x="3" y="5" width="18" height="14" rx="2" />
                <path d="M3 7l9 6 9-6" />
              </Icon>
              <span>Invitations</span>
              <span className="count-badge">{invites}</span>
            </a>
          </li>
        )}
      </ul>
      <p className="muted small-text sidebar-heading">Organizations</p>
      <ul>
        {orgs.map((org) => {
          const href = link(`/org/${encodeURIComponent(org.slug)}`)
          const active = current === href || current.startsWith(`${href}/`) || current.startsWith(`${href}?`)
          return (
            <li key={org.id}>
              <a
                href={href}
                aria-current={active ? 'page' : undefined}
                title={
                  org.deletion_scheduled_for
                    ? `${orgLabel(org)}: scheduled for deletion, locked`
                    : `${orgLabel(org)}: people, projects and plan`
                }
              >
                <Icon>
                  {org.kind === 'personal' ? (
                    <>
                      <circle cx="12" cy="8" r="4" />
                      <path d="M4 21a8 8 0 0 1 16 0" />
                    </>
                  ) : (
                    <>
                      <circle cx="9" cy="8" r="3.5" />
                      <circle cx="17" cy="9" r="2.5" />
                      <path d="M2 21a7 7 0 0 1 14 0" />
                      <path d="M16 15a5 5 0 0 1 6 5" />
                    </>
                  )}
                </Icon>
                <span>{orgLabel(org)}</span>
                {org.deletion_scheduled_for && <span className="badge badge-muted sidebar-locked">locked</span>}
              </a>
            </li>
          )
        })}
        <li>
          <a
            href={link('/')}
            onClick={(e) => {
              e.preventDefault()
              setCreating(true)
            }}
          >
            <Icon>
              <path d="M12 5v14" />
              <path d="M5 12h14" />
            </Icon>
            <span>New organization</span>
          </a>
        </li>
      </ul>
      <NewOrgDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(org) => {
          setCreating(false)
          notifyOrgsChanged()
          toast(`Created ${org.name} on the Free plan. Upgrade it from its Plan tab to invite people.`)
          window.location.hash = link(`/org/${encodeURIComponent(org.slug)}`)
        }}
      />
    </nav>
  )
}
