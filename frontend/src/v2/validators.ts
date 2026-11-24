export const defaultLimits = { shortText: 120, longText: 5000, numberDigits: 9, phoneMin: 8, phoneMax: 15 } as const

export type ValidationIssue = { key: string; values?: Record<string, string | number> }
export type Validator = (value: string) => ValidationIssue | undefined

const issue = (key: string, values?: ValidationIssue['values']): ValidationIssue => ({ key: `validation.${key}`, values })
const format = (test: (value: string) => boolean, key: string): Validator =>
  value => value.trim() && !test(value.trim()) ? issue(key) : undefined

export const validators = {
  required: (value: string) => value.trim() ? undefined : issue('required'),
  length: (max: number = defaultLimits.shortText): Validator =>
    value => [...value].length > max ? issue('maxLength', { max }) : undefined,
  email: format(value => /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$/.test(value), 'email'),
  phone: format(value => {
    const digits = value.replace(/\D/g, '').length
    return /^\+?[\d ().-]+$/.test(value) && digits >= defaultLimits.phoneMin && digits <= defaultLimits.phoneMax
  }, 'phone'),
  url: format(value => {
    try { return /^https?:\/\//i.test(value) && Boolean(new URL(value).hostname) } catch { return false }
  }, 'url'),
  host: format(value => {
    if (/^\[[\da-f:]+\]$/i.test(value)) {
      try { return Boolean(new URL(`https://${value}`).hostname) } catch { return false }
    }
    return value.length <= 253 && value.replace(/\.$/, '').split('.').every(part => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/i.test(part))
  }, 'host'),
  slug: format(value => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value), 'slug'),
  number: ({ min, max, digits = defaultLimits.numberDigits, integer = false }: {
    min?: number; max?: number; digits?: number; integer?: boolean
  } = {}): Validator => value => {
    const input = value.trim()
    if (!input) return undefined
    const amount = Number(input)
    if (!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/.test(input) || !Number.isFinite(amount)) return issue('number')
    if (integer && !Number.isInteger(amount)) return issue('integer')
    if (input.replace(/\D/g, '').length > digits) return issue('digits', { max: digits })
    if (min !== undefined && amount < min) return issue('minimum', { min })
    if (max !== undefined && amount > max) return issue('maximum', { max })
  },
}

export const guidedLimits = {
  prompt: 60_000, item: 600, coveredBy: 200, answer: 2_000, note: 500, scopeName: 120,
  scopeItems: 100, files: 5, fileBytes: 5 * 1024 * 1024, totalBytes: 12 * 1024 * 1024,
}
export const documentAccept = '.pdf,.docx,.xlsx,.txt,.md'

export function intakeDocuments(existing: File[], picked: File[]) {
  const files = [...existing]
  const errors: ValidationIssue[] = []
  let total = files.reduce((size, file) => size + file.size, 0)
  for (const file of picked) {
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    const key = !documentAccept.split(',').includes(extension) ? 'documentType'
      : !file.size ? 'documentEmpty'
      : file.size > guidedLimits.fileBytes ? 'documentSize'
      : files.length >= guidedLimits.files ? 'documentCount'
      : total + file.size > guidedLimits.totalBytes ? 'documentTotal' : undefined
    if (key) errors.push(issue(key, { name: file.name }))
    else {
      files.push(file)
      total += file.size
    }
  }
  return { files, errors }
}

export function planNameChecks(existing: string[], kept: number): Validator[] {
  return [
    name => existing.includes(name.trim()) ? issue('scopeDuplicate') : undefined,
    () => kept >= guidedLimits.scopeItems ? issue('scopeLimit', { max: guidedLimits.scopeItems }) : undefined,
  ]
}

export const deliveryLimits = { goal: 8000, workspace: 100, checkpoint: 100, proposalRole: 40 }

export const isUuid = (value: string) => /^[\da-f]{8}(-[\da-f]{4}){3}-[\da-f]{12}$/i.test(value)
