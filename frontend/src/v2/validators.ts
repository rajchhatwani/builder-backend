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

const workspaceFileBytes = 256 * 1024

export function validateWorkspaceContent(content: string) {
  if (content.includes('\0')) return 'editor.fileNul'
  if (new TextEncoder().encode(content).byteLength > workspaceFileBytes) return 'editor.fileLimit'
}

export const entryLimits = {
  email: 254, name: 100, loginPassword: 256, passwordMin: 12, passwordMax: 128,
  code: 32, verifyMin: 10, verifyMax: 200, inviteMin: 16, inviteMax: 128,
}

export const entryEmailChecks = [
  validators.required,
  (value: string) => validators.length(entryLimits.email)(value.trim()),
  validators.email,
]

export const checkPresentPassword: Validator = value => value.length ? undefined : issue('required')

export function newPasswordChecks(email: string): Validator[] {
  const emailName = email.trim().toLowerCase().split('@')[0]
  return [
    checkPresentPassword,
    value => [...value].length < entryLimits.passwordMin ? issue('passwordMinimum', { min: entryLimits.passwordMin }) : undefined,
    validators.length(entryLimits.passwordMax),
    value => emailName.length >= 4 && value.toLowerCase().includes(emailName) ? issue('passwordGuessable') : undefined,
    value => new Set(value).size < 5 ? issue('passwordVariety') : undefined,
  ]
}

