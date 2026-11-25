import type { DocumentsSettings, DocumentTemplate, LibraryTemplate } from '../api/documents'

export type PdfAction = (
  | { type: 'settings'; patch: Partial<Pick<DocumentsSettings, 'enabled' | 'rate_limit'>> }
  | { type: 'add'; item: LibraryTemplate; roles: string[] }
  | { type: 'remove'; index: number }
  | { type: 'template'; index: number; patch: Partial<DocumentTemplate> }
) & { base: DocumentsSettings } | { type: 'reset' }

export function pdfDraft(draft: DocumentsSettings | null, action: PdfAction): DocumentsSettings | null {
  if (action.type === 'reset') return null
  const base = draft ?? action.base
  switch (action.type) {
    case 'settings': return { ...base, ...action.patch }
    case 'add': {
      let id = action.item.id
      for (let suffix = 2; base.templates.some(template => template.id === id); suffix++) id = action.item.id + '_' + suffix
      return {
        ...base, enabled: true, templates: [...base.templates, {
          id, title: action.item.title, kind: action.item.id, entity: null, compute: action.item.compute,
          roles: action.roles.length === 1 ? action.roles : [], template: action.item.template,
        }],
      }
    }
    case 'remove': return { ...base, templates: base.templates.filter((_, index) => index !== action.index) }
    case 'template': return { ...base, templates: base.templates.map((template, index) =>
      index === action.index ? { ...template, ...action.patch } : template) }
  }
}
