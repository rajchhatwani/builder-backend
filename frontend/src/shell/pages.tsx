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
]

export function findSection(id: AnySection) {
  return SECTIONS.find((s) => s.id === id) ?? V2_SECTIONS.find((s) => s.id === id)
}
