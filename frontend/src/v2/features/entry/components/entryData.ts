import type { Organization, Project } from '../api/projects'

export const projectLocked = (project: Project, org?: Organization) => Boolean(project.organization_locked || org?.deletion_requested_at)

export const formatEntryDate = (date: string | null | undefined, locale: string, unset: string) =>
  date ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(date)) : unset
