import { expect, it } from 'vitest'
import { initialSchemaDraft, schemaDraftReducer, shownErrors } from './schemaDraft'
import { initialTemplateDraft, renderTemplate, templateDraftReducer } from './templateDraft'

it('schema drafts keep their initial version across refetches and reset field errors after a reorder', () => {
  const base = { rows: [{ name: 'a' }, { name: 'b' }] }
  const edited = schemaDraftReducer(initialSchemaDraft, { type: 'edit', path: ['rows', 0, 'name'], next: 'edited', base, version: 2 })
  const touched = schemaDraftReducer(edited, { type: 'touch', path: 'rows.0.name' })
  expect(shownErrors(touched, { 'rows.0.name': ['Check name'] })).toEqual({ 'rows.0.name': ['Check name'] })
  const reordered = schemaDraftReducer(schemaDraftReducer(touched, { type: 'structure', path: 'rows' }),
    { type: 'edit', path: ['rows'], next: [{ name: 'b' }, { name: 'edited' }], base, version: 3 })
  expect(reordered.draft).toEqual({ value: { rows: [{ name: 'b' }, { name: 'edited' }] }, version: 2 })
  expect(shownErrors(reordered, { 'rows.0.name': ['Check name'] })).toEqual({})
  expect(schemaDraftReducer(reordered, { type: 'reset' }).draft).toBeUndefined()
})

it('template drafts keep their first version and escape only values in HTML preview', () => {
  const edit = templateDraftReducer(initialTemplateDraft, { type: 'edit', changes: { body: '<p>{{ customer }}</p>' }, version: 2 })
  const sample = templateDraftReducer(edit, { type: 'sample', variable: 'customer', value: '<name> & Co' })
  const html = templateDraftReducer(sample, { type: 'edit', changes: { html: true }, version: 3 })
  expect(html.version).toBe(2)
  expect(renderTemplate(html.edits.body!, html.samples, true)).toBe('<p>&lt;name&gt; &amp; Co</p>')
  expect(renderTemplate('{{ constructor }}', html.samples, false)).toBe('{{ constructor }}')
  expect(templateDraftReducer(html, { type: 'reset' })).toEqual(initialTemplateDraft)
})
