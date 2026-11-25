import { expect, it } from 'vitest'
import { library, time } from '../../../../../e2e/v2/fixtures/operate-c'
import type { DocumentsSettings } from '../api/documents'
import { pdfDraft } from './pdfDraft'

it('keeps the original save version, duplicates a library entry with a unique name, and resets independently', () => {
  const base: DocumentsSettings = { project_id: 'project', enabled: false, rate_limit: '30/minute', templates: [], version: 2, updated_at: time }
  const added = pdfDraft(null, { type: 'add', base, item: library[0], roles: ['admin'] })
  const second = pdfDraft(added, { type: 'add', base: { ...base, version: 3 }, item: library[0], roles: ['admin'] })
  expect(second?.version).toBe(2)
  expect(second?.templates.map(item => item.id)).toEqual(['invoice', 'invoice_2'])
  expect(second?.templates[0].roles).toEqual(['admin'])
  expect(base.templates).toEqual([])
  expect(pdfDraft(second, { type: 'reset' })).toBeNull()
})
