import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Button, Dialog, Grid, Row, Stack, Table } from '../../ui'
import { AccessDiffTable, type AccessEditorProps } from './AccessModel'
import { controlsApi, type AuthorizationSettings } from './api/controls'
import { checkField, LoadFailure, pickField, readText } from './SecureForm'

export function AccessFieldRules({ id, spec, settings, roles, editable, busy, onSave }: AccessEditorProps & { onSave: (settings: AuthorizationSettings) => void }) {
  const t = useT()
  const [editing, setEditing] = useState<{ index: number; base: AuthorizationSettings }>()
  const [entity, setEntity] = useState('')
  const [field, setField] = useState('')
  const [read, setRead] = useState('_inherit')
  const [write, setWrite] = useState('_inherit')
  const [review, setReview] = useState<AuthorizationSettings>()
  const preview = useMutation({ mutationFn: (settings: AuthorizationSettings) =>
    controlsApi.diffAccess(id, { field_access: settings.field_access }),
    onSuccess: (_result, proposed) => { setEditing(undefined); setReview(proposed) } })
  const list = settings.field_access
  const current = editing?.base.field_access[editing.index]
  const fields = spec.entities.find(item => item.name === entity)?.fields ?? []
  const label = (value: string[] | null) => value === null ? t('authorization.inherit') : value.join(', ') || t('authorization.nobody')
  const start = (index: number) => {
    setEntity(list[index]?.entity ?? '')
    setField(list[index]?.field ?? '')
    setRead(list[index]?.read_roles != null ? '_restrict' : '_inherit')
    setWrite(list[index]?.write_roles != null ? '_restrict' : '_inherit')
    preview.reset()
    setEditing({ index, base: settings })
  }
  const roleChoices = (name: 'read' | 'write') => [...roles, ...(name === 'read' ? current?.read_roles ?? [] : current?.write_roles ?? [])
    .filter(name => !roles.some(role => role.name === name)).map(name => ({ name, label: name }))]
  const mode = (name: 'read' | 'write', value: string, change: (value: string) => void) => [
    pickField(name, t(`authorization.${name}Field`), value, [
      { value: '_inherit', label: t('authorization.inherit') }, { value: '_restrict', label: t('authorization.restrict') },
    ], { change }),
    ...value === '_restrict' ? roleChoices(name).map(role => checkField(`${name}.${role.name}`, role.label,
      (name === 'read' ? current?.read_roles : current?.write_roles)?.includes(role.name) ?? false)) : [],
  ]
  const form = [
    pickField('entity', t('authorization.entity'), entity, spec.entities.map(item => ({ value: item.name, label: item.name })),
      { change: value => { setEntity(value); setField('') }, locked: Boolean(current), required: !current, placeholder: t('authorization.choose') }),
    { ...pickField('field', t('authorization.field'), field, fields.map(item => ({ value: item.name, label: item.name })),
      { change: setField, locked: Boolean(current), required: !current, placeholder: t('authorization.choose') }),
      validateWith: (value: string) => !current && list.some(item => item.entity === entity && item.field === value) ?
        { key: 'validation.accessDuplicateField' } : undefined },
    ...mode('read', read, setRead), ...mode('write', write, setWrite),
  ]
  return <Stack gap={2}>
    {preview.isError && <LoadFailure error={preview.error} message={t('authorization.diffError')}
      retry={() => { if (preview.variables) preview.mutate(preview.variables) }} />}
    {list.length ? <Table label={t('authorization.fieldAccess')} columns={['field', 'readField', 'writeField', 'actions'].map(key =>
      ({ id: key, label: t(`authorization.${key}`) }))} rows={list.map((item, index) => ({
        id: item.entity + '.' + item.field, cells: [item.entity + '.' + item.field, label(item.read_roles), label(item.write_roles),
          editable && <Row><Button disabled={busy} onClick={() => start(index)}>{t('authorization.edit')}</Button>
            <ConfirmDestructive trigger={<Button variant="danger" disabled={busy}>{t('authorization.delete')}</Button>}
              title={t('authorization.deleteField')} description={t('authorization.deleteFieldHelp')} action={t('authorization.delete')}
              onConfirm={() => preview.mutateAsync({ ...settings, field_access: list.filter((_, position) => index !== position) }).then(() => undefined)} /></Row>],
      }))} /> : <p>{t('authorization.noFieldRules')}</p>}
    {editable && <Row><Button disabled={busy || list.length >= 1000 || !spec.entities.length}
      onClick={() => start(list.length)}>{t('authorization.addField')}</Button></Row>}
    {editing !== undefined && <Dialog open title={t(current ? 'authorization.editField' : 'authorization.addField')}
      onOpenChange={open => { if (!open) setEditing(undefined) }}>
      <Form fields={form} pending={preview.isPending} submitLabel={t('common.save')}
        formError={preview.isError ? t('authorization.diffError') : undefined}
        layout={controls => <Grid>{form.map(field => controls[field.name])}</Grid>}
        onSubmit={data => {
          const rule = { entity, field: current?.field ?? readText(data, 'field'),
            read_roles: read === '_inherit' ? null : roleChoices('read').filter(role => data.has(`read.${role.name}`)).map(role => role.name),
            write_roles: write === '_inherit' ? null : roleChoices('write').filter(role => data.has(`write.${role.name}`)).map(role => role.name) }
          const field_access = [...editing.base.field_access]
          field_access[editing.index] = rule
          preview.mutate({ ...editing.base, field_access })
        }} />
    </Dialog>}
    {review && <ConfirmDestructive open title={t('authorization.reviewDiff')} description={t('authorization.weakenHelp')}
      action={t('common.save')} onOpenChange={open => { if (!open) setReview(undefined) }} onConfirm={() => onSave(review)}>
      {preview.data && <AccessDiffTable diff={preview.data} />}
    </ConfirmDestructive>}
  </Stack>
}
