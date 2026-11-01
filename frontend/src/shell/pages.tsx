import type { ReactNode } from 'react'
import { SECTIONS, type Section, type V2Section } from '../components/Sidebar'

export type AnySection = Section | V2Section

/** Pages that exist only in the new shell. Their ids are valid in #/p/<id>/<section> (see parseHash). */
export const V2_SECTIONS: { id: V2Section; label: string; icon: ReactNode }[] = [
  {
    id: 'machines',
    label: 'State machines',
    icon: (
      <>
        <circle cx="5" cy="6" r="2.5" />
        <circle cx="19" cy="6" r="2.5" />
        <circle cx="12" cy="18" r="2.5" />
        <path d="M7.5 6h9" />
        <path d="M17.5 8l-4 8" />
        <path d="M6.5 8l4 8" />
      </>
    ),
  },
  {
    id: 'rules',
    label: 'Rules',
    icon: (
      <>
        <path d="M5 4h14v16H5z" />
        <path d="M8 9h8M8 13h5" />
        <path d="M15 16l1.5 1.5L19 15" />
      </>
    ),
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: (
      <>
        <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
        <circle cx="16" cy="7" r="2" />
        <circle cx="8" cy="17" r="2" />
      </>
    ),
  },
  {
    id: 'hooks',
    label: 'Hooks',
    icon: (
      <>
        <path d="M9 4v9a4 4 0 1 0 8 0v-1" />
        <circle cx="9" cy="3.5" r="1.5" />
        <path d="M14 10l3 3 3-3" />
      </>
    ),
  },
  {
    id: 'seed',
    label: 'Seed data',
    icon: (
      <>
        <ellipse cx="12" cy="6" rx="7" ry="3" />
        <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
        <path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
      </>
    ),
  },
  {
    id: 'forms',
    label: 'Forms preview',
    icon: (
      <>
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <path d="M8 9h8M8 13h8M8 17h4" />
      </>
    ),
  },
  {
    id: 'history',
    label: 'Change history',
    icon: (
      <>
        <path d="M3 12a9 9 0 1 0 3-6.7" />
        <path d="M3 4v5h5" />
        <path d="M12 8v4l3 2" />
      </>
    ),
  },
  {
    id: 'timeline',
    label: 'History timeline',
    icon: (
      <>
        <path d="M6 4v16" />
        <circle cx="6" cy="7" r="2" />
        <circle cx="6" cy="17" r="2" />
        <path d="M11 7h8M11 17h6" />
      </>
    ),
  },
  {
    id: 'notifications',
    label: 'Notifications',
    icon: (
      <>
        <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
        <path d="M10 20a2 2 0 0 0 4 0" />
      </>
    ),
  },
  {
    id: 'webhooks',
    label: 'Webhooks',
    icon: (
      <>
        <circle cx="6" cy="17" r="2.5" />
        <circle cx="18" cy="17" r="2.5" />
        <circle cx="12" cy="6" r="2.5" />
        <path d="M12 8.5l-4.5 6.5M9 17h6M13.5 8.7l3.7 6.3" />
      </>
    ),
  },
  {
    id: 'providers',
    label: 'Provider integrations',
    icon: (
      <>
        <path d="M9 3v5M15 3v5" />
        <path d="M6 8h12v4a6 6 0 0 1-12 0z" />
        <path d="M12 18v3" />
      </>
    ),
  },
  {
    id: 'jobs',
    label: 'Jobs and schedules',
    icon: (
      <>
        <circle cx="12" cy="13" r="8" />
        <path d="M12 9v4l3 2" />
        <path d="M9 3h6" />
      </>
    ),
  },
  {
    id: 'workers',
    label: 'Workers and queues',
    icon: (
      <>
        <rect x="3" y="4" width="18" height="6" rx="1.5" />
        <rect x="3" y="14" width="18" height="6" rx="1.5" />
        <path d="M7 7h.01M7 17h.01" />
      </>
    ),
  },
  {
    id: 'workflows',
    label: 'Workflows',
    icon: (
      <>
        <rect x="3" y="3" width="6" height="5" rx="1" />
        <rect x="15" y="9" width="6" height="5" rx="1" />
        <rect x="3" y="16" width="6" height="5" rx="1" />
        <path d="M9 5.5h3v6h3M6 8v8" />
      </>
    ),
  },
]

export function findSection(id: AnySection) {
  return SECTIONS.find((s) => s.id === id) ?? V2_SECTIONS.find((s) => s.id === id)
}
