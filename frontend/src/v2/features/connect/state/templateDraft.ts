import type { NotificationType, Template } from '../api/blocks'

export type TemplateDraft = {
  edits: Partial<Template>
  samples: Record<string, string>
  version?: number
}
type Action =
  | { type: 'edit'; changes: Partial<Template>; version: number }
  | { type: 'sample'; variable: string; value: string }
  | { type: 'reset' }

export const initialTemplateDraft: TemplateDraft = { edits: {}, samples: {} }

export function templateDraftReducer(state: TemplateDraft, action: Action): TemplateDraft {
  switch (action.type) {
    case 'edit': return { ...state, version: state.version ?? action.version, edits: { ...state.edits, ...action.changes } }
    case 'sample': return { ...state, samples: { ...state.samples, [action.variable]: action.value } }
    case 'reset': return initialTemplateDraft
  }
}

export function applyTemplate(type: NotificationType, template: Template) {
  return { ...type, templates: type.templates.some(row => row.channel === template.channel)
    ? type.templates.map(row => row.channel === template.channel ? template : row) : [...type.templates, template] }
}

export function renderTemplate(text: string, samples: Record<string, string>, html: boolean) {
  const escape = (value: string) => value.replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;',
  })[character]!)
  return text.replace(/\{\{\s*([a-z][a-z0-9_]{0,39})\s*\}\}/g, (token, name: string) => {
    if (!Object.hasOwn(samples, name)) return token
    return html ? escape(samples[name]) : samples[name]
  })
}
