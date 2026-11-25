export type DraftValue = string | boolean | string[]
export type SettingsDraft = Record<string, DraftValue>
export type DraftAction =
  | { type: 'change'; name: string; value: DraftValue }
  | { type: 'replace'; values: SettingsDraft }

export function draftReducer(draft: SettingsDraft, action: DraftAction): SettingsDraft {
  if (action.type === 'replace') return action.values
  return { ...draft, [action.name]: action.value }
}

export function draftFrom(config: object, path = ''): SettingsDraft {
  return Object.fromEntries(Object.entries(config).flatMap(([name, value]) => {
    const key = path ? path + '.' + name : name
    if (value && typeof value === 'object' && !Array.isArray(value)) return Object.entries(draftFrom(value, key))
    return [[key, value == null ? '' : typeof value === 'number' ? String(value) : value]]
  }))
}

export const text = (draft: SettingsDraft, name: string) => String(draft[name] ?? '')
export const number = (draft: SettingsDraft, name: string) => Number(text(draft, name))
export const optionalNumber = (draft: SettingsDraft, name: string) => text(draft, name) ? number(draft, name) : null
export const checked = (draft: SettingsDraft, name: string) => draft[name] === true
export function list(draft: SettingsDraft, name: string) {
  const value = draft[name]
  if (Array.isArray(value)) return value
  const separator = name === 'currencies' || name.startsWith('roles.') ? /[,\n]/ : /\n/
  return text(draft, name).split(separator).map(entry => entry.trim()).filter(Boolean)
}