export function inviteTokenFrom(value: string) {
  const trimmed = value.trim()
  const link = trimmed.match(/(?:#\/invite\/|^\/invite\/)([^/?#\s]+)(?:[/?#]|$)/)
  if (link) {
    try { return decodeURIComponent(link[1]) } catch { return '' }
  }
  return /^[-_a-z0-9%]+$/i.test(trimmed) ? trimmed : ''
}

export const checkInviteLink: Validator = value => {
  const token = inviteTokenFrom(value)
  return token.length < entryLimits.inviteMin || token.length > entryLimits.inviteMax ? issue('inviteLink') : undefined
}

export const checkTotp: Validator = value => /^\d{6}$/.test(value.trim()) ? undefined : issue('totp')

export const checkTotpOrRecovery: Validator = value => {
  const recovery = value.trim().replace(/[- ]/g, '')
  return !checkTotp(value) || (value.length <= entryLimits.code && /^[a-z0-9]{10}$/i.test(recovery))
    ? undefined : issue('totpOrRecovery')
}

export const projectLimits = { name: 100, slug: 100, description: 2000 } as const
export const checkProjectSlug = format(value => /^[a-z][a-z0-9-]*$/.test(value), 'projectSlug')
export const checkPasswordConfirmation = (repeat: string, next: string) => repeat === next ? undefined : issue('passwordMismatch')
export const tokenLimits = { name: 100, description: 255, minDays: 1, maxDays: 365, active: 25 } as const
export const checkTokenDays = validators.number({ min: tokenLimits.minDays, max: tokenLimits.maxDays, integer: true })

export const orgLimits = {
  sessionHours: 720, approvalHours: 168, ssoUrl: 500, entityId: 500, cert: 20_000,
  clientId: 255, clientSecret: 2000, domain: 260, groups: 100, groupName: 255, aiKey: 300,
} as const

export const orgSessionHours = validators.number({ min: 1, max: orgLimits.sessionHours, integer: true })
export const orgApprovalHours = validators.number({ min: 1, max: orgLimits.approvalHours, integer: true })
export const orgUsageLimit = validators.number({ min: 0, max: Number.MAX_SAFE_INTEGER, digits: 16, integer: true })
export const orgAiKey = format(value => value.length >= 20 && /^sk[-_][\w-]{17,}$/.test(value), 'providerKey')
export const orgAiBudget = format(value => /^(?:\d{1,9}(?:\.\d{1,6})?|\.\d{1,6})$/.test(value), 'budget')
export const orgSsoUrl = format(value => /^https:\/\//i.test(value) && !validators.url(value), 'https')
export const orgSsoDomain = format(value => value.includes('.') && !validators.host(value), 'domain')

export function orgGroupName(name: string, names: string[]): ValidationIssue | undefined {
  if (!name.trim()) return issue('required')
  return names.filter(other => other.trim().toLowerCase() === name.trim().toLowerCase()).length > 1
    ? issue('duplicateGroup') : undefined
}

export const behaviorIdentifier = (max: number): Validator =>
  format(value => value.length <= max && /^[a-z][a-z0-9_]*$/.test(value), 'behaviorName')
export const hookModelName = format(value => /^[A-Z][A-Za-z0-9]{0,39}$/.test(value) && value !== 'BaseModel', 'hookModel')
export const effectHost = format(value => /^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$/.test(value) && !/^\d+(?:[.\d]*)$/.test(value), 'effectHost')
export const settingColor = format(value => /^#[a-f\d]{6}$/i.test(value), 'settingColor')
export const seedDate = format(value => /^\d{4}-\d{2}-\d{2}$/.test(value) &&
  !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value &&
  Number(value.slice(0, 4)) >= 1990 && Number(value.slice(0, 4)) <= 2100, 'seedDate')

export function safeJsonArray(max: number): Validator {
  return value => {
    if (!value.trim()) return undefined
    try {
      const parsed: unknown = JSON.parse(value)
      if (Array.isArray(parsed) && parsed.length <= max) return undefined
    } catch { /* Report a field-specific validation issue. */ }
    return issue('jsonArray', { max })
  }
}

export const booleanValue = format(value => /^(true|false)$/i.test(value), 'booleanValue')

export const hookFieldName = format(value => /^[a-z][a-z0-9_]{0,39}$/.test(value) && !value.startsWith('model_'), 'behaviorName')
export const hookDate = format(value => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) &&
  new Date(value).toISOString().slice(0, 10) === value, 'dateValue')
export const hookDateTime = format(value => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value) &&
  !Number.isNaN(Date.parse(value)), 'dateTimeValue')
export const hookUuid = format(isUuid, 'uuidValue')

export const customFieldOptions = format(value => {
  const values = value.split('\n').map(item => item.trim()).filter(Boolean)
  return values.length <= 100 && new Set(values).size === values.length &&
    values.every(item => /^[A-Za-z0-9_.-]{1,64}$/.test(item))
}, 'customFieldOptions')

export const seedPrefix = format(value => /^[A-Za-z0-9_.-]{1,40}$/.test(value), 'seedPrefix')
export const seedEmailPrefix = format(value => /^[a-z][a-z0-9]{0,19}$/.test(value), 'seedEmailPrefix')

export function lineValues(checks: Validator[], max: number): Validator {
  return value => {
    const values = value.split('\n').map(line => line.trim()).filter(Boolean)
    if (!values.length || values.length > max) return issue('lineValues', { max })
    return values.flatMap((line, index) => checks.map(check => {
      const child = check(line)
      return child ? issue('lineValue', { count: index + 1 }) : undefined
    })).find(Boolean)
  }
}

export function looksSecretName(name: string) {
  return /secret|password|passwd|passphrase|token|credential|private_key|api_key|cardnumber|card_number/i.test(name) ||
    name.replace(/([a-z0-9])(?=[A-Z])/g, '$1_').toLowerCase().split(/[^a-z0-9]+/)
      .some(part => ['pwd', 'pin', 'otp', 'cvv', 'cvc', 'ssn', 'iban', 'credentials'].includes(part))
}

export const publicBehaviorName = format(value => !looksSecretName(value), 'publicBehaviorName')
export const sequencePrefix = format(value => /^[A-Za-z0-9_/\-]{1,20}$/.test(value), 'sequencePrefix')
export const settingDecimal = format(value => /^-?[0-9]{1,18}(\.[0-9]{1,8})?$/.test(value), 'settingDecimal')

export const signInRate = format(value => /^[1-9][0-9]{0,5}\/([1-9][0-9]{0,3})?(second|minute|hour|day)s?$/.test(value), 'signInRate')
export const signInSmsSender = (provider: string) => format(value => /^\+[1-9]\d{7,14}$/.test(value) ||
  (provider === 'aws_sns' && /^[A-Za-z0-9]{1,11}$/.test(value)), 'signInSmsSender')
export const signInLine = format(value => !/[\r\n]/.test(value), 'signInLine')
export const signInFieldName = (reserved: readonly string[]) => format(value =>
  /^[a-z][a-z0-9_]*$/.test(value) && !reserved.includes(value), 'signInFieldName')
export const signInEnumChoices = format(value => {
  const values = value.split('\n').map(item => item.trim()).filter(Boolean)
  return values.length > 0 && values.length <= 50 && new Set(values).size === values.length &&
    values.every(item => /^[A-Za-z0-9_.-]{1,64}$/.test(item))
}, 'signInEnumChoices')
export const orderedNumber = (min: string, max: string): ValidationIssue | undefined =>
  min && max && Number(min) > Number(max) ? issue('signInBounds') : undefined

export function secureAddress(value: string, local = false) {
  if (value.length > 2000 || /[\s"'<>\x60\x5c*\x00-\x1f\x7f#]/.test(value)) return undefined
  try {
    const url = new URL(value)
    return url.port !== '0' && /^https?:\/\//.test(value) && (url.protocol === 'https:' ||
      (local && url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) &&
      !url.username && !url.password && !/^[^:]+:\/\/[^/?]*@/.test(value) ? url : undefined
  } catch { return undefined }
}
export const keycloakRedirects = format(value => {
  const lines = value.split('\n').map(line => line.trim()).filter(Boolean)
  return lines.length <= 20 && lines.length === new Set(lines).size && lines.every(line => !!secureAddress(line, true))
}, 'keycloakRedirects')
export const keycloakRealm = format(value => /^[a-z0-9][a-z0-9-]{0,62}$/.test(value) && value !== 'master', 'keycloakRealm')
export const keycloakClient = format(value => /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(value), 'keycloakClient')
export const keycloakAlias = format(value => /^[a-z][a-z0-9-]{0,30}$/.test(value), 'keycloakAlias')
export const keycloakProviderClient = format(value => !/[\s\u0000-\u001f\u007f]/.test(value), 'keycloakProviderClient')
export const keycloakEndpoint = format(value => !!secureAddress(value), 'keycloakEndpoint')
export const suiteIdentifier = format(value => /^[a-z0-9][a-z0-9-]{0,55}$/.test(value) && !value.endsWith('-'), 'suiteIdentifier')
export const suiteIssuer = (realm: string) => format(value => {
  const url = secureAddress(value, true)
  return !!url && !value.includes('?') && url.pathname.replace(/\/$/, '').endsWith('/realms/' + realm)
}, 'suiteIssuer')
export const signInObject = format(value => {
  try {
    const parsed: unknown = JSON.parse(value)
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
  } catch { return false }
}, 'signInObject')

export const dependencyChecks = {
  package: format(value => /^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$/.test(value), 'dependencyPackage'),
  version: format(value => /^(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){0,3}(?:(?:a|b|rc)\d{1,4})?(?:\.post\d{1,4})?(?:\.dev\d{1,4})?$/.test(value), 'dependencyVersion'),
  reason: (value: string) => value.trim().length < 3 ? issue('dependencyReason') : undefined,
  hashes: format(value => {
    const lines = value.split(/\s+/)
    return lines.length <= 20 && lines.every(line => /^sha256:[a-f0-9]{64}$/.test(line))
  }, 'dependencyHashes'),
}

export const complianceChecks = {
  purposes: (value: string) => {
    const purposes = value.split(',').map(item => item.trim()).filter(Boolean)
    if (purposes.length > 32 || purposes.some(item => !/^[a-z][a-z0-9_-]{0,39}$/.test(item))) return issue('compliancePurposes')
    if (new Set(purposes).size !== purposes.length) return issue('complianceDuplicatePurpose')
  },
  exportTreatment: (name: string, fieldType: string | undefined, treatment: string, protectedField: boolean): Validator => () => {
    if (protectedField) return ['keep', 'generalise'].includes(treatment) ? issue('complianceProtectedExport') : undefined
    const fragments = /email|phone|name|ssn|passport|address|dob|birth|postal|postcode|latitude|longitude|licence|license|insurance/
    const words = name.match(/[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+/g) ?? []
    const shortNames = ['ip', 'zip', 'mrn', 'lat', 'lng', 'lon', 'geo', 'nhs', 'tin', 'nin', 'dob', 'ssn']
    if (treatment === 'keep' && (['email', 'phone', 'text'].includes(fieldType ?? '') ||
      fragments.test(name.toLowerCase()) || words.some(word => shortNames.includes(word.toLowerCase())))) {
      return issue('complianceIdentifier')
    }
  },
  selection: (values: readonly string[], selected: string[]): Validator => () =>
    selected.some(value => !values.includes(value)) ? issue('complianceUnavailable') : undefined,
}

export const accessChecks = {
  name: format(value => /^[a-z][a-z0-9_]*$/.test(value), 'accessName'),
  policyName: format(value => /^[a-z][a-z0-9_]{0,39}$/.test(value), 'accessPolicyName'),
  jsonObject: format(value => {
    try {
      const parsed: unknown = JSON.parse(value)
      return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
    } catch { return false }
  }, 'accessJsonObject'),
  literal: format(value => {
    try {
      const parsed: unknown = JSON.parse(value)
      return !Array.isArray(parsed) || parsed.length <= 100
    } catch { return false }
  }, 'accessLiteral'),
}

export function checkPolicyCondition(node: {
  kind: 'all' | 'any' | 'comparison'
  children?: readonly unknown[]
  left?: { kind: string; value: string }
  right?: { kind: string; value: string }
  op?: string
}, depth: number, size: number): ValidationIssue | undefined {
  if (depth > 4 || size > 24) return issue('accessConditionLimit')
  if (node.kind !== 'comparison') return !node.children?.length ? issue('accessConditionChildren') : undefined
  const operand = (value?: { kind: string; value: string }) => !value?.value.trim() ? issue('accessOperandRequired') :
    value.kind === 'literal' ? accessChecks.literal(value.value) : undefined
  return operand(node.left) ?? (node.op === 'is_null' || node.op === 'not_null' ? undefined : operand(node.right))
}
