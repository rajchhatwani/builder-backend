import type { ReactNode } from 'react'
import type { Project } from '../api/types'

export type Section = 'overview' | 'model' | 'auth' | 'access' | 'generate'

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
    id: 'access',
    label: 'Roles & access',
    icon: (
      <>
        <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />
        <path d="M9 12l2 2 4-4" />
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

function Icon({ children }: { children: ReactNode }) {
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

/** Sidebar on the projects list. */
export function ProjectsSidebar() {
  return (
    <nav>
      <ul>
        <li>
          <a href={link('/')} aria-current="page">
            <Icon>
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
            </Icon>
            Projects
          </a>
        </li>
      </ul>
    </nav>
  )
}

interface ProjectSidebarProps {
  project: Project
  section: Section
  /** Number of problems per section, shown as a badge. */
  problems: Partial<Record<Section, number>>
}

/** Sidebar inside a project: one entry per step of building the backend. */
export function ProjectSidebar({ project, section, problems }: ProjectSidebarProps) {
  return (
    <nav>
      <a className="sidebar-back" href={link('/')}>
        ← All projects
      </a>
      <div className="sidebar-project">
        <strong>{project.name}</strong>
      </div>
      <ul>
        {SECTIONS.map((s) => (
          <li key={s.id}>
            <a
              href={link(`/p/${project.id}/${s.id}`)}
              aria-current={section === s.id ? 'page' : undefined}
            >
              <Icon>{s.icon}</Icon>
              <span>{s.label}</span>
              {!!problems[s.id] && <span className="count-badge">{problems[s.id]}</span>}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
