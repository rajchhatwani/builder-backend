import { createContext } from 'react'
import type { MemberRole } from './api/workspace'

export const WorkspaceContext = createContext<{
  role?: MemberRole
  rolePending?: boolean
  roleError?: boolean
  retryRole?: () => void
  project?: string
  organization?: string
  version?: number
}>({})
