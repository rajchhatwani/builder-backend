import { noNullIssue, wholeIssue } from './operateRuntime'

export const aiIssue = (id: string, values?: Record<string, string | number>) => ({ key: 'runtime.' + id, values })
export const aiText = (missing: string, max: number) => (value: string) =>
  !value.trim() ? aiIssue(missing) : value.length > max ? aiIssue('tooLong', { max }) : noNullIssue(value)

export const sourceRoles = (value: string) => value.split(',').map(role => role.trim()).filter(Boolean)
export const roleIssue = (value: string, ownerOnly: boolean, known: string[]) => {
  const roles = sourceRoles(value)
  if (roles.length && ownerOnly) return aiIssue('visibilityConflict')
  if (!roles.length && !ownerOnly) return aiIssue('visibilityRequired')
  if (roles.length > 50) return aiIssue('roleLimit')
  const unknown = known.length ? roles.find(role => !known.includes(role)) : undefined
  return unknown ? aiIssue('unknownRole', { role: unknown }) : noNullIssue(value)
}
export const resultLimit = (max: number) => (value: string) => wholeIssue(value, 1, max)
